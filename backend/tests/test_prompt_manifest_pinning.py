"""Gate 15 item — "Prompt versions pinned" (PHASES.md Phase 15, E2).

ADR-003 gives every LLM-backed agent a versioned prompt directory and a
single `manifest.json` that pins which version is active. For demo day
that pin must be *explicit and concrete* — no `-latest`, no floating
alias, no empty string, no manifest entry pointing at a file that does
not exist, and no prompt directory that has been added without a
corresponding pin. This module is the tripwire for all of those.

It also confirms `app.prompts.loader.load_prompt` records the resolved
version as provenance the demo-path agents copy into
`contracts.agents.AgentOutput.prompt_version` (spot-checked on A12, the
Implication Agent the spec §24 exception beat runs through).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from contracts.graph_types import NodeId

from app.agents.consequence.implication_agent import AGENT_ID as A12_ID
from app.agents.consequence.implication_agent import ImplicationAgent
from app.agents.consequence.types import HouseholdContext, ImplicationRequest
from app.prompts import loader
from app.prompts.loader import PromptNotFound, load_prompt
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_PROMPTS_DIR = Path(loader.__file__).parent
_MANIFEST_PATH = _PROMPTS_DIR / "manifest.json"

# An explicit, pinned prompt version: the literal string "v" followed by
# one or more digits, and nothing else. Rejects "", "latest", "v1-latest",
# "v1 ", "main", "HEAD", "v1.2", and every other floating / imprecise form.
_EXPLICIT_VERSION = re.compile(r"^v[0-9]+$")


def _manifest() -> dict[str, object]:
    data: dict[str, object] = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


def _pinned_entries() -> dict[str, object]:
    """Manifest entries that are real agent pins — the leading-underscore
    keys (`_comment`) are documentation, not pins."""
    return {key: value for key, value in _manifest().items() if not key.startswith("_")}


def test_manifest_is_valid_json_and_non_empty() -> None:
    entries = _pinned_entries()
    assert entries, "manifest.json has no agent pins"


@pytest.mark.parametrize("agent_key", sorted(_pinned_entries()))
def test_every_manifest_entry_is_an_explicit_pinned_version(agent_key: str) -> None:
    value = _pinned_entries()[agent_key]
    assert isinstance(value, str), f"{agent_key!r} pins a non-string: {value!r}"
    assert _EXPLICIT_VERSION.match(value), (
        f"{agent_key!r} resolves to {value!r} — not an explicit vN version. "
        "Floating aliases (-latest, main, HEAD, empty) are forbidden on the prompt-loading path."
    )


@pytest.mark.parametrize("agent_key", sorted(_pinned_entries()))
def test_every_manifest_entry_points_to_a_file_that_exists(agent_key: str) -> None:
    dir_name = loader._AGENT_DIR_NAMES.get(agent_key)
    assert dir_name is not None, (
        f"{agent_key!r} is pinned in manifest.json but has no directory mapping in loader._AGENT_DIR_NAMES"
    )
    version = _pinned_entries()[agent_key]
    assert isinstance(version, str)
    version_file = _PROMPTS_DIR / dir_name / f"{version}.md"
    assert version_file.is_file(), f"{agent_key!r} pins {version!r} but {version_file} does not exist"
    assert version_file.read_text(encoding="utf-8").strip(), f"{version_file} is empty"


@pytest.mark.parametrize("agent_key", sorted(loader._AGENT_DIR_NAMES))
def test_every_mapped_agent_directory_is_pinned_in_the_manifest(agent_key: str) -> None:
    """The reverse guard: a new prompt directory added to
    `_AGENT_DIR_NAMES` without a `manifest.json` pin would `load_prompt`-
    fail at runtime — catch it here instead."""
    assert agent_key in _pinned_entries(), (
        f"{agent_key!r} has a prompt directory mapping but no manifest.json pin"
    )


@pytest.mark.parametrize("agent_key", sorted(_pinned_entries()))
def test_load_prompt_resolves_each_entry_to_its_pinned_version(agent_key: str) -> None:
    loaded = load_prompt(agent_key)
    assert loaded.version == _pinned_entries()[agent_key]
    assert _EXPLICIT_VERSION.match(loaded.version)
    assert loaded.text.strip()
    assert loaded.agent_id == agent_key


def test_no_prompt_directory_contains_a_floating_alias_file() -> None:
    """Every `*.md` in every prompt directory is an explicit `vN.md` —
    a `latest.md` / `current.md` sitting on disk (even unreferenced) is
    an attractive nuisance a future manifest edit could point at."""
    offenders: list[str] = []
    for md_file in _PROMPTS_DIR.rglob("*.md"):
        if not _EXPLICIT_VERSION.match(md_file.stem):
            offenders.append(str(md_file.relative_to(_PROMPTS_DIR)))
    assert not offenders, f"non-versioned prompt files present: {offenders}"


def test_loader_rejects_a_floating_alias_even_if_one_reached_the_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: if a bad pin ever lands in the manifest, the
    loader must fail loudly (no silent fallback to some 'latest' file)."""
    real_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == _MANIFEST_PATH:
            return json.dumps({"A12": "latest"})
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    with pytest.raises(PromptNotFound):
        load_prompt("A12")


def test_a12_records_its_pinned_prompt_version_as_provenance() -> None:
    """spec §24's live exception beat runs through A12 — its output must
    carry the exact manifest-pinned prompt version, not a hardcoded
    guess, so the approval evidence bundle is honest about what ran."""
    agent = ImplicationAgent(
        gemini_client=GeminiClient(router=fake_router(FakeModels(texts=[json.dumps({"candidates": []})])))
    )
    result = agent.imply(
        ImplicationRequest(
            source_document_id=NodeId("doc-x"),
            document_text="Field trip Friday. Nut-free lunch required.",
            household_context=HouseholdContext(
                people=(), constraints=(), open_obligations=(), stated_obligations=()
            ),
        )
    )
    assert result.prompt_version == load_prompt(A12_ID).version
    assert _EXPLICIT_VERSION.match(result.prompt_version)
