# A12 Implication Agent — honest evaluation baseline

Per PHASES.md Phase 4 ("The honest evaluation"): "Record the number either way — it is the project's real risk signal." This is that record, scored by hand by the CTO against 20 held-out documents A12 was never tuned against, using real live Vertex AI Gemini calls (`gemini-2.5-pro`, `location=global` per ADR-010), run 2026-08-24.

**Read this before trusting any obligation A12 produces without review**: the numbers below are genuinely mixed. Recall and citation discipline are strong. There is one clear, systematic weakness — A12 does not reliably recognize when nothing is genuinely implied — tracked as DEBT-007, repayment required before Phase 5.

## Methodology

**The 20 documents** (`backend/tests/evaluation/held_out_documents.py`) are new content written specifically for this evaluation — not reused from Phase 3's golden-file suite, not iterated against during A12's development. Each carries hand-written ground truth (`ground_truth_implied`), written *before* running A12, describing what a careful human would derive as genuinely implied (not stated) obligations, each tagged `clear` or `borderline`. Two documents (`eval-15-grocery-receipt`, `eval-20-library-books`) are deliberate **hallucination-rate control documents**: ordinary, low-stakes documents with zero genuine implied obligations, specifically designed to tempt a model into manufacturing plausible-sounding busywork. Any candidate obligation produced for either is a hallucination by construction.

**Scoring is by hand, deliberately not automated.** Matching a real, freely-worded model obligation against a hand-written ground-truth description is a semantic judgment call — automating it with a second LLM call would substitute one model's judgment for another's, not remove the judgment call (this reasoning is recorded directly in `implication_eval.py`'s own docstring, written by E2). The CTO read all 60 produced candidates, all 29 ground-truth items, and the one discarded inference, against the source text of every document, and scored each individually below.

**No iteration happened between this run and any prompt change.** This is a genuine first-pass, single-run baseline — not a number reached after tuning against these specific documents. (See "What happens next," below, for why a second run was deliberately not performed to chase a better number.)

## Headline numbers

| Metric | Value | Detail |
|---|---|---|
| **Recall** (of 29 ground-truth items across 18 non-control documents) | **81%** (23.5/29) | 21 full matches, 1 partial match (0.5), 6 full misses (one of which was discarded, not missed by reasoning — see below) |
| **Hallucination rate — overall** | **15%** (9/60 candidates) | The number PHASES.md calls "the number that matters" |
| **Hallucination rate — organic** (excluding the 2 designed control documents) | **9%** (5/56 candidates) | The more representative real-world rate |
| **Hallucination rate — control documents** | **100%** (4/4 candidates, both control docs) | The standout finding — see below |
| **Citation validity** (span is real, verbatim, *and* genuinely supports the specific claim made) | **85%** (51/60) | Every one of the 60 citations resolved to a real, verbatim span in its document — `citation_validator.py`'s structural guarantee held every time, zero fabricated spans. The 15% gap is entirely "real span, unsupported specific claim" (the hallucinated candidates), not "fake span" |

## The headline finding: A12 does not reliably recognize "nothing is genuinely implied"

Both control documents (`eval-15-grocery-receipt`: a plain, already-paid grocery delivery receipt; `eval-20-library-books`: a routine library return reminder) were designed so that a careful human derives **zero** further obligations. A12 produced 2 candidates for each, 4 total, **100% of which are hallucinations by the control's own construction** — plausible-sounding but genuinely invented tasks ("put away the groceries," "break down the packaging," "find the library books," "pack them into the school bag"). Every one of these citations is technically real (the model didn't fabricate a nonexistent span), but the specific *claim* — that these are genuine implied obligations, distinct from generic common sense — is not supported by anything in the document.

This is a narrower, more specific, and more actionable finding than "15% hallucination rate" makes it sound: **A12 currently has no working output path for "this document implies nothing beyond what's stated."** It always finds something to say. That is a real, fixable prompt-level gap (an explicit instruction and/or a worked negative example showing zero-candidate output is a valid, expected response), not evidence of broad unreliability — recall on the 18 real-world-shaped documents is strong (81%), and the organic hallucination rate on those same documents (9%) reflects a handful of specific, defensible-if-debatable overreach judgment calls (see per-document notes), not systematic invention.

**Tracked as `docs/DEBT.md` DEBT-007. Repayment required before Phase 5** — per PHASES.md's own decision point ("everything downstream assumes this agent is trustworthy"), shipping a flagship agent that reliably invents tasks on two out of two designed "nothing to imply" tests is not acceptable to carry into the phase that builds the Approval Gate around this agent's output.

## Second finding: the citation-length safeguard has a real short-document blind spot

`citation_validator.py` rejects any located span covering more than 60% of the whole document — a deliberate, reasoned anti-gaming measure (`_MAX_SPAN_FRACTION_OF_DOCUMENT`, preventing "cite the whole email" from trivially satisfying the citation requirement). On `eval-13-relative-visiting` (a two-sentence WhatsApp message, ~140 characters total), A12 correctly derived the single most valuable insight in the entire evaluation — the guest room is scheduled for painting the exact days the guest arrives — cited it accurately, and had it **discarded** solely because the necessarily-short document meant the specific, accurate citation covered 80% of the whole message. The reasoning was correct; the citation was real and specific; it was discarded on a structural technicality that disproportionately penalizes short source documents (SMS, chat messages) where any genuinely specific quote is a large fraction of the whole.

This is not a prompt problem — A12 got this one right. It's a citation-validator design trade-off worth revisiting (e.g., a length-aware threshold — an absolute minimum span length combined with the fraction, rather than a fraction alone). **Not fixed under time pressure during this evaluation** — patching the threshold hastily risks reopening the exact gaming vulnerability it exists to prevent, and deserves a proper ADR-level decision, not a mid-scoring patch. Tracked as DEBT-008.

