import type { Metadata } from "next";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import styles from "./tokens-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Design tokens",
};

interface TokenEntry {
  name: string;
  note?: string;
}

function ColorSection({
  title,
  note,
  tokens,
}: {
  title: string;
  note?: string;
  tokens: TokenEntry[];
}) {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {note && <p className={styles.sectionNote}>{note}</p>}
      <div className={styles.grid}>
        {tokens.map((token) => (
          <div key={token.name} className={styles.swatch}>
            <div
              className={styles.swatchFill}
              style={{ backgroundColor: `var(--${token.name})` }}
            />
            <div className={styles.swatchLabel}>
              <span className={styles.swatchName}>--{token.name}</span>
              {token.note && <span className={styles.swatchMeta}>{token.note}</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

const SURFACE_TOKENS: TokenEntry[] = [
  { name: "surface-base" },
  { name: "surface-raised" },
  { name: "surface-overlay" },
];

const INK_TOKENS: TokenEntry[] = [
  { name: "ink-primary", note: ">=4.5:1 on surface-base" },
  { name: "ink-secondary", note: ">=4.5:1 on surface-base" },
  { name: "ink-muted", note: ">=4.5:1 on surface-base" },
];

const ROYAL_TOKENS: TokenEntry[] = [
  { name: "royal-primary", note: "text-safe on surface-base" },
  { name: "royal-deep", note: "fill only" },
  { name: "royal-soft", note: "fill/tint only" },
  { name: "on-royal", note: "text on royal fills" },
];

const ACCENT_TOKENS: TokenEntry[] = [
  { name: "accent-brass", note: "text-safe on surface-base" },
  { name: "accent-brass-muted", note: "fill/tint only" },
  { name: "on-brass", note: "text on brass fills" },
];

const CYAN_TOKENS: TokenEntry[] = [
  { name: "accent-cyan", note: "text-safe on surface-base" },
  { name: "accent-cyan-muted", note: "fill/tint only" },
  { name: "on-cyan", note: "text on cyan fills" },
];

const BORDER_TOKENS: TokenEntry[] = [
  { name: "border", note: "default hairline" },
  { name: "border-strong", note: "inputs, selected rows" },
  { name: "focus-ring" },
  { name: "glow", note: "halo behind a selected graph node" },
];

const GRAPH_PALETTE_TOKENS: TokenEntry[] = [
  { name: "graph-1", note: "indigo, people" },
  { name: "graph-2", note: "cyan, vendors" },
  { name: "graph-3", note: "violet, decisions" },
  { name: "graph-4", note: "emerald" },
  { name: "graph-5", note: "amber, money" },
  { name: "graph-6", note: "rose" },
  { name: "graph-7", note: "blue, attendance" },
  { name: "graph-8", note: "fuchsia, patterns" },
];

const STATE_TOKENS: TokenEntry[] = [
  { name: "state-success" },
  { name: "state-warning" },
  { name: "state-danger" },
  { name: "state-info" },
];

const DERIVATION_TOKENS: TokenEntry[] = [
  { name: "derivation-extracted", note: "solid border on graph edges" },
  { name: "derivation-inferred", note: "dashed border on graph edges" },
  { name: "derivation-ambiguous", note: "dotted border on graph edges" },
];

const EDGE_TOKENS: TokenEntry[] = [{ name: "edge-conflict", note: "the red that matters" }];

const SCRIM_TOKENS: TokenEntry[] = [
  { name: "scrim-overlay", note: "wash behind a dialog / mobile drawer" },
];

const HIGHLIGHT_TOKENS: TokenEntry[] = [
  { name: "highlight-surface", note: "carries --ink-primary text: >=7:1 both themes" },
];

const SPACING_TOKENS = [
  "space-0",
  "space-1",
  "space-2",
  "space-3",
  "space-4",
  "space-5",
  "space-6",
  "space-7",
  "space-8",
  "space-9",
];

const RADIUS_TOKENS = ["radius-sm", "radius-md", "radius-lg", "radius-xl", "radius-full"];
const ELEVATION_TOKENS = ["elevation-0", "elevation-1", "elevation-2", "elevation-3"];
const MOTION_DURATION_TOKENS = [
  "motion-instant",
  "motion-fast",
  "motion-base",
  "motion-slow",
  "motion-graph-grow",
  "motion-graph-stagger",
];

export default function TokensPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.heading}>GharOS design tokens</h1>
          <p className={styles.subheading}>
            Every token in <code>styles/tokens.css</code>, organised by category, both themes.
            This is the review surface for the whole design system, toggle theme below and
            confirm every swatch still reads correctly.
          </p>
        </div>
        <ThemeSwitcher />
      </div>

      <ColorSection
        title="Surfaces"
        note="Base is the tinted page; raised and overlay are pure white, separated by border and shadow."
        tokens={SURFACE_TOKENS}
      />

      <ColorSection
        title="Ink"
        note="Near-black indigo (light) / near-white (dark). Contrast ratios target AA against each theme's worst-case surface."
        tokens={INK_TOKENS}
      />

      <ColorSection
        title="Royal — the house colour (electric indigo)"
        note="Token name is a role, not a hue. -deep and -soft are fill/tint tokens; use --on-royal for text placed on top of a royal fill."
        tokens={ROYAL_TOKENS}
      />

      <ColorSection
        title="Accent, brass — the warm accent (coral)"
        note="Token name is a role, not a hue. --accent-brass is a deepened coral that clears AA for text; --accent-brass-muted is the pale coral fill/tint only."
        tokens={ACCENT_TOKENS}
      />

      <ColorSection
        title="Accent 2 — cyan"
        note="A deepened teal-cyan, text-safe on --surface-base; -muted is a fill/tint only."
        tokens={CYAN_TOKENS}
      />

      <ColorSection
        title="Borders, focus, glow"
        note="--border is the default hairline, --border-strong for inputs and selected rows. --glow is the indigo halo behind a selected graph node."
        tokens={BORDER_TOKENS}
      />

      <ColorSection
        title="Graph node palette"
        note="A vivid categorical ramp for at-a-glance node grouping on the canvas. Node shape still carries the precise type; this is the category tint."
        tokens={GRAPH_PALETTE_TOKENS}
      />

      <ColorSection
        title="State"
        note="Success / warning / danger / info, all verified >=4.5:1 on --surface-base."
        tokens={STATE_TOKENS}
      />

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Derivation, load-bearing, not decorative</h2>
        <p className={styles.sectionNote}>
          Marks extracted / inferred / ambiguous graph data everywhere it appears. Colour is
          reinforced by a border-style convention (solid / dashed / dotted) that will match the
          graph edge styling exactly, so the encoding still reads for colour-blind viewers.
        </p>
        <div className={styles.flexWrapRow}>
          <DerivationBadge derivation="extracted" confidence={0.97} />
          <DerivationBadge derivation="inferred" confidence={0.78} />
          <DerivationBadge derivation="ambiguous" confidence={0.41} />
        </div>
        <ColorSection title="Raw derivation colours" tokens={DERIVATION_TOKENS} />
      </section>

      <ColorSection
        title="Edge conflict"
        note="Reserved exclusively for conflict edges in the graph, never reused as a generic error colour."
        tokens={EDGE_TOKENS}
      />

      <ColorSection
        title="Scrim"
        note="The one sanctioned non-palette colour literal: a translucent occlusion wash behind a modal dialog or the mobile nav drawer. Heavier on Vault, where the ground is already near-black."
        tokens={SCRIM_TOKENS}
      />

      <ColorSection
        title="Highlight surface"
        note="A pale indigo marked / edited region that DOES carry --ink-primary text on top (source-span highlight, re-allocated cost-matrix cell, commitment tag). Unlike --accent-brass-muted it is held to the text-contrast bar with --ink-primary in both themes."
        tokens={HIGHLIGHT_TOKENS}
      />

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Spacing</h2>
        <p className={styles.sectionNote}>4px base unit.</p>
        {SPACING_TOKENS.map((name) => (
          <div className={styles.spacingRow} key={name}>
            <span className={styles.rowLabel}>--{name}</span>
            <div className={styles.spacingBar} style={{ width: `var(--${name})` }} />
          </div>
        ))}
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Radius</h2>
        <div className={styles.flexWrapRow}>
          {RADIUS_TOKENS.map((name) => (
            <div className={styles.radiusRow} key={name}>
              <div
                className={styles.radiusBox}
                style={{ borderRadius: `var(--${name})` }}
              />
              <span className={styles.rowLabel}>--{name}</span>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Elevation</h2>
        <p className={styles.sectionNote}>Soft, indigo-cast shadows in light mode; pure-black cast in dark.</p>
        <div className={styles.flexWrapRow}>
          {ELEVATION_TOKENS.map((name) => (
            <div className={styles.elevationRow} key={name}>
              <div className={styles.elevationBox} style={{ boxShadow: `var(--${name})` }} />
              <span className={styles.rowLabel}>--{name}</span>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Motion</h2>
        <p className={styles.sectionNote}>
          Hover a row to preview its duration. The graph growing is the one place animation
          carries real meaning: --motion-graph-grow is a single node/edge growing in,
          --motion-graph-stagger is the gap between consecutive live arrivals so a burst
          reads as a cadence on camera. Everything else stays quick and quiet.
        </p>
        {MOTION_DURATION_TOKENS.map((name) => (
          <div className={styles.motionRow} key={name}>
            <span className={styles.rowLabel}>--{name}</span>
            <div
              className={styles.motionBox}
              style={{
                transitionDuration: `var(--${name})`,
                transitionTimingFunction: "var(--motion-ease-standard)",
              }}
            />
          </div>
        ))}
      </section>
    </div>
  );
}
