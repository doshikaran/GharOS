# GharOS — Master Build Specification v2

**Working title:** GharOS
**Hackathon:** Google "All Things Agentic" (Devpost) — submission window Aug 3–31, 2026
**Track:** **Taskmaster** (decided; rationale §3)
**Document status:** Build reference. No code. Every behaviour described is intended to be implementable as written.

**What changed from v1:**
- The Household State Model is promoted to a full **Household Knowledge Graph** (§5) — typed nodes, typed edges, provenance-tagged, walkable, explainable. It is now the substrate, not a database.
- New **Subsystem 6 — Household Council** (§12): genuine agent-to-agent deliberation for major decisions, built on specialization and conflicting interests rather than debate.
- New **Subsystem 7 — Outbound Concierge** (§13): the system acts in the outside world — discovers providers, clarifies requirements, ranks, calls, books, verifies.
- New **Document-Type Registry** (§5.4): fourteen typed extractors, each with its own field schema and its own edge mapping into the graph. Extraction is a registry, not one general extractor.
- New **verification-document model** (§5.5): receipts, statements and confirmations *close* edges rather than opening them, making the graph self-correcting. Includes the `absent_from` signal — expected real-world evidence that never arrived.
- New **Voice interface and multilingual operation** (§14): voice as a first-class input channel, with English, Hindi, Marathi and Spanish including intra-sentential code-mixing (Hinglish, Marathi-English).
- Agent roster expanded from 34 to 69 agents (§15), including line-item extraction, verification, and the voice pipeline.
- Graph query language, council protocol, and voice-call architecture fully specified.

---

## TABLE OF CONTENTS

1. What this document is and how to use it
2. Product definition
3. Track decision and rubric mapping
4. Positioning, pitch order, competitive differentiation
5. **The Household Knowledge Graph (the substrate)**
6. System architecture overview
7. Subsystem 1 — Consequence Engine
8. Subsystem 2 — Fair Allocator
9. Subsystem 3 — Intention→Action Converter
10. Subsystem 4 — Household Ledger
11. Subsystem 5 — Household Simulator
12. **Subsystem 6 — Household Council (agent-to-agent deliberation)**
13. **Subsystem 7 — Outbound Concierge (real-world execution)**
14. **Voice interface and multilingual operation**
15. Complete agent roster (69 agents)
16. Complete tool inventory and permission model
17. Ingestion adapters
18. Human-in-the-loop policy
19. Failure tolerance, idempotency, confidence handling
20. Memory, consolidation, and graph maintenance
21. Google stack mapping (mandatory requirements)
22. Observability and audit
23. Security, privacy, data handling, and legal constraints
24. The 4-minute demo script
25. Build sequencing
26. Demo data requirements
27. Known risks and open questions
28. Glossary

---

## 1. WHAT THIS DOCUMENT IS AND HOW TO USE IT

Single source of truth for building GharOS. Defines *what* each component does, *why* it exists, *what it reads and writes*, *how it fails*, and *where the human intervenes*.

**How to use while coding:**
- §5 (Knowledge Graph) is the contract. Everything reads and writes the graph. A feature that doesn't touch the graph probably doesn't belong.
- §15 (Agent Roster) is the build checklist. Each agent has one responsibility, an input contract, an output contract, and an explicit forbidden list.
- §16 (Tool Inventory) defines permission scoping. The isolation rules are the architectural argument for the 30% weight.
- §18 (HITL) and §19 (Failure Tolerance) define behaviour that must be demonstrable live.

**Non-negotiables — violating any of these damages the submission:**
1. No agent that reasons about money may also move money.
2. Every autonomous action writes an audit record *before* it executes.
3. Every derived node and edge carries a provenance pointer and a derivation tag.
4. Low-confidence outputs escalate; they never silently act.
5. Financial and irreversible actions require explicit human approval.
6. **Never frame agent-to-agent interaction as "debate."** It is specialization and interest representation (see §12.2).
7. A failed tool call never produces a fabricated success.

---

## 2. PRODUCT DEFINITION

### 2.1 One-line definition

GharOS is an autonomous household operating system. It ingests the messy multi-channel stream a family actually receives — school emails, WhatsApp threads, UPI SMS, scanned notices, bills, photographed forms — reasons about what each item *implies*, records everything in a walkable knowledge graph, assigns resulting obligations fairly, drives them to completion, watches the financial surface continuously, executes in the outside world (calls, bookings, claims), and convenes a council of specialized and interest-representing agents when a decision is genuinely hard.

### 2.2 The unifying thesis

Existing family software captures *events*. GharOS reasons about *consequences* and remembers *why*.

A shared calendar can tell you a field trip is Friday. It cannot tell you the nut-free requirement invalidates Tuesday's lunch, the ₹500 needs cash you don't have, the 1:30 pickup collides with a work meeting, the permission slip needs the parent who's travelling, and that the same person has absorbed the last eleven of these. And it certainly cannot tell you, two years later, *why* the family chose the school they did, what the trade-off was, and who conceded what.

GharOS does both: it automates the anticipation, and it keeps the reasoning.

### 2.3 Scope of the household

- **Children** — school/college commitments, fees, forms, exams, transport, extracurriculars, health
- **Adults** — work constraints, commitments, income, spend
- **Elderly members** — appointments, medication, specialist follow-ups, care coordination across siblings, insurance
- **Domestic staff** — attendance, salary, advances, leave, coverage
- **The dwelling** — society dues, maintenance, utilities, repairs, vendors, warranties
- **Financial surface** — recurring debits, autopay mandates, subscriptions, bills, dues, refunds
- **Major decisions** — vehicles, property, schools, relocation, care arrangements, large purchases

### 2.4 What GharOS is NOT

- Not a chatbot. Conversation is the escalation surface, not the product.
- Not a shared calendar. Calendars are an output.
- Not a budgeting app. The Ledger acts.
- Not a generic AI life assistant. Every capability anchors to a reasoning step a script cannot perform.
- Not a debate engine. See §12.2.

---

## 3. TRACK DECISION AND RUBRIC MAPPING

### 3.1 Track: Taskmaster

**Rationale:**
1. **BYOF strength.** An Indian urban household on WhatsApp, UPI mandates, informal domestic labour, society dues, elderly care and board-exam calendars is a highly defensible, non-generic friction.
2. **Competitive asymmetry.** Collaborative Partner rewards guided dialogue — where the largest field will cluster. GharOS's differentiator is that it works when nobody is talking to it.
3. **Graceful overflow.** A Taskmaster that also converses reads as correct escalation design. A Collaborative Partner that acts autonomously reads as scope creep.
4. **Council and Simulator resolution.** Under Taskmaster framing, both are what the autonomous system does when it hits a decision above its authority — serving the rubric's "know when *not* to act."

**Track-eligibility warning (actively manage):** A seven-subsystem multi-agent household OS with a council drifts toward *Fortified Enterprise Fleet* shape. That track is excluded. To stay in Taskmaster:
- Present as ONE household agent with specialized sub-agents and tools — not a fleet of independent institutional agents.
- Do NOT build or foreground an agent registry, cross-household discovery, or multi-tenant governance.
- The Council is an *internal deliberation mechanism*, not a federation of institutional agents. Frame it that way consistently.
- Keep everything single-household, single-tenant.

**Track-switch condition:** If at midpoint the count of actions completed end-to-end *with no human touch* is near zero, the autonomy story cannot be demonstrated — switch to Collaborative Partner rather than be graded harshly on absent autonomy.

### 3.2 Rubric mapping

**Innovation & Operational Utility — 40%**

| Rubric signal | How GharOS earns it |
|---|---|
| Eliminates real-world friction | Automates household cognitive labour — the best-evidenced pain in the research |
| Genuine "twist" | Consequence-chaining + walkable decision graph + interest-representing council |
| Autonomous execution over chat | Event-driven; primary loop runs with no user present; makes real outbound calls |
| Multi-step workflows | Every subsystem is a multi-stage pipeline with waiting and adaptation |
| Unusual/messy data | Handwritten registers, WhatsApp screenshots, UPI SMS, scanned notices, school PDFs |
| Bring Your Own Friction | Indian household operations, specific and personal |
| Unlikely Hero | The member silently carrying anticipation and monitoring |

**Architectural Discipline & Tech Stack — 30%**

| Rubric signal | How GharOS earns it |
|---|---|
| Multi-agent delegation justified by complexity | Seven distinct reasoning domains; council agents hold genuinely different information and interests |
| Separation of concerns | Reasoning agents cannot act; action tools cannot reason; enforced structurally |
| Robust state management | Provenance-tagged knowledge graph, versioned, walkable |
| Failure tolerance | Idempotency keys, confidence thresholds, dispute branches, escalation, call-failure recovery |
| Secure tool isolation | Payment and voice tools reachable only via Approval Gate |

**Demo & Production Readiness — 30%**

| Rubric signal | How GharOS earns it |
|---|---|
| Live proof it performed the task | Graph mutating live; a real booking confirmed; Cloud Run logs |
| Runs on Google Cloud | Cloud Run + Pub/Sub + Firestore + Cloud Scheduler visible in console |
| Handles a realistic exception | Scripted ambiguity → escalation; failed call → fallback, shown live |
| Reproducible | Architecture diagram + documented setup |

---

## 4. POSITIONING, PITCH ORDER, COMPETITIVE DIFFERENTIATION

### 4.1 Pitch order rule (critical)

**Never lead with "operating system for the home."** That phrase pattern-matches within ten seconds to *generic AI personal assistant* — an explicitly penalized category.

**Correct order:** one unmistakable autonomous action → the reasoning chain that produced it → breadth revealed as the demo proceeds → OS framing named last, as a summary of what was just shown.

Breadth *stated* upfront reads as vagueness. Breadth *demonstrated* after a concrete win reads as ambition.

### 4.2 Competitive landscape

| Competitor | Does | Does NOT do | Our wedge |
|---|---|---|---|
| Cozi | Shared family calendar | No reasoning, no action, no implication | We derive obligations, not store events |
| Ohai.ai | Parses dates from email to calendar | No consequence chaining, no conflict detection, no action | Full implication chain + acts |
| Jam / Hearth | Family calendar surfaces | Passive display | Autonomous background execution |
| Yohana (Panasonic, shut Sept 30 2025) | Human concierge for family tasks | Died on human-ops economics | Autonomy removes the cost structure that killed it |
| Milo (YC) | Human-in-loop family assistant | Same economics failure | Same |
| Rocket Money | Subscription detect + cancel | No refunds, price protection, bill audit, dues; surfaces a to-do rather than executing | Ledger executes recovery end-to-end |
| Spliddit | Fair division (Max Nash Welfare) | Requires manual valuation entry over a fixed list | Our valuations come from *observed behaviour*; task list auto-supplied |
| Graphify | Code knowledge graph with provenance | Codebases, not households | Same provenance discipline applied to family decisions |

**Yohana/Milo is a strong pitch asset:** they proved demand (Yohana reported helping 4,500+ families, users reporting 8–10 hours/week returned) and died because humans-in-the-loop don't scale economically. That is exactly the cost structure autonomy removes. This is the "why now."

**Spliddit honesty:** the fair-division math is not novel and is already shipped. Never claim the algorithm is new. Claim the input pipeline — automatic task list, behaviourally-derived valuations — which Spliddit structurally cannot do.

---

## 5. THE HOUSEHOLD KNOWLEDGE GRAPH (THE SUBSTRATE)

### 5.1 Why a graph and not a database

The design reference is Graphify's core discipline: **the answer is a path, not a vibe.** Every edge is tagged with how it is known, and every conclusion can be traced as a walk through real, auditable relationships.

Ported to a household this is not decoration — it is what makes autonomy trustworthy. When the agent moves a pickup, kills a subscription, books a dentist, or recommends a car, it can show the path it walked: `school_email#412 ──states──▸ nut_free_requirement ──violates──▸ tuesday_lunch_plan ──owned_by──▸ Priya`. A judge can audit it. A family member can challenge it.

Three properties a flat state model cannot give:
1. **Multi-hop reasoning.** "What breaks if we move in June?" is a traversal, not a query.
2. **Explainability by construction.** Every recommendation is a subgraph, not a paragraph.
3. **Institutional memory.** Two years later, "why did we choose that school?" returns the actual decision node with its branches, the council positions, who conceded what, and the outcome.

### 5.2 Node types

**PERSON** — household members, staff, extended family
- Identity, aliases (WhatsApp display name, email, school records, nicknames like "Amma")
- Role: adult / child / elder / staff / extended
- Availability model, capability flags (can drive, can sign, has bank access, has medical proxy)
- Contact channels
- **Language profile:** primary language, languages understood, script preference, code-mixing profile, formality preference, literacy mode (see §14.3)
- Voice: speaker voiceprint reference, pronunciation hints for the person's name
- Derived: friction profile, valuation profile, load history

**CONSTRAINT** — dietary, medical, schedule, financial, religious, legal, custody, mobility
- Hard vs soft, validity window, structured + original natural language

**OBLIGATION** — a unit of household work
- Title, type, due datetime, computed must-start-by, effort estimate
- Status: derived → assigned → prepared → in-progress → completed → dropped → superseded
- **derivation: stated | implied** (critical)

**LEDGER_EVENT** — debit, credit, due, mandate created/cancelled, price change, refund, salary, advance

**RECURRING_COMMITMENT** — label, counterparty, amount, cadence, price history, last-used signal, status

**VENDOR** — category, contacts, job history, reliability score, response latency

**PROVIDER** — external service candidates (dentists, clinics, dealerships, schools, contractors)
- Ratings, distance, availability, price band, specialisations
- Interaction history with this household

**DECISION** — a fork the household faced
- Question, trigger, status, resolution, rationale
- **Permanent record. Never pruned.**

**BRANCH** — one option within a Decision, with projected impacts, grounding refs, critiques

**COUNCIL_POSITION** — one agent's stance in a deliberation, with its reasoning and evidence
- **This is what makes the council auditable rather than mystical**

**OUTCOME** — predicted vs actual, variance, attribution tags
- The calibration substrate for the Simulator

**SOURCE_DOCUMENT** — raw payload reference, channel, extraction record
- Every derived node points back here

**ACTION_RECORD** — what the system did, when, under whose approval

**APPROVAL_REQUEST** — proposed action, evidence bundle, risk tier, confidence, status

**PURCHASE_ITEM** — a single line item extracted from a receipt or bill
- Description, normalized product category, quantity, unit price, line total
- Links to the LEDGER_EVENT that paid for it and, where applicable, to the OBLIGATION it discharges or the CONSTRAINT it verifies
- **The finest-grained evidence node in the system** — see §5.7

**PATTERN** — a mined regularity ("Dad's appointments always slip when scheduled on Mondays")

### 5.3 Edge types

