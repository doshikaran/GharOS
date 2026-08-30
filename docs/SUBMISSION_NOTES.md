# GharOS — submission notes (the honesty pass)

**Purpose.** This is the single document the Devpost write-up, the demo narration, and any judge Q&A draw their phrasing from. Every claim GharOS makes in the submission must be traceable to something in this file, and everything in this file is traceable to code, a test, or a deployment artifact. **Overclaiming discredits everything else** (spec §8.2, §27.1). Written and signed by the CTO at the Phase 15 write-up honesty pass, 2026-08-30.

Cross-references: `docs/FAIRNESS_GUARANTEE.md`, `docs/IMPLICATION_BASELINE.md`, `docs/DEPLOYMENT_PROOF.md`, `docs/DEBT.md`, `docs/adr/016`, `docs/adr/022`, `docs/adr/023`, `verification.md`.

---

## 1. What GharOS is, stated plainly

One household. Single-tenant. An event-driven autonomous system that turns the family's inbound stream (email, forwarded chat/SMS, photographed forms, bills, scheduled ticks, voice) into a provenance-tagged knowledge graph, reasons about what each item *implies*, assigns the resulting obligations, monitors them, watches the financial surface, executes real-world actions behind an approval gate, and convenes an internal council of specialised sub-agents for hard decisions. Conversation (voice/text) is an **escalation and input surface**, not the product — the primary loop runs with nobody present.

**Pitch order (do not violate):** lead with one concrete autonomous action, then the reasoning chain that produced it, then breadth as the demo proceeds, then the "operating system for the home" framing **last**, as a summary. Never open with the OS framing.

---

## 2. The fairness guarantee — exact, code-matching claim

**Claim, verbatim:** the Fair Allocator delivers **EF1 (envy-free up to one item) for chores under additive cost valuations, computed by fixed-order round-robin sequential picking.** For every ordered pair of people, after the solve, there exists one task in the person's own bundle whose removal brings their own cost for their bundle to no more than their own cost for the other person's bundle.

**What we explicitly do NOT claim:**
- **Not Pareto-optimal.** Round-robin's output can be Pareto-dominated; `solve_fair_allocation` does not search for a cost-minimal or welfare-maximal split.
- **Not Maximum Nash Welfare.** MNW gives EF1 + Pareto-optimality *for goods* (Caragiannis et al., EC 2016); that combined result does not transfer to chores, where a general EF1+PO existence result for additive costs is preprint-stage. We deliberately chose the algorithm whose chore guarantee is unconditional and completely verifiable (ADR-014).
- **No algorithmic novelty.** Round-robin picking sequences are textbook (Lipton–Markakis–Mossel–Saberi, EC 2004). Spliddit has shipped MNW since 2014. GharOS's contribution is the **input pipeline** — the auto-derived task list and the behaviourally-derived cost valuations (A18) — not the division algorithm.

