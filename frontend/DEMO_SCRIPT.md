# GharOS — 4-minute demo runbook (on-screen operator guide)

**Owner:** E4 (frontend). **Scope:** what is clicked, what is said, what must be
visible on camera, and the fallback for each beat. Mirrors `GharOS_Build_Spec_v2.md`
§24 beat-for-beat. Backend trigger orchestration, `DEMO_MODE`, seed reset, and the
sandbox call counterparty are E3/E1 — this file references them and names the
coordination points; it does not redefine them.

> **Placement note for the CTO:** this runbook lives in `frontend/` because E4 owns
> only that directory. If a shared `docs/DEMO_SCRIPT.md` is wanted, lift it verbatim.

---

## 0. Pre-flight checklist (run once, ~10 min before filming)

Do these in order. Do not start filming until every box is checked in **both themes**.

### 0.1 Services up

- [ ] `make emulators` — Firestore + Pub/Sub emulators running clean. If a previous
      session left emulators up, **kill them first** (`scripts/emulators.sh` handles
      this; a stale degraded emulator set has mass-failed the suite before — see
      `docs/PROGRESS.md` Phase 6 note).
- [ ] `make dev-backend` — `gharos-api` on `http://localhost:8000`. Hit
      `http://localhost:8000/health` (or `/healthz` per E3) and confirm `200`.
- [ ] `make seed-demo` — the full demo household loaded (E1: roster, hard
      constraints, 8–12 ugly documents, 3 months of financial signals, OUTCOME
      history for calibration, the engineered verification receipt). Re-run the
      **clean reset script** (E1) if the graph already has run artefacts from a
      rehearsal — the graph-growth beat only reads as *live* from a pre-trigger
      baseline.
- [ ] `DEMO_MODE` on per E3 (deterministic exception beat, cached/sandboxed
      external calls, sandbox dentist counterparty).
- [ ] `make dev-frontend` — Next.js on `http://localhost:3000`.
- [ ] `frontend/.env.local` has `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
      (the default if unset, so this only matters if a stale `.env.local` points
      elsewhere).

### 0.2 Browser

- [ ] **Chrome**, 1440×900 logical (the layout's primary target; also verified at
      375 for the responsive claim, but film at 1440).
- [ ] Zoom 100%. Bookmarks bar hidden. One window, one tab.
- [ ] DevTools **closed** during filming (open only for the network-panel proof in
      beat 8 if that route is taken).
- [ ] Hard-reload `http://localhost:3000` once so fonts are warm (no FOUT on camera).

### 0.3 Theme

The switcher is in the left nav sidebar footer (light / dark / system). It is also
on `/tokens`.

- [ ] Walk **every** route below once in **light** (Alice Blue `#F0F8FF` ground),
      once in **dark** (Vault `#0E1311` ground). Confirm: no unreadable text, no
      element that vanishes into the ground, no raw-white or raw-black panel, no
      horizontal page scroll.
- [ ] Pick the filming theme deliberately. **Dark (Vault) is recommended for
      camera** — the emerald/gold accents and the conflict-edge red pop harder
      against Vault, and the graph canvas reads with more contrast. Light is the
      backup theme if the room is bright.
- [ ] Whichever you pick, set it explicitly (not "system") so a machine theme change
      mid-demo can't flip it.

### 0.4 Tabs to pre-open (in this left-to-right order)

1. `http://localhost:3000/` — landing (problem framing)
2. `http://localhost:3000/graph` — the spine
3. `http://localhost:3000/approvals`
4. `http://localhost:3000/concierge`
5. `http://localhost:3000/voice`
6. `http://localhost:3000/council`
7. `http://localhost:3000/ledger` — outcome numbers
8. `http://localhost:3000/status` — Google Cloud proof (plus `docs/DEPLOYMENT_PROOF.md` open in a second app)

Leave `/graph` on tab 2 **un-triggered** (baseline only). Everything else can be
pre-loaded.

### 0.5 Data-source map (know which surfaces need the backend)