Every edge is typed and directional:

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
| `argued_by` | COUNCIL_POSITION → AGENT | Who held this position |
| `supports` / `opposes` | COUNCIL_POSITION → BRANCH | Stance |
| `grounded_in` | BRANCH \| POSITION → SOURCE_DOCUMENT \| external ref | Evidence |
| `resolved_as` | DECISION → BRANCH | What was chosen |
| `conceded_by` | DECISION → PERSON | Who gave ground (fairness memory) |
| `predicted_by` | OUTCOME → BRANCH \| PATTERN | Calibration link |
| `constrains` | CONSTRAINT → PERSON | Ownership |
| `booked_with` | OBLIGATION → PROVIDER | Outbound execution |
| `learned_from` | PATTERN → OUTCOME[] | Pattern derivation |
| `line_item_of` | PURCHASE_ITEM → LEDGER_EVENT | Item belongs to this transaction |
| `discharges` | PURCHASE_ITEM \| LEDGER_EVENT → OBLIGATION | This purchase completed that obligation |
| `verifies` | PURCHASE_ITEM → CONSTRAINT | Real-world evidence the constraint is being honoured |
| `contradicts` | PURCHASE_ITEM → CONSTRAINT | Evidence it is being violated (nut-containing item bought under a nut-free constraint) |
| `absent_from` | CONSTRAINT → SOURCE_DOCUMENT[] | Expected evidence never appeared — silent non-compliance |
| `substitutes` | PURCHASE_ITEM → PURCHASE_ITEM | Bought instead of the planned item |
| `evidences_effort` | PURCHASE_ITEM \| LEDGER_EVENT → PERSON | Who actually did this run — behavioural valuation input |

### 5.4 The Document-Type Registry

**Design decision:** extraction is NOT one general-purpose extractor. It is a **registry of typed extractors**, each with its own field schema and its own set of target edges into the graph. A receipt, a permission slip, an attendance register, a society notice and a bank statement have genuinely different field sets and genuinely different downstream consequences. One generic extractor produces mush for all five.

The registry is **open** — adding a document type means adding a schema and an edge mapping, not modifying the pipeline. This is what makes the input surface genuinely general rather than three hard-coded cases.

#### 5.4.1 Registry structure

Each entry defines:
- **Type identifier and detection signals** — how the Intake Router recognises it
- **Field schema** — what to extract, with types and required/optional status
- **Confidence floors** — per-field minimums below which the field is marked ambiguous
- **Target nodes** — what graph nodes this document creates
- **Target edges** — how those nodes connect to existing household structure
- **Downstream subsystems** — which pipelines this document triggers
- **Verification duties** — what existing graph claims this document confirms or contradicts

#### 5.4.2 The registry

**RECEIPT / ITEMISED BILL** *(retail, grocery, restaurant, pharmacy, fuel)*
- **Detection:** merchant header, line-item block, total, payment method, tax lines
- **Schema:** merchant name and category · transaction datetime · payment method and last-4 · line items (description, quantity, unit price, line total, tax) · subtotal, tax, discounts, total · loyalty/account identifiers
- **Nodes created:** LEDGER_EVENT (one), PURCHASE_ITEM (one per line)
- **Edges:** `line_item_of` to the transaction · `owed_to` merchant · `discharges` any matching open shopping/purchase OBLIGATION · `verifies` / `contradicts` relevant CONSTRAINTs · `substitutes` where a planned item was replaced · `evidences_effort` to whoever made the purchase · `belongs_to` a RECURRING_COMMITMENT if it matches a series
- **Triggers:** Ledger reconciliation · constraint verification · Consequence Engine (a purchase can imply new obligations — a new appliance implies warranty registration and a service schedule) · Fair Allocator behavioural signal
- **Verification duties:** this is the strongest verification document in the system — see §5.5

**UTILITY / SERVICE BILL** *(electricity, water, broadband, DTH, gas, phone)*
- **Detection:** account number, billing period, due date, consumption block
- **Schema:** provider · account identifier · billing period · consumption reading and units · amount due · due date · late-fee terms · prior balance
- **Nodes:** LEDGER_EVENT (due), RECURRING_COMMITMENT (create or match)
- **Edges:** `belongs_to` series · `owed_to` provider · creates a payment OBLIGATION with the due date
- **Triggers:** Ledger (due tracking, silent-hike detection via consumption-normalised price history) · Consequence Engine (payment obligation)
- **Note:** consumption data enables a distinct capability — flagging anomalous usage (a leak, a failing appliance) that no bill-payment app surfaces

**SOCIETY / HOA MAINTENANCE NOTICE**
- **Detection:** society letterhead, unit reference, circular or notice framing
- **Schema:** society name · unit · notice type (dues, meeting, rule change, work notice, penalty) · amount if any · due date · effective date for rule changes · contact
- **Nodes:** LEDGER_EVENT (if dues), OBLIGATION, CONSTRAINT (if a rule change constrains the household — parking, renovation hours, pet rules)
- **Edges:** `owed_to` society · `constrains` household · payment obligation
- **Triggers:** Ledger · Consequence Engine · Constraint Learner

**SCHOOL / INSTITUTIONAL COMMUNICATION**
- **Detection:** school identifiers, student name, academic framing
- **Schema:** institution · student · communication type (event, fee, form, exam, disciplinary, holiday, requirement) · dates · amounts · requirements (consent, materials, dietary, dress, transport) · response deadline
- **Nodes:** OBLIGATION (multiple — the implication-rich case), candidate CONSTRAINT
- **Edges:** `states` / `implies` from source · `benefits` the child · `violates` where a requirement collides
- **Triggers:** Consequence Engine (primary) · Ledger (fees) · Outbound Concierge (if a booking or call is implied)

**PERMISSION SLIP / CONSENT FORM**
- **Detection:** signature block, consent language, tear-off section
- **Schema:** issuing body · subject person · what is being consented to · required signatory type · return deadline · attached requirements (payment, medical info, emergency contact)
- **Nodes:** OBLIGATION (with a capability requirement — signatory authority)
- **Edges:** `owned_by` a person with signing capability (capability-aware assignment matters here) · `depends_on` any prerequisite
- **Triggers:** Consequence Engine · form pre-fill

**ATTENDANCE REGISTER** *(handwritten, domestic staff)*
- **Detection:** grid/tabular structure, date column, name rows, tick/cross marks
- **Schema:** staff member · month · per-day presence marks · leave annotations · advance notations in margins
- **Confidence floors:** **strictest in the registry** — handwriting misread directly causes wrong salary payment. Below threshold → present the image to the human, never infer
- **Nodes:** attendance records on STAFF PERSON node
- **Edges:** feeds salary computation
- **Triggers:** Ledger payroll
- **Verification duties:** cross-check against WhatsApp leave messages; discrepancy → dispute branch, never silent reconciliation

**BANK / CARD STATEMENT**
- **Detection:** account header, transaction table, period, balances
- **Schema:** account · period · per-transaction (date, description, amount, direction, balance) · opening/closing balance
- **Nodes:** LEDGER_EVENT (many)
- **Edges:** `belongs_to` series where matched · `owed_to` resolved counterparties
- **Triggers:** Ledger reconciliation · leakage detection · recurring-series discovery
- **Note:** the statement is the reconciliation *ground truth* against which SMS alerts are checked

**UPI / PAYMENT SMS ALERT**
- **Detection:** short structured text, amount, VPA/merchant, reference number
- **Schema:** amount · direction · counterparty VPA or merchant string · reference · timestamp · account last-4
- **Nodes:** LEDGER_EVENT
- **Edges:** `belongs_to` series if matched; unmatched → flagged for reconciliation
- **Triggers:** Ledger · mandate detection
- **Note:** merchant strings are notoriously opaque ("PAYTM*XXXXX") — entity resolution confidence is typically low; low-confidence merchant resolution must not drive a cancellation recommendation on its own

**MEDICAL DOCUMENT** *(prescription, lab report, appointment card, discharge summary)*
- **Detection:** clinical letterhead, patient identifiers, clinical terminology
- **Schema:** patient · provider · date · document type · appointment/follow-up dates · medication names and schedules · stated restrictions
- **Nodes:** OBLIGATION (appointments, follow-ups, refills), CONSTRAINT (dietary/activity restrictions, medication timing)
- **Edges:** `constrains` the patient · `benefits` the patient · care obligations
- **Triggers:** Consequence Engine · Outbound Concierge (booking follow-ups) · Council Care Specialist
- **Hard rule:** extraction and scheduling only. **The system never interprets clinical meaning, never advises, never adjusts medication.** Restrictions are recorded as stated, never inferred.

**INSURANCE DOCUMENT** *(policy, renewal notice, claim correspondence)*
- **Schema:** insurer · policy number · covered persons · coverage type and limits · premium and due date · renewal date · exclusions
- **Nodes:** RECURRING_COMMITMENT, OBLIGATION (renewal), CONSTRAINT (coverage limits affect Council Finance reasoning)
- **Triggers:** Ledger · Council

**WARRANTY / PURCHASE PROTECTION**
- **Schema:** product · purchase date · warranty period and expiry · coverage terms · claim process · serial number
- **Nodes:** OBLIGATION (claim-or-lose before expiry)
- **Edges:** links back to the originating RECEIPT's PURCHASE_ITEM — **this is why receipt line-item extraction matters months later**
- **Triggers:** Ledger

**GOVERNMENT / LEGAL NOTICE** *(tax, licence, registration, compliance)*
- **Schema:** issuing body · reference · subject · required action · deadline · penalty for non-compliance
- **Nodes:** OBLIGATION (high-consequence, deadline-critical)
- **Triggers:** Consequence Engine · escalation (typically R2+ given consequence)

**QUOTE / ESTIMATE** *(contractor, service provider)*
- **Schema:** provider · scope of work · line-item costs · validity period · terms
- **Nodes:** PROVIDER, BRANCH (if part of an active Decision)
- **Triggers:** Council (comparison), Outbound Concierge (quote-gathering mode)

**CHAT / MESSAGE THREAD** *(WhatsApp, SMS, group)*
- **Schema:** participants · timestamps · message content · embedded commitments, complaints, leave notifications, intentions
- **Nodes:** OBLIGATION (from commitments made in chat), intention captures, valuation signals, staff leave records
- **Triggers:** all subsystems — the most polymorphic input
- **Note:** requires speaker attribution and code-mixed language handling; commitments made casually in chat ("I'll pick her up Friday") are real obligations and should be captured as such

#### 5.4.3 Extraction routing rules

1. The Intake Router classifies document type **before** extraction; misclassification is more damaging than low-confidence extraction because it applies the wrong schema entirely.
2. Ambiguous type → attempt the two most likely schemas, compare field-fill rates, choose the better; if still ambiguous, escalate.
3. A document may match multiple types (a school communication containing a fee slip) → extract under both, deduplicate the resulting nodes.
4. Unknown type → generic extractor + human triage. **Log it as a registry gap** — this is how the registry grows.
5. Every extracted field carries a source region pointer. Non-negotiable across all types.

### 5.5 Closing the loop: verification documents

**This is a structural property worth naming, because it is what makes the graph self-correcting rather than merely accumulative.**

Most inputs generate obligations pointing *forward*. Receipts, statements, and confirmations are different: they are **evidence of what actually happened**, and they close edges rather than opening them.

A grocery receipt does four things simultaneously:
1. **Settles** the payment obligation the Ledger was tracking (`discharges`)
2. **Confirms or contradicts** the shopping list the Consequence Engine generated (`substitutes` where an item was swapped)
3. **Writes real spend** against the recurring series, feeding leakage detection with actuals rather than estimates
4. **Verifies constraints against reality** (`verifies` / `contradicts`)

The fourth is the non-obvious one and the most valuable. **If the nut-free bread never appears on any receipt, the constraint the system believes it is honouring is not actually being honoured in the physical world.** Nothing else in the input set catches that. An `absent_from` edge — expected evidence that never arrived — is a first-class signal, and the Pattern Miner should surface it.

**Second-order value:** receipts are the least gameable behavioural record available. The Fair Allocator's entire novelty claim over Spliddit is that valuations derive from observed behaviour rather than self-report. Receipts show who *actually* did the grocery run, how often, at what cost — a far stronger input to the cost matrix than a chat complaint. `evidences_effort` edges are therefore a primary Allocator input, not a side effect.

**Verification duties by document type:**

| Document | Verifies |
|---|---|
| Receipt | Constraint compliance, obligation discharge, planned-vs-actual purchases, who did the work |
| Bank statement | That UPI SMS alerts were accurate; that payments the system believes it made actually cleared |
| Booking confirmation | That the Outbound Concierge's call achieved what it reported (**required before recording — §13**) |
| Attendance register vs chat leave messages | That salary computation rests on consistent evidence |
| Delivery confirmation | That an ordered item arrived |

**Rule:** where a verification document contradicts a graph claim, the system **never silently overwrites**. It opens a discrepancy, presents both, and escalates. Silent correction destroys the audit trail that makes the whole system trustworthy.

### 5.6 Provenance tagging (the discipline)

Every node and edge carries:
- `derivation`: **`extracted`** (found in the source — openable at a specific region) | **`inferred`** (reasoned from structure and context; usually right, worth checking) | **`ambiguous`** (evidence points more than one way, and the graph says so)
- `source_ref` — pointer to the SOURCE_DOCUMENT and the region within it
- `confidence` — numeric
- `deriving_agent` — which agent produced it
- `created_at`, `superseded_at`

**This is the single most important discipline in the system.** It is what turns "the agent decided" into "here is the path it walked," and it is what allows a human to check rather than trust.

### 5.7 Graph query capabilities

The graph must support these operations, because subsystems depend on them:

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
| `unexplained(scope)` | Audit | Nodes lacking provenance — should be empty |
| `unverified(scope)` | Verification | Graph claims with no real-world evidence behind them |
| `expected_but_absent(constraint)` | Verification, Pattern Miner | Constraints the receipts never confirm — silent non-compliance |
| `spend_by_category(window)` | Ledger, Council Finance | Real spend from line items, not estimates |
| `effort_evidence(person, window)` | Fair Allocator | Who actually did the runs, from receipts and transactions |

### 5.8 Graph visualisation (the demo asset)

A live force-directed rendering: nodes coloured by type, edges styled by derivation tag (solid = extracted, dashed = inferred, dotted = ambiguous), conflict edges in red.

**Demo behaviour:** when a source document arrives, the graph visibly *grows* — new nodes appear, edges connect them to existing household structure, and a conflict edge lights up red. This is the "holy shit" moment: the graph assembling itself out of mess, in real time.

**Rule:** the graph must be *built live from messy input during the demo.* If it is hand-seeded, it is a database with a nice visualisation and a judge will sense it.

---

## 6. SYSTEM ARCHITECTURE OVERVIEW

### 6.1 The primary loop

