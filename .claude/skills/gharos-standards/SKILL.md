---
name: gharos-standards
description: Use before writing or modifying any GharOS code, in any phase, in any role (cto, e1, e2, e3, e4) — the engineering standards, architecture patterns, testing requirements, cost rules, and the eight safety invariants that apply uniformly across the whole build. Also use when reviewing a phase's Definition of Done.
---

# GharOS engineering standards

Full source: `PHASES.md` §2, §3, §6, §7, and `GharOS_Build_Spec_v2.md` §1. This skill is the condensed, always-apply version, with concrete examples — read the source sections directly whenever a rule here needs more context than fits.

## The goal

Production-ready code, not a prototype that happens to run. **No technical debt enters a merged phase.** If a shortcut is truly unavoidable, it goes in `docs/DEBT.md` with an owner and a repayment phase, and the CTO must approve it explicitly. Undocumented shortcuts are rejected at review.

## The seven non-negotiables (spec §1) — these sit above every other rule in this document

1. No agent that reasons about money may also move money.
2. Every autonomous action writes an audit record *before* it executes.
3. Every derived node and edge carries a provenance pointer and a derivation tag.
4. Low-confidence outputs escalate; they never silently act.
5. Financial and irreversible actions require explicit human approval.
6. Never frame agent-to-agent interaction as "debate." It is specialization and interest representation.
7. A failed tool call never produces a fabricated success.

## Non-negotiable quality rules

1. No commented-out code — delete it, git remembers.
2. No `TODO` without an owner and a referenced issue.
3. No magic values — named constants in a config or constants module. (`RiskTier.R3_EXPLICIT_APPROVE`, not the string `"R3"` scattered through call sites.)
4. Functions ≤ ~50 lines, files ≤ ~500 lines, without a stated reason.
5. Full type annotations: Python `mypy --strict` clean; TypeScript `strict: true`, no `any` without a justifying comment.
6. Docstrings on every public function: purpose, params, returns, raises.
7. Typed errors. No bare `except:`. No swallowed exceptions — catch to handle meaningfully or re-raise with context.
8. No secrets in code — env vars via a single settings module (`backend/app/settings.py`, a pydantic-settings model).
9. Structured JSON logging (via `structlog`). Never `print()`.

## Architecture and design patterns, with concrete shape

- **Hexagonal / ports-and-adapters.** Domain logic imports no framework code. `backend/app/agents/consequence/implication_agent.py` never does `from google.cloud import firestore` — it depends on `contracts.repositories.GraphReader`, injected.
- **Dependency injection.** No module-level singletons holding I/O:
  ```python
  # WRONG — module-level singleton holding I/O
  _db = firestore.Client()

  def get_obligation(id: str) -> Obligation:
      return _db.collection("obligations").document(id).get()

  # RIGHT — dependency passed in, testable without a real client
  class FirestoreObligationRepository:
      def __init__(self, client: firestore.Client) -> None:
          self._client = client

      def get(self, obligation_id: NodeId) -> Obligation | None:
          ...
  ```
- **Repository pattern** for all graph access. Agents call repositories defined in `contracts/repositories.py`, never a database client directly.
- **Strategy pattern** for the document-type registry — each of the fourteen document types is a registered strategy (a class or function satisfying a common protocol, registered in a dict/registry object), never a branch in a growing `if document_type == "receipt": ... elif document_type == "utility_bill": ...`.
- **Command pattern** for actions. Every action is an object (`contracts.actions.Action`) carrying a risk tier, an idempotency key, and an audit reference — this is what lets the approval gate be enforced in *one* place (the code that constructs and calls `.execute()` on an `Action`) rather than scattered across every call site that might want to, say, send a message.
- **Result types** for expected failure paths (see ADR-002 for the full policy): `contracts.actions.ActionResult[T]` for tool-layer outcomes; typed exceptions from `contracts.errors` for reasoning/repository-layer conditions with a known handler up the stack. Exceptions are for the genuinely unexpected — a `KeyError` reaching production code is a bug, not a Result.
- **Immutability by default** for domain objects. Graph writes create versions; they do not mutate in place — every node/edge dataclass in `contracts/graph_types.py` is `frozen=True`.

## Testing requirements — a phase without tests does not pass its gate

- **Unit tests** for all domain logic and agents (model calls mocked). ≥80% coverage on `backend/app/`; **100% on anything in the money or safety path** (T6 tools, the Approval Gate, the provenance guard, idempotency store).
- **Contract tests** for every repository and tool, proving the `contracts/` interface is honoured — e.g. a test that instantiates every concrete repository and asserts `isinstance(concrete_repo, contracts.repositories.GraphReader)` (or the structural equivalent for Protocols), plus behavioural tests against the documented semantics.
- **Integration tests** per subsystem against the Firestore emulator — not mocks, the actual emulator, so index/query behaviour is real.
- **Golden-file tests** for extraction — a fixed set of real messy documents with known-correct expected extractions, checked into the repo, run on every change. This is the regression net for the most fragile part of the system.
- **Adversarial tests** for the Implication Agent: documents designed to tempt hallucination (plausible-sounding but unstated claims), asserting uncitable inferences are discarded, not just flagged low-confidence.
- **Frontend:** design-system component tests; smoke tests for graph render and approval flow.

