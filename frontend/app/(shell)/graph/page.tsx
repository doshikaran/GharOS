import type { Metadata } from "next";
import { GraphExplorer } from "@/components/graph/GraphExplorer";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./graph-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Household knowledge graph",
};

export default async function GraphPage({ searchParams }: PageProps<"/graph">) {
  const params = await searchParams;
  const nodeParam = params.node;
  const initialSelectedNodeId = typeof nodeParam === "string" ? nodeParam : null;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Household knowledge graph</h1>
        <p className={styles.subheading}>
          Every node and edge GharOS holds about this household, assembling itself live as documents arrive,
          click a node to see where it came from, or trace a conclusion back to its source (PHASES.md Phase 6,
          Gate 6).
        </p>
      </div>
      <GraphExplorer
        key={initialSelectedNodeId ?? "no-deep-link"}
        baseUrl={getApiBaseUrl()}
        initialSelectedNodeId={initialSelectedNodeId}
      />
    </div>
  );
}