```
INBOUND SIGNAL (email / SMS / WhatsApp / photo / PDF / portal / scheduled tick / voice)
        │
        ▼
   Pub/Sub topic (per channel)
        │
        ▼
   INTAKE LAYER ── normalize, extract, resolve entities, write SOURCE_DOCUMENT node
        │
        ▼
   GRAPH WRITE ── nodes + edges with provenance tags
        │
        ▼
   ROUTING ── which subsystem(s)?
        │
        ├──▸ CONSEQUENCE ENGINE  (obligations)
        ├──▸ HOUSEHOLD LEDGER    (financial signals)
        ├──▸ INTENTION→ACTION    (stated intentions)
        ├──▸ SIMULATOR           (decision triggers)
        ├──▸ COUNCIL             (major decisions)
        └──▸ OUTBOUND CONCIERGE  (real-world execution)
        │
        ▼
   FAIR ALLOCATOR ── assign ownership of unowned obligations
        │
        ▼
   ARBITRATION ── confidence check → risk tier → execute OR request approval
        │
        ▼
   ACTION LAYER ── tools touch the world (idempotent, permissioned)
        │
        ▼
   GRAPH WRITE + AUDIT RECORD
        │
        ▼
   MONITORING ── watch for response, deadline, non-completion
        │
        └──▸ re-enters loop on change
```

### 6.2 Layering

- **Layer 0 — Ingestion adapters.** Channel-specific, swappable.
- **Layer 1 — Perception.** Extraction, entity resolution. Writes SOURCE_DOCUMENT.
- **Layer 2 — Graph.** The substrate. All reads and writes pass through it.
- **Layer 3 — Reasoning.** The seven subsystems. Read graph, propose changes. **No direct external action.**
- **Layer 4 — Arbitration.** Confidence, risk tiering, approval gating.
- **Layer 5 — Action.** Tools that touch the outside world. Separately permissioned. Idempotent.
- **Layer 6 — Audit.** Immutable record.

**The Layer 3 / Layer 5 separation is the core architectural claim.** Reasoning agents propose; only tools act; arbitration decides which proposals become actions. Never give a reasoning agent an action credential.

---

## 7. SUBSYSTEM 1 — CONSEQUENCE ENGINE

### 7.1 The pain

Information *implies* work. The information is not the work. A school email arrives and one person mentally unpacks it into six obligations, checks them against everything else that week, and carries them until done.

Research anchor: Daminger's cognitive-labour taxonomy (*American Sociological Review*, 2019, 35 couples) decomposes household labour into anticipate → identify → decide → monitor, and finds anticipation and monitoring performed alone by one person in nearly all couples. Chores get split because they are visible; anticipation does not because it is not. OECD 2024 time-use data: women average ~4 hours/day unpaid work, roughly twice men's.

### 7.2 Why existing software fails

Family apps extract a date and put it on a calendar. They surface the *event*. They do not perform implication, do not check implications against household constraints, and do not detect that two implications collide.

### 7.3 The four-stage pipeline

**Stage 1 — EXTRACT.** Pull literal content from messy multimodal input. Every field tagged `extracted` with confidence and source region.

**Stage 2 — IMPLY** *(the flagship reasoning step)*

Worked example — *"Field trip Friday. Signed permission slip due Wednesday. ₹500 fee. Nut-free lunch required. Early pickup 1:30pm."*

| Stated | Implied |
|---|---|
| Slip due Wed | Must be printed; signed by a parent with signing authority; usual signer travels Tue–Wed → must be signed **Monday** |
| ₹500 fee | Cash must be physically available → ATM stop or exact change → must travel with the child Friday morning |
| Nut-free lunch | Tuesday's planned peanut-butter lunch violates a **hard constraint** → menu substitution → grocery item may be needed |
| Early pickup 1:30 | Someone must collect; usual pickup person has a work commitment → coverage needed |
| Trip Friday | Regular Friday after-school activity needs cancellation/notification |

Six obligations, five implied. Each written as a node with an `implies` edge from the source document and a pointer to the exact source span.

**Stage 3 — DECONFLICT.** Check against hard constraints (violation = blocking), soft constraints (advisory), existing obligations, availability models, and ledger state.

Conflict types: **temporal** (same person, same time), **constraint violation**, **resource** (the car, cash on hand), **capability** (cannot sign, cannot drive), **load** (one person over a fairness threshold → hand to Fair Allocator).

**Stage 4 — OWN.** Assign owner, compute must-start-by, classify risk tier, then execute / prepare / queue for approval.

### 7.4 Feature list (A–Z)

Multimodal ingestion (email, PDF, image, screenshot, forwarded message, portal notification) · handwriting tolerance · multi-language and code-mixed text · stated-vs-implied separation with explicit tagging · source-span provenance per obligation · confidence scoring · hard/soft constraint checking · cross-member conflict radar · resource conflict detection · capability-aware assignment · must-start-by computation working backwards through dependencies and availability · dependency chains · duplicate detection across channels · supersession handling · recurrence recognition · automatic constraint learning (confirmation-gated) · escalation on ambiguity

### 7.5 Data in / actions out

**Consumes:** unstructured email bodies, phone photos of paper forms, PDFs, portal screenshots, group-chat text, school app notifications.
**Produces:** calendar entries; pre-filled forms routed for signature; drafted messages; conflict alerts; payment requests queued for approval; shopping-list additions; menu substitution proposals.
**Graph writes:** SOURCE_DOCUMENT, OBLIGATION (multiple), candidate CONSTRAINT, `implies`/`states`/`conflicts_with`/`violates` edges.
**Graph reads:** PERSON, CONSTRAINT, open OBLIGATIONs, availability, ledger signals.

### 7.6 Failure modes

| Failure | Mitigation |
|---|---|
| Hallucinated obligation | Every `implies` edge must cite a source span; uncitable → discarded |
| Missed implication | Confidence floor + "what might I have missed" second pass on high-stakes docs; unresolved → surface raw doc |
| Wrong constraint match | Hard constraints require exact entity resolution; ambiguity escalates |
| Duplicates across channels | Content-hash + semantic dedupe against open obligations |
| Over-firing on noise | Relevance classifier before implication; low-relevance logged, not expanded |

### 7.7 HITL points

Payment → approval. Outbound message to a non-household person → approval. New **hard** constraint → confirmation. Confidence below threshold → surfaced, not actioned. Unresolvable conflict → escalate with options.

### 7.8 Demo beat

One chaotic email → six obligations, five implied → hard-constraint violation caught → temporal collision caught → drafted coverage message → the graph visibly growing.

---

## 8. SUBSYSTEM 2 — FAIR ALLOCATOR

### 8.1 The pain

Households argue about chores endlessly because they have no fair *procedure* — only power dynamics, habit, and whoever notices first. The person who notices first absorbs the work permanently.

### 8.2 Mechanism (and an honesty requirement)

**Grounding:** Maximum Nash Welfare yields allocations simultaneously envy-free-up-to-one-item (EF1) and Pareto-optimal (Caragiannis, Kurokawa, Moulin, Procaccia, Shah, Wang — EC 2016 / ACM TEAC 2019). For *chores* (allocating "bads") the theory is subtler: Nash welfare does not directly guarantee EF1 on chores; competitive-equilibrium methods give EF1 + fractional-PO in structured cases (Chaudhury, Garg, McGlaughlin, Mehta, EC 2022); a general EF1+PO existence result for additive costs is recent and preprint-stage.

**Honesty requirement:** state precisely which guarantee the implementation actually delivers. Overclaiming a mathematical property in front of judges who know the literature is worse than claiming less.

**Defensible novelty claim:** Spliddit has shipped Maximum Nash Welfare since 2014. The algorithm is not our contribution. Our contribution is the input pipeline — task list auto-derived from the Consequence Engine, valuations derived from *observed behaviour* in the OUTCOME history. Structurally impossible for Spliddit, and only possible because of the merge.

### 8.3 What it does

1. **Elicit** — adaptive *comparative* interview ("would you rather do two school runs or handle the plumber once?"), because humans compare better than they rate.
2. **Extract valuations** — mutate complaint streams, interview answers, voice notes, and observed completion history into a per-person cardinal cost matrix.
3. **Solve** — a deterministic isolated solver computes the allocation. **A code tool, not an LLM.** The fairness property is computed, not generated.
4. **Verify and explain** — check the property holds on the produced allocation (external verifiable signal, not self-critique), then explain each person's share in terms of *their own* stated valuations.
5. **Renegotiate on change** — life events (night shifts, travel, illness, exam season, staff resignation) detected from the household signal stream trigger re-allocation.

### 8.4 Feature list (A–Z)

Adaptive comparative interview · voice-note and chat-export preference signals · behavioural valuation inference from OUTCOME history · cardinal cost matrix construction · load imbalance detection · deterministic fairness solver (isolated) · fairness property verification · per-person explanation · renegotiation triggers on detected life change · capability-aware constraints · temporary reassignment during travel/illness · staff-inclusive allocation · historical fairness tracking (fair *over time*, not just this cycle) · manual override with reason capture feeding back into the model · **concession ledger** (who has given ground historically — feeds the Council)

### 8.5 Data / graph

**Consumes:** chat exports, voice notes, interview responses, calendars, OUTCOME history, staff terms.
**Graph writes:** valuation profiles on PERSON, `owned_by` edges, allocation history, concession records.
**Graph reads:** unassigned OBLIGATION, PERSON capabilities/availability, OUTCOME history, CONSTRAINT.

### 8.6 Failure modes

| Failure | Mitigation |
|---|---|
| Wrong cost matrix → illusory fairness | Human confirms matrix before first allocation; matrix visible, not hidden |
| Overclaiming the guarantee | State exactly what is delivered |
| Degenerate matrix | Validate before solve; fall back to explicit human assignment |
| Ignores capability | Hard capability constraints enforced pre-solve |
| Household rejects result | Override with reason capture; reason updates the model |

### 8.7 Demo beat

Paste a real family chat → agent extracts who complains and who actually does → cost matrix on screen → deterministic solver → per-person fairness explanation → inject "I just started night shifts" → live re-allocation.

---

## 9. SUBSYSTEM 3 — INTENTION→ACTION CONVERTER

### 9.1 The pain, and the finding that defines it

Everyone assumes unfulfilled intentions are a *memory* problem — hence a world full of reminder apps. A 2026 diary study (*Cognitive Research: Principles and Implications*) found **forgetting accounts for only ~10–14% of unfulfilled daily intentions.** The rest is situational and motivational: the intention was remembered and still didn't happen, because at the moment of action there was friction.

**Implication:** a reminder addresses about one-eighth of the problem. The other seven-eighths need the friction removed *before* the moment of action.

### 9.2 Why existing software fails

To-do apps are built on the memory hypothesis. They notify you about something you already remembered and were already avoiding — adding a notification to a friction problem.

### 9.3 What it does

**Stage 1 — Capture.** Intercept intentions wherever expressed: a note, a passing message ("we should really get the AC serviced"), a stated goal, or an OBLIGATION gone stale.

**Stage 2 — Diagnose the blocker.** The core reasoning step. Taxonomy:
- **Information blocker** — a needed fact is missing (number, account, policy, last service date)
- **Decision blocker** — an unmade choice sits upstream
- **Window blocker** — action only possible when the person is never free
- **First-step ambiguity** — the person doesn't know the actual first action
- **Dependency blocker** — something must happen first
- **Aversion blocker** — the person systematically avoids this *modality* (never makes calls)

**Stage 3 — Unblock.** Fetch the information; narrow an open decision to a binary; find a window where person AND counterparty are available; pre-stage the first step; pre-draft the message; switch modality. **Or hand to the Outbound Concierge (§13) to execute entirely.**

**Stage 4 — Schedule and monitor.** Place into a window where completion is realistic. If it slips again, re-diagnose — the first diagnosis may have been wrong.

**Worked example — "call the dentist."** Blocker is not memory: the number isn't to hand, last-visit date is unknown, the clinic is only open during working hours, and this person has an aversion blocker for phone calls. Unblock options: (a) retrieve number + history, find a window, pre-draft the script — 90 seconds instead of 15 minutes; or (b) **escalate to the Outbound Concierge and let the system make the call itself.** See §13.

### 9.4 Feature list (A–Z)

Passive intention capture from message streams · stale-obligation detection · six-type blocker diagnosis · information pre-fetching · decision narrowing · business-hours-aware window finding · modality switching based on aversion patterns · pre-drafting the first communication · first-step decomposition · per-person friction profile · re-diagnosis on repeat slippage · explicit diagnosis statement (so wrong diagnoses can be corrected) · completion-pattern learning into OUTCOME · **handoff to Outbound Concierge for full execution**

### 9.5 Failure modes

| Failure | Mitigation |
|---|---|
| Misdiagnosed blocker | State the diagnosis explicitly; capture correction; feed back |
| Over-preparation for trivial tasks | Effort threshold |
| Scheduling into a window the person won't honour | Use observed completion patterns, not stated preferences |
| Repeated failed unblocking | After N attempts escalate: "this has slipped 4 times — drop, delegate, or pay someone?" |

### 9.6 Demo beat

A task untouched for four months completes in 30 seconds because the agent removed the actual blocker — or handed it to the Concierge, which called and booked it.

---

## 10. SUBSYSTEM 4 — HOUSEHOLD LEDGER

*(Merges Money Sentinel and GharOS financial operations — the same loop with different signal adapters: monitor → reconcile → detect leakage or dues → act behind a payment gate.)*

### 10.1 The pain

**Leakage side:** CNET's 2026 subscription survey puts average spend at $111/month, with ~$21/month ($252/year) on unused services. Self Financial's 2026 survey (1,272 US adults) found 70% have forgotten to cancel a free trial. Beyond subscriptions: unclaimed price-protection windows, expired return windows, unaudited billing errors, unclaimed warranty remedies.

**Indian household side:** the ledger lives in WhatsApp memory, UPI SMS, and paper society notices. Nobody owns the whole picture. Recurring spend is systematically underestimated because autopay mandates spread across multiple payment apps with no consolidated view — and no third party can pull a live consolidated mandate list from NPCI. Staff salary is computed monthly from remembered attendance minus remembered advances.

**Structural reason it persists:** recovering ₹2,000 or $30 requires 40 minutes navigating a deliberately hostile interface. The economics never work for a human. They work fine for an agent.

### 10.2 Why existing software fails

Rocket Money and peers do subscription detection and cancellation — one narrow slice. No price-hike monitoring on wanted services, no refund chasing, no price adjustments, no bill audit, no dues, no staff salary. And they surface findings and hand you a to-do rather than executing recovery.

### 10.3 Functions

**A — Signal ingestion.** UPI/bank SMS, statements, bill PDFs, society notices, receipts, WhatsApp payment confirmations, handwritten attendance registers.

**B — Reconciliation** *(read-only agent — structurally cannot move money)*
Match debits to series · detect novel recurrences (silent-renewal finder) · detect price changes within a series (silent hikes) · detect duplicates · reconcile society dues against payments · compute staff salary (expected days − absences − advances) · flag SMS-vs-ledger mismatches → dispute branch.