Example of the provenance-guard test style expected at Gate 1 (illustrative, not literal code to copy verbatim):
```python
from hypothesis import given, strategies as st

@given(st.builds(SomeNode, provenance=st.none()))
def test_write_rejects_missing_provenance(node: SomeNode, repo: GraphWriter) -> None:
    with pytest.raises(ProvenanceMissing):
        repo.write_node(node)
```
A handful of example-based tests is not sufficient evidence for "structurally impossible" — a property-based fuzz test is what Gate 1 actually asks for.

## The eight safety invariants — impossible to violate in code, each with a test

| # | Invariant | Introduced | Enforced by |
|---|---|---|---|
| 3 | Provenance on every node/edge | Phase 1 | Repository write guard |
| 2 | Audit before execute | Phase 1 | `write_before_execute` |
| 4 | Low confidence escalates | Phase 4 | Confidence Arbiter |
| 1 | Money reasoners hold no money tools | Phase 5 | Tool registration |
| 5 | Financial/irreversible need approval | Phase 5 | Approval Gate |
| 7 | No fabricated tool success | Phase 5 | Tool error contract |
| 6 | No debate framing | Phase 12 | Code review + lint rule |
| 8 | Voice confers no action capability | Phase 13 | Voice intent routing |

`backend/tests/test_safety_invariants.py` is created in Phase 1 and grows every phase. It is never skipped and never marked `xfail`. Before an invariant's introduction phase, it may exist as an explicit `@pytest.mark.skip(reason="implemented in Phase N")` placeholder naming the correct future phase — but the file itself, and every placeholder, must exist from Phase 1 onward and must be visibly tracked, not silently absent.

## Cost control (enforced from Phase 0, owned by E3 but binding on everyone)

1. Every Cloud Run service deploys with `--min-instances=0`. Never overridden.
2. `--max-instances=2` initially.
3. Model tier routing enforced in code (`reasoning/model_router.py`): Flash for ingestion/normalization/routing/classification; Pro-tier only for the named hard reasoning steps (implication, valuation extraction, branch simulation/critique, council specialist reasoning, blocker diagnosis, voice interaction, cross-script entity resolution on ambiguity). A Pro-tier call from a non-allowlisted agent is a **test failure**, not a warning.
4. Elevated thinking budgets are opt-in per agent, never global.
5. Local development uses Firestore and Pub/Sub **emulators** — no cloud spend day to day.
6. `infra/teardown.sh` scales to zero; run after every proof capture.
7. **No Dockerfile anywhere in this repository, ever.** Cloud Run uses source deploys via buildpacks (`gcloud run deploy --source .`).

## Definition of done — every phase

- [ ] All assigned work items complete
- [ ] `ruff check` + `mypy --strict` clean (backend)
- [ ] `eslint` + `tsc --noEmit` clean (frontend)
- [ ] All tests pass; coverage targets met
- [ ] `test_safety_invariants.py` passes, with the phase's new invariants added
- [ ] No new `docs/DEBT.md` entries without CTO approval
- [ ] `contracts/` matches implementation, proven by contract tests
- [ ] ADR written for every non-obvious decision
- [ ] Green-Light Gate demo runs end-to-end
- [ ] CTO Review Checklist signed

## File ownership — hard, not advisory

An engineer may not edit files outside their owned directories (see each role's own agent definition in `.claude/agents/`). Needing a change elsewhere means raising it to `cto`, who makes it or assigns it. This is what makes parallel execution across E1-E4 safe — skipping it produces a reconciliation phase nobody planned for.

| Role | Owns |
|---|---|
| `cto` | `contracts/`, `docs/adr/`, `README.md`, `PHASES.md`, `verification.md`, root config |
| `e1` | `backend/app/graph/`, `persistence/`, `audit/`, `solvers/`, `migrations/`, `seeds/` |
| `e2` | `backend/app/agents/`, `reasoning/`, `prompts/` |
| `e3` | `backend/app/tools/`, `adapters/`, `events/`, `voice/`, `infra/`, `scripts/` |
| `e4` | `frontend/` |

## Phase gating — the operator's standing rule for this project

One phase at a time. Never start a phase whose dependencies have not passed their own gate. Never bundle work across phases even if it looks efficient. At the end of each phase, the CTO writes a summary into `verification.md` (append-only, one section per phase) and the operator reviews it before authorising the next phase — see the `gharos-gate-review` skill for how that review is actually run.