| Route | Backend needed? | Notes |
|---|---|---|
| `/` | no | Static landing. |
| `/graph` | **yes** | `/graph/snapshot` for baseline, `/graph/stream` (SSE) for the growth beat. |
| `/approvals` | no | Fixture-backed queue — deterministic on camera. |
| `/concierge` | yes (names only) | Graph snapshot for household names; the clarify/rank/call/verify/fallback content is deterministic fixture data (A50–A56 have no HTTP endpoint yet). |
| `/voice` | yes | `VoiceSessionPanel` + `LanguageProfileSettings` call the backend. |
| `/council` | partial | `CouncilExplorer` (the deliberation view) is fixture-backed and deterministic; `CouncilHistoryBrowser` ("Why did we decide this?") is live. |
| `/ledger` | yes | Recovered-money counter, disputes, payroll all read the live graph. |
| `/fair-allocator` | yes | Cost matrix + explanations + renegotiation read the live graph. |
| `/simulator` | no | Fixture-backed branches — deterministic. |
| `/status` | yes | Each card calls a real backend endpoint and shows the real response/error. |
| `/tokens` | no | Design-system reference. |

---

## The beats

Every beat lists: **window · route · say · on screen · fallback.**

---

### Beat 1 — The problem, concretely — 0:00–0:20

- **Route:** `/` (landing)
- **Say:** "One household, one week. The invisible load — the anticipating, the
  tracking, the remembering — falls on one person. Cognitive-labour research says
  that's real, not anecdote."
- **On screen:** the landing hero. Scroll once, slowly, to the single worked
  transaction (₹3,500 society maintenance threading through the device and the
  narrative). Do not linger past 0:20.
- **Fallback:** if a scroll-reveal stutters, stop scrolling and talk over the static
  hero — it carries the line on its own.

---

### Beat 2 — The trigger — 0:20–0:40

- **Route:** switch to `/graph` (tab 2), which is showing the **baseline** graph.
- **Say:** "A chaotic school email just landed. Nobody asked GharOS to do anything.
  It wakes on a Pub/Sub event with no user present."
- **On screen:** the messy source email shown in full (E3's trigger surface / the
  raw document), then the `/graph` baseline — a modest graph of known household
  structure, sitting still.
- **Do:** E3 fires the trigger now (the forwarded email → Pub/Sub → autonomous
  cycle). Hands off the keyboard; narrate.
- **Fallback:** if the live trigger stalls, E3 replays the same Pub/Sub message from
  the cached fixture. The graph beat (below) is what must land; the trigger
  mechanism can be the cached path without weakening the claim, as long as it is
  described honestly as a forwarded-email adapter.

---

### Beat 3 — Autonomous execution + the graph assembling itself — 0:40–1:40

**This is the highest-stakes visual beat. It must read as built live, not replayed.**

- **Route:** `/graph` (stay here the whole minute).
- **Say, while it grows:** "Extraction off the messy source. Six obligations —
  five of them *implied*, never stated — each with a provenance edge back to the
  exact span that produced it. Solid edge, extracted. Dashed, inferred. Now watch —
  a conflict edge lights up red: the nut allergy against Tuesday's menu. And a
  temporal collision — the 1:30 pickup against the 1:00 meeting. The Fair Allocator
  assigns each obligation an owner with a one-line reason. Every one of these is a
  live Firestore write."
- **On screen (in order, over ~30–40s):**
  1. New nodes fade + scale in on the canvas at a readable cadence — one, then an
     edge, then another — **not a single pop**. (This pacing is
     `lib/graph-growth-pacing.ts`: `--motion-graph-stagger` = 450 ms between
     arrivals, `--motion-graph-grow` = 600 ms per element. A backend burst is
     spread client-side so it's followable on camera; genuinely spaced arrivals are
     not delayed.)
  2. Provenance edges connect the new obligation nodes back into existing household
     structure.
  3. A **conflict edge in `--edge-conflict` red**, at 3× line width — unmissable.
  4. The node count in the summary line climbs live.
