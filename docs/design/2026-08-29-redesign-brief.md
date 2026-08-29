# GharOS visual redesign brief — royal, classy, elegant

**Author:** CTO, per explicit operator order, 2026-08-29 (after Phase 12's gate).
**Scope:** `frontend/styles/tokens.css`, fonts, a new motion system, a real narrative landing page, and the unified shell — every existing page inherits the refresh through the shell + tokens, not through a rewrite of each page's own internals.

## Why these choices — inspiration checked directly, not assumed

Fetched directly (real fetches, not guessed from memory):
- **antimattr.one** — real extracted palette: near-black surfaces (`#050505`/`#0d0d0d`/`#121212`), a navy-blue accent (`#09488a`/`#1083fa`), a deep-red accent (`#7c0505`/`#e10909`), a gold/amber accent (`#fea710`/`#feb940`), set on near-black. Inter throughout. Minimalist, bracketed micro-typography (`[reserve early access]`), a roadmap/timeline section, serious aspirational copy. This is the reference for the **dark theme's** new richness.
- **twotimespi.dev ("tau")** — this is the exact site the operator originally shared a screenshot of in Phase 7: a light graph-paper/notebook grid background with a red vertical margin rule (legal-pad style), a serif display + italic accent font pairing, navy-blue accents, Greek-letter mathematical motifs, sophisticated-yet-approachable tone. This is the reference for the **light theme's** background texture and the font-pairing direction.
- **workers.io** — blocked (403), no data obtained.
- **reducto.ai** — no visual data obtainable (JS-rendered, markdown-only fetch), but confirms the "serious agentic-product" positioning register GharOS's own copy should sit in.

## What changes, and what deliberately doesn't

**Does not change:** `--royal-primary`/`--royal-deep`/`--royal-soft`, `--accent-brass`/`--accent-brass-muted`, `--state-*`, `--derivation-*`, `--edge-conflict`, spacing, radius. These are load-bearing (dozens of already-shipped, already-tested components reference them by name) and already WCAG-verified — the operator's complaint was the background, the fonts, and the near-absence of motion, not these. Re-deriving them risks real regressions for no requested benefit.

**Does change:**
1. `--surface-base`/`--surface-raised`/`--surface-overlay` in both themes (below) — lighter/crisper in light mode, true near-black in dark mode (replacing the current brownish-ink dark, which reads muddy next to antimattr's actual near-black).
2. A new graph-paper grid texture and a red "margin rule" motif — genuinely thematic, not decorative-for-its-own-sake: GharOS's own tagline is "a ledger and archive that happens to think," and a ledger page's own grid + margin rule is a literal, on-brand callback, not a borrowed skin.
3. New font tokens — an elegant accent serif for hero/pull-quote moments, alongside (not replacing) the existing Fraunces/Inter pairing.
4. A new, real motion system — the existing `--motion-*` tokens stay (functional UI transitions still want to be quick and quiet); new `--reveal-*` tokens are added specifically for marketing/landing-surface animation, which is where "more animation" actually belongs. The graph's own growth animation (Phase 6, spec §5.8's signature moment) is untouched in logic — only its easing curve may pick up the new emphasized-motion token if E4 judges it reads better.
5. A genuinely new landing page with a real storyline (the current one is a Phase 0 placeholder that was never turned into a product page — see the copy below).

## Exact token additions/changes for `frontend/styles/tokens.css`

```css
:root {
  /* SURFACES — replaces the old warm-parchment values. Lighter, crisper
     "fine stationery" ivory rather than "old parchment" beige. */
  --surface-base: #f9f7f1;
  --surface-raised: #fdfcf8;
  --surface-overlay: #ffffff;

  /* NEW — graph-paper grid texture (light theme): a faint royal-blue
     line, low enough opacity to read as texture, never as UI chrome. */
  --paper-grid-line: rgba(34, 60, 119, 0.08);
  --paper-grid-size: 28px;

  /* NEW — the margin-rule motif: a deep, classic ledger red — richer/
     more restrained than a bright red, matching "royal" rather than
     "alert." Distinct hue register from --state-danger and
     --edge-conflict on purpose (this is decorative/structural, never a
     status color — must never be reused for an error or a conflict). */
  --margin-rule: #8a2332;

  /* NEW — accent serif, for hero headlines/pull-quotes/landing-page
     storytelling moments only — never body copy, never dense UI text.
     `--font-display` (Fraunces) and `--font-body` (Inter) are unchanged
     and keep their existing roles everywhere else. */
  --font-accent: var(--font-accent-family, "Instrument Serif", var(--font-display));

  /* NEW — expressive motion, for marketing/landing surfaces only. The
     existing --motion-* tokens are unchanged and still govern ordinary
     UI transitions (buttons, panels, the approval queue, etc). */
  --reveal-duration: 640ms;
  --reveal-stagger: 90ms;
  --reveal-distance: 24px;
  --reveal-ease: cubic-bezier(0.16, 1, 0.3, 1);
}

[data-theme="dark"] {
  /* SURFACES — true near-black, replacing the old brownish-ink dark.
     Matches antimattr's actual extracted values, not a guess. */
  --surface-base: #0c0a08;
  --surface-raised: #17130f;
  --surface-overlay: #211b15;

  /* NEW — graph-paper grid texture (dark theme): a faint brass line,
     reusing the existing --accent-brass hue so the texture always
     belongs to this theme's own palette rather than introducing a
     seventh color family. */
  --paper-grid-line: rgba(221, 179, 95, 0.08);

  /* NEW — margin rule, dark theme: warmed/lightened so it stays legible
     and rich against near-black rather than reading as pure alarm-red. */
  --margin-rule: #c9605a;
}
```

**Mandatory for E4 before treating this as done:** re-verify every existing WCAG contrast ratio this file's own comments already document (ink-primary/secondary/muted, royal-primary, accent-brass, every state-*, every derivation-*, edge-conflict — both themes) against the **new** `--surface-base`/`--surface-raised`/`--surface-overlay` values above, the same rigor this file's own header comment already demands of itself. Lightening light-mode and darkening dark-mode should only improve dark-text-on-light / light-text-on-dark contrast, but verify computationally, don't assume — if anything genuinely drops under 4.5:1, adjust *that one token* minimally and document why, exactly as every prior token change in this file's own history has done. Do not touch `--royal-*`/`--accent-brass*`/`--state-*`/`--derivation-*`/`--edge-conflict` values themselves unless a real, computed failure forces a specific one — this should not be needed.

**Font loading:** add Google Font `Instrument Serif` (400, 400 italic) alongside the existing Fraunces/Inter loads in `frontend/app/layout.tsx`, bound to `--font-accent-family` the same way Fraunces/Inter are already bound to their own CSS variables — follow the exact existing pattern in that file, don't invent a new loading mechanism.

## The graph-paper texture and margin rule — where they actually appear

Not as a blanket page background applied everywhere indiscriminately — that would fight the existing information-dense subsystem UIs (graph, ledger, fair-allocator, etc.), which need a calm, low-texture surface to let dense real data stand out. Apply the full grid-paper texture + margin rule as a genuine visual identity in exactly these places:
- The new landing page (below) — this is where the identity gets to breathe.
- `AppShell`'s own chrome (sidebar background, top bar) — a subtle version, so the "ledger" feeling is present everywhere the product is used, not just on the marketing page.
- Card/panel headers across existing subsystem pages may pick up a thin margin-rule accent (e.g. a left border on a section heading) as a light-touch signature detail — E4's own judgment on where this reads as elegant rather than busy; the dense data area of each page (the graph canvas, the ledger table, the cost matrix) stays clean and untextured.

## The new landing page — real storyline, not a feature list

Replace `frontend/app/(shell)/page.tsx` entirely (the current one is an unfinished Phase 0 placeholder — confirmed by reading it directly). Section-by-section content, written for this brief, ready to use as real copy (adapt tone/line-breaks as needed, keep the substance and the ordering — this is deliberately the accurate, honest register the rest of this project has used everywhere else, not marketing hyperbole):

### 1. Hero
- Eyebrow: `GharOS`
- Headline (large, `--font-display`, Fraunces): **"The household remembers, even when you don't."**
- Sub-headline (`--font-accent`, Instrument Serif italic, one line): *"Not a to-do list. A memory."*
- Body line: "An autonomous operating system for the one institution nobody runs like one — built on a knowledge graph that shows its work, not a dashboard that hides it."
- Two CTAs: primary **"Enter the graph"** → `/graph`; secondary **"Read how it works"** → scrolls to section 2.

### 2. The pain (three short vignettes, real, not generic)
Lead line: *"Somewhere between a WhatsApp message about school fees, a crumpled receipt for a water purifier, and a doctor's appointment nobody wrote down, the truth of a household gets lost."*
Three columns:
- **Fragmented information** — "The budget reality, the care requirements, the school-run logistics, and the resale outlook live in different heads and different documents."
- **Unequal voice** — "Whoever argues hardest or earns most usually wins; quieter members' constraints get discovered after the fact."
- **No memory** — "Two years later, nobody remembers why the choice was made, what was traded away, or who conceded."

### 3. The insight
Headline: **"The answer is a path, not a vibe."**
Body: "Every fact GharOS holds carries how it knows it — extracted from a real document, inferred from context, or flagged ambiguous when the evidence genuinely points more than one way. A recommendation is never a paragraph asserting itself; it's a subgraph you can walk, node by node, back to the message or receipt it came from."
A small, real visual: reuse the existing `DerivationBadge` component (extracted/inferred/ambiguous) already built and shipped — do not invent new UI for this, the real thing already exists and is more credible than a mockup.

### 4. The journey — nine chapters
Present as a vertical, scroll-revealed sequence (this is the primary home for the new `--reveal-*` motion tokens — each chapter fades/slides in as it enters view, staggered). One line of real, honest description each, not feature-speak:
1. **Perception** — "Reads what actually arrives: WhatsApp exports, receipts, SMS, forms — never a hypothetical clean inbox."
2. **Consequence Engine** — "Infers what a message actually implies, cites its evidence, and says so plainly when it isn't sure."
3. **Arbitration** — "Never moves money or sends a message alone on anything that matters. A human approves first."
4. **Household Ledger** — "Finds the leakage hiding in plain sight — a mandate nobody cancelled, a price that quietly crept up."
5. **Fair Allocator** — "Divides chores with a provable fairness guarantee, not by whoever complains loudest."
6. **Intention → Action** — "Notices when a real plan is quietly stalling, diagnoses why, and does something about it."
7. **Outbound Concierge** — "Calls the dentist so you don't have to — and discloses, every time, that it's a system calling."
8. **Household Simulator** — "Projects a big decision against your own household's real history, never a stranger's."
9. **Household Council** — "Surfaces the real trade-off between real interests. Humans always decide."

### 5. The proof
Headline: **"Built on real infrastructure, held to real safety rules."**
Two rows:
- A real Google Cloud stack strip: Gemini via Vertex AI · Cloud Run · Firestore · Cloud Pub/Sub · Cloud Scheduler (no logos that aren't genuinely accurate to what's built — text/wordmark treatment only).
- A short, real list of the eight safety invariants (pull the exact wording from `PHASES.md` Appendix B — do not paraphrase loosely; this list is load-bearing and already precise).

### 6. Closing CTA
Headline: **"This isn't a dashboard. It's an institution's memory."**
Single CTA: **"Enter GharOS"** → `/graph`.

## What E4 should NOT do

- Do not touch `--royal-*`, `--accent-brass*`, `--state-*`, `--derivation-*`, or `--edge-conflict` values.
- Do not rewrite the internals of `/ledger`, `/fair-allocator`, `/intention-action`, `/concierge`, `/simulator`, `/council`, `/approvals`, `/status`, `/graph`, or `/tokens` — they inherit the refreshed look through the shell and the token changes; only light-touch accent details (e.g. a margin-rule on a section heading) if it clearly reads as elegant, never a content or layout rewrite.
- Do not invent statistics, safety claims, or stack components not actually true of this build — the proof section must stay exactly as accurate as everywhere else in this codebase.
