"""GharOS — Google Secret Manager adapter (PHASES.md Phase 2 work item 4).

Wraps `google.cloud.secretmanager.SecretManagerServiceClient` behind a
small, dependency-injected class, mirroring the construction pattern
`app.persistence.firestore_client.create_firestore_client` already
establishes in this codebase: a plain `create_*_client` function builds the
real SDK client from typed settings, and the adapter class takes that
client in its constructor rather than reaching for a module-level
singleton (gharos-standards: "no module-level singletons holding I/O").

**Wiring is real, the demo secret's VALUE is a placeholder.** This adapter
talks to the live Secret Manager API — there is no local emulator for
Secret Manager (unlike Firestore/Pub/Sub), so even local development
targets the real GCP project. What is a placeholder, and documented as
one everywhere it appears, is the *content* of `gharos-demo-secret`
(created via `gcloud secrets create` for Phase 2 stack-proof purposes) —
a literal placeholder string, never a real credential. Real secrets this
adapter will read in later phases (voice-provider API keys, sandbox
payment tokens — spec §23: "financial credentials never touch a reasoning
agent") get their own secret ids, created the same way, still never
committed to source.

Every reasoning agent under `backend/app/agents/` must reach a secret only
through an adapter like this one, injected at the composition root — never
by importing `google.cloud.secretmanager` directly.
"""

from __future__ import annotations

from typing import Any, Protocol

from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.cloud import secretmanager

from app.settings import Settings

DEFAULT_SECRET_VERSION = "latest"
"""The Secret Manager version alias meaning "the newest enabled version" —
named here so call sites never hardcode the string "latest" ad hoc
(gharos-standards: no magic values)."""


class _SecretVersionPayload(Protocol):
    """Structural shape of `access_secret_version()`'s `response.payload` —
    only the `data` attribute this adapter reads.

    Declared as a read-only `@property` rather than a plain attribute:
    mypy checks plain (mutable) Protocol attributes invariantly, which
    would require a conforming class's `payload`/`data` types to match
    exactly rather than merely satisfy the nested Protocol structurally.
    A read-only property is checked covariantly, which is what actually
    lets both the real `AccessSecretVersionResponse` and a lightweight
    test double satisfy this nested shape.
    """

    @property
    def data(self) -> bytes: ...


class _AccessSecretVersionResponse(Protocol):
    """Structural shape of `access_secret_version()`'s return value — only
    the `payload` attribute this adapter reads (see `_SecretVersionPayload`
    for why this is a read-only property, not a plain attribute)."""

    @property
    def payload(self) -> _SecretVersionPayload: ...


class SecretManagerClient(Protocol):
    """Structural shape of `SecretManagerServiceClient` covering only the
    two methods `SecretManagerAdapter` actually calls.

    `SecretManagerAdapter` depends on this `Protocol`, not the concrete
    `secretmanager.SecretManagerServiceClient` class — the narrowest
    interface actually used (gharos-standards: dependency injection). The
    real client satisfies it structurally with no explicit subclassing, and
    so does a plain test double implementing the same two methods, with no
    client-mocking library and no `# type: ignore` needed to make
    `mypy --strict` accept the substitution in tests.
    """

    def secret_version_path(self, project: str, secret: str, secret_version: str) -> str: ...

    def access_secret_version(self, request: dict[str, Any]) -> _AccessSecretVersionResponse: ...


class SecretManagerError(RuntimeError):
    """Base class for adapter-level Secret Manager failures.

    A failed Secret Manager call never produces a fabricated secret value
    (gharos-standards non-negotiable #7: "a failed tool call never
    produces a fabricated success") — every failure path here raises one
    of this class's subclasses instead of returning an empty string or a
    cached/default value.
    """


class SecretNotConfigured(SecretManagerError):
    """Raised when no GCP project id is available to address Secret
    Manager against.

    Unlike `create_firestore_client`, this adapter has no local-emulator
    fallback project id to substitute — Secret Manager has no emulator, so
    an unset project id is always a real misconfiguration, never a valid
    local-dev path.
    """

    def __init__(self) -> None:
        super().__init__(
            "gcp_project_id is unset — Secret Manager has no local emulator; "
            "a real GCP project id is required even for local development. "
            "Set GCP_PROJECT_ID in backend/.env."
        )


class SecretNotFoundError(SecretManagerError):
    """Raised when the named secret or secret version does not exist."""

    def __init__(self, *, secret_id: str, version: str) -> None:
        self.secret_id = secret_id
        self.version = version
        super().__init__(f"Secret Manager: no such secret/version: {secret_id}@{version}")


class SecretManagerUnavailable(SecretManagerError):
    """Raised when the Secret Manager API call failed for any reason other
    than the secret/version simply not existing (network, permission,
    quota, transient service error)."""

    def __init__(self, *, secret_id: str, version: str, cause: str) -> None:
        self.secret_id = secret_id
        self.version = version
        self.cause = cause
        super().__init__(f"Secret Manager call failed for {secret_id}@{version}: {cause}")


def create_secret_manager_client() -> secretmanager.SecretManagerServiceClient:
    """Constructs a real `SecretManagerServiceClient`.

    Authenticates via Application Default Credentials — the same
    credentials `gcloud auth application-default login` configures for
    local development, or the attached service account identity on Cloud
    Run in a real deployment. No credentials are ever embedded in code
    (gharos-standards rule 8: "no secrets in code").
    """
    return secretmanager.SecretManagerServiceClient()


class SecretManagerAdapter:
    """Reads named secrets from Google Secret Manager for a single GCP
    project, resolved once at construction time.

    Example (composition root wiring, mirroring `create_firestore_client`
    call sites):

        settings = get_settings()
        adapter = SecretManagerAdapter.from_settings(settings)
        api_key = adapter.get_secret("gharos-demo-secret")
    """

    def __init__(self, client: SecretManagerClient, *, project_id: str) -> None:
        """
        Args:
            client: anything satisfying `SecretManagerClient` — pass the
                result of `create_secret_manager_client()` in production
                code, or a fake implementing the same two methods in tests.
            project_id: the GCP project to address secrets in. Must be
                non-empty; raises `SecretNotConfigured` otherwise.
        """
        if not project_id:
            raise SecretNotConfigured
        self._client = client
        self._project_id = project_id

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        client: SecretManagerClient | None = None,
    ) -> SecretManagerAdapter:
        """Convenience constructor: builds a real client if none is
        supplied, and reads the project id from typed settings — mirrors
        `create_firestore_client(settings)`'s settings-driven wiring
        style."""
        return cls(client or create_secret_manager_client(), project_id=settings.gcp_project_id)

    def get_secret(self, secret_id: str, *, version: str = DEFAULT_SECRET_VERSION) -> str:
        """Fetches and decodes one secret version's payload as UTF-8 text.

        Args:
            secret_id: the Secret Manager secret id (not the full resource
                path — this method builds that from `project_id`).
            version: the secret version, defaults to `"latest"`.

        Returns:
            The decoded secret payload.

        Raises:
            SecretNotFoundError: no such secret/version exists.
            SecretManagerUnavailable: the API call failed for any other
                reason (network, permission, quota).
        """
        name = self._client.secret_version_path(self._project_id, secret_id, version)
        try:
            response = self._client.access_secret_version(request={"name": name})
        except NotFound as exc:
            raise SecretNotFoundError(secret_id=secret_id, version=version) from exc
        except GoogleAPICallError as exc:
            raise SecretManagerUnavailable(secret_id=secret_id, version=version, cause=str(exc)) from exc
        payload: bytes = response.payload.data
        return payload.decode("utf-8")