- **Do:** once it settles, click the conflict-involved obligation node → the **node
  inspector** opens → click **"Explain"** → the **path explainer** walks the chain
  back to the source document, highlighting the source span (now on
  `--highlight-surface`, legible in both themes). This is the provenance claim made
  concrete.
- **Mandatory-requirement proof #1 (Gemini):** say "the implication step there is a
  Gemini Pro-tier call via Vertex AI" — the extraction/implication that produced the
  implied obligations is the Gemini call. Optionally show one Cloud Logging line for
  it in beat 8.
- **Fallback:** if `/graph/stream` does not deliver, reload `/graph` once — the
  **snapshot** now contains everything the cycle wrote, so the end-state is intact
  (nodes, edges, the red conflict edge, provenance). You lose the *animation* but
  keep the *result*; narrate that the growth is live in the recorded backup. If even
  the snapshot is thin, cut to the backup recording for this beat only.

---

### Beat 4 — The outbound call — 1:40–2:20

- **Route:** `/concierge`
- **Say:** "Now it acts in the outside world. 'Book a dentist.' It asks two
  clarifying questions — not twenty, because the graph already knows the rest. Here's
  the ranked shortlist, each provider with its reason. Before any call is placed —
  the **approval gate**. Full evidence bundle: the proposed action, the reasoning,
  the evidence consulted, the confidence, and what happens if it's wrong."
- **On screen:**
  1. `ClarificationDisplay` — the two questions, and (greyed) what the graph already
     answered so nobody asked.
  2. `RankedShortlist` — providers with per-provider reasons (rank badge now
     `--ink-primary` on `--royal-soft`, legible in both themes).
  3. `CallApprovalGate` — **must be visibly approved before the call.** Click
     **Approve**. `approved` is real component state, not a fixture.
  4. `LiveCallTranscript` — the live, sandboxed **text** conversation streams in
     (never synthesised audio — ADR-016). The requested slot is gone; the agent
     adapts within authorised bounds and takes the next slot.
  5. `BookingConfirmation` — the booking, shown only after independent verification.
     A calendar entry appears. Back on `/graph` (quick tab flick) the graph has a new
     APPOINTMENT node.
- **Mandatory-requirement proof #2 (ADK tool call):** say "placing that call is an
  ADK tool invocation, permission-scoped — the reasoning agent that ranked providers
  cannot itself place calls or move money." The approval gate is the ADK callback.
- **Fallback:** every sub-panel here is deterministic fixture data except the
  `approved` toggle. If the transcript animation misbehaves, it renders fully on
  mount — scroll it. Do **not** skip the approval-gate click; it is non-negotiable
  that a call is never shown being placed without a visible confirm.

---

### Beat 5 — Voice, multilingual — 2:20–2:40 (20 seconds, hard cap)

- **Route:** `/voice`
- **Say:** "Voice is just another input path onto the same pipeline. A family member,
  in Hinglish: *'Aarav ko Friday ko field trip hai, permission slip sign karna
  hai.'*"
- **On screen:** the live transcript with **per-span** language tags (Hindi spans
  and English spans tagged separately *within* the one sentence, not one tag for the
  whole utterance). The graph grows from the spoken input. The reply comes back in
  matching register. A second speaker in Marathi, correctly attributed.
- **Fallback:** if live ASR/session misbehaves, use the scripted/cached utterance
  (E3). Keep this to 20 seconds regardless — **do not let voice become the
  centrepiece.** If it's shaky, cut it to 10 seconds and move on.

---

### Beat 6 — The Council — 2:40–3:05

- **Route:** `/council`
- **Say:** "For a major decision — the car — GharOS convenes **specialists with
  different data and delegates with different interests.** Finance reports from the
  real Ledger. Logistics from real recurring trips. Care contributes a **hard
  constraint that eliminates options** rather than scoring them down. The delegates
  are in genuine conflict. The Adversary lands a hit using the household's own
  history. A **deterministic arbiter** — not an LLM — publishes the explicit
  trade-off and who conceded."
  *(Never say "debate.")*
