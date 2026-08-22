---
name: gharos-tool-permissions
description: Use whenever implementing or reviewing a tool, a permission tier, an approval gate, a risk tier, or any code path where an agent's output could lead to a real-world effect. Load before writing anything in backend/app/tools/, before wiring a new agent's tool access, or before a gate review checking secure tool isolation.
---

# Tool inventory, permission tiers, and risk tiers — complete reference

Full source: `GharOS_Build_Spec_v2.md` §16 (tools/permissions) and §18 (human-in-the-loop policy). This is the architectural core of the 30%-weighted "secure tool isolation" rubric criterion — treat every rule here as load-bearing.

## Permission tiers (spec §16.1) — what a tool is allowed to do

| Tier | Capability | Who may invoke |
|---|---|---|
| **T0 — Read** | Graph read, documents, statements | Any reasoning agent (subgraph-scoped) |
| **T1 — Search** | External research, business hours, provider discovery, merchant terms | Grounding, Discovery, Unblocker, Leakage agents |
| **T2 — Draft** | Compose messages, forms, claims, briefs (no send) | Drafting agents |
| **T3 — Internal write** | Graph writes, calendar entries | Writer agents only |
| **T4 — External communication** | Send messages outside the household | **Approval Gate only** |
| **T5 — Voice (outbound)** | Place outbound calls | **Approval Gate only, within authorised bounds** |
| **T5i — Voice (inbound)** | ASR, TTS, speaker ID for household interaction | Voice agents; confers **no action capability of its own** |
| **T6 — Financial** | Execute payment, pause/cancel mandate | **Approval Gate only, after explicit human approval** |

## The tool list by tier (spec §16.2)

- **T0:** graph reader (subgraph-scoped) · document store reader · statement/SMS archive reader · calendar reader · outcome history reader · transcript reader
- **T1:** web research (citation-returning) · provider/places search · business hours lookup · merchant terms lookup · availability lookup
- **T2:** message composer · form pre-filler · claim/dispute composer · decision brief composer · call-script composer
- **T3:** graph writer (provenance-enforcing) · calendar writer · outcome recorder
- **T4:** message sender (approval-gated) · form submitter (approval-gated)
- **T5:** outbound voice caller (approval-gated, bounds-enforced, disclosure-enforced)
- **T5i:** streaming ASR (multilingual, code-mix tolerant) · TTS (four languages) · speaker identification · pronunciation store
- **T6:** payment executor (approval-gated, idempotency-keyed) · mandate pause/cancel (approval-gated) · refund/claim submitter (approval-gated)
- **Deterministic computation tools (not LLM):** fairness solver (Nash welfare / competitive equilibrium) · Council mechanism arbiter (deterministic by design — this is what prevents the Council degenerating into LLM consensus-generation) · salary calculator (days − absences − advances) · calibration/variance calculator · deterministic conflict detector (runs before the reasoning pass) · idempotency key generator · graph integrity checker

## Isolation invariants — enforced structurally, proven by test, not by review comment

1. No agent holds both money-analysis (T0 on the Ledger subgraph) and financial (T6) capability.
2. T4, T5, and T6 are reachable **only** through the Approval Gate.
3. Every T3/T4/T5/T6 invocation writes an AuditRecord **before** execution.
4. T6 invocations carry an idempotency key; replays are no-ops.
5. T5 invocations carry authorised bounds; out-of-bounds requests terminate the call politely.
6. Council specialists have **mutually distinct** T0 subgraph scopes — enforced, not conventional.
7. Inbound voice (T5i) confers **no action capability**. A voice utterance is an input; it must pass through the same arbitration and approval path as any other input. **R3 money actions are never approved by voice alone.**

A reasoning agent (anything under `backend/app/agents/`) must have literally no importable path to `contracts.tools.ApprovalGatedTool` or any concrete T4/T5/T6 tool class. This is what "structural" means here — not a runtime permission check that could be bypassed, but an import graph a static test can assert against.

## Risk tiers (spec §18.1) — what happens to a proposed action

