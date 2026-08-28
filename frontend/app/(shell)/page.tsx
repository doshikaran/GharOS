import Link from "next/link";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Button } from "@/components/design-system/Button";
import { Card } from "@/components/design-system/Card";
import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import styles from "./home-page.module.css";

export default function Home() {
  return (
    <main className={styles.page}>
      <span className={styles.eyebrow}>GharOS</span>
      <h1 className={styles.title}>A household ledger and archive that happens to think.</h1>
      <p className={styles.subtitle}>
        The design system is live — deep lapis and antique brass on warm parchment, inverted to
        ink and candlelight in dark mode. Every colour below comes from a CSS custom property,
        never a raw hex value.
      </p>

      <div className={styles.actions}>
        <Link href="/tokens">
          <Button variant="primary">View design tokens</Button>
        </Link>
        <ThemeSwitcher />
      </div>

      <Card title="Provenance, at a glance" interactive>
        Every node and edge in the household graph carries a derivation tag. This is how it reads
        everywhere it appears — in the graph, in the ledger, in an approval request.
        <div className={styles.badgeRow}>
          <DerivationBadge derivation="extracted" />
          <DerivationBadge derivation="inferred" />
          <DerivationBadge derivation="ambiguous" />
        </div>
      </Card>
    </main>
  );
}