- **On screen:** `SpecialistPositions` (one card per specialist, each with its
  evidence — never a blended paragraph), `EliminatedBranches` (Care's hard
  constraint, shown as elimination), `DelegateScores` (per-person, conflicting),
  `AdversaryAttackView`, `TradeOffStatement` (the explicit trade-off). Then scroll to
  **"Why did we decide this?"** (`CouncilHistoryBrowser`) — a past DECISION node with
  every COUNCIL_POSITION, the trade-off, and who conceded. Institutional memory as a
  UI feature.
- **Fallback:** `CouncilExplorer` is entirely fixture-backed and deterministic — it
  cannot fail from a backend issue. Only the history browser is live; if it errors,
  skip the scroll and end the beat on `TradeOffStatement`.

---

### Beat 7 — The exception (must be live) — 3:05–3:25

- **Route:** `/approvals`, scroll to the **escalation surface** (below the queue).
  `R4` never appears in the queue — it routes straight here.
- **Say:** "Here's a form where the child's name is ambiguous — and that entity
  carries a hard constraint. GharOS does **not** guess. It escalates, showing the
  raw image and its own reasoning for not resolving it. The agent knowing when *not*
  to act is the point."
- **On screen:** `EscalationCard` / `EscalationSurface` — the source image, the
  ambiguity called out, the system's stated reason for declining, and **no
  approve/resolve button** (that is the escalation contract — it is never visually
  conflated with an approval).
- **Mandatory:** E2 guarantees this beat is **deterministic** in `DEMO_MODE`.
- **Fallback:** the escalation content is deterministic. If the surface itself won't
  render, cut to the backup recording for this 20 seconds — do not paper over it
  with a different beat.

---

### Beat 8 — Outcome + Google Cloud proof — 3:25–4:00

**Outcome (3:25–3:40):** route `/ledger` (for the money number) and one glance at
`/graph` (for the derived-vs-stated count).

- **Say:** "Measurable. Six obligations derived, five that were never written down.
  Two conflicts caught that would have surfaced too late. Found ₹X a year of leakage
  — three claims drafted, awaiting approval. One real booking, verified. Everything
  else: zero human touch. Where approval was required, we say so."
- **On screen:** `RecoveredMoneyCounter` running total; the "N obligations, M
  implied" summary on `/graph`.

**Architecture + Cloud proof (3:40–4:00):** route `/status`, with
`docs/DEPLOYMENT_PROOF.md` open alongside.

- **Say:** "Pub/Sub event → an ADK agent topology on Cloud Run → a Firestore graph
  mutation → an audit trail with **real timestamps from a genuine overnight run**.
  Cloud Scheduler drives the cycles. Now the framing it's earned: this is an
  operating system for a household."
- **On screen:** `/status` cards each showing a real response from the deployed
  `gharos-api`; then `docs/DEPLOYMENT_PROOF.md` — console screenshots, the
  source-build revision detail, the overnight Cloud Logging excerpt.
- **Mandatory-requirement proof #3 (Google Cloud infra):** `/status` proves the
  deployed frontend reaches the deployed backend; `DEPLOYMENT_PROOF.md` covers Cloud
  Run (both services, source deploys, `min-instances=0`), Firestore, Pub/Sub, Cloud
  Scheduler.
- **Fallback:** if the deployed backend was already scaled to zero (or is being kept
  at zero for cost), `/status` cards will show cold-start latency or errors — that's
  honest but weak on camera. Prefer showing `DEPLOYMENT_PROOF.md` screenshots and the
  Cloud Logging excerpt for this beat, and run `/status` live only against the local
  backend as the "frontend reaches API" demonstration.

---

## Where the three mandatory requirements are proven on camera

