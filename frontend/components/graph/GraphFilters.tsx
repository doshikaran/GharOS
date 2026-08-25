"use client";

import { DERIVATIONS, NODE_TYPES, type Derivation, type NodeType } from "@/lib/graph-types";
import { EMPTY_GRAPH_FILTER_STATE, hasActiveFilters, type GraphFilterState } from "@/lib/graph-filters";
import { Button } from "@/components/design-system/Button";
import styles from "./GraphFilters.module.css";

export interface GraphPersonOption {
  readonly id: string;
  readonly label: string;
}

export interface GraphFiltersProps {
  readonly value: GraphFilterState;
  readonly onChange: (next: GraphFilterState) => void;
  /** Every current PERSON node, for the person-filter dropdown. */
  readonly people: readonly GraphPersonOption[];
}

const NODE_TYPE_LABELS: Record<NodeType, string> = {
  PERSON: "Person",
  CONSTRAINT: "Constraint",
  OBLIGATION: "Obligation",
  LEDGER_EVENT: "Ledger event",
  RECURRING_COMMITMENT: "Recurring commitment",
  VENDOR: "Vendor",
  PROVIDER: "Provider",
  DECISION: "Decision",
  BRANCH: "Branch",
  COUNCIL_POSITION: "Council position",
  OUTCOME: "Outcome",
  SOURCE_DOCUMENT: "Source document",
  ACTION_RECORD: "Action record",
  APPROVAL_REQUEST: "Approval request",
  PURCHASE_ITEM: "Purchase item",
  PATTERN: "Pattern",
};

const DERIVATION_LABELS: Record<Derivation, string> = {
  extracted: "Extracted",
  inferred: "Inferred",
  ambiguous: "Ambiguous",
};

function toggleMember<T>(current: readonly T[] | null, all: readonly T[], member: T): readonly T[] | null {
  const set = new Set(current ?? all);
  if (set.has(member)) set.delete(member);
  else set.add(member);
  // Every option selected reads identically to "no filter engaged" — collapse
  // back to null so the summary/UI don't claim a filter is active for nothing.
  if (set.size === all.length) return null;
  return all.filter((item) => set.has(item));
}

/**
 * The four client-side filter dimensions (Phase 6 CTO scope boundary):
 * type, person, time window, derivation — applied live against whatever is
 * currently rendered, snapshot plus anything streamed in since.
 */
export function GraphFilters({ value, onChange, people }: GraphFiltersProps) {
  function toggleType(type: NodeType) {
    onChange({ ...value, types: toggleMember(value.types, NODE_TYPES, type) });
  }

  function toggleDerivation(derivation: Derivation) {
    onChange({ ...value, derivations: toggleMember(value.derivations, DERIVATIONS, derivation) });
  }

  function handlePersonChange(personId: string) {
    onChange({ ...value, personId: personId.length > 0 ? personId : null });
  }

  function handleFromChange(from: string) {
    const to = value.timeWindow?.to ?? null;
    onChange({ ...value, timeWindow: from.length === 0 && to === null ? null : { from: from.length > 0 ? from : null, to } });
  }

  function handleToChange(to: string) {
    const from = value.timeWindow?.from ?? null;
    onChange({ ...value, timeWindow: to.length === 0 && from === null ? null : { from, to: to.length > 0 ? to : null } });
  }

  return (
    <div className={styles.filters} aria-label="Graph filters">
      <div className={styles.headerRow}>
        <h3 className={styles.title}>Filters</h3>
        {hasActiveFilters(value) && (
          <Button variant="ghost" onClick={() => onChange(EMPTY_GRAPH_FILTER_STATE)}>
            Clear all
          </Button>
        )}
      </div>

      <fieldset className={styles.group}>
        <legend className={styles.groupLabel}>Type</legend>
        <div className={styles.chipRow}>
          {NODE_TYPES.map((type) => {
            const active = value.types === null || value.types.includes(type);
            return (
              <button
                key={type}
                type="button"
                aria-pressed={active}
                className={[styles.chip, active && styles.chipActive].filter(Boolean).join(" ")}
                onClick={() => toggleType(type)}
              >
                {NODE_TYPE_LABELS[type]}
              </button>
            );
          })}
        </div>
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.groupLabel}>Derivation</legend>
        <div className={styles.chipRow}>
          {DERIVATIONS.map((derivation) => {
            const active = value.derivations === null || value.derivations.includes(derivation);
            return (
              <button
                key={derivation}
                type="button"
                aria-pressed={active}
                className={[styles.chip, active && styles.chipActive].filter(Boolean).join(" ")}
                onClick={() => toggleDerivation(derivation)}
              >
                {DERIVATION_LABELS[derivation]}
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className={styles.group}>
        <label htmlFor="graph-filter-person" className={styles.groupLabel}>
          Person
        </label>
        <select
          id="graph-filter-person"
          className={styles.select}
          value={value.personId ?? ""}
          onChange={(event) => handlePersonChange(event.target.value)}
        >
          <option value="">Everyone</option>
          {people.map((person) => (
            <option key={person.id} value={person.id}>
              {person.label}
            </option>
          ))}
        </select>
      </div>

      <div className={styles.group}>
        <span className={styles.groupLabel} id="graph-filter-time-label">
          Created between
        </span>
        <div className={styles.timeRow} role="group" aria-labelledby="graph-filter-time-label">
          <label className={styles.timeField}>
            <span>From</span>
            <input
              type="datetime-local"
              value={value.timeWindow?.from?.slice(0, 16) ?? ""}
              onChange={(event) => handleFromChange(event.target.value ? new Date(event.target.value).toISOString() : "")}
            />
          </label>
          <label className={styles.timeField}>
            <span>To</span>
            <input
              type="datetime-local"
              value={value.timeWindow?.to?.slice(0, 16) ?? ""}
              onChange={(event) => handleToChange(event.target.value ? new Date(event.target.value).toISOString() : "")}
            />
          </label>
        </div>
      </div>
    </div>
  );
}
