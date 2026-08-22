---
name: gharos-agent-roster
description: Use whenever implementing, reviewing, or reasoning about any of the 69 named GharOS agents (A0-A69) — their model tier, forbidden list, input/output contract, or which subsystem they belong to. Load before writing an agent, before a gate review that checks an agent didn't do something on its forbidden list, or when deciding which existing agent should own a new piece of reasoning.
---

# The complete 69-agent roster

Full source: `GharOS_Build_Spec_v2.md` §15. Design rule throughout: **one responsibility per agent, explicit input/output contract, explicit forbidden list.** Reasoning agents never hold action credentials. Model tier (Flash/Pro/Deterministic) is part of each agent's contract, not an implementation detail — see `backend/app/reasoning/model_router.py`'s allowlist.

## Orchestration (2)

**A0 — Household Coordinator.** Root orchestrator. Routes normalized events to subsystem pipelines, sequences them, manages run state. Pro-tier. *Forbidden:* extraction, deep content reasoning, external action. *Failure:* unroutable → human triage queue.

**A1 — Priority Arbiter.** When multiple subsystems claim the same event or resources contend, decides ordering by urgency and consequence. Flash. *Forbidden:* performing the work it schedules.

## Intake layer (8)

**A2 — Intake Router.** Classify channel and content type; assess relevance. Flash. *Forbidden:* extraction, implication, action. *Failure:* unknown type → human triage, never silent discard.

**A3 — Document Extraction Agent (multimodal).** Extract structured content applying the schema from the Document-Type Registry for the classified type. Field-level confidence and source-region pointers. Flash for clean, Pro-tier for degraded/handwriting. *Forbidden:* **inferring anything not literally present** — extraction and implication are separate agents by design. *Failure:* below threshold → mark ambiguous, retain image, surface. Registry gap → generic extraction + human triage + log the gap.

**A3b — Line-Item Extraction Agent.** Sub-extractor for receipts/bills/statements: per-line description, quantity, unit price, total, tax; product-category normalisation across merchants. Pro-tier multimodal for degraded thermal receipts. *Forbidden:* inferring items not printed, guessing quantities. *Failure:* partial extraction acceptable and flagged; fabricated lines are poison.

**A3c — Verification Agent.** Given a verification document, checks what it confirms or contradicts in the graph. Pro-tier. *Outputs:* `verifies`/`contradicts`/`absent_from` edges, discrepancy records. *Forbidden:* **silently overwriting a contradicted graph claim** — always opens a discrepancy and escalates.

**A4 — Message Normalization Agent.** WhatsApp exports/screenshots, UPI SMS, app notifications → normalized events. Multi-language, code-mixed. Flash. *Forbidden:* action, implication.

**A5 — Entity Resolution Agent.** Map mentions to graph nodes ("Amma", "Mummy", a phone number → one PERSON). Flash with Pro-tier escalation. *Forbidden:* creating entities above a confidence threshold without confirmation. *Failure:* never guess on hard-constraint-bearing entities — wrong child's allergy is a safety failure.

**A6 — Relevance Classifier.** Filter noise before expensive reasoning. Flash. *Forbidden:* discarding — low-relevance is logged, not deleted.

## Graph layer (5)

**A7 — Graph Builder.** Write nodes/edges with provenance, derivation, confidence. Deterministic + Flash. *Forbidden:* creating any edge without a provenance pointer.

**A8 — Graph Query Agent.** Translate subsystem information needs into traversals. Flash. *Forbidden:* interpreting results (the caller does that).

**A9 — Path Explainer.** Given a conclusion, produce the walkable path that justifies it, tagged by derivation type. Pro-tier. *Forbidden:* asserting anything not on the path.

**A10 — Pattern Miner.** Scheduled. Mine OUTCOME history for regularities → PATTERN nodes. Pro-tier. *Forbidden:* creating patterns below a support threshold.

**A11 — Graph Maintainer.** Scheduled. Supersession, staleness, orphan detection, integrity checks. Deterministic. *Forbidden:* pruning DECISION, OUTCOME, provenance, or hard-constraint nodes — ever.