**C — Worth reasoning** *(why an LLM, not a cron job)*
A price rise on a daily-used service is fine; the same rise on one last touched in March is not. A mandate for a gym nobody has attended since the family moved is waste. Per-item judgment against usage signals and household priorities.

**D — Obligation generation.** Dues → payment OBLIGATIONs with deadlines. Salary cycles → monthly payment OBLIGATIONs. Warranty expiry approaching → claim-or-lose. Return window closing → decide-now.

**E — Recovery execution.** Draft cancellation, file price adjustment, open dispute, submit warranty claim, request refund — and **follow up** when nobody responds. Following-up is where human attempts die and autonomous persistence wins decisively.

**F — Vendor chasing.** The plumber who said "tomorrow" four days ago. Track request → response → scheduled → completed with latency, build reliability, escalate or switch vendor.

### 10.4 Feature list (A–Z)

Multi-channel financial signal ingestion · handwritten register OCR · recurring-series detection · silent price-hike detection with price history · unused-service detection via usage signals · duplicate charge detection · billing error detection · society dues reconciliation · staff salary computation · advance tracking · leave and coverage tracking · return-window tracking · warranty registry and expiry · price-protection eligibility · refund and claim drafting · autonomous follow-up · vendor reliability scoring · dispute branch · idempotent payments (one debit per due-ID per cycle) · recovered-money running total (the demo metric)

### 10.5 Tool isolation (critical)

Three separately-permissioned groups:
1. **Read tools** — statements, SMS, documents. The Reconciliation Agent has ONLY these.
2. **Communication tools** — draft/send outreach. Cannot touch money.
3. **Payment tools** — execute payment, pause/cancel mandate. Reachable ONLY via the Approval Gate.

**The Reconciliation Agent is structurally incapable of moving money.** The single strongest sentence in the architecture pitch — and it stays true only if you never hand it a payment credential for build convenience.

### 10.6 Failure modes

| Failure | Mitigation |
|---|---|
| Wrong cancellation / wrong account | Hard approval gate with evidence bundle; entity resolution threshold |
| Double payment | Idempotency key per (due-ID, cycle); replay-safe |
| Misread handwriting | Confidence threshold; below it, show the image to the human |
| SMS total ≠ ledger | Dispute branch — never auto-resolve |
| Cancelling something wanted | Usage-signal check + approval ("you used this 3 times last month") |
| Merchant interface changes | Adapter fails gracefully, logs, escalates; never fabricates success |

### 10.7 Demo beat

Running money counter: "found ₹X/year of leakage — three claims drafted, awaiting approval." Plus a live silent-mandate kill and a staff-salary reconciliation from a photographed handwritten register. **Show the approval gate.**

---

## 11. SUBSYSTEM 5 — HOUSEHOLD SIMULATOR

*(Merges Fork and Pre-Mortem — one engine, two query modes.)*

### 11.1 The pain

**Forward mode.** A household faces a genuine fork — relocate abroad, move an elderly parent in, change schools mid-year, take a job in another city. In an Indian household these are never individual decisions: they touch the child's board-exam year, the parent's dialysis schedule, ten years of domestic staff employment, extended-family care obligations, and the whole financial surface. Humans are poor at affective forecasting, and regret in this class is dominated by inaction.

**Backward mode.** People misjudge their own future behaviour. The planning fallacy (Kahneman & Tversky, 1979) is among the most replicated findings in behavioural science — 30–50% underestimation — and persists even when known, because people reason from the plan rather than their own history. Generic advice is useless; "*your* projects run over by 40%, specifically when they need your brother to respond first" is not.

### 11.2 The design constraint that makes this defensible

**The most important paragraph in this subsystem.**

LLM social simulation has **no established external validity for predicting novel real-world behaviour.** A 2025 Springer review concluded validation is the central unsolved problem for generative agent-based models. The widely-cited Stanford/DeepMind "1,000 people" result reached ~85% fidelity — but at *replicating known survey answers of people interviewed for two hours*, not predicting strangers' novel behaviour.

Therefore: **GharOS never simulates strangers, populations, or markets.** It simulates *this household's own logged history*, projected forward. Ordinary personal-history modelling — defensible. Not synthetic-population prediction — indefensible.

Grounding in the graph repairs the original "fortune-telling" risk. Every branch anchors to auditable records:
- Not "NYC is expensive" → "your Ledger shows ₹X/month in staff salaries and society dues that don't transfer; here is the delta"
- Not "moving is disruptive" → "a June move lands mid-way through your daughter's board year; here is the obligation chain that breaks"
- Not "healthcare varies" → "your father's specialist visits run every 6 weeks; the destination has a 4-month new-patient wait — a 10-week care gap"

A branch a judge can poke holes in is credible. One they cannot check is mysticism.

### 11.3 What it does

