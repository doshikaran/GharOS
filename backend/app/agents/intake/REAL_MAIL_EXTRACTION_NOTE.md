# A3 extraction on real-shaped mail vs. the golden-file baseline — honesty note

**Phase:** 14.5 (ADR-023) · **Owner:** E2 · **Status of the live run:** pending (see §4)

Gate 14.5 / PHASES.md Phase 14.5 E2 item: "Run A3 extraction against real
(not golden-file) mail bodies; write a short honesty note comparing
real-world extraction quality to the golden-file baseline." This is that
note. It is deliberately unflattering where the evidence points that way
— an honest degradation estimate is more useful to the gate than an
optimistic one.

---

## 1. What "the golden-file baseline" actually is

`backend/tests/test_golden_extraction.py` + `tests/golden/text_fixtures.py`
/ `image_fixtures.py`. Its own module docstring states the caveat this
note builds on:

> **Synthetic fixtures, disclosed plainly** … this suite has no access to
> real scanned/photographed household documents, so the five image-shaped
> registry types are rendered synthetically via Pillow … and the nine
> text-native types are hand-authored realistic-messy text.

So the "baseline" is: **hand-authored messy text, written by the same
people who wrote the extraction prompt, with every expected field and its
exact `str.index()` source span known in advance.** The golden suite
asserts field presence, `0.0 <= confidence <= 1.0`, `derivation in
{EXTRACTED, AMBIGUOUS}` (never `INFERRED`), and that every cited region
reproduces against the fixture text. It does **not** assert a numeric
field-recall percentage — there is no published baseline recall number to
regress against, only "the planted fields come back, cited, not
hallucinated."

The golden corpus has **no `email` channel fixture that went through
`EmailAdapter` first** — the text-native fixtures are fed to A3 directly.
Phase 14.5 is the first time a real mailbox message shape
(`RawIntakePayload` → `EmailAdapter.normalize` → A3) is exercised.

## 2. The real-shaped mail bodies used

Three hand-authored bodies, each written to look like what
`GmailConnector` / `OutlookConnector` hand `email_adapter.py` after MIME /
Graph-JSON parsing — i.e. messy in the ways *real forwarded household
mail* is messy, not the ways a hand-authored extraction fixture is messy.
They are checked in as test inputs, not as golden fixtures with expected
values:

| # | Shape | Where it lives |
|---|---|---|
| A | Parent forwards a school field-trip notice to a family Google Group. Substantive content sits under `---------- Forwarded message ---------`, a mail-client header block, and one level of `>` reply quoting. Outer forwarder adds their own sentence on top. | `tests/test_intake_router_real_mail.py::_REAL_MAIL_BODY`; A3 form in `tests/test_live_gemini_intake.py::test_a3_real_extraction_on_a_real_shaped_forwarded_school_mail` |
| B | Same notice re-forwarded a second time (two quote levels, `On <date>, <name> wrote:` separators, a top-posted "see below"). Used to confirm `EmailAdapter` de-quoting is idempotent and the content-hash dedupe (ADR-023 §3 item 6, NFC-normalized post-adapter text) still collapses it to the same document. | narrative here; structurally identical to A after `EmailAdapter`, which is the point |
| C | A utility-bill notification email: short HTML-turned-plaintext body, a table flattened to `Label: value` lines, a due date and an amount, plus a marketing footer and an unsubscribe line. | narrative here — representative of the other high-volume real mail class |

`school_communication` field schema under test (from the live registry):
`institution` (req, floor 0.70), `student` (req, 0.70),
`communication_type` (req, 0.65), `event_date` (opt, 0.70), `amount`
(opt, 0.75), `requirements` (opt, list, 0.60), `response_deadline` (opt,
0.75).

## 3. Predicted differences vs. the golden baseline

This section is a **reasoned prediction**, not a measurement (the
measurement is §4, pending). It is grounded in what `EmailAdapter`
actually does to the text and in the known failure modes of the A3 prompt.

### 3a. Field recall — expected *slightly lower*, concentrated on optional fields