## Consequence Engine (5)

**A12 — Implication Agent (flagship).** Derive obligations NOT stated. Pro-tier, elevated thinking. *Outputs:* candidate OBLIGATIONs with `implies` edges, confidence, mandatory source-span citation. *Forbidden:* writing graph directly, acting, producing an obligation without a citable span. *Failure:* uncitable → discarded, logged.

**A13 — Constraint Checker.** Evaluate candidates against hard/soft constraints. Flash for lookup, Pro-tier for interpretation ("does 'may contain traces' violate a nut allergy?" — yes, but that's judgment). *Forbidden:* resolving violations. *Failure:* hard-constraint ambiguity → always escalate.

**A14 — Conflict Radar.** Temporal, resource, capability, load conflicts. Pro-tier. *Forbidden:* unilaterally resolving multi-person conflicts.

**A15 — Obligation Writer.** Persist validated obligations with provenance; dedupe; supersession. Flash/deterministic. *Forbidden:* modifying content.

**A16 — Constraint Learner.** Detect repeated signals suggesting a new constraint. Pro-tier. *Forbidden:* writing hard constraints without human confirmation.

## Fair Allocator (5)

**A17 — Interviewer.** Adaptive comparative elicitation. Flash for flow, Pro-tier for question selection. *Forbidden:* computing valuations or assigning.

**A18 — Valuation Extraction Agent.** Complaints + interviews + voice notes + observed history → cardinal cost matrix. Pro-tier. *Forbidden:* solving. *Failure:* sparse matrix → request coverage, never fabricate values.

**A19 — Fairness Verifier / Explainer.** Verify the property holds; explain each share in that person's own valuations. Pro-tier for explanation; verification deterministic. *Forbidden:* altering the allocation. *Note:* verifies against an external checkable signal, deliberately avoiding LLM self-critique.

**A20 — Renegotiation Trigger.** Monitor for life events warranting re-allocation. Flash.

**A21 — Load Monitor.** Continuous fairness-over-time tracking; detects creeping imbalance between formal re-allocations. Flash.

## Intention→Action (5)

**A22 — Intention Capture.** Detect intentions expressed in passing; detect stale obligations. Flash. *Forbidden:* acting directly.

**A23 — Blocker Diagnosis Agent (core).** Six-type taxonomy (information / decision / window / first-step-ambiguity / dependency / aversion blocker). Pro-tier. *Outputs:* classification + explicit diagnosis shown to the user. *Forbidden:* unblocking.

**A24 — Unblocker / Preparation.** Fetch information, narrow decisions, pre-draft, decompose first steps. Flash retrieval, Pro-tier narrowing/drafting. *Tools:* read, search, draft. **No send without approval.**

**A25 — Window Scheduling.** Find windows where person AND counterparty are available AND historical patterns suggest completion. Flash with Pro-tier fallback.

**A26 — Slippage Analyst.** On repeat failure, re-diagnose; after N attempts escalate with options (drop / delegate / pay). Pro-tier.

## Household Ledger (8)

**A27 — Financial Signal Ingestion.** Normalize financial signals to LEDGER_EVENTs. Flash; Pro-tier multimodal for handwritten registers and degraded scans. *Forbidden:* reconciliation judgment, action.

**A28 — Reconciliation Agent (read-only by construction).** Match debits to series; detect recurrences/price changes/duplicates; reconcile dues; compute staff salary. Pro-tier matching, arithmetic delegated to a tool. *Tools:* **READ ONLY — no communication, no payment.** Architectural non-negotiable. *Failure:* mismatch → dispute branch.

**A29 — Leakage Detection.** The "worth reasoning" step — still wanted, given usage and priorities? Pro-tier. *Forbidden:* cancelling anything.

**A30 — Recovery Drafting.** Draft cancellations, disputes, claims, price-adjustment requests via learned per-merchant playbooks. Pro-tier. *Tools:* draft only. *Forbidden:* sending, moving money.

**A31 — Follow-up / Persistence.** Track open claims/requests; re-contact on cadence; escalate after N. Flash. *Note:* where autonomous persistence beats humans most decisively.

**A32 — Dispute Branch.** Assemble both conflicting figures with evidence for human resolution. Pro-tier. *Forbidden:* choosing which is correct.

**A33 — Vendor Relations.** Vendor request lifecycle, reliability scoring, switching proposals. Flash. *Tools:* communication (draft), read.

**A34 — Staff Payroll Agent.** Attendance → days worked → minus advances → salary due; leave/coverage tracking. Pro-tier for attendance interpretation; arithmetic deterministic. *Forbidden:* paying.

## Household Simulator (6)

**A35 — Decision Framing.** Clarify the real decision; detect false binaries; surface unconsidered options. Pro-tier.

**A36 — Grounding / Research.** Pull real external data per branch with citations. Flash retrieval, Pro-tier relevance. *Forbidden:* projecting consequences.

**A37 — Path Simulator (instantiated per branch, parallel).** Project one branch across the entire graph. Pro-tier, elevated thinking. *Forbidden:* comparing branches, self-assessing quality. **Parallel exploration, not debate.**

**A38 — Consistency Critic (adversarial).** Red-team each branch for wishful thinking, omitted second-order effects, optimism bias. Pro-tier, elevated thinking. *Note:* critiques *another* agent's output.

**A39 — Calibration Agent.** Adjust projections using this household's own OUTCOME variance. Pro-tier; statistics delegated to a tool. *Failure:* insufficient history → say so, never fabricate precision.

**A40 — Decision Synthesizer.** Assemble the brief; support interrogation. Pro-tier. *Forbidden:* recommending a choice on emotionally-loaded family decisions — presents trade-offs, not verdicts.

## Household Council (9)

**A41 — Council Convener.** Detect major-decision triggers; select which specialists and delegates to instantiate. Pro-tier. *Forbidden:* holding a position itself.

**A42 — Finance Specialist.** Ledger subgraph: affordability, existing commitments, EMI capacity, upcoming outflows. Pro-tier. *Tools:* ledger read only.

**A43 — Care Specialist.** Constraint/medical subgraph: mobility, access, proximity, care continuity. Pro-tier. *Tools:* constraint read only. *Note:* produces **hard constraints that eliminate options**, not scores.

**A44 — Education Specialist.** Education subgraph: exam years, admission cycles, transfer windows, catchment. Pro-tier.

**A45 — Logistics Specialist.** Obligation subgraph: real recurring trips, distances, capacity, parking. Pro-tier.

**A46 — Legal/Compliance Specialist.** Documentation, society rules, regulatory requirements. Pro-tier. *Forbidden:* giving legal advice — flags issues for professional review.

**A47 — Member Delegate (one per relevant household member).** Scores options against **that person's actual valuation profile** from the Fair Allocator. Pro-tier. *Forbidden:* inventing preferences not supported by the profile, speaking for anyone else. *Note:* the profile is visible and correctable by the person it represents.

**A48 — Council Adversary.** Attacks the leading option using household history. Pro-tier, elevated thinking. *Forbidden:* proposing alternatives (that's option generation).

**A49 — Council Recorder.** Write every COUNCIL_POSITION with evidence to the graph; record concessions. Deterministic. *Forbidden:* summarising positions into consensus.

*(The mechanism arbiter is a deterministic tool, not an agent.)*

## Outbound Concierge (7)

**A50 — Requirement Clarifier.** Query the graph first; ask only genuinely unknown things; detect urgency. Pro-tier. *Forbidden:* asking what the graph already knows.

**A51 — Service Discovery.** Find candidate providers by relevant location and service type. Flash. *Tools:* search, places.

**A52 — Provider Ranking.** Multi-factor transparent ranking including prior household experience. Pro-tier. *Outputs:* ranked list **with reasons**. *Forbidden:* opaque ranking.

**A53 — Call Planner.** Pre-call brief: objective, authorised bounds, disclosable facts, must-not-answer list. Pro-tier. *Forbidden:* setting bounds beyond what the human approved.

**A54 — Voice Call Agent.** Conducts the call. Pro-tier realtime. *Tools:* voice (approval-gated). *Forbidden:* agreeing outside authorised bounds, guessing answers, failing to disclose it is automated.

**A55 — Confirmation Verifier.** Cross-check the outcome against what was requested before anything is recorded. Pro-tier. *Forbidden:* **recording an unverified booking.**

**A56 — Fallback Coordinator.** Retry ladder, web-booking fallback, graceful escalation with everything pre-prepared. Flash.

## Voice interface (8)

**A62 — Voice Session Manager.** Owns the session: wake/PTT, turn-taking, barge-in, silence timeouts, multi-turn context, session close. Flash realtime. *Forbidden:* interpreting content. *Failure:* session corruption → close cleanly, re-prompt, never act on a partial turn.

**A63 — Speech Recognition Handler.** Streaming ASR, per-token confidence, code-mix tolerant, noise-robust. Gemini realtime. *Outputs:* transcript with token-level confidence and timing. *Forbidden:* "cleaning up" the transcript into fluent monolingual text — destroys the code-mixing signal and hides uncertainty. *Failure:* low confidence on consequential tokens → forces clarification.

**A64 — Language & Script Identifier.** Per-span (not per-utterance) language tagging; Hindi/Marathi disambiguation by lexicon and grammar, not script. Flash. *Failure:* ambiguous short utterance → fall back to speaker's primary_language, flag low confidence.

**A65 — Normalisation Agent.** Transliteration variance, numerals (lakh/crore, spoken amounts), dates, kinship terms → canonical forms. Pro-tier for ambiguous amounts. *Forbidden:* discarding the original text. *Failure:* ambiguous amount → always clarify, never round or guess.

**A66 — Speaker Identification Agent.** Who in the household is speaking. Flash. *Outputs:* PERSON reference with confidence. *Failure:* unknown speaker → **restrict to R0/R1 actions only** — never accept an approval from an unidentified voice.

**A67 — Voice Intent Classifier.** Capture / intention / command / query / approval / decision-trigger / correction. Pro-tier. *Forbidden:* executing — classifies and routes only.

**A68 — Confirmation Agent.** Enforces the read-back discipline: normalised forms, digit-grouped amounts, name-plus-relationship, explicit affirmative required. Pro-tier. *Forbidden:* **treating silence or ambiguity as approval.** *Hard rule:* R3 is never approved by voice alone.

**A69 — Voice Response Agent.** Spoken responses in the speaker's language and register, pacing adapted to the listener. Pro-tier + TTS. *Forbidden:* reading long lists aloud or narrating the graph — summarise and point to the visual surface.

## Cross-cutting (2 + services)

**A57 — Confidence Arbiter.** Evaluates every proposed action against thresholds; decides execute / approve / escalate / discard. Deterministic policy + Pro-tier for borderline. **Sits between reasoning and action and is the only path to action.**

**A58 — Escalation Agent.** Routes escalations to the right member (capability- and availability-aware) with enough context to decide. Flash.

**Services (not LLM agents):** Approval Gate (assembles evidence bundles, manages expiry — expiry escalates, never auto-approves); Audit Logger (immutable append, written before every action); Memory Consolidation (scheduled off-peak promotion of observations into consolidated knowledge).

## Working checklist when implementing any agent from this roster

1. Copy the agent's *Forbidden* list into your working notes before writing a line of its logic.
2. Design at least one test that would fail if the agent violated each forbidden item.
3. Confirm its model tier against `backend/app/reasoning/model_router.py`'s allowlist — a Pro-tier agent not on the allowlist, or a Flash agent silently escalating itself to Pro, is a defect.
4. Confirm its output satisfies `contracts.agents.AgentOutput` — citations populated where the agent makes a claim, `prompt_version` set, `derivation` set correctly.
5. If the agent is LLM-backed, its prompt lives under `backend/app/prompts/<agent_id>_<name>/`, versioned per ADR-003 — never inline in code.