## Per-document scoring

Full source documents, all 60 candidates' reasoning, and all citations are in `backend/tests/evaluation/held_out_documents.py` (ground truth) — this table is the scored summary, not a substitute for reading the source if auditing a specific call.

| Doc | GT items | Matched | Missed | Candidates | Hallucinated | Notes |
|---|---|---|---|---|---|---|
| 01 sports-day | 2 | 1.5 | 0.5 | 5 | 1 | Partial: correctly identifies Priya must sign (Rohan traveling) but misses the sharper "must sign by Monday, not the stated Wednesday" deadline-pull-forward insight. Hallucination: fabricated "check T-shirt/shoes condition" despite text stating items "already issued." |
| 02 allergy-test | 2 | 2 | 0 | 5 | 1 | Both GT items matched, including correctly using external context (Priya's fixed 9am meeting) to derive Rohan must take Aarav. Hallucination: manufactured a "plan call outside lunch hours" task from an incidental clinic-hours detail. |
| 03 water-shutoff | 2 | 1 | 1 | 4 | 0 | Correctly derived Sunita's cleaning must move. Missed the specific "must store by Saturday evening, not just 'in advance'" timing nuance — produced a real but less sharp "calculate how much water" instead. |
| 04 electricity-bill | 2 | 2 | 0 | 2 | 0 | Clean — both GT items matched precisely, no extraneous candidates. |
| 05 vet-reminder | 2 | 1 | 1 | 4 | 1 | Correctly booked around the Goa departure. Missed the boarding/pet-sitter implication entirely. Hallucination: invented a "prepare payment" task with no textual basis for a fee. |
| 06 car-insurance | 2 | 1 | 1 | 2 | 0 | Correctly derived the PUC-before-renewal chain. Missed the sharper "must finish before Tuesday's cardiology drive, since Rohan is sole driver" framing — produced a generic "pay premium" instead. |
| 07 landlord-inspection | 2 | 2 | 0 | 2 | 0 | Clean — both GT items matched precisely. |
| 08 sunita-leave | 1 | 1 | 0 | 2 | 0 | Correctly derived the elder-care coverage gap from a Hindi/English code-mixed message. |
| 09 bank-fraud-alert | 2 | 2 | 0 | 3 | 0 | Clean — both GT items matched, including the conditional "investigate before deciding" framing. |
| 10 pta-fee-costume | 1 | 1 | 0 | 3 | 0 | Correctly derived the costume deadline is the binding one, using external context (Aarav is in the group dance) not stated in the document. |
| 11 passport-renewal | 2 | 2 | 0 | 3 | 0 | Clean — both GT items matched, including the harder both-parents/travel-conflict reasoning. |
| 12 meera-medication | 2 | 1 | 1 | 3 | 1 | Correctly derived the medication-timing schedule conflict. Missed telling Sunita (the actual caregiver) entirely — never mentioned her. Hallucination: invented a "keep doctor's contact info ready" task from "report immediately." |
| 13 relative-visiting | 2 | 1 | 1 | 2 (+1 discarded) | 0 | The single strongest inference in the whole evaluation (painter/guest-room conflict) was correctly derived, correctly cited, and discarded on the citation-validator's short-document span-fraction limitation — see "Second finding" above. Scored as missed since it never reached the graph, though the reasoning was right. |
| 14 agm-proxy | 1 | 1 | 0 | 3 | 0 | Clean — correctly chained the proxy deadline against the travel dates. |
| 15 grocery-receipt (control) | 0 | — | — | 2 | 2 | Both candidates are hallucinations by the control's design — see "Headline finding" above. |
| 16 chat-dentist | 1 | 1 | 0 | 2 | 0 | Correctly connected a two-line WhatsApp exchange to a recurring tuition obligation not mentioned anywhere in the chat itself — genuinely strong context use. |
| 17 property-tax | 1 | 1 | 0 | 2 | 0 | Clean. |
| 18 appliance-service | 1 | 1 | 0 | 2 | 0 | Correctly connected the free-service window to an existing unresolved complaint from external context. |
| 19 dinner-reservation | 1 | 1 | 0 | 3 | 1 | Correctly derived the child-supervision gap (the key insight). Hallucination: invented generic "plan travel to the restaurant" busywork with no household-specific basis. |
| 20 library-books (control) | 0 | — | — | 2 | 2 | Both candidates are hallucinations by the control's design — see "Headline finding" above. |

## What happens next

Per PHASES.md's decision point, this baseline is being recorded honestly rather than silently accepted — and the specific, narrow, well-understood weakness it surfaced (no "nothing implied" output path) is tracked as **DEBT-007, repayment required before Phase 5**, not deferred indefinitely. A second live run chasing a better aggregate number was deliberately not performed as part of this same session: the fix this evaluation calls for is a specific prompt change (an explicit instruction/example for the zero-candidate case), and validating that fix properly needs its own full 20-document re-run scored with the same rigor as this one — conflating "fix the prompt" and "re-score under time pressure to get a cleaner number for this document" would risk exactly the kind of quietly-relaxed rigor this evaluation exists to prevent. DEBT-007's repayment condition requires a real re-run against this same held-out set, honestly labeled as no-longer-blind once that happens.

DEBT-008 (citation-validator short-document span-fraction limitation) is tracked separately, lower urgency — it caused a real miss but not a hallucination, and the current behavior (reject rather than risk a gaming vulnerability) is the safer default while an ADR-level fix is designed properly.