| Requirement | Beat | What the viewer sees |
|---|---|---|
| **Gemini 3.5+ via Vertex AI** | 3 (graph growth) | The implied-obligation implication step; named aloud as a Pro-tier Vertex call. Optional Cloud Logging line in beat 8. |
| **Google Agent Framework (ADK)** | 4 (outbound call) | The permission-scoped call tool invocation and the approval-gate callback; named aloud. Reinforced by the Council's tool-isolated specialists in beat 6. |
| **Google Cloud infra service** | 8 (Cloud proof) | `/status` (deployed FE → deployed API) + `DEPLOYMENT_PROOF.md` (Cloud Run, Firestore, Pub/Sub, Cloud Scheduler, overnight logs). |

---

## Rehearsal log (Gate 15 requires ≥3 clean full runs)

Record each run: date, filming theme, total time, and every break point + fix.

| Run | Date | Theme | Time | Break points | Fixed? |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**The exception beat (7) must fire cleanly on all three runs.** If it doesn't,
stop and escalate to E2 — do not proceed to filming.

---

## Backup recording — checklist / storyboard

Captured **before** the live presentation, as insurance. The capture itself is an
operator action; this is the spec they follow.

### Capture settings

- **Resolution:** 1920×1080, 60 fps (the graph-growth animation benefits from 60 fps;
  everything else is fine at 30). H.264 MP4.
- **Browser:** Chrome, 1440×900 logical viewport, 100% zoom, DevTools closed, single
  tab per beat as in §0.4.
- **Theme:** the chosen filming theme (dark/Vault recommended). Do the whole capture
  in one theme — do not switch mid-recording.
- **Audio:** record the narration track live over the capture, or capture silent and
  voice-over after. Either way the timing below is the target.
- **Environment:** local stack (§0.1), `DEMO_MODE` on, seed freshly reset so the
  graph-growth beat is genuinely from a clean baseline.

### Storyboard (target: 4:00 total)

| # | Beat | Route | Duration | Must be captured |
|---|---|---|---|---|
| 1 | Problem | `/` | 0:20 | Hero + one slow scroll to the worked transaction. |
| 2 | Trigger | trigger surface → `/graph` | 0:20 | Full ugly email; `/graph` baseline sitting still; trigger fired. |
| 3 | Graph growth | `/graph` | 1:00 | Staggered node/edge arrivals; provenance edges; **red conflict edge**; temporal collision; node inspector → path explainer → highlighted source span; count climbing. |
| 4 | Outbound call | `/concierge` | 0:40 | Two clarifiers; ranked shortlist with reasons; **approval gate approved on camera**; live transcript; slot-gone adaptation; verified booking; calendar entry. |
| 5 | Voice | `/voice` | 0:20 | Per-span language tags within one Hinglish sentence; graph grows from speech; Marathi second speaker attributed. **Hard 20s cap.** |
| 6 | Council | `/council` | 0:25 | Specialist cards with evidence; hard-constraint elimination; conflicting delegate scores; Adversary hit; deterministic trade-off; history browser. **No "debate."** |
| 7 | Exception | `/approvals` (escalation surface) | 0:20 | Raw ambiguous image; stated reason for declining; **no approve button.** |
| 8 | Outcome + Cloud | `/ledger` → `/status` + `DEPLOYMENT_PROOF.md` | 0:35 | Recovered-money counter; derived-vs-stated count; `/status` live cards; console screenshots + overnight Cloud Logging excerpt; OS framing last. |

### Post-capture

- [ ] Watch it once end-to-end at full speed. Confirm every "must be captured" item
      is actually on screen and legible.
- [ ] Confirm no raw-hex flash, no theme flip, no horizontal scrollbar, no DevTools
      visible, no console error toast.
- [ ] File: `GharOS_demo_backup_<YYYY-MM-DD>.mp4`. Store per E3/CTO instruction
      (submission asset location — not in this repo; it exceeds sane git size).
- [ ] Note its exact runtime. If over 4:00, trim beat 5 first, then beat 6's history
      scroll, then beat 1's scroll.
- [ ] After all captures/proofs: `make teardown` (Cloud Run services to zero).
