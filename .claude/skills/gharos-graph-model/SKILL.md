---
name: gharos-graph-model
description: Use whenever reading, writing, designing, or reviewing anything that touches the GharOS Household Knowledge Graph — node types, edge types, the Document-Type Registry, provenance rules, verification documents, or graph query operations. Load before implementing a repository, an extractor, a graph-writing agent, or any UI that renders graph data.
---

# The Household Knowledge Graph — complete reference

Full source: `GharOS_Build_Spec_v2.md` §5. This skill is the complete node/edge/registry model condensed for implementation reference — consult the source section directly for anything not covered here.

## Why a graph, not a database

The design reference is Graphify's core discipline: **the answer is a path, not a vibe.** Every edge is tagged with how it is known, and every conclusion can be traced as a walk through real, auditable relationships. Three properties a flat state model cannot give: multi-hop reasoning ("what breaks if we move in June?" is a traversal, not a query), explainability by construction (every recommendation is a subgraph, not a paragraph), institutional memory (two years later, "why did we choose that school?" returns the actual decision node with its branches, council positions, who conceded what, and the outcome).

## The 18 node types

| Node | Key fields | Notes |
|---|---|---|
| **PERSON** | identity, aliases (WhatsApp name, email, school records, nicknames), role (adult/child/elder/staff/extended), availability model, capability flags (can drive, can sign, has bank access, has medical proxy), contact channels, language profile, voiceprint ref, pronunciation hints, derived friction/valuation/load-history profiles | Household members, staff, extended family |
| **CONSTRAINT** | kind (dietary/medical/schedule/financial/religious/legal/custody/mobility), hard vs soft, validity window, structured form + original natural language | Original text is never discarded |
| **OBLIGATION** | title, type, due datetime, computed must-start-by, effort estimate, status (derived→assigned→prepared→in-progress→completed→dropped→superseded), **derivation: stated \| implied** | The stated/implied field is the flagship Consequence Engine distinction |
| **LEDGER_EVENT** | debit/credit/due/mandate-created/mandate-cancelled/price-change/refund/salary/advance | |
| **RECURRING_COMMITMENT** | label, counterparty, amount, cadence, price history, last-used signal, status | |
| **VENDOR** | category, contacts, job history, reliability score, response latency | |
| **PROVIDER** | ratings, distance, availability, price band, specialisations, interaction history with this household | External service candidates — dentists, clinics, dealerships, schools, contractors |
| **DECISION** | question, trigger, status, resolution, rationale | **Permanent record. Never pruned, ever.** |
| **BRANCH** | one option within a Decision, projected impacts, grounding refs, critiques | |
| **COUNCIL_POSITION** | one agent's stance, reasoning, evidence | What makes the Council auditable rather than mystical |
| **OUTCOME** | predicted vs actual, variance, attribution tags | Calibration substrate for the Simulator |
| **SOURCE_DOCUMENT** | raw payload reference, channel, extraction record | Every derived node points back here |
| **ACTION_RECORD** | what the system did, when, under whose approval | |
| **APPROVAL_REQUEST** | proposed action, evidence bundle, risk tier, confidence, status | |
| **PURCHASE_ITEM** | description, normalized product category, quantity, unit price, line total | **The finest-grained evidence node in the system** |
| **PATTERN** | a mined regularity, e.g. "Dad's appointments always slip when scheduled on Mondays" | |
| **ATTENDANCE_RECORD** | staff person id, month (`"YYYY-MM"`), rollup counts (present/absent/leave/total), real per-day marks, advance annotations (cross-reference only) | Added Phase 7, ADR-013 — DEBT-004's repayment; month granularity, not per-day, since the salary calculator's whole query shape is "one person, one pay cycle" |
| **VALUATION_PROFILE** | person id, costs (task id → cardinal cost, sparse by omission), elicitation method (interview/complaint_inference/observed_history/mixed) | Added Phase 8, ADR-014 — the Fair Allocator's deterministic solver's real input |

## The 35 edge types