**Forward mode:** Frame (detect false binaries; surface the unconsidered third option) → Branch (2–4 concrete options) → Ground (real external data + real graph state) → Simulate (project each branch across every affected node) → Critique (adversarial pass for wishful thinking and missing second-order effects) → Calibrate (adjust using this household's own variance) → Present (structured, evidence-linked, interrogable).

**Backward mode:** Take a committed plan → assume it failed → reason backwards to the likely cause using OUTCOME history → identify the specific predicted failure point → hand mitigations to Intention→Action.

### 11.4 Feature list (A–Z)

Decision framing and false-binary detection · branch construction including unconsidered options · external grounding with citation · internal grounding against the full graph · per-person impact projection · per-obligation impact projection (what breaks, transfers, must be recreated) · constraint continuity checking · financial delta from actual Ledger data not generic indices · care-gap detection · education-continuity checking (exam years, admission cycles, transfer windows) · staff-employment impact (notice, severance, references) · adversarial consistency critique · personal calibration from OUTCOME variance · interrogation mode · timing sensitivity ("what if December instead of June") · risk register per branch · mitigation handoff · **blast-radius traversal via the graph**

### 11.5 Failure modes

| Failure | Mitigation |
|---|---|
| Fortune-telling perception | Every projection cites graph data or an external source; frame as decision-*support* |
| Wishful simulation | Adversarial critic; show it catching an over-optimistic branch live |
| Cold start | Backward mode is weak until OUTCOME history accumulates — be honest; seed history for the demo and say so |
| Over-confident numbers | Present ranges using the household's own historical variance |
| Emotionally heavy output delivered badly | Present options and trade-offs, never verdicts on family choices |

### 11.6 Demo beat

Relocation: branches grounded in real household state, the critic catching an optimistic assumption, a decision brief the family can interrogate. Optionally backward mode contradicting their own timeline: "you think this takes a weekend; your last three moves took nine days each."

---

## 12. SUBSYSTEM 6 — HOUSEHOLD COUNCIL (AGENT-TO-AGENT DELIBERATION)

### 12.1 The pain

Major household decisions — buy a car, buy a house, choose a school, take on a large loan — are made under three simultaneous failures:
1. **Fragmented information.** The budget reality, the care requirements, the school-run logistics, and the resale outlook live in different heads and different documents.
2. **Unequal voice.** Whoever argues hardest or earns most usually wins; quieter members' constraints get discovered after the purchase.
3. **No memory.** Two years later nobody remembers why the choice was made, what was traded away, or who conceded.

### 12.2 THE CRITICAL DISTINCTION — why this is not multi-agent debate

**Read this before building anything in this subsystem.**

Multi-agent *debate* — several instances of the same model arguing to converge on a better answer — is empirically weak. Replications across methods, benchmarks and models find it frequently fails to beat a strong single agent with chain-of-thought or self-consistency; the gains that do appear come from *ensembling* rather than from the debate itself; and multi-agent pipelines amplify errors, with hallucinations cascading and conformity bias locking in early mistakes. **Never describe the Council as agents debating to find the truth.** That framing invites a knowledgeable judge to mark you down.

**What the Council actually is, and why it works:**

The Council agents are legitimate because they differ in **information** and **interest**, not in opinion:

| Agent kind | Why it's different | Not interchangeable because |
|---|---|---|
| **Domain specialists** (Finance, Care, Education, Logistics, Legal) | Each queries a *different subgraph* with *different tools* | The Finance agent reads the Ledger; the Care agent reads medical schedules. They aren't arguing — they're reporting from different data |
| **Member delegates** (one per household member) | Each carries that person's *actual* valuation profile from the Fair Allocator, derived from observed behaviour | They represent genuinely conflicting *preferences*, not competing guesses at a fact |
| **Adversary** | Structurally tasked with attacking the leading option | Critiques *another agent's* output — the pattern the literature shows works, unlike self-critique |
| **Mechanism arbiter** | **Deterministic code, not an LLM** | Computes the trade-off; does not vote or "synthesize a consensus" |

The Council is **preference aggregation under conflicting interests**, which is mechanism design — a solved and legitimate field — not epistemic debate, which is the invalidated one. Nobody is trying to converge on a fact. They are surfacing a real trade-off between real interests, and a deterministic mechanism resolves it.

**Design rules that keep it legitimate:**
1. No two agents may have identical tool access and identical objectives. If two agents would produce the same output, delete one.
2. Positions are *reported*, never averaged into a consensus by an LLM.
3. Resolution is computed by the deterministic arbiter, not "decided" by a synthesizer agent.
4. Every position is recorded as a COUNCIL_POSITION node with its evidence — auditable, challengeable, permanent.
5. The Council never makes the final call on R4-tier decisions. It produces a decision brief; humans decide.

### 12.3 The council protocol

**Phase 0 — Convene.** A trigger (explicit request, or a Ledger/Simulator signal that a major decision is imminent) instantiates the council. The convener selects which specialists and which member delegates are relevant — a car decision convenes Finance, Logistics, Care, and all adult delegates plus a delegate for any child materially affected.

**Phase 1 — Independent reporting.** Each specialist queries its own subgraph *in isolation* — critically, **before seeing any other agent's output**, to prevent conformity bias and anchoring. Each produces a position with evidence.

**Phase 2 — Constraint publication.** Hard constraints are published to all agents. These are non-negotiable and remove options rather than being weighed (a car Dad cannot physically get into is eliminated, not scored down).

**Phase 3 — Option generation.** Concrete options are generated against the surviving space, each grounded in real data (real listings, real prices, real financing terms).

**Phase 4 — Interest scoring.** Each member delegate scores each option against *its own person's* valuation profile. This is where genuine conflict surfaces: the delegate for the person who does the school run values boot space and parking size; the delegate for the person who drives to work values fuel economy; the Care delegate values door height and seat height.

**Phase 5 — Adversarial pass.** The Adversary attacks the leading option: what's the failure mode, what's the resale risk, what maintenance is being ignored, what does the household's own history say about this kind of purchase?

**Phase 6 — Mechanism resolution.** A **deterministic arbiter** computes the outcome from the published interest scores and constraints — the same fair-division machinery as the Allocator, applied to a decision rather than chores. It produces the trade-off explicitly: "Option B maximises joint welfare; it costs Priya most on parking convenience and gains Dad most on accessibility."

**Phase 7 — Brief and escalate.** A decision brief with the recommendation, the trade-off, every position, every piece of evidence, and the risk register. **Humans decide.**

**Phase 8 — Record and learn.** The DECISION, its BRANCHes, every COUNCIL_POSITION, the resolution, and `conceded_by` edges are written permanently to the graph. When the outcome is later known, an OUTCOME node closes the loop and calibrates future councils.

### 12.4 Worked example — buying a car

**Trigger:** repeated maintenance LedgerEvents on the existing car plus a stated intention captured from a message.

**Convened:** Finance, Logistics, Care, Adversary, delegates for both adults and one for the elder.

- **Finance agent** (queries Ledger subgraph): actual savings trajectory, existing recurring commitments, real affordability band, current EMI capacity given school fees due in March. Not a guess — computed from real ledger history.
- **Logistics agent** (queries obligation subgraph): the car does school runs 5×/week, one dialysis trip 2×/week, and a monthly society run. Boot space and parking-slot dimensions are real constraints from real obligations.
- **Care agent** (queries constraint subgraph): Dad's mobility constraint sets minimum door height and maximum seat height. **Hard constraint — eliminates options.**
- **Member delegates:** each scores from their own behaviourally-derived valuation profile.
- **Adversary:** "your household has historically underestimated maintenance by 40% — here are the three OUTCOME records; the leading option's service network is thin in your city."
- **Arbiter (deterministic):** computes the welfare-maximising option under the hard constraints and publishes the exact trade-off.
- **Brief:** presented to the family, with a path to *why* — every claim walkable to its evidence.

**Two years later:** "why did we buy this car?" returns the DECISION node, all positions, the trade-off, and who conceded. That is institutional memory no family app has.

### 12.5 Worked example — buying a house

Same protocol, wider blast radius: Finance (affordability, existing commitments, transaction costs from real data), Education (school catchment vs the child's board-exam year and transfer windows), Care (proximity to the parent's specialist, hospital access, step-free access), Logistics (commute deltas computed against real calendar obligations), Legal/Compliance (documentation, society rules), Adversary (resale, hidden costs, the household's own history of underestimating moves), plus member delegates.

The Simulator is invoked per shortlisted property for blast-radius traversal: what obligations break, what recurring commitments transfer, what care gaps open.

### 12.6 Feature list (A–Z)

Trigger detection for major decisions · dynamic council composition · isolated independent reporting (anti-anchoring) · hard-constraint publication and option elimination · grounded option generation from real listings/data · per-member interest scoring from behavioural valuation profiles · adversarial attack pass · deterministic mechanism resolution · explicit trade-off statement · risk register · permanent position recording · concession-ledger tracking across decisions (fairness *over time*) · outcome closure and calibration · full graph traceability · interrogation mode ("what if the budget were 15% higher?")

### 12.7 Failure modes

| Failure | Mitigation |
|---|---|
| Reads as multi-agent debate | Never use the word; enforce different tools/objectives per agent; deterministic arbiter |
| Conformity/anchoring | Phase 1 isolation — specialists report before seeing others |
| Error cascade | Positions are independent; no agent consumes another's conclusion as fact, only as a stated position with evidence |
| Delegate misrepresents its person | Valuation profiles are visible and confirmable; the person can correct their own delegate |
| Council used for trivial decisions | Trigger threshold — councils are expensive and reserved for R4-tier decisions |
| Family feels overruled by software | Council never decides R4; produces a brief; humans decide |

### 12.8 Demo beat

Convene a car decision live. Show specialists reporting from genuinely different subgraphs, the Care agent's hard constraint *eliminating* options, delegates scoring in conflict, the Adversary landing a hit using the household's own history, and the deterministic arbiter publishing the explicit trade-off — then the whole deliberation persisting into the graph as a walkable record.

---

## 13. SUBSYSTEM 7 — OUTBOUND CONCIERGE (REAL-WORLD EXECUTION)

### 13.1 The pain

The last mile of household admin is contacting the outside world: calling a dentist, booking a service, chasing a plumber, getting three quotes. It is exactly where intentions die — it requires being free during business hours, knowing what to ask, and tolerating a modality many people avoid.

### 13.2 What it does — the dentist flow, end to end

**Trigger:** "book a dentist appointment" (typed, spoken, or an Intention captured passively).

**Step 1 — Clarify (only what's genuinely needed).** The agent does not interrogate. It queries the graph first and asks only what it cannot infer:
- *Already known from the graph:* who it's for, their availability model, the last visit date, insurance details, past provider history, whether this person hates morning appointments.
- *Genuinely unknown, so asked:* Is this routine or is something hurting? Any preference for the previous clinic? Any date constraints?
- If pain is reported → urgency escalates → the search prioritises earliest availability over rating.

**Step 2 — Discover.** Search providers by proximity to a graph-known location (home, office, or school depending on who it's for and when), filtered by service type and insurance acceptance.

**Step 3 — Rank.** Multi-factor, transparent: rating, distance from the *relevant* location, earliest availability against the person's real free windows, price band, insurance acceptance, and prior household experience (a provider who no-showed before is demoted). **Ranking is explainable — the user sees why #1 is #1.**

**Step 4 — Confirm intent to act.** R2/R3 gate: "I'm going to call Dr. X, 1.2 km from home, rated 4.7, with a Thursday 4pm slot that fits your free window. Proceed?"

**Step 5 — Execute the call.** The voice agent calls, states purpose, requests the slot, answers routine questions (name, insurance, reason for visit), handles common branches (slot gone → take the next fitting one within pre-authorised bounds; clinic asks a question it cannot answer → do not guess, take a message and escalate).

**Step 6 — Verify.** Confirmation is captured, cross-checked against what was requested, and only then written to the graph. **A booking is not recorded until verified.** Discrepancy → escalate.

**Step 7 — Close the loop.** Calendar entry with travel time; reminder chain; obligation marked complete; OUTCOME node written; provider interaction history updated for future ranking.

**Step 8 — Fallback.** No answer → retry schedule. Voicemail → leave a callback message and switch to a web-booking path if available. Three failures → escalate to the human with everything already prepared, so the human's cost is one minute, not fifteen.

### 13.3 Voice architecture

- **Pre-call brief:** the calling agent receives a tightly scoped objective, authorised bounds (acceptable date range, acceptable price ceiling), the exact facts it may disclose, and an explicit list of what it must *not* answer.
- **In-call:** turn-taking, structured objective tracking, branch handling, real-time transcript.
- **Disclosure:** the agent identifies itself as an automated assistant calling on behalf of the household. **Non-negotiable — see §23.**
- **Post-call:** transcript stored as a SOURCE_DOCUMENT node; extracted outcome; verification; graph write.
- **Hard bound:** the voice agent may never agree to anything outside its pre-authorised bounds. Out-of-bounds request → "I'll need to confirm and call back."

### 13.4 Feature list (A–Z)

Graph-first clarification (ask only the unknown) · urgency detection and re-prioritisation · provider discovery by relevant location · multi-factor transparent ranking · insurance/coverage filtering · prior-experience weighting · availability matching against real free windows · pre-call authorisation bounds · automated disclosure · in-call branch handling · out-of-bounds refusal · confirmation verification before recording · calendar write with travel time · reminder chain · provider history update · retry and fallback ladder · web-booking fallback path · full transcript provenance · **quote-gathering mode** (call three vendors, compare, report)

### 13.5 Data / graph

**Consumes:** intention text, graph state (person, availability, constraints, insurance, history), provider directories, real-time availability.
**Produces:** outbound calls, bookings, quote comparisons, vendor outreach.
**Graph writes:** PROVIDER nodes, `booked_with` edges, call transcripts as SOURCE_DOCUMENT, OBLIGATION completion, OUTCOME.
**Graph reads:** PERSON availability and preferences, CONSTRAINT, prior PROVIDER interactions, OBLIGATION.

### 13.6 Failure modes

| Failure | Mitigation |
|---|---|
| Books the wrong slot/person | Verification step before recording; read-back in call |
| Agrees to something unauthorised | Hard pre-authorised bounds; out-of-bounds → callback |
| Clinic asks something it can't answer | Never guess — take a message, escalate |
| Call fails / no answer | Retry ladder → web fallback → escalate with everything prepared |
| Provider is hostile to automated callers | Detect, abandon gracefully, escalate |
| Booking recorded but not actually made | **Never record without verification**; discrepancy escalates |
| Legal exposure on recording/disclosure | Disclosure always; recording policy per §23 |

### 13.7 Demo beat

"Book a dentist" → two clarifying questions, not twenty → transparent ranked shortlist with reasons → approval gate → **live call placed and heard** → slot unavailable, agent adapts within bounds → booking verified → calendar entry appears → graph updated. This is the most visceral "it actually did that" moment available in the entire system.

**Demo safety:** run against a controlled/sandbox counterparty rather than a real clinic (§23). Say so honestly rather than implying a live cold call to a real business.

---

## 14. VOICE INTERFACE AND MULTILINGUAL OPERATION

**Scope note.** §13 covers *outbound* voice — the system calling a dentist. This section covers *inbound* voice — the household talking to GharOS — and the multilingual operation of the entire system, which is broader than voice alone.

### 14.1 Why voice is the correct primary interface for this product

Not a feature bolt-on. Three structural reasons:

1. **The mental load is spoken, not typed.** Household coordination happens verbally, in passing, while doing something else — "remind me to call the plumber," "Aarav has a field trip Friday," "did we pay the society dues?" A typing interface requires stopping, unlocking, opening, and composing. Most intentions die in that gap (see §9: forgetting is only ~10–14% of unfulfilled intentions; friction is the rest). Voice removes the friction the Intention→Action Converter exists to attack.
2. **The Unlikely Hero is usually mid-task.** The person carrying household anticipation is cooking, driving, or supervising homework when the thought arrives. Hands and eyes are occupied; the mouth is free.
3. **Language reach.** A typed interface in English silently excludes household members — grandparents, domestic staff — who are central to household operations but may not type comfortably in English, or at all. Voice in the language they actually speak includes them.

**Design consequence:** voice is a first-class input channel on equal footing with email and document upload — it enters the same Pub/Sub pipeline, produces the same SOURCE_DOCUMENT nodes, and triggers the same subsystems. It is *not* a chat window with a microphone icon.

**Track discipline:** voice must not turn GharOS into a conversational assistant. The autonomy story is unchanged — voice is an input and escalation surface, not the product. Most of what the system does still happens with nobody talking to it. Guard this in the demo: show background action first, voice second.

### 14.2 Supported languages

**English, Hindi (हिन्दी), Marathi (मराठी), Spanish (Español).**

Two distinct challenge classes, and they are not equally hard:

**Class A — Code-mixed Indic (Hindi, Marathi).** The hard case. Real Indian household speech is not pure Hindi or pure Marathi. It is Hinglish and Marathi-English mixing, often mid-sentence:
- *"Aarav ko Friday ko field trip hai, permission slip sign karna hai"*
- *"Society maintenance cha payment kela ka?"*
- *"Maid aaj nahi aayi, mark her absent"*

The system must handle **intra-sentential code-switching** — not detect one language per utterance, but handle two or three within one sentence, including English nouns inside Hindi/Marathi grammar. Treating this as "detect language, then translate" fails badly.

**Additional Indic complications:**
- **Hindi and Marathi share Devanagari script.** Script detection does not disambiguate them. Disambiguation must be lexical and grammatical, and some short utterances are genuinely ambiguous between the two.
- **Transliteration variance.** The same word is romanised many ways ("nahi", "nahin", "nhi"); the same name appears in Devanagari, in Latin script, and in multiple spellings across documents.
- **Numerals and amounts.** Lakh/crore conventions, mixed numeral systems, spoken amounts ("saade teen hazaar" = 3,500). Errors here flow directly into payments.
- **Kinship terms as identifiers.** "Amma", "Baba", "Kaku", "Didi", "Mausi" are how people are actually referred to. These must resolve to PERSON nodes and are person-specific — one household's "Kaku" is a different individual from another's.

**Class B — Spanish.** Comparatively clean: consistent script, mature ASR/TTS, well-defined grammar. Main considerations are regional variation (Latin American vs Peninsular vocabulary and pronunciation), formality register (tú/usted — matters for outbound calls), and date/number formats. Include it for reach and demo breadth, but do not let its relative ease mask how much harder Class A is.

### 14.3 Language is a graph property, not a global setting

**Per-PERSON language profile** (extends the PERSON node in §5.2):
- `primary_language` — what they speak by default
- `languages_understood[]` — what they can be addressed in
- `script_preference` — Devanagari vs Latin transliteration for written output
- `code_mixing_profile` — observed mixing pattern; learned, not declared
- `formality_preference` — relevant to Spanish and to Hindi/Marathi honorifics
- `literacy_mode` — voice-only, text-capable, or both (matters for domestic staff)

**Language routing rules:**
1. **Respond in the language the person used**, matching their code-mixing register — not "correct" formal Hindi to someone speaking Hinglish. Over-formalising reads as alien.
2. **Notifications** go in each recipient's `primary_language`, independent of the language the triggering document was in.
3. **A single household is multilingual.** One family may have a Marathi-speaking grandparent, Hinglish-speaking parents, English-speaking children, and a Hindi-speaking maid. The same obligation may need to be communicated to four people in three languages. This is normal, not an edge case.
4. **Outbound calls (§13)** use the *provider's* likely language, not the household's — a Pune clinic is addressed in Marathi or Hindi; the language choice is part of the pre-call brief and is approved along with everything else.
5. **The graph stores the original.** Every utterance and document retains its source-language text alongside any normalised form. **Never discard the original** — provenance requires being able to show what was actually said, and translation is lossy.

### 14.4 The inbound voice pipeline

```
UTTERANCE
   │
   ▼
Wake / push-to-talk / continuous session
   │
   ▼
STREAMING ASR ── multilingual, code-mix tolerant, per-token confidence
   │
   ▼
LANGUAGE + SCRIPT IDENTIFICATION ── per-span, not per-utterance
   │
   ▼
NORMALISATION ── transliteration, numerals, dates, amounts, kinship terms
   │
   ▼
ENTITY RESOLUTION ── against graph, language-aware alias matching
   │
   ▼
INTENT CLASSIFICATION ── command / information / intention / question / approval
   │
   ▼
CONFIRMATION DISCIPLINE ── read back anything consequential (§14.6)
   │
   ▼
ROUTE to subsystem  ──▸ same Pub/Sub pipeline as every other input
   │
   ▼
SOURCE_DOCUMENT node written (audio ref + transcript + original language)
   │
   ▼
RESPONSE ── TTS in the speaker's language and register
```

### 14.5 What voice can and cannot do

| Intent class | Example | Handling |
|---|---|---|
| **Capture** | "Aarav has a field trip Friday" | Route to Consequence Engine as a source; full implication pipeline runs |
| **Intention** | "Remind me to call the plumber" | Route to Intention→Action; blocker diagnosis follows |
| **Command (R0/R1)** | "Mark the maid absent today" | Execute; confirm verbally |
| **Query** | "Did we pay the society dues?" | Graph query; answer with the path if asked |
| **Approval (R2/R3)** | "Yes, cancel that subscription" | **Read-back confirmation required — see §14.6** |
| **Decision trigger (R4)** | "Should we buy a car?" | Convene Council; voice is the *entry point*, the brief is delivered visually |
| **Correction** | "No, that's Kaku not Baba" | Update entity resolution; feed back into alias learning |

**Deliberate limits:**
- **R4 decisions are never resolved by voice.** A relocation or property brief is too information-dense for audio; voice initiates, the visual surface delivers.
- **Long lists are not read aloud.** Beyond about three items, the system summarises and points to the visual surface.
- **The graph is not narrated.** Path explanations are shown, not spoken, except for a one-line "because…" summary.

### 14.6 Confirmation discipline (the safety core of voice)

ASR errors are qualitatively different from typing errors: the user does not see them before they take effect. This is the single largest new risk voice introduces.

**Mandatory read-back for:**
- Any amount of money
- Any person's name where a hard constraint is involved
- Any date or time being committed to
- Any approval of an R2/R3 action
- Any staff attendance or salary entry

**Read-back rules:**
1. Read back in the **speaker's language**, using the **normalised, unambiguous form** ("three thousand five hundred rupees" — not "saade teen hazaar" echoed back, which would confirm nothing).
2. Amounts are read digit-grouped and repeated ("₹3,500 — three thousand five hundred").
3. Names are read with their graph relationship for disambiguation ("Aarav, your son").
4. **Approval by voice requires an explicit affirmative.** Silence, ambiguity, or a non-committal response is treated as *not approved*.
5. Low ASR confidence on any consequential token forces a clarifying question, never a guess.
6. **R3 (money) actions may be *initiated* by voice but require confirmation on a visual surface.** Voice alone is not sufficient authorisation to move money — spoofing and misrecognition risk are both too high.

### 14.7 Multilingual operation beyond voice

Language handling is a whole-system property, not a voice feature:

- **Document extraction (§5.4)** must handle mixed-script and mixed-language documents — school notices in English with Hindi headers, society notices in Marathi, handwritten registers with names in Devanagari.
- **Chat ingestion** must handle romanised Hindi/Marathi in WhatsApp, which is the dominant real-world form.
- **Entity resolution (A5)** must match across scripts and transliterations — "आरव", "Aarav", "Arav" as one PERSON.
- **Outbound drafting** produces messages in the recipient's language with correct register and honorifics.
- **The Fair Allocator interview (A17)** runs in each person's own language — a Marathi-speaking grandparent must be able to state preferences without an English intermediary.
- **Council member delegates** carry their person's language for any surfaced reasoning.
- **Notifications and approvals** render per-recipient.

### 14.8 Voice agents

*(These are agents A62–A69, listed in full in §15.11.)* In summary: session management, streaming ASR handling, per-span language identification, normalisation, intent classification, confirmation, response generation with TTS, and accessibility adaptation.

### 14.9 Feature list (A–Z)

Barge-in and interruption handling · code-mixed intra-sentential understanding · confirmation read-back with normalised forms · continuous and push-to-talk modes · correction handling ("no, I meant…") · Devanagari and Latin script handling · digit-group amount read-back · elder-friendly pacing and volume adaptation · formality/honorific register matching · graph-aware alias resolution across scripts · hands-free operation · Hindi/Marathi disambiguation · intent classification · kinship-term resolution · language identification per span · multi-speaker household voice identification (who is speaking) · noise-robust ASR (kitchen, car, street) · numeral system handling (lakh/crore, spoken amounts) · per-person language profiles · regional Spanish variation · response in speaker's register · session state across turns · silence and ambiguity treated as non-approval · transliteration variance tolerance · TTS in four languages · voice-initiated Council convening · wake word

### 14.10 Failure modes

| Failure | Severity | Mitigation |
|---|---|---|
| ASR misrecognises an amount | **Critical** | Mandatory digit-grouped read-back; R3 requires visual confirmation |
| ASR misrecognises a child's name where an allergy is involved | **Critical** | Name + relationship read-back; never guess on hard-constraint entities |
| Hindi/Marathi confusion on a short utterance | Medium | Fall back to the speaker's `primary_language`; ask if still ambiguous |
| Code-mixing breaks a monolingual ASR path | High | Code-mix-tolerant model; per-span identification, never per-utterance |
| Kinship term resolves to the wrong person | High | Per-household alias learning; confirm on first use; escalate on ambiguity |
| Background noise produces phantom commands | Medium | Confidence floor; wake-word gating; no R2+ action without explicit affirmative |
| Voice spoofing authorises a payment | High | Voice never sufficient for R3; visual confirmation required |
| Speaker misidentified in a multi-person household | Medium | Voice identification with confidence; unknown speaker → restricted to R0/R1 |
| TTS mispronounces names badly enough to confuse | Low | Pronunciation hints on PERSON nodes, learned from corrections |
| Elderly user's speech pattern poorly recognised | Medium | Slower pacing, longer silence tolerance, patient re-prompting; never rush a re-ask |
| Translation loses meaning in the graph | Medium | **Always retain the original-language text**; normalised form is additive, never replacing |

### 14.11 Accessibility

Voice is an accessibility feature, and the design should treat it as one deliberately:
- Elderly members with limited literacy or poor eyesight can participate fully
- Domestic staff who may not read English can report attendance and leave in their own language
- Hands-free operation for anyone mid-task
- Adjustable pacing, repeat-on-request, and patient re-prompting without penalty
- Voice-only mode (`literacy_mode`) for people who will never use the visual surface

### 14.12 Demo beat

A household member says, in Hinglish: *"Aarav ko Friday ko field trip hai, permission slip sign karna hai aur paise dene hai."*

On screen: the code-mixed utterance transcribed with per-span language tags · the graph growing as the Consequence Engine derives the implied obligations · the response spoken back in matching Hinglish register · then a second utterance in Marathi from a different family member, correctly attributed and handled.

This is a strong beat because multilingual code-mixed voice driving an autonomous action pipeline is visibly hard and visibly working. **Keep it to ~20 seconds and do not let it become the centrepiece** — the autonomy is the story; voice is how the story gets started.

---

## 15. COMPLETE AGENT ROSTER (69 AGENTS)

Design rule throughout: **one responsibility per agent, explicit input/output contracts, explicit forbidden list.** Reasoning agents never hold action credentials.

### 15.1 Orchestration (2)

**A0 — Household Coordinator.** Root orchestrator. Routes normalized events to subsystem pipelines, sequences them, manages run state. Pro-tier. *Forbidden:* extraction, deep content reasoning, external action. *Failure:* unroutable → human triage queue.

**A1 — Priority Arbiter.** When multiple subsystems claim the same event or resources contend, decides ordering by urgency and consequence. Flash. *Forbidden:* performing the work it schedules.

### 15.2 Intake layer (8)

**A2 — Intake Router.** Classify channel and content type; assess relevance. Flash. *Forbidden:* extraction, implication, action. *Failure:* unknown type → human triage, never silent discard.

**A3 — Document Extraction Agent (multimodal).** Extract structured content from images, PDFs, scans, screenshots, handwritten notices — **applying the schema from the Document-Type Registry (§5.4) for the classified type.** Field-level confidence and source-region pointers. Gemini multimodal — Flash for clean, Pro-tier for degraded/handwriting. *Forbidden:* **inferring anything not literally present.** Extraction and implication are separate agents by design — mixing them launders hallucinations as extracted facts. *Failure:* below threshold → mark ambiguous, retain image, surface. *Registry gap:* unknown type → generic extraction + human triage + log the gap.

**A3b — Line-Item Extraction Agent.** Specialised sub-extractor for receipts, itemised bills, and statements: per-line description, quantity, unit price, total, tax; product-category normalisation across merchants (so "AMUL TAAZA 1L" and "Milk 1 litre" resolve to the same category). Pro-tier multimodal for degraded thermal receipts. *Forbidden:* inferring items not printed; guessing quantities. *Failure:* partial extraction is acceptable and flagged — a receipt with 12 of 15 lines read is still useful; a receipt with fabricated lines is poison.

**A3c — Verification Agent.** Given a verification document (§5.5), check what it confirms or contradicts in the graph: did the constraint-required item get bought, did the payment clear, did the booking actually happen, does the attendance register agree with the chat leave messages. Pro-tier. *Outputs:* `verifies` / `contradicts` / `absent_from` edges, and discrepancy records. *Forbidden:* **silently overwriting a contradicted graph claim** — always opens a discrepancy and escalates. Silent correction destroys the audit trail.

**A4 — Message Normalization Agent.** WhatsApp exports/screenshots, UPI SMS, app notifications → normalized events. Multi-language and code-mixed. Flash. *Forbidden:* action, implication.

**A5 — Entity Resolution Agent.** Map mentions to graph nodes ("Amma", "Mummy", a phone number → one PERSON). Flash with Pro-tier escalation. *Forbidden:* creating entities above a confidence threshold without confirmation. *Failure:* **never guess on hard-constraint-bearing entities** — wrong child's allergy is a safety failure.

**A6 — Relevance Classifier.** Filter noise (school marketing, promotional SMS) before expensive reasoning. Flash. *Forbidden:* discarding — low-relevance is logged, not deleted.

### 15.3 Graph layer (5)

**A7 — Graph Builder.** Write nodes and edges with provenance tags, derivation types, confidence. Deterministic + Flash. *Forbidden:* creating any edge without a provenance pointer.

**A8 — Graph Query Agent.** Translate subsystem information needs into traversals. Flash. *Forbidden:* interpreting results (the caller does that).

**A9 — Path Explainer.** Given a conclusion, produce the walkable path that justifies it, tagged by derivation type. Pro-tier. **This is the "answer is a path, not a vibe" capability.** *Forbidden:* asserting anything not on the path.

**A10 — Pattern Miner.** Scheduled. Mine OUTCOME history for regularities → PATTERN nodes ("appointments scheduled Monday slip 60% of the time"). Pro-tier. *Forbidden:* creating patterns below a support threshold.

**A11 — Graph Maintainer.** Scheduled. Supersession, staleness marking, orphan detection, integrity checks. Deterministic. *Forbidden:* pruning DECISION, OUTCOME, provenance, or hard-constraint nodes — **ever**.

### 15.4 Consequence Engine (5)

**A12 — Implication Agent** *(flagship).* Derive obligations NOT stated. Pro-tier, elevated thinking. *Outputs:* candidate OBLIGATIONs with `implies` edges, confidence, and **mandatory source-span citation**. *Forbidden:* writing graph directly; acting; producing an obligation without a citable span. *Failure:* uncitable → discarded, logged.

**A13 — Constraint Checker.** Evaluate candidates against hard/soft constraints. Flash for lookup, Pro-tier for interpretation ("does 'may contain traces' violate a nut allergy?" — yes, but that's judgment). *Forbidden:* resolving violations. *Failure:* hard-constraint ambiguity → **always escalate**, never resolve optimistically.

**A14 — Conflict Radar.** Temporal, resource, capability, load conflicts. Pro-tier (needs reasoning over availability and implicit travel time). *Forbidden:* unilaterally resolving multi-person conflicts.

**A15 — Obligation Writer.** Persist validated obligations with provenance; dedupe; supersession. Flash/deterministic. *Forbidden:* modifying content.

**A16 — Constraint Learner.** Detect repeated signals suggesting a new constraint. Pro-tier. *Forbidden:* writing hard constraints without human confirmation.

### 15.5 Fair Allocator (5)

**A17 — Interviewer.** Adaptive comparative elicitation. Flash for flow, Pro-tier for question selection. *Forbidden:* computing valuations or assigning.

**A18 — Valuation Extraction Agent.** Complaints + interviews + voice notes + observed history → cardinal cost matrix. Pro-tier. *Forbidden:* solving. *Failure:* sparse matrix → request coverage, never fabricate values.

**A19 — Fairness Verifier / Explainer.** Verify the property holds; explain each share in that person's own valuations. Pro-tier for explanation; verification deterministic. *Forbidden:* altering the allocation. *Note:* verification against an external checkable signal — deliberately avoids LLM self-critique.

**A20 — Renegotiation Trigger.** Monitor for life events warranting re-allocation. Flash.

**A21 — Load Monitor.** Continuous fairness-over-time tracking; detects creeping imbalance between formal re-allocations. Flash.

### 15.6 Intention→Action (5)

**A22 — Intention Capture.** Detect intentions expressed in passing; detect stale obligations. Flash. *Forbidden:* acting directly.

**A23 — Blocker Diagnosis Agent** *(core).* Determine the specific obstacle per the six-type taxonomy. Pro-tier. *Outputs:* classification + explicit natural-language diagnosis shown to the user. *Forbidden:* unblocking.

**A24 — Unblocker / Preparation.** Fetch information, narrow decisions, pre-draft, decompose first steps. Flash for retrieval, Pro-tier for narrowing/drafting. *Tools:* read, search, draft. **No send without approval.**

**A25 — Window Scheduling.** Find windows where person AND counterparty are available AND historical patterns suggest completion. Flash with Pro-tier fallback.

**A26 — Slippage Analyst.** On repeat failure, re-diagnose; after N attempts escalate with options (drop / delegate / pay). Pro-tier.

### 15.7 Household Ledger (8)

**A27 — Financial Signal Ingestion.** Normalize financial signals to LEDGER_EVENTs. Flash; Pro-tier multimodal for handwritten registers and degraded scans. *Forbidden:* reconciliation judgment, action.

**A28 — Reconciliation Agent** *(read-only by construction).* Match debits to series; detect recurrences, price changes, duplicates; reconcile dues; compute staff salary. Pro-tier for matching; arithmetic delegated to a calculation tool. *Tools:* **READ ONLY — no communication, no payment.** Architectural non-negotiable. *Failure:* mismatch → dispute branch.

**A29 — Leakage Detection.** The "worth reasoning" step — is this still wanted, given usage signals and priorities? Pro-tier. *Forbidden:* cancelling anything.

**A30 — Recovery Drafting.** Draft cancellations, disputes, claims, price-adjustment requests using learned per-merchant playbooks. Pro-tier. *Tools:* draft only. *Forbidden:* sending; moving money.

**A31 — Follow-up / Persistence.** Track open claims and vendor requests; re-contact on cadence; escalate after N. Flash. *Note:* where autonomous persistence beats humans most decisively.

**A32 — Dispute Branch.** Assemble both conflicting figures with evidence for human resolution. Pro-tier. *Forbidden:* choosing which is correct.

**A33 — Vendor Relations.** Vendor request lifecycle, reliability scoring, switching proposals. Flash. *Tools:* communication (draft), read.

**A34 — Staff Payroll Agent.** Attendance → days worked → minus advances → salary due; leave and coverage tracking. Pro-tier for attendance interpretation; arithmetic deterministic. *Forbidden:* paying.

### 15.8 Household Simulator (6)

**A35 — Decision Framing.** Clarify the real decision; detect false binaries; surface unconsidered options. Pro-tier.

**A36 — Grounding / Research.** Pull real external data per branch with citations. Flash retrieval, Pro-tier relevance. *Forbidden:* projecting consequences.

**A37 — Path Simulator** *(instantiated per branch, parallel).* Project one branch across the entire graph. Pro-tier, elevated thinking. *Forbidden:* comparing branches; self-assessing quality. **Parallel exploration, not debate — never frame it as debate.**

**A38 — Consistency Critic** *(adversarial).* Red-team each projected branch for wishful thinking, omitted second-order effects, optimism bias. Pro-tier, elevated thinking. *Note:* critiques *another agent's* output — the pattern that works.

**A39 — Calibration Agent.** Adjust projections using this household's own OUTCOME variance. Pro-tier; statistics delegated to a tool. *Failure:* insufficient history → say so, never produce false precision.

**A40 — Decision Synthesizer.** Assemble the brief; support interrogation. Pro-tier. *Forbidden:* recommending a choice on emotionally-loaded family decisions — presents trade-offs, not verdicts.

### 15.9 Household Council (9)

**A41 — Council Convener.** Detect major-decision triggers; select which specialists and delegates to instantiate. Pro-tier. *Forbidden:* holding a position itself.

**A42 — Finance Specialist.** Queries the Ledger subgraph: real affordability, existing commitments, EMI capacity, upcoming known outflows. Pro-tier. *Tools:* ledger read only.

**A43 — Care Specialist.** Queries the constraint/medical subgraph: mobility, access, proximity, care continuity. Pro-tier. *Tools:* constraint read only. *Note:* produces **hard constraints that eliminate options**, not scores.

**A44 — Education Specialist.** Queries the education subgraph: exam years, admission cycles, transfer windows, catchment. Pro-tier.

**A45 — Logistics Specialist.** Queries the obligation subgraph: real recurring trips, distances, capacity requirements, parking. Pro-tier.

**A46 — Legal/Compliance Specialist.** Documentation, society rules, regulatory requirements. Pro-tier. *Forbidden:* giving legal advice — flags issues for professional review.

**A47 — Member Delegate** *(one instantiated per relevant household member).* Scores options against **that person's actual valuation profile** from the Fair Allocator. Pro-tier. *Forbidden:* inventing preferences not supported by the profile; speaking for anyone else. *Note:* the profile is visible and correctable by the person it represents.

**A48 — Council Adversary.** Attacks the leading option using the household's own history. Pro-tier, elevated thinking. *Forbidden:* proposing alternatives (that's option generation).

**A49 — Council Recorder.** Write every COUNCIL_POSITION with evidence to the graph; record concessions. Deterministic. *Forbidden:* summarising positions into consensus.

*(The mechanism arbiter is a deterministic tool, not an agent — see §16.)*

### 15.10 Outbound Concierge (7)

**A50 — Requirement Clarifier.** Query the graph first; ask only genuinely unknown things; detect urgency. Pro-tier. *Forbidden:* asking what the graph already knows.

**A51 — Service Discovery.** Find candidate providers by relevant location and service type. Flash. *Tools:* search, places.

**A52 — Provider Ranking.** Multi-factor transparent ranking including prior household experience. Pro-tier. *Outputs:* ranked list **with reasons**. *Forbidden:* opaque ranking.

**A53 — Call Planner.** Produce the pre-call brief: objective, authorised bounds, disclosable facts, must-not-answer list. Pro-tier. *Forbidden:* setting bounds beyond what the human approved.

**A54 — Voice Call Agent.** Conduct the call. Pro-tier realtime. *Tools:* voice (approval-gated). *Forbidden:* agreeing outside authorised bounds; guessing answers; failing to disclose it is automated.

**A55 — Confirmation Verifier.** Cross-check the outcome against what was requested before anything is recorded. Pro-tier. *Forbidden:* **recording an unverified booking.** Discrepancy → escalate.

**A56 — Fallback Coordinator.** Retry ladder, web-booking fallback, graceful escalation with everything pre-prepared. Flash.

### 15.11 Voice interface (8)

**A62 — Voice Session Manager.** Own the session: wake/push-to-talk, turn-taking, barge-in, silence timeouts, multi-turn context, session close. Flash realtime. *Forbidden:* interpreting content. *Failure:* session corruption → close cleanly and re-prompt, never act on a partial turn.

**A63 — Speech Recognition Handler.** Streaming ASR with per-token confidence, code-mix tolerant, noise-robust. Gemini realtime. *Outputs:* transcript with token-level confidence and timing. *Forbidden:* "cleaning up" the transcript into fluent monolingual text — **that destroys the code-mixing signal and hides uncertainty.** *Failure:* low confidence on consequential tokens → forces clarification.

**A64 — Language & Script Identifier.** Per-span (not per-utterance) language tagging; Hindi/Marathi disambiguation by lexicon and grammar, not script. Flash. *Failure:* ambiguous short utterance → fall back to speaker's `primary_language`, flag low confidence.

**A65 — Normalisation Agent.** Transliteration variance, numerals (lakh/crore, spoken amounts), dates, kinship terms → canonical forms. Pro-tier for ambiguous amounts. *Forbidden:* discarding the original text. *Failure:* ambiguous amount → always clarify, never round or guess.

**A66 — Speaker Identification Agent.** Who in the household is speaking. Flash. *Outputs:* PERSON reference with confidence. *Failure:* unknown speaker → **restrict to R0/R1 actions only**; never accept an approval from an unidentified voice.

**A67 — Voice Intent Classifier.** Capture / intention / command / query / approval / decision-trigger / correction. Pro-tier. *Forbidden:* executing — it classifies and routes only.

**A68 — Confirmation Agent.** Enforce the read-back discipline of §14.6: normalised forms, digit-grouped amounts, name-plus-relationship, explicit affirmative required. Pro-tier. *Forbidden:* **treating silence or ambiguity as approval.** *Hard rule:* R3 (money) is never approved by voice alone.

**A69 — Voice Response Agent.** Generate spoken responses in the speaker's language and register, with pacing adapted to the listener (elder mode, noisy-environment mode). Pro-tier + TTS. *Forbidden:* reading long lists aloud or narrating the graph — summarise and point to the visual surface.

### 15.12 Cross-cutting (2 + services)

**A57 — Confidence Arbiter.** Evaluate every proposed action against thresholds; decide execute / approve / escalate / discard. Deterministic policy + Pro-tier for borderline. **Sits between Layer 3 and Layer 5 and is the only path to action.**

**A58 — Escalation Agent.** Route escalations to the right member (capability- and availability-aware) with enough context to decide. Flash.

**Services (not LLM agents):** Approval Gate (assembles evidence bundles, manages expiry — **expiry escalates, never auto-approves**); Audit Logger (immutable append, written before every action); Memory Consolidation (scheduled off-peak promotion of observations into consolidated knowledge).

---

## 16. COMPLETE TOOL INVENTORY AND PERMISSION MODEL

### 16.1 Permission tiers

| Tier | Capability | Who may invoke |
|---|---|---|
| **T0 — Read** | Graph read, documents, statements | Any reasoning agent (scoped by subgraph) |
| **T1 — Search** | External research, business hours, provider discovery, merchant terms | Grounding, Discovery, Unblocker, Leakage |
| **T2 — Draft** | Compose messages, forms, claims, briefs (no send) | Drafting agents |
| **T3 — Internal write** | Graph writes, calendar entries | Writer agents only |
| **T4 — External communication** | Send messages outside the household | **Approval Gate only** |
| **T5 — Voice (outbound)** | Place outbound calls | **Approval Gate only, within authorised bounds** |
| **T5i — Voice (inbound)** | ASR, TTS, speaker ID for household interaction | Voice agents; inbound voice grants **no action capability of its own** |
| **T6 — Financial** | Execute payment, pause/cancel mandate | **Approval Gate only, after explicit human approval** |

### 16.2 Tool list

**T0:** graph reader (subgraph-scoped) · document store reader · statement/SMS archive reader · calendar reader · outcome history reader · transcript reader

**T1:** web research (citation-returning) · provider/places search · business hours lookup · merchant terms lookup · availability lookup

**T2:** message composer · form pre-filler · claim/dispute composer · decision brief composer · call-script composer

**T3:** graph writer (provenance-enforcing) · calendar writer · outcome recorder

**T4:** message sender — *approval-gated* · form submitter — *approval-gated*

**T5:** outbound voice caller — *approval-gated, bounds-enforced, disclosure-enforced*

**T5i:** streaming ASR (multilingual, code-mix tolerant) · TTS (four languages) · speaker identification · pronunciation store

**T6:** payment executor — *approval-gated, idempotency-keyed* · mandate pause/cancel — *approval-gated* · refund/claim submitter — *approval-gated*

**Deterministic computation tools (not LLM):**
- **Fairness solver** (Nash welfare / competitive equilibrium) — used by the Allocator
- **Council mechanism arbiter** — computes decision resolution from published positions and constraints. **Deterministic by design; this is what prevents the Council from degenerating into LLM consensus-generation.**
- Salary calculator (days − absences − advances)
- Calibration/variance calculator
- Deterministic conflict detector (runs before the reasoning pass)
- Idempotency key generator
- Graph integrity checker

### 16.3 Isolation invariants

1. No agent holds both money-analysis (T0) and financial (T6) capability.
2. T4, T5 and T6 are reachable **only** through the Approval Gate.
3. Every T3/T4/T5/T6 invocation writes an AuditRecord **before** execution.
4. T6 invocations carry an idempotency key; replays are no-ops.
5. T5 invocations carry authorised bounds; out-of-bounds requests terminate the call politely.
6. Council specialists have **mutually distinct** T0 subgraph scopes — enforced, not conventional.
7. Inbound voice (T5i) confers **no action capability**. A voice utterance is an input; it must pass through the same arbitration and approval path as any other input. **R3 money actions are never approved by voice alone** (§14.6).

---

## 17. INGESTION ADAPTERS

Swappable, so ingestion fragility is an adapter problem, not a core-architecture problem.

| Adapter | Source | Mechanism | Fragility | Notes |
|---|---|---|---|---|
| Email | School, merchants, utilities, society | Mailbox integration or forwarding address | Low | Most reliable |
| Document upload | Photographed forms, notices, registers | Direct upload | Low | Best demo surface — visibly messy |
| SMS / UPI alerts | Bank and payment debits | User-forwarded or Android notification access | **High — no official personal-data API** | Be transparent |
| WhatsApp | Staff coordination, society group | Chat export, screenshot, forwarding | **High — no personal-data API** | Be transparent |
| Portal notification | School/utility portals | Forwarded notification or credentialed scrape | Medium | |
| Voice inbound (telephony) | Confirmations, callbacks | Telephony webhook | Medium | Pairs with Concierge |
| **Voice inbound (household)** | Spoken capture, commands, intentions | Device mic → streaming ASR | Low–Medium | **Primary interface (§14)**; multilingual, code-mix tolerant |
| Scheduled tick | Monthly cycles | Cloud Scheduler | Low | |
| Manual intention | Voice note, quick text | Direct capture | Low | |

**Honesty requirement:** WhatsApp and UPI have no official personal-data APIs. The system relies on user-forwarded data or device notification access. **State this plainly in the submission and demo.** A judge who discovers an overclaimed integration discounts everything else; a team that states the limitation and shows a clean adapter abstraction reads as rigorous.

---

## 18. HUMAN-IN-THE-LOOP POLICY

### 18.1 Action risk tiers

| Tier | Definition | Policy | Examples |
|---|---|---|---|
| **R0 — Silent** | Reversible, internal, no external effect | Execute; log | Graph write, calendar entry, information prep |
| **R1 — Notify** | Reversible, low-impact, visible | Execute; notify | Draft message, propose menu substitution, shopping list |
| **R2 — Approve** | External communication, non-financial | Require approval | Send message outside household, submit form, **place a call** |
| **R3 — Explicit approve** | Any movement of money | Require approval + evidence bundle | Pay dues, pay salary, cancel mandate, file dispute |
| **R4 — Escalate only** | Irreversible, high-stakes, emotionally loaded | **Never auto-execute; present options only** | Relocation, property purchase, care arrangements, ending staff employment, medical choices |

### 18.2 Rules

- Confidence below threshold downgrades an action at least one tier.
- Hard-constraint involvement forces at least R2.
- Approval expiry escalates; **never auto-approves.**
- Every approval request carries: proposed action, reasoning, evidence consulted, confidence, consequence-if-wrong.
- Overrides captured with reason and fed back into the relevant model.
- The Council never resolves R4 — it produces a brief; humans decide.
- **Demo requirement:** the approval gate must be visible. Never show the agent spending money or placing a call without a visible confirm.

---

## 19. FAILURE TOLERANCE, IDEMPOTENCY, CONFIDENCE

### 19.1 Idempotency

Every action carries a key from (entity-ID, action-type, cycle/period). Replays are no-ops returning the original result. Payments are strictest: one debit per due-ID per cycle, enforced at the **tool** level, not the agent level. **Demonstrate it:** kill a run mid-flight, restart, show no duplicate.

### 19.2 Confidence

Every derived node, edge, and proposed action carries a confidence score. Thresholds configurable per action tier — safety-critical paths (hard constraints, payments, medical, voice) strictest. Below threshold: downgrade tier, escalate, or discard. **Never silently proceed.** Confidence surfaced in every approval request.

### 19.3 Worker failure and recovery

- Sub-agents are time-boxed; hung or looping agents terminated, absence handled by the orchestrator.
- Parallel branch simulation and council reporting proceed on survivors; failures reported, not hidden.
- Tool failures logged and escalated. **A failed tool call never produces a fabricated success** — a hallucinated "claim submitted" or "appointment booked" is worse than a reported failure.
- Reconciliation mismatches enter the dispute branch.
- Call failures enter the fallback ladder.

### 19.4 Checkpointing

Long-running workflows checkpoint at named stages. Multi-day workflows (claim awaiting response, due awaiting payment, callback pending) persist and resume on event. Resume is safe because of idempotency.

---

## 20. MEMORY, CONSOLIDATION, GRAPH MAINTENANCE

**Persists:** the full graph; valuation and friction profiles; vendor/merchant/provider playbooks; OUTCOME history; DECISION and COUNCIL_POSITION records; full audit log with provenance chains.

**Scheduled consolidation (off-peak):** repeated dietary mentions → candidate hard CONSTRAINT (confirmation-gated) · completion patterns → friction profiles · vendor latency → reliability scores · valuation signals → cost matrix drift · OUTCOME clusters → PATTERN nodes · stale obligations → flagged for review.

Running this off the critical path makes the morning's reasoning cheaper and better than computing cold.

**Never prune:** provenance records, DECISION nodes, COUNCIL_POSITIONs, OUTCOME records, hard-constraint nodes.

**Why this is the moat:** month six is materially better than day one. The graph compounds. This is the honest answer to "could a competitor copy this in a weekend" — they can copy the pipeline; they cannot copy six months of a specific household's accumulated, provenance-tagged decision history.

---

## 21. GOOGLE STACK MAPPING (MANDATORY REQUIREMENTS)

### 21.1 Requirement 1 — Gemini 3.5+ via Gemini API or Vertex AI ✔

Load-bearing in seven distinct places:

| Use | Why Gemini specifically | Tier |
|---|---|---|
| Multimodal ingestion | Native handling of photographed forms, handwritten registers, scanned notices, screenshots, bill PDFs — the messiest input set in the competition | Flash / Pro-tier for degraded |
| Implication reasoning | Deriving unstated obligations is reasoning, not extraction | Pro-tier, elevated thinking |
| Valuation extraction | Mutating complaint streams into a cardinal cost matrix | Pro-tier |
| Branch simulation & critique | Multi-step projection across a large graph + adversarial critique | Pro-tier, elevated thinking |
| Council specialist reasoning | Domain reasoning over distinct subgraphs | Pro-tier |
| Blocker diagnosis | Judgment about why *this* person stalls on *this* task | Pro-tier |
| Voice interaction (outbound) | Realtime conversation with branch handling | Pro-tier realtime |
| Voice interaction (inbound) | Multilingual streaming ASR/TTS with intra-sentential code-mixing across English, Hindi, Marathi, Spanish | Realtime; Pro-tier for ambiguous normalisation |
| Cross-script entity resolution | Matching आरव / Aarav / Arav as one person | Flash, Pro-tier on ambiguity |

**Cost discipline (state explicitly):** Flash for high-volume ingestion, normalization, routing, and bulk consolidation; Pro-tier reserved for the hard reasoning steps. Long context for whole-graph reasoning; structured output enforces the graph schema at every write.

### 21.2 Requirement 2 — Google Agent Framework: ADK ✔

- Multi-agent orchestration: coordinator + 61 specialized sub-agents
- Sequential pipelines (extract → imply → deconflict → own)
- Parallel execution (per-branch simulation; independent council reporting)
- Loop patterns (follow-up persistence, unblock-retry, call fallback ladder)
- Tool isolation and scoped permissions (§16)
- Callbacks implementing approval gates, bounds enforcement, and escalation
- Session/state services backing the graph

**The strongest architectural story in the build; maps directly onto the 30% weight's "secure tool isolation" and "failure tolerance."**

### 21.3 Requirement 3 — Google Cloud infrastructure ✔

| Service | Role | Why it exists |
|---|---|---|
| **Firestore** | The household knowledge graph | Document-shaped, evolving, per-household; the entity that visibly mutates on stage |
| **Pub/Sub** | Inbound triggers, inter-stage messaging, council fan-out | Makes the system *event-driven* rather than chat — the most-rewarded Taskmaster property |
| **Cloud Run** | Agent services, scale-to-zero | Proves genuine background operation; cost story between events |
| **Cloud Scheduler** | Monthly cycles, consolidation, follow-up cadence, call retries | Salary cycles, dues, renewals, off-peak consolidation |

**Optional if genuinely earned:** Cloud SQL for relational reconciliation; a managed memory/vector service for consolidated knowledge; a graph-capable store if Firestore traversal performance becomes the bottleneck.

**Do not add services for diagram sophistication.** Every service must be defensible in one sentence.

---

## 22. OBSERVABILITY AND AUDIT

- Every agent invocation traced: inputs consulted, outputs produced, model tier, confidence, latency.
- Every action preceded by an AuditRecord write.
- Full provenance chain queryable from any node back to the source region that produced it.
- Council deliberations fully replayable: who said what, on what evidence, in what order.
- Call transcripts retained as SOURCE_DOCUMENT nodes.
- **Demo use:** audit trail + Cloud Run logs are the "it actually ran on Google Cloud" proof. Show real timestamps from a genuine prior background run, not only the live run.

---

## 23. SECURITY, PRIVACY, DATA HANDLING, LEGAL CONSTRAINTS

- **All demo data synthetic.** No real family data, no real financial credentials, no real medical records.
- Household data is inherently sensitive: children's schooling, elderly medical schedules, domestic staff employment, family finances.
- Financial credentials never touch a reasoning agent — only the gated payment tool, targeting a **sandbox** in the hackathon build.
- **Staff data** (attendance, salary, advances) is employment data about a third party who has not consented to an AI system. Acknowledge explicitly rather than ignoring it.
- **Medical information** is read-only context for scheduling and care-gap detection. The system **never advises on medical decisions.**
- **Children's data** warrants the strictest handling; a minor's delegate agent in the Council represents scheduling and welfare interests only.
- **Voice calls — legal constraints (important):**
  - The agent **must disclose** it is an automated assistant calling on behalf of the household. Non-negotiable.
  - Call recording consent law varies by jurisdiction (one-party vs all-party consent). Do not record without meeting the stricter standard for the jurisdictions involved.
  - Automated calling may violate some providers' terms of service.
  - **For the demo, call a controlled/sandbox counterparty, not a real business — and say so honestly.** Implying a live cold call to a real clinic when it is staged is the kind of overclaim that discredits an otherwise strong submission.
- Provenance retention is a privacy trade-off: it enables auditability but retains sensitive originals. State the retention policy.

---

## 24. THE 4-MINUTE DEMO SCRIPT

Pitch-order rule (§4.1) applies: concrete autonomous action first, OS framing last.

**0:00–0:20 — The problem, concretely.** One household, one week, the invisible load. Name the Unlikely Hero. One line of evidence (cognitive-labour research) to establish this is real, not anecdotal.

**0:20–0:40 — The trigger.** A chaotic school email lands, shown in full ugliness. The agent wakes on a Pub/Sub event with **no user present.** Emphasise: nobody asked it to do anything.

*(Voice enters later, at 2:20 — deliberately after autonomy is established, so the submission never reads as a voice assistant.)*

**0:40–1:40 — Autonomous execution + the graph assembling itself.**
- Extraction from the messy source, visible
- Six obligations appear — five **implied** — each with a provenance edge back to its source span
- **The graph visibly grows on screen**; a conflict edge lights up red (nut allergy vs Tuesday's menu)
- Temporal collision caught (1:30 pickup vs 1:00 meeting)
- Fair Allocator assigns ownership with a one-line reason
- Firestore writes live

**1:40–2:20 — The outbound call (the visceral beat).**
"Book a dentist" → two clarifying questions (not twenty — the graph already knows the rest) → transparent ranked shortlist with reasons → **approval gate shown** → **live call placed and audible** → the requested slot is gone, the agent adapts within authorised bounds → booking verified → calendar entry appears → graph updated.

**2:20–2:40 — Voice, multilingual (short and deliberate).** A family member says, in Hinglish: *"Aarav ko Friday ko field trip hai, permission slip sign karna hai."* Show the per-span language tagging, the graph growing from spoken input, and the reply in matching register. Then a second speaker in Marathi, correctly attributed. **Twenty seconds — do not let voice become the centrepiece.**

**2:40–3:05 — The Council (the intellectual beat).**
Convene the car decision. Specialists report from genuinely different subgraphs — Finance from the real Ledger, Logistics from real recurring trips, Care contributing a **hard constraint that eliminates options rather than scoring them**. Member delegates score in genuine conflict from behaviourally-derived profiles. The Adversary lands a hit using the household's own history. The **deterministic arbiter** publishes the explicit trade-off. The whole deliberation persists into the graph as a walkable record.
*Say "specialists with different data and delegates with different interests." Never say "debate."*

**3:05–3:25 — The exception (must be live).** A form where the child's name is ambiguous → the agent does **not** guess on a hard-constraint-bearing entity → escalates with the image and its reasoning. **The agent knowing when not to act is the point.**

**3:25–3:40 — Outcome.** Measurable: obligations derived vs stated, conflicts caught that would have surfaced too late, money identified, actions completed with no human touch, one real booking. Be honest about what required approval.

**3:40–4:00 — Architecture + Google Cloud proof.** Pub/Sub event → ADK topology on Cloud Run → Firestore graph mutation → audit trail with **real timestamps from a genuine overnight run**. Close with the OS framing — now it's earned.

---

## 25. BUILD SEQUENCING

**Phase 1 — Graph substrate.** Node/edge schemas in Firestore; provenance discipline; traversal operations; graph integrity checker; audit logger; Pub/Sub topics; Cloud Run skeleton; ADK coordinator.

**Phase 2 — Perception.** Intake router; multimodal extraction; message normalization; entity resolution; relevance classifier. Test against the *ugliest* documents first.

**Phase 3 — Consequence Engine.** Implication agent (flagship — most time here); constraint checker; conflict radar; obligation writer; constraint learner.

**Phase 4 — Graph visualisation.** Live force-directed rendering with derivation-tagged edges. Built early because it is the demo's spine and drives schema decisions.

**Phase 5 — Arbitration and action.** Confidence arbiter; approval gate; risk tiering; tool permission scoping; idempotency; first real external actions.

**Phase 6 — Outbound Concierge.** Clarifier; discovery; ranking; call planner; voice agent; verifier; fallback ladder.

**Phase 7 — Ledger.** Signal ingestion; reconciliation (read-only); leakage detection; payroll; recovery drafting; follow-up; dispute branch; vendor relations.

**Phase 8 — Fair Allocator.** Interviewer; valuation extraction; deterministic solver; verifier/explainer; renegotiation; load monitor.

**Phase 9 — Intention→Action.** Capture; blocker diagnosis; unblocker; window scheduling; slippage analyst.

**Phase 10 — Simulator.** Framing; grounding; parallel branch simulation; consistency critic; calibration; synthesizer.

**Phase 11 — Council.** Convener; five specialists; member delegates; adversary; recorder; deterministic mechanism arbiter.

**Phase 12 — Consolidation and pattern mining.** Memory consolidation; pattern miner; graph maintainer; observability; a genuine unattended overnight run producing real logs.

**Phase 13 — Voice and multilingual layer.** Session management; streaming multilingual ASR; per-span language identification; normalisation (transliteration, numerals, kinship terms); speaker identification; intent classification; confirmation discipline; TTS in four languages. Build *after* the text pipeline works — voice is an input path onto an existing pipeline, and debugging both at once is avoidable pain. Extend cross-script entity resolution at the same time.

**Phase 14 — Demo hardening.** Rehearse the live path repeatedly; identify break points; cache/mock flaky external calls; sandbox the call counterparty; record a backup video; verify the exception beat fires reliably.

---

## 26. DEMO DATA REQUIREMENTS

All synthetic, all realistic:

- **Roster:** two adults, two children (one in a board-exam year), one elderly parent with a recurring medical schedule and a mobility constraint, two domestic staff
- **Constraints:** at least one hard dietary, one hard medical schedule, one mobility, one custody or travel constraint
- **Ugly documents (8–12), spanning multiple registry types:** photographed permission slip with handwriting; scanned society maintenance notice; school PDF with mixed-language text; utility bill PDF; WhatsApp screenshot with code-mixed text; handwritten attendance register photo; **a crumpled thermal grocery receipt** (the verification beat); **a restaurant bill**; a warranty card
- **The verification pair (build this deliberately):** a grocery receipt that (a) discharges an open shopping obligation, (b) shows a substitution against the planned list, and (c) is **missing** the nut-free item the constraint required — producing an `absent_from` signal live on stage. This single artifact demonstrates the loop closing.
- **Financial signals:** 3 months of UPI SMS including one silent price hike, one unused recurring service, one duplicate charge
- **Outcome history:** enough completed obligations with predicted-vs-actual variance for Calibration to produce non-generic output — **required**, or backward mode gives generic advice
- **Decision scenarios:** a car purchase with real grounding data; optionally a relocation
- **Provider set:** a controlled/sandbox dentist counterparty for the live call
- **One deliberately ambiguous document** to trigger the live escalation beat
- **Voice and language set:** a household with genuinely mixed language profiles (Marathi-speaking grandparent, Hinglish-speaking parents, English-speaking children, Hindi-speaking domestic staff) · scripted code-mixed utterances in Hinglish and Marathi-English · names appearing in both Devanagari and Latin script across documents · at least one spoken amount in Indic numeral convention ("saade teen hazaar") to demonstrate normalisation and read-back · one Spanish utterance for breadth

---

## 27. KNOWN RISKS AND OPEN QUESTIONS

### 27.1 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Pattern-matched as "generic AI personal assistant" | High | Pitch order (§4.1); lead with concrete autonomous action |
| Council read as invalidated multi-agent debate | **High** | §12.2 discipline; distinct tools/objectives; deterministic arbiter; never say "debate" |
| Track ambiguity — reads as Fortified Enterprise Fleet | High | Single-household framing; no registry; internal deliberation, not a federation |
| Ingestion fragility (WhatsApp/UPI no API) | Medium-High | Adapter abstraction; state openly |
| Autonomy thinner than claimed | High | Measure no-human-touch actions at midpoint; switch track if near zero |
| Hallucinated implied obligations | High | Mandatory source-span citation; uncitable → discard |
| Fabricated booking (recorded but not made) | **High** | Verification before recording; never fabricate success |
| Voice call legal/ToS exposure | Medium-High | Disclosure always; sandbox counterparty for demo; honest framing |
| Overclaiming the fairness guarantee | Medium | State exactly what is delivered |
| Simulator reads as fortune-telling | Medium | Ground every branch in graph data; show the critic working |
| Live demo brittleness | High | Rehearse; cache flaky calls; backup recording; deterministic exception beat |
| Graph looks hand-seeded | Medium | **Build it live from messy input during the demo** |
| Voice reframes the product as a chat assistant | **High** | Voice enters the demo at 2:20, after autonomy is established; keep the beat to 20s |
| ASR error on an amount causes a wrong payment | **Critical** | Digit-grouped read-back; R3 never approved by voice alone; visual confirmation required |
| ASR error on a child's name where a hard constraint applies | **Critical** | Name-plus-relationship read-back; never guess on constraint-bearing entities |
| Code-mixing breaks the ASR path | High | Code-mix-tolerant model; per-span language ID, never per-utterance |
| Hindi/Marathi confused on short utterances | Medium | Lexical/grammatical disambiguation, not script; fall back to speaker's primary language |
| Four languages is more than can be done well | Medium-High | English + Hinglish carry the demo; Marathi and Spanish demonstrate breadth. **Better to do two excellently and two adequately than four badly** |

### 27.2 Open questions to resolve before/during build

1. Which ingestion adapter is primary for the demo — forwarded email (reliable) or notification access (impressive, fragile)?
2. What exact fairness property will the chores solver deliver, and how will it be stated?
3. How much OUTCOME history must be seeded for Calibration to be non-generic?
4. Which is the live exception beat — ambiguous-document escalation or a failed call recovery? (Both compete for the same ~20 seconds.)
5. Does the payment tool target a sandbox rail or is it stubbed with a visible "would execute" state?
6. What is the minimum graph density that makes Conflict Radar produce *surprising* catches rather than obvious ones?
7. Is the demo's Council scenario the car (tighter, more legible) or the house (bigger blast radius, harder to fit in 45 seconds)?
8. Does Firestore traversal performance hold at demo graph size, or is a graph-native store needed?
9. How many registry types must be implemented for the demo to feel general rather than hard-coded? (Suggested floor: four visibly different types processed live — a school communication, a receipt, a handwritten register, and a financial alert.)
10. Product-category normalisation across merchants is a real sub-problem — is a fixed taxonomy sufficient, or does it need to be learned per household?
11. Does the verification beat (`absent_from` on the nut-free item) land in the demo, or does it need too much setup to be legible in the time available?
12. Which two of the four languages get full-depth treatment, and which two are breadth demonstrations? (Recommended: English and Hinglish at depth.)
13. Does the available ASR handle intra-sentential Hinglish acceptably out of the box, or does it need prompting/post-correction? **Test this in week one — it gates the entire voice layer.**
14. Is speaker identification reliable enough in a noisy household to gate approvals on, or should all approvals route to the visual surface regardless of speaker confidence?
15. How are kinship terms bootstrapped for a new household — explicit onboarding, or learned from first-use confirmations?

---

## 28. GLOSSARY

- **Obligation** — a unit of household work, stated or implied
- **Implication** — the reasoning step deriving unstated obligations; the core product capability
- **Provenance** — the pointer chain from any node/edge back to the source region that produced it
- **Document-Type Registry** — the open set of typed extractors, each with its own schema and edge mapping (§5.4)
- **Verification document** — an input that closes edges rather than opening them: receipts, statements, confirmations (§5.5)
- **`absent_from`** — the signal that expected real-world evidence never arrived; silent non-compliance
- **Registry gap** — an unrecognised document type, logged so the registry can grow
- **Code-mixing** — switching languages within a single sentence (Hinglish, Marathi-English); the normal form of Indian household speech, not an edge case
- **Intra-sentential** — code-mixing *within* one sentence, as opposed to between sentences; the harder case
- **Per-span language ID** — tagging language at the phrase level rather than per utterance
- **Read-back discipline** — mandatory verbal confirmation of amounts, names, dates and approvals in normalised form (§14.6)
- **Literacy mode** — whether a person uses voice only, text, or both; matters for elderly members and domestic staff
- **Derivation tag** — `extracted` / `inferred` / `ambiguous`
- **Hard constraint** — must never be violated (allergy, medical, legal, custody, mobility)
- **Soft constraint** — preference; violation is advisory
- **Conflict radar** — cross-member detection of temporal, resource, capability, load conflicts
- **Blast radius** — graph traversal computing everything a change would affect
- **Council** — interest-and-information-based deliberation for major decisions; **not debate**
- **Member delegate** — an agent carrying one person's behaviourally-derived valuation profile
- **Mechanism arbiter** — the deterministic tool computing council resolution
- **Concession ledger** — historical record of who has given ground, for fairness over time
- **Risk tier (R0–R4)** — action classification determining autonomy vs approval
- **Permission tier (T0–T6)** — tool capability classification
- **Leakage** — money lost to unused, duplicated, or silently increased recurring charges
- **Silent hike** — a price increase within an existing recurring commitment
- **Dispute branch** — escalation path when reconciliation figures disagree
- **Forward / Backward mode** — Simulator's two query modes
- **Authorised bounds** — the pre-approved envelope a voice agent may commit within
- **Unlikely Hero** — the household member silently carrying anticipation and monitoring
- **BYOF** — "Bring Your Own Friction"

---

*End of specification v2.*