| Tier | Definition | Policy | Examples |
|---|---|---|---|
| **R0 — Silent** | Reversible, internal, no external effect | Execute; log | Graph write, calendar entry, information prep |
| **R1 — Notify** | Reversible, low-impact, visible | Execute; notify | Draft message, propose menu substitution, shopping list |
| **R2 — Approve** | External communication, non-financial | Require approval | Send message outside household, submit form, **place a call** |
| **R3 — Explicit approve** | Any movement of money | Require approval + evidence bundle | Pay dues, pay salary, cancel mandate, file dispute |
| **R4 — Escalate only** | Irreversible, high-stakes, emotionally loaded | **Never auto-execute; present options only** | Relocation, property purchase, care arrangements, ending staff employment, medical choices |

**Rules (spec §18.2):**
- Confidence below threshold downgrades an action at least one tier.
- Hard-constraint involvement forces at least R2.
- Approval expiry escalates; **never auto-approves.**
- Every approval request carries: proposed action, reasoning, evidence consulted, confidence, consequence-if-wrong (`contracts.actions.EvidenceBundle`).
- Overrides are captured with reason and fed back into the relevant model.
- The Council never resolves R4 — it produces a brief; humans decide.
- **Demo requirement:** the approval gate must be visible. Never show the agent spending money or placing a call without a visible confirm.

## Idempotency and failure tolerance (spec §19)

Every action carries a key from `(entity-ID, action-type, cycle/period)` — `contracts.actions.IdempotencyKey`. Replays are no-ops returning the original result. Payments are strictest: one debit per due-ID per cycle, enforced at the **tool** level, not the agent level. Demonstrate it: kill a run mid-flight, restart, show no duplicate.

Worker failure: sub-agents are time-boxed; hung or looping agents terminated, absence handled by the orchestrator. Parallel branch simulation and council reporting proceed on survivors; failures are reported, never hidden. **A failed tool call never produces a fabricated success** — a hallucinated "claim submitted" or "appointment booked" is worse than a reported failure. Reconciliation mismatches enter the dispute branch. Call failures enter the fallback ladder.

Long-running workflows checkpoint at named stages (claim awaiting response, due awaiting payment, callback pending); resume is safe because of idempotency.

## Ingestion adapters and their fragility (spec §17)

| Adapter | Fragility | Notes |
|---|---|---|
| Email | Low | Most reliable |
| Document upload | Low | Best demo surface — visibly messy |
| SMS / UPI alerts | **High — no official personal-data API** | User-forwarded or notification access; be transparent |
| WhatsApp | **High — no personal-data API** | Chat export, screenshot, forwarding; be transparent |
| Portal notification | Medium | |
| Voice inbound (telephony) | Medium | Pairs with Concierge |
| Voice inbound (household) | Low-Medium | Primary interface, multilingual, code-mix tolerant |
| Scheduled tick | Low | Cloud Scheduler |
| Manual intention | Low | |

**Honesty requirement:** state the WhatsApp/UPI API limitation plainly in the submission and demo. A judge who discovers an overclaimed integration discounts everything else; a team that states the limitation and shows a clean adapter abstraction reads as rigorous.

## Security, privacy, legal constraints (spec §23) — binding on every tool and adapter you write

- All demo data is synthetic — no real family data, no real financial credentials, no real medical records.
- Financial credentials never touch a reasoning agent — only the gated payment tool, targeting a **sandbox** in the hackathon build.
- Staff data (attendance, salary, advances) is employment data about a third party who has not consented to an AI system — acknowledge explicitly.
- Medical information is read-only context for scheduling and care-gap detection; the system **never advises on medical decisions.**
- Children's data warrants the strictest handling; a minor's delegate agent in the Council represents scheduling and welfare interests only.
- Voice calls: disclosure of automated-assistant status is mandatory, non-configurable. Recording consent law varies by jurisdiction — meet the stricter standard. Automated calling may violate some providers' ToS. **For the demo, call a controlled/sandbox counterparty, not a real business, and say so honestly.**
- Provenance retention is a privacy trade-off (auditability vs. retaining sensitive originals) — state the retention policy explicitly wherever it's implemented.