*(The spec §5.3 table below has 29 rows, same as spec v2's original — but `supports`/`opposes` is one row for two distinct enum members, so the actual original `EdgeType` member count was 30. ADR-005 (Phase 1) removed `argued_by` — `AGENT` is not a graph node type, so `argued_by` (COUNCIL_POSITION → AGENT) could never resolve; `CouncilPosition.held_by_agent: AgentId` already carries this information directly on the node — bringing it to 29. ADR-009 (Phase 3) added `covers` (OBLIGATION → PURCHASE_ITEM) — spec §5.4.2's WARRANTY entry names this relationship explicitly ("links back to the originating RECEIPT's PURCHASE_ITEM") but the original table never gave it its own edge type — bringing it back to 30. ADR-012 (Phase 5) added `acts_on`, `authorizes`, and `approved_by` — DEBT-002's repayment, the first edges ever connecting ACTION_RECORD/APPROVAL_REQUEST to anything — bringing it to 33. ADR-013 (Phase 7) added `attendance_of` (ATTENDANCE_RECORD → PERSON) — DEBT-004's repayment — bringing it to 34. ADR-014 (Phase 8) added `valuation_of` (VALUATION_PROFILE → PERSON) — bringing it to 35, five more than the table below shows.)*

| Edge | From → To | Meaning |
|---|---|---|
| `states` | SOURCE_DOCUMENT → OBLIGATION | Literally present in the source |
| `implies` | SOURCE_DOCUMENT → OBLIGATION | Derived by reasoning |
| `owned_by` | OBLIGATION → PERSON | Assignment |
| `benefits` | OBLIGATION → PERSON | Who it's for |
| `conflicts_with` | OBLIGATION → OBLIGATION \| CONSTRAINT | Detected collision |
| `violates` | OBLIGATION → CONSTRAINT | Hard/soft violation |
| `depends_on` | OBLIGATION → OBLIGATION | Sequencing |
| `supersedes` | OBLIGATION → OBLIGATION | Replacement on update |
| `completes_into` | OBLIGATION → OUTCOME | Completion record |
| `belongs_to` | LEDGER_EVENT → RECURRING_COMMITMENT | Series membership |
| `owed_to` | LEDGER_EVENT → VENDOR \| PERSON | Counterparty |
| `paid_for` | LEDGER_EVENT → OBLIGATION | Settlement |
| `contains` | DECISION → BRANCH | Option set |
| `supports` / `opposes` | COUNCIL_POSITION → BRANCH | Stance |
| `grounded_in` | BRANCH \| POSITION → SOURCE_DOCUMENT \| external ref | Evidence |
| `resolved_as` | DECISION → BRANCH | What was chosen |
| `conceded_by` | DECISION → PERSON | Who gave ground — fairness memory |
| `predicted_by` | OUTCOME → BRANCH \| PATTERN | Calibration link |
| `constrains` | CONSTRAINT → PERSON | Ownership |
| `booked_with` | OBLIGATION → PROVIDER | Outbound execution |
| `learned_from` | PATTERN → OUTCOME[] | Pattern derivation |
| `line_item_of` | PURCHASE_ITEM → LEDGER_EVENT | Item belongs to this transaction |
| `discharges` | PURCHASE_ITEM \| LEDGER_EVENT → OBLIGATION | This purchase completed that obligation |
| `verifies` | PURCHASE_ITEM → CONSTRAINT | Real-world evidence the constraint is being honoured |
| `contradicts` | PURCHASE_ITEM → CONSTRAINT | Evidence it is being violated |
| `absent_from` | CONSTRAINT → SOURCE_DOCUMENT[] | Expected evidence never appeared — silent non-compliance |
| `substitutes` | PURCHASE_ITEM → PURCHASE_ITEM | Bought instead of the planned item |
| `evidences_effort` | PURCHASE_ITEM \| LEDGER_EVENT → PERSON | Who actually did this run — behavioural valuation input |
| `covers` | OBLIGATION → PURCHASE_ITEM | Added Phase 3, ADR-009 — a warranty claim-or-lose obligation back to the purchase it protects |
| `acts_on` | ACTION_RECORD → OBLIGATION \| LEDGER_EVENT \| VENDOR \| PROVIDER \| RECURRING_COMMITMENT | Added Phase 5, ADR-012 — the "what" an executed action affected |
| `authorizes` | APPROVAL_REQUEST → ACTION_RECORD | Added Phase 5, ADR-012 — the specific approval that authorized this specific executed action |
| `approved_by` | APPROVAL_REQUEST → PERSON | Added Phase 5, ADR-012 — who approved it, graph-traversal-visible (alongside `ActionRecord.approved_by`'s own scalar field) |
| `attendance_of` | ATTENDANCE_RECORD → PERSON | Added Phase 7, ADR-013 — the staff member one month's attendance record belongs to |
| `valuation_of` | VALUATION_PROFILE → PERSON | Added Phase 8, ADR-014 — whose cardinal cost matrix this is |

The seven `line_item_of` through `evidences_effort` are the **verification/receipt edges** — they are what closes the loop (see below) and they are frequently the ones a first draft forgets. `contracts/graph_types.py:EdgeType` is the frozen enum; never add an edge type there without going through the CTO.

## Provenance — the single most important discipline in the system

Every node and edge carries:
- `derivation`: **`extracted`** (found in the source — openable at a specific region) | **`inferred`** (reasoned from structure and context; usually right, worth checking) | **`ambiguous`** (evidence points more than one way, and the graph says so)
- `source_ref` — pointer to the SOURCE_DOCUMENT and the region within it
- `confidence` — numeric, 0.0-1.0
- `deriving_agent` — which agent produced it
- `created_at`, `superseded_at`

This turns "the agent decided" into "here is the path it walked," and it is what allows a human to check rather than trust. **A write missing any required field must be rejected by the repository at write time.**

## The Document-Type Registry — fourteen types, open registry (strategy pattern)

Each entry defines: type identifier + detection signals, field schema (with confidence floors per field), target nodes, target edges, downstream subsystems, verification duties. The registry is **open** — adding a type means adding a schema and an edge mapping, never modifying the pipeline.

| Type | Nodes created | Key edges | Notable rule |
|---|---|---|---|
| RECEIPT / ITEMISED BILL | LEDGER_EVENT, PURCHASE_ITEM (many) | `line_item_of`, `owed_to`, `discharges`, `verifies`/`contradicts`, `substitutes`, `evidences_effort`, `belongs_to` | Strongest verification document in the system |
| UTILITY / SERVICE BILL | LEDGER_EVENT, RECURRING_COMMITMENT | `belongs_to`, `owed_to` | Consumption data enables leak/anomaly detection, not just billing |
| SOCIETY / HOA NOTICE | LEDGER_EVENT?, OBLIGATION, CONSTRAINT? | `owed_to`, `constrains` | |
| SCHOOL / INSTITUTIONAL COMM. | OBLIGATION (multiple), candidate CONSTRAINT | `states`/`implies`, `benefits`, `violates` | The implication-rich case |
| PERMISSION SLIP / CONSENT | OBLIGATION (with capability requirement) | `owned_by` (capability-aware), `depends_on` | Signing authority matters |
| ATTENDANCE REGISTER (handwritten) | attendance records on STAFF PERSON | feeds salary computation — real `ATTENDANCE_RECORD` node + `attendance_of` edge since Phase 7 (ADR-013) | **Strictest confidence floors in the registry** |
| BANK / CARD STATEMENT | LEDGER_EVENT (many) | `belongs_to`, `owed_to` | Reconciliation ground truth |
| UPI / PAYMENT SMS ALERT | LEDGER_EVENT | `belongs_to` or flagged unmatched | Merchant strings notoriously opaque — low confidence must not drive cancellation alone |
| MEDICAL DOCUMENT | OBLIGATION (appointments/follow-ups), CONSTRAINT | `constrains`, `benefits` | **Never interprets clinical meaning, never advises, never adjusts medication** |
| INSURANCE DOCUMENT | RECURRING_COMMITMENT, OBLIGATION (renewal), CONSTRAINT | | Coverage limits feed Council Finance reasoning |
| WARRANTY / PURCHASE PROTECTION | OBLIGATION (claim-or-lose) | links back to originating receipt's PURCHASE_ITEM | Why receipt line-item extraction matters months later |
| GOVERNMENT / LEGAL NOTICE | OBLIGATION (high-consequence) | | Typically R2+ given consequence |
| QUOTE / ESTIMATE | PROVIDER, BRANCH (if part of active Decision) | | |
| CHAT / MESSAGE THREAD | OBLIGATION (from commitments), intention captures, valuation signals, staff leave records | | Most polymorphic input; requires speaker attribution + code-mixed handling |

**Routing rules:** classify type before extraction (misclassification > low-confidence extraction in damage). Ambiguous type → try the two most likely schemas, compare field-fill rates, escalate if still ambiguous. Multi-type match → extract under both, dedupe. Unknown type → generic extraction + human triage + logged registry gap. Every field carries a source-region pointer, always.

## Closing the loop: verification documents (spec §5.5)

Most inputs generate obligations pointing *forward*. Receipts, statements, and confirmations point *backward* — they are evidence of what actually happened, and they **close edges rather than opening them**. A grocery receipt simultaneously: settles the payment obligation (`discharges`), confirms or contradicts the shopping list (`substitutes` on a swap), writes real spend against the recurring series (feeding leakage detection with actuals), and verifies constraints against reality (`verifies`/`contradicts`).

The fourth is the non-obvious, highest-value one: **if the nut-free bread never appears on any receipt, the constraint the system believes it is honouring is not actually being honoured in the physical world.** Nothing else in the input set catches that — `absent_from` is a first-class signal, not a null result, and the Pattern Miner should surface it.

**Rule, always:** where a verification document contradicts a graph claim, the system never silently overwrites. It opens a discrepancy, presents both, and escalates. Silent correction destroys the audit trail that makes the whole system trustworthy.

| Document | Verifies |
|---|---|
| Receipt | Constraint compliance, obligation discharge, planned-vs-actual purchases, who did the work |
| Bank statement | That UPI SMS alerts were accurate; that payments the system believes it made actually cleared |
| Booking confirmation | That the Outbound Concierge's call achieved what it reported (required before recording) |
| Attendance register vs chat leave messages | That salary computation rests on consistent evidence |
| Delivery confirmation | That an ordered item arrived |

## The 14 graph query operations every subsystem depends on

| Operation | Used by | Example |
|---|---|---|
| `neighbours(node, edge_type)` | All | Obligations owned by Priya |
| `path(a, b)` | Path Explainer | Why does this email affect Tuesday's lunch? |
| `blast_radius(node, depth)` | Simulator, Council | What breaks if we relocate in June? |
| `conflicts(scope)` | Conflict Radar | All unresolved collisions this week |
| `load(person, window)` | Fair Allocator | Priya's obligation load this month |
| `series(commitment)` | Ledger | All debits in this recurring series |
| `history(entity)` | Calibration | All outcomes for school-run obligations |
| `decisions_touching(entity)` | Council | Every past decision involving the car |
| `concession_ledger(person)` | Council | Who has conceded most, historically |
| `unexplained(scope)` | Audit | Nodes lacking provenance — must be empty |
| `unverified(scope)` | Verification | Graph claims with no real-world evidence behind them |
| `expected_but_absent(constraint)` | Verification, Pattern Miner | Constraints the receipts never confirm |
| `spend_by_category(window)` | Ledger, Council Finance | Real spend from line items, not estimates |
| `effort_evidence(person, window)` | Fair Allocator | Who actually did the runs, from receipts and transactions |

## Firestore layout (see `docs/adr/001-firestore-edge-layout.md` for the full decision record)

One top-level collection per node type, document ID = NodeId, `provenance` embedded as a map. One flat top-level `edges` collection (not subcollections), composite indexes on `(from_id, edge_type)` and `(to_id, edge_type)`. `path`/`blast_radius` are repository-layer BFS/DFS, depth-bounded.

## Graph visualisation (spec §5.8) — the demo asset

Live force-directed rendering: nodes coloured by type, edges styled by derivation tag (solid = extracted, dashed = inferred, dotted = ambiguous), conflict edges in red. When a source document arrives, the graph must visibly *grow* in real time — this is the project's signature "holy shit" moment. **The graph must be built live from messy input during the demo — if it's hand-seeded, it's a database with a nice visualisation and a judge will sense it.**