- **Required fields (`institution`, `student`, `communication_type`)**:
  expected recall comparable to the golden baseline. `institution` is
  usually in an unambiguous signature block ("Greenwood International
  School" / "Grade 4 Coordinator, Greenwood…"), which survives
  `EmailAdapter` de-quoting intact. `communication_type` is inferable from
  strong lexical signal ("field trip", "consent", "payment").
- **`student`**: *higher miss risk than the golden baseline.* Real
  forwarded school mail is frequently addressed "Dear Parents" with the
  child's name **only in the subject line or not in the body at all** —
  and `EmailAdapter` does not carry the subject into `text_content` (it
  goes to `source_metadata`, which A3 is not given). Golden fixtures
  reliably plant the student name in the body; real mail does not. Expect
  `student` to land in `fields_not_found` more often, correctly (a miss,
  not a hallucination).
- **Optional fields (`event_date`, `amount`, `requirements`,
  `response_deadline`)**: recall expected to be **noisier**. Real bodies
  bury these in prose ("due back by Wednesday, 3 September", "a
  contribution of Rs. 500 per child") rather than in labelled lines. The
  model generally finds them, but `response_deadline` vs `event_date`
  disambiguation ("Friday 5 Sept" the trip vs "Wednesday 3 Sept" the slip
  deadline) is a real error source the golden fixtures under-represent
  because their dates are more explicitly labelled.

### 3b. Citation validity — expected *equal*, with one new offset hazard

The A3 prompt requires `text[start:end]` to reproduce the cited value,
and `document_extraction.py` re-validates the region in code (not by
trusting the model). This guarantee is structural and channel-independent
— **no degradation expected** in *whether* a citation is valid.

New hazard specific to this path: `EmailAdapter._normalize_body` rewrites
the text (drops boilerplate lines, strips `>` prefixes, collapses blank
runs). A3 cites offsets into the **normalized** body, which is correct
(that is the text it is given and the text stored as the SOURCE_DOCUMENT
payload). But anyone cross-referencing a citation against the *raw* MIME
body will find the offsets do not line up. This is expected and
acceptable — provenance points at the normalized artifact, consistently —
but it is called out here so a reviewer does not read an offset mismatch
against raw bytes as a citation bug.

### 3c. Hallucination / `INFERRED` leakage — expected *no change*

`Derivation.INFERRED` cannot be produced by A3 (grep-asserted in the
module; extraction and implication are separate agents by charter). The
real-mail bodies contain more *plausible-but-unstated* invitations to
infer (an outer forwarder writing "someone arrange the cash before
Wednesday" is not the school stating a deadline) — but A3's job is to
extract only what a span supports, and the below-floor →
`Derivation.AMBIGUOUS` path handles the rest. Expect the extra inferential
temptation to show up as **more `AMBIGUOUS` fields and more
`fields_not_found`**, not as fabricated `EXTRACTED` values. If a live run
shows otherwise, that is a real regression and a gate blocker.

### 3d. `EmailAdapter` as a failure point *before* A3

Two `EmailAdapter` behaviours materially change what A3 sees:

1. **Total-boilerplate bodies raise `IntakeNormalizationError`** ("email
   body was entirely forwarding/quoting boilerplate"). A real
   auto-generated notification whose entire content is a header block +
   an unsubscribe line can trip this. That is an adapter-level visible
   failure (→ `ERROR` outcome in the orchestrator, ADR-023 §4), not a
   silent drop, but it means "A3 recall" is conditional on the body
   surviving normalization at all.
2. **De-quoting is greedy on `>`**. A body that legitimately uses `>` as a
   literal character (rare in household mail, common in a forwarded
   code snippet or a quoted quote) loses that character. Low-probability
   for the school/utility/society classes Phase 14.5 targets; noted for
   completeness.

## 4. The live run — status and how to run it

**Not run in the environment that produced this note:** no Vertex AI
credentials / `GHAROS_RUN_LIVE_GCP_TESTS` is unset here, matching every
other `live_gcp`-marked test in the suite (skipped by default,
`test_gemini_client.py` convention). What *was* run here:

- `EmailAdapter.normalize` on body A — verified it keeps every
  substantive line and drops the forward marker, the header block, and
  the `>` markers (`tests/test_intake_router_real_mail.py`, 5 tests,
  passing).
- The full `EmailAdapter → A2 IntakeRouter` plumbing on body A with a
  faked model — verified it classifies as `school_communication` and, at
  low confidence, routes to a registry gap rather than dropping
  (same file).

The real A3-against-real-mail call is wired and ready:

```
GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=<project> \
  uv run pytest tests/test_live_gemini_intake.py \
    -m live_gcp -k real_shaped_forwarded_school_mail -v
```

It asserts the two conservative things a non-deterministic API allows:
`institution` is recovered, and every returned field is well-formed
(confidence in range, derivation not `INFERRED`, a well-formed source
region that resolves within the normalized body). **When a maintainer
with credentials runs it, the observed field set, per-field confidences,
and any `fields_not_found` / `AMBIGUOUS` entries should be pasted into a
new §5 of this file**, turning the §3 predictions above into a measured
comparison for the CTO gate.

## 5. Measured results

_(pending — populate from the live run in §4)_
