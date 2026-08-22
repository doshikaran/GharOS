import type { Metadata } from "next";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import styles from "./tokens-page.module.css";

export const metadata: Metadata = {
  title: "GharOS — Design tokens",
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
];

export default function TokensPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.heading}>GharOS design tokens</h1>
          <p className={styles.subheading}>
            Every token in <code>styles/tokens.css</code>, organised by category, both themes.
            This is the review surface for the whole design system (PHASES.md Gate 0) — toggle
            theme below and confirm every swatch still reads correctly.
          </p>
        </div>
        <ThemeSwitcher />
      </div>

      <ColorSection
        title="Surfaces"
        note="Base / raised / overlay — the paper stacked on paper of the ledger."
        tokens={SURFACE_TOKENS}
      />

      <ColorSection
        title="Ink"
        note="Text colour on parchment (light) / ink (dark). Contrast ratios verified against --surface-base."
        tokens={INK_TOKENS}
      />

      <ColorSection
        title="Royal"
        note="Deep lapis. -deep and -soft are fill/tint tokens; use --on-royal for text placed on top of a royal fill."
        tokens={ROYAL_TOKENS}
      />

      <ColorSection
        title="Accent — brass"
        note="Antique brass in light mode, candlelight brass in dark mode. -muted is a fill/tint token only."
        tokens={ACCENT_TOKENS}
      />

      <ColorSection
        title="State"
        note="Success / warning / danger / info — all verified >=4.5:1 on --surface-base."
        tokens={STATE_TOKENS}
      />

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Derivation — load-bearing, not decorative</h2>
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
        note="Reserved exclusively for conflict edges in the graph — never reused as a generic error colour."
        tokens={EDGE_TOKENS}
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
        <p className={styles.sectionNote}>Warm-tinted shadows — never pure black.</p>
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
          carries real meaning (--motion-graph-grow) — everything else stays quick and quiet.
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