**Where it is enforced:** `backend/app/solvers/fair_allocation.py::solve_fair_allocation`. Independently verified by `TestEF1ExternalVerification` in `backend/tests/test_fair_allocation.py` (a checker that duplicates none of the solver's internals) across four worked allocations; determinism by `TestDeterminism`. Capability constraints are applied before the round-robin loop (`OrphanedTaskError` on a task nobody can take), and the guarantee holds with respect to each person's valuation *restricted to the tasks they were capability-eligible for*. `docs/FAIRNESS_GUARANTEE.md` is checked word-for-word against the code at every Gate 8 review.

---

## 3. Ingestion — what is real and what is not

**No official personal-data API exists for WhatsApp or UPI.** GharOS relies on user-forwarded / exported data or device-notification access for those channels. The adapters (`email_adapter`, `sms_adapter`, `chat_export_adapter`, `document_upload_adapter`) normalise whatever the user hands over. This is stated openly; it is not implied away.

**Gmail and Google Drive** (Phase 14.5): real OAuth 2.0 (Authorization Code + PKCE), restricted scopes `gmail.readonly` + `drive.file`, running in **OAuth test mode** for the demo — this means a **7-day refresh token**, a **<100-user** cap, and no CASA security assessment. The demo must be recorded within 7 days of connecting the Google account. Refresh tokens live in Secret Manager keyed by principal, never in Firestore, never in an agent input (ADR-022).

**Outlook / Microsoft 365**: real Microsoft Graph OAuth, delegated `Mail.Read` + `offline_access`, standard user consent.

**Google Photos**: **Picker-only** — the user selects specific items. No photo-library sweep.

**Not possible from a deployed web app, and not claimed anywhere:** reading the local filesystem, Apple Photos, or iMessage. Those require a native desktop/mobile companion, which is a post-submission roadmap item, not a capability GharOS has. The demo does not show any of them.

**The ingestion path itself**: one synchronous `POST /ingest` entry → `IngestionOrchestrator` → per-source fetch → content-hash dedupe → raw-payload store → audit append → A2 route → A3/A3b/A3c extract → A5 entity resolution → registered strategy `map_to_graph` → `GraphWriter` (ADR-023). Idempotent per `compute_content_hash`: a re-scan of the same window writes zero new nodes. Real, proven end to end against the Firestore emulator by `test_ingestion_orchestrator.py::test_one_real_document_produces_provenance_linked_graph_nodes`. Live runs against real Gmail/Outlook accounts are code-complete and fully tested against fakes; they need operator-created OAuth credentials to exercise against the real providers (enumerated in `verification.md` § Phase 14.5).

---

## 4. The outbound-concierge counterparty is a sandboxed persona, not a real business

The "call" placed during the demo is a real, multi-turn conversation against a **sandboxed, independently-reasoning LLM persona** playing the dentist's receptionist — **never a real phone call to a real business** (ADR-016, spec §23, §27.1). What is genuinely real:
- The **automated-disclosure turn** — the agent states it is an automated assistant, and there is no model-call path that skips it.
- **Bounds enforcement** — A53 copies the human-approved bounds verbatim; A54 cannot agree outside them (adversarially tested).
- **Adaptation** — when the requested slot is "gone," the agent re-negotiates within authorised bounds.
- **Verification before recording** — A55's two-layer structural-then-semantic check can only turn a pass into a fail; an unverified booking is never written to the graph (proven by test).

The **audio** in the demo is a text transcript rendered on screen (ADR-016). Synthesised *speech* is a separate capability — the Phase 13 voice channel, Gemini native TTS (`gemini-2.5-flash-preview-tts`), verified live in four languages. If the demo plays synthesised audio over the concierge transcript, that is the Phase 13 TTS path applied to the transcript, and the narration should say so.

---

## 5. All demo data is synthetic

The household roster, the hard constraints, the 8–12 "ugly" documents, the three months of financial signals (including the engineered silent price hike, unused service, and duplicate charge), the OUTCOME history used for calibration, and the engineered verification receipt (discharges an open obligation + shows a substitution + is missing the nut-free item) are all **synthetic and engineered for the demo** (`backend/seeds/demo_household.py`). No real family's data, no real financial credentials, no real medical records. The graph is nonetheless **built live from that messy input during the demo** — it is not hand-seeded into its final shape; the seed is a starting household and the demo's documents are ingested and reasoned about on stage.

---

## 6. The implication agent — honest baseline

A12 Implication Agent was evaluated by hand by the CTO against 20 held-out documents it was never tuned on, using real live Vertex AI Gemini calls. **Report the v2 numbers** (`docs/IMPLICATION_BASELINE.md`, prompt `a12_implication_agent/v2.md`):

| Metric | Value |
|---|---|
| Recall (of 29 ground-truth implied obligations across 18 real-world documents) | **71%** |
| Hallucination rate — organic (real household documents) | **0%** |
| Hallucination rate — overall (incl. 2 designed "nothing implied" control documents) | **4%** |
| Citation validity (span is real, verbatim, *and* supports the specific claim) | **96%** |
| Designed control documents fully clean (0 fabricated obligations) | **1 of 2** |

**State it honestly:** the v2 prompt eliminated organic hallucination entirely, at a real cost of ~10 points of recall versus v1. One of the two control documents still produces a single "a child needs an adult to prepare X" candidate — a narrow, identified pattern, not systemic invention. **A12 is not claimed to be hallucination-free.** The load-bearing guarantee is that the *system* never acts on a hallucination: every A12 output passes through the A57 Confidence Arbiter, and anything that could become an action goes through the Approval Gate with an evidence bundle that surfaces the cited span for human review. This is tracked as **DEBT-007, monitoring status** (not struck — the original "0/2 control documents clean" bar is not met, and we do not pretend otherwise). See `docs/DEBT.md` for the full disposition.

Related: **DEBT-008** — the citation validator rejects a located span covering >60% of a short source document (an anti-"cite the whole email" measure), which can discard a correct citation from a very short message. This causes a miss, never a hallucination. During Phase 15 rehearsal, E2/E3 confirm no scripted short-source demo beat (the Hinglish voice utterance, any WhatsApp-screenshot beat) trips this and silently drops a citation the script expects on screen.

---

## 7. Cloud / cost posture

- **No `Dockerfile` anywhere in the repository.** Both Cloud Run services deploy from source via buildpacks. Verify: `find . -iname "Dockerfile*"` → empty. This is a gate item at Phase 2 and Phase 15.
- **`min-instances=0`** on both `gharos-api` and `gharos-web`, never overridden. `--max-instances=2`. Confirmed via `gcloud run services describe` (no "Min instances" line printed = default 0).
- **Model-tier routing enforced in code** (`reasoning/model_router.py`): Flash for ingestion/normalisation/routing/classification; Pro-tier only for the named hard-reasoning agents on the allowlist. A Pro-tier call from a non-allowlisted agent is a test failure.
- **Scale-to-zero after every proof capture** — `infra/teardown.sh` (`make teardown`). Revision history and Cloud Logging survive; compute cost goes to zero.
- Budget alert active on the real project (INR-denominated, `docs/DEPLOYMENT_PROOF.md`).

---

## 8. The overnight Cloud Logging run

**Status as of 2026-08-30: mechanism proven AND the genuine unattended overnight run captured** (`docs/DEPLOYMENT_PROOF.md` § "Phase 15 — Demo Hardening", Requirement 4(b)).

- Phase 14 captured a **real, unattended, Cloud-Scheduler-triggered firing** of the deployed nightly consolidation job — Scheduler → Pub/Sub publish → OIDC-verified push → a real `ConsolidationRunResult` → `204`, with real Cloud Logging timestamps (`docs/DEPLOYMENT_PROOF.md` Requirement 4). That firing was manually kicked to start the clock; everything after the trigger was a genuine unattended Cloud Run execution.
- Three Scheduler jobs are live and `ENABLED` and have been accumulating real firings on their own cron since 2026-08-29 (no teardown was run): `gharos-heartbeat-tick` (*/5 min), `gharos-consolidation-nightly` (03:00 IST), `gharos-followup-sweep` (07:00 / 19:00 IST).
- **Captured 2026-08-30 07:45Z (E3):** the accumulation window from the Phase 14 deploy (`gharos-api-00008-c6h`, `2026-08-29T16:02:18Z`) to capture is ≈ 15 h 43 m of continuous human-untouched operation, spanning the household's full overnight window. `gharos-consolidation-nightly`'s **natural `30 21 * * *` UTC cron fired at `2026-08-29T21:30:04Z` = 03:00 IST with no human involved** — full Cloud Logging trace with `message_id`, real timestamps, `204`. `gharos-followup-sweep` landed both natural twice-daily firings; `gharos-heartbeat-tick` recorded 187 firings in the window with zero misses. `min-instances=0` held throughout (no `minScale` annotation on either service). Re-capture any time with the read-only `./scripts/capture_deploy_proof.sh`. The honest `patterns_mined=0` / `constraint_promotion_wired=False` outputs (empty demo graph, DEBT-012) are shown, not suppressed.

---

## 9. Safety invariants — where each is enforced and proven

All eight have a **real, passing** test in `backend/tests/test_safety_invariants.py`. That file contains no `@pytest.mark.skip` and no `xfail` — verified by direct read at the Phase 15 audit. The only skipped tests in the entire backend suite (~12) are `live_gcp`-marked network tests (real Vertex AI / Secret Manager / TTS), which is by design.

| # | Invariant | Proving test(s) — all real, none skipped | Notes from the Phase 15 audit |
|---|---|---|---|
| **3** | Provenance on every node/edge | `TestInvariant3ProvenanceEnforcement` — incl. a **Hypothesis fuzz** over every non-empty subset of the five provenance fields being absent, run against the real Firestore-emulator `FirestoreGraphWriter`; the `AMBIGUOUS`-derivation `None` `source_ref` carve-out is tested; a rejected supersession is proven not to mutate the original. Full suite: `test_provenance_guard.py`, `test_provenance_guard_unit.py`. | Strong. This is the "structurally impossible to bypass" proof Gate 1 asked for, not example-based. |
| **2** | Audit before execute | `TestInvariant2AuditBeforeExecute` — `AuditGuardedAction.execute()` raises `AuditNotWritten` on a `None` `audit_ref`, against the real `FirestoreAuditLog`; the sanctioned `write_before_execute` path succeeds. Also `test_ingestion_orchestrator.py::test_audit_write_failure_blocks_every_graph_write` (audit-before-graph-write on the ingestion wire). Full suite: `test_audit_and_write_before_execute.py`. | Strong, structural. |
| **4** | Low confidence escalates | `TestInvariant4LowConfidenceEscalates` — catastrophic confidence (0.05) → `ArbiterDecision.DISCARD` (never `EXECUTE`); a low-confidence R1 `DRAFT_MESSAGE` (0.30) is downgraded to `RiskTier.R2_APPROVE` + `ArbiterDecision.APPROVE`. Depth: `test_confidence_arbiter.py` — **12 tests** read at this audit, covering the hard-constraint R2 floor, tier downgrade without a model call, the absolute discard floor at every tier, borderline→Pro-tier, `test_malformed_borderline_response_never_silently_proceeds`, and `test_unmapped_action_type_raises_rather_than_guessing`. | Adequate. Headline test is 2 examples but the backing suite is broad and includes the fail-closed cases. |
| **1** | Money reasoners hold no money tools | `TestInvariant1MoneyReasonersHoldNoMoneyTools` — an A28-shaped registry (T0 ledger-read only) refuses a T6 tool outright; **every** `GATED_TIERS` member (T4/T5/T6) is refused when registration is attempted from an agent-side location. Full suite: `test_tool_registry.py`. | Strong — covers all gated tiers, not just T6. |
| **5** | Financial / irreversible need approval | `TestInvariant5FinancialIrreversibleNeedsApproval` — a `GatedAction` for `PAY_DUES` constructed directly (bypassing the gate) raises `ApprovalRequired`; the only path that executes is `request_approval` then explicit `approve_and_execute` by a named person. Runs against the real Firestore-emulator reader/writer/audit/idempotency. Full suite: `test_approval_gate.py`. | Strong, structural — proves "never" means "cannot be constructed," not "we always remember to call the gate." |
| **7** | No fabricated tool success | `TestInvariant7NoFabricatedToolSuccess` — a `GraphWriteTool` over a writer that always raises returns **no** `ActionResult.success`; it raises `ToolFailure`. Also `test_ingestion_orchestrator.py::test_connector_failure_is_run_data_never_raised` (a connector auth failure becomes visible `ConnectorFailure` run data, never a fabricated empty success). Per-tool suites: `test_graph_write_tool.py`, `test_graph_read_tool.py`, `test_payment_tool.py`, `test_booking_write_tool.py`. | Strong. Headline test covers the graph-write tool; the payment and booking tools have their own no-fabrication suites — audit confirms those files exist. |
| **6** | No "debate" framing | `test_invariant_6_no_debate_framing` — a **repo-wide case-insensitive grep** over every `.py` under `backend/app/`, every prompt `.md` under `backend/app/prompts/`, and every test file except the two that define the rule. Also `test_council_structural_invariants.py::TestNeverSaysDebate`. | Real since Phase 12 (was a tracked `@pytest.mark.skip` placeholder before, closed for real by E2 — which also caught and fixed one genuine pre-existing violation in Phase 11 code). Independently re-grepped at this audit across `*.py/*.ts/*.tsx/*.md`: the only occurrences are the lint-rule tests themselves and the `/story` page rendering PHASES.md Appendix B's invariant list ("No debate framing"). Clean. |
| **8** | Voice confers no action capability | `TestInvariant8VoiceConfersNoActionCapability` — three parts: (a) an **AST import-boundary scan** proves no voice reasoning/infra module imports `app.arbitration` or a gated-tool symbol, except `routing.py`; (b) a sanity check that `routing.py` genuinely *is* that one sanctioned importer (not vacuously passing); (c) a maximally-affirmative R3 voice confirmation routed through `VoiceRouter.route` yields `outcome.kind == "approval_pending"` and **never** calls `ApprovalGate.approve_and_execute`. Extended by `TestInvariant8VoiceScanMailboxIsReadOnlyIngestionNeverAction` (Phase 14.5 — the spoken "scan my Gmail" intent carries no risk tier, is classified with zero model calls, routes only to a non-action callback) and `TestPhase145IngestionCredentialAndSpeakerBoundary` (an unidentified voice cannot trigger a private-mailbox scan). Full suites: `test_voice_session_manager.py`, `test_voice_agents_arbitration_boundary.py`, `test_voice_infra_arbitration_boundary.py`. | Real since Phase 13 (was a tracked skip before). Strong — structural import boundary + behavioural R3 proof + the Phase 14.5 speaker-identity gate. |

**No invariant's test is weak, skipped, or trivial.** All eight headline tests were read line by line at this audit and each exercises the real mechanism against the real emulator or a real AST/grep scan — not `assert True`, not an always-passing mock. Backing suites (`test_confidence_arbiter.py`, `test_tool_registry.py`, `test_approval_gate.py`, `test_provenance_guard.py`, `test_audit_and_write_before_execute.py`, `test_council_structural_invariants.py`, `test_voice_session_manager.py`) were spot-checked for breadth and are substantial.

---

## 10. Track-eligibility check (spec §3.1) — PASS

**GharOS is ONE household agent with specialised sub-agents, single-tenant.** Audited across all 15 phases at the Phase 15 review:

- **No agent registry.** The only things named "*Registry*" are `ToolRegistry` (a per-agent permission-tier gate on *tools* — an isolation mechanism, the opposite of a discovery registry), `DocumentTypeRegistry` (the spec-mandated open strategy registry for the 14 document types), and `RegistryGapLog` (logs unknown document types for human triage). None is an agent registry or a discovery/federation mechanism.
- **No cross-household discovery, no multi-tenant governance.** Grep for `agent_registry` / `cross-household` / `multi-tenant` / `tenant_id` / `federation` / `marketplace` across `backend/app/`, `frontend/`, and `contracts/` returns nothing but the comment in `contracts/events.py` that *forbids* them.
- **`household_id` is a single-value future seam, used single-tenant.** It exists on `InboundEnvelope`, `AgentInput`, and `IngestionRequest`, and every runtime path resolves it to one constant (`DEMO_HOUSEHOLD_ID = "gharos-demo-household"`). `contracts/events.py` documents this explicitly: "deployment MUST use exactly one value for it. No agent registry, no cross-household discovery."
- **The Council is an internal deliberation mechanism**, framed that way consistently in code, ADR-019, the diagrams, and UI copy — five sub-agents reading disjoint scopes of *one household's* graph, resolved by deterministic code. It is never a federation of institutional agents.
- **A Taskmaster that also converses** (the voice channel) reads as correct escalation design, not scope creep — voice enters the demo at 2:20, after autonomy is established, and stays a 20-second beat.

Nothing built across the 15 phases drifts GharOS toward the excluded *Fortified Enterprise Fleet* shape.

---

## 11. What the demo actually demonstrates — and what needed a human

Be specific in the outcome beat (spec §24, 3:25–3:40). Report, honestly:
- Obligations **derived** vs. obligations **stated** (implied count is the headline — target ≥5 implied from the field-trip document, each with a valid source-span citation).
- Conflicts caught that would otherwise have surfaced too late (the temporal 1:30-vs-1:00 collision; the nut-allergy hard-constraint violation against Tuesday's menu).
- Money identified (the silent price hike, the unused service, the duplicate charge).
- Actions completed **end-to-end with no human touch** — count them precisely. If this number is near zero, the autonomy story is not demonstrated and the track decision must be revisited (spec §3.1 track-switch condition).
- Actions that **required approval** and were shown going through the Approval Gate — say so plainly. The booking (R2, and R3 if it carries a deposit), any payment, any outbound message to a non-household person.
- One real booking, verified before it was recorded.
- The live exception beat: the ambiguous child-name document where the agent **did not guess** on a hard-constraint-bearing entity and escalated with the image and its reasoning. **Knowing when not to act is the point.**

---

## 12. Deferred items carried into submission

`docs/DEBT.md` is not empty, but every open entry carries a dated CTO disposition explaining why deferring past submission is honest, why no demo beat depends on the missing capability, and why the write-up does not claim it. **Struck across Phases 14.5–15:** DEBT-009 (end-to-end orchestrator, 14.5), DEBT-013 (staleness-rule duplication removed, 15), DEBT-004 (photographed register → provenance-chained `AttendanceRecord` through the production strategy on the real wire, 15). Remaining open: 005, 006, 007, 008, 010, 011, 012. In one line each:

- **004 (STRUCK)** — the production `AttendanceRegisterExtractionStrategy` now builds a real `AttendanceRecord` + salary `Obligation` + `implies` edge; `test_attendance_register_ingest_wire.py` drives an image through the real `IngestionOrchestrator` and asserts the provenance chain, audit-before-write, and an integrity-clean graph. The AMBIGUOUS-marks safety gate (an uncertain mark never feeds a salary) is intact. The write-up may claim extract → map → graph-write end to end for a photographed register.
- **005 / 006** — resource-conflict and travel-time-aware conflict detection: not demo beats; write-up lists temporal / constraint / capability / load conflicts as demonstrated, resource / geospatial as designed-not-demonstrated.
- **007** — A12 "nothing implied" recognition: disclosed monitoring item; real numbers reported; system-never-acts-on-a-hallucination is the guarantee.
- **008** — short-document citation blind spot: causes a miss not a hallucination; rehearsal check that no scripted beat trips it.
- **010** — A31 follow-up has no durable producer: no multi-day recovery-loop beat in the demo.
- **011** — Council per-decision `ValuationProfile` not an addressable node: persists losslessly as evidence; no in-place-correction beat.
- **012** — automatic nightly constraint-promotion / vendor-scoring not wired: the overnight beat is A10/A11 firing unattended, which works.
- **013 (STRUCK)** — staleness rule now has one definition (`app.solvers.staleness`); `intention_capture_agent` imports it; equivalence + no-reappearance tests added.
