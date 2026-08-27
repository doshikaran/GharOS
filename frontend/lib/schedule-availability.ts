/**
 * TypeScript port of `backend/app/agents/intention_action/schedule_parsing.py`
 * (ADR-015, Phase 9) — the real, deterministic overlap check A25 (Window
 * Scheduling) runs against a person's `SCHEDULE`-kind `Constraint`s. No
 * model call anywhere in this module, on either side of the wire: parsing a
 * structured object of three known keys and checking two time ranges for
 * overlap is arithmetic, not reasoning — this file is a faithful port, not
 * a reimplementation, so the frontend's `AvailabilityVerdict` for a given
 * (constraints, window) pair is provably the same verdict the real backend
 * function would reach.
 *
 * ADR-015's formal `SCHEDULE` `structured` schema:
 *   - `days_of_week`: comma-separated lowercase 3-letter days
 *     (`"mon,tue,wed,thu,fri"`), or the literal `"daily"` for all seven.
 *   - `start_time` / `end_time`: `"HH:MM"`, 24-hour, local time.
 *
 * A malformed or legacy `SCHEDULE` constraint (predates ADR-015, or has a
 * typo) never crashes this module and is never silently treated as
 * available or blocked — see `personAvailabilityForWindow`'s own contract,
 * mirroring `schedule_parsing.person_availability_for_window`'s exactly.
 */

export type ConstraintSeverity = "hard" | "soft";
export type ConstraintKind =
  | "dietary"
  | "schedule"
  | "medical"
  | "financial"
  | "safety"
  | "other";

/** The minimal real `Constraint` shape this module needs — a structural
 * subset of `contracts.graph_types.Constraint`, so this function can accept
 * either a live `/graph/snapshot` `CONSTRAINT` node's `fields` bag or a
 * fixture object built directly in this shape, with no adapter needed. */
export interface ScheduleConstraintInput {
  readonly id: string;
  readonly kind: ConstraintKind;
  readonly severity: ConstraintSeverity;
  readonly structured: Readonly<Record<string, string>>;
}

export type AvailabilityVerdict = "available" | "hard_blocked" | "soft_avoid" | "cannot_determine";

export interface ParsedScheduleWindow {
  readonly constraintId: string;
  readonly severity: ConstraintSeverity;
  /** Lowercase 3-letter day abbreviations this window applies to — always a
   * non-empty subset of `VALID_DAY_ABBREVIATIONS`. */
  readonly daysOfWeek: ReadonlySet<string>;
  /** Minutes since midnight, `[0, 1440)`. */
  readonly startMinutes: number;
  readonly endMinutes: number;
}

const VALID_DAY_ABBREVIATIONS: ReadonlySet<string> = new Set([
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
]);

/** `Date.getUTCDay()` returns `0` for Sunday .. `6` for Saturday —
 * index-aligned to that, not to `VALID_DAY_ABBREVIATIONS`'s insertion order. */
const JS_WEEKDAY_TO_ABBREVIATION: readonly string[] = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

function parseTimeToMinutes(raw: string): number | null {
  const parts = raw.trim().split(":");
  if (parts.length !== 2) return null;
  const [hourStr, minuteStr] = parts;
  if (!/^\d+$/.test(hourStr) || !/^\d+$/.test(minuteStr)) return null;
  const hour = Number(hourStr);
  const minute = Number(minuteStr);
  if (!(hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59)) return null;
  return hour * 60 + minute;
}

function parseDaysOfWeek(raw: string): ReadonlySet<string> | null {
  const normalized = raw.trim().toLowerCase();
  if (normalized === "daily") return VALID_DAY_ABBREVIATIONS;
  if (!normalized) return null;
  const days = new Set(normalized.split(",").map((day) => day.trim()));
  if (days.size === 0) return null;
  for (const day of days) {
    if (!VALID_DAY_ABBREVIATIONS.has(day)) return null;
  }
  return days;
}

/**
 * Parses one constraint against ADR-015's formal `SCHEDULE` schema.
 * Returns `null` when `constraint.kind !== "schedule"`, or `structured` is
 * missing any of the three formal keys, or any value fails to parse (a
 * legacy informal entry, e.g. the pre-migration `{quiet_hours: "14:00-16:00"}`
 * shape, included) — mirrors `parse_schedule_constraint`'s own contract:
 * never throws, a malformed real-world entry is the expected case this
 * function exists to degrade gracefully on.
 */
export function parseScheduleConstraint(constraint: ScheduleConstraintInput): ParsedScheduleWindow | null {
  if (constraint.kind !== "schedule") return null;

  const daysRaw = constraint.structured.days_of_week;
  const startRaw = constraint.structured.start_time;
  const endRaw = constraint.structured.end_time;
  if (daysRaw === undefined || startRaw === undefined || endRaw === undefined) return null;

  const days = parseDaysOfWeek(daysRaw);
  const start = parseTimeToMinutes(startRaw);
  const end = parseTimeToMinutes(endRaw);
  if (days === null || start === null || end === null) return null;
  if (start >= end) {
    // An overnight/zero-length window has no "crosses midnight" convention
    // under ADR-015's schema as written — treated as unparseable rather
    // than guessed at, exactly mirroring the Python port.
    return null;
  }

  return { constraintId: constraint.id, severity: constraint.severity, daysOfWeek: days, startMinutes: start, endMinutes: end };
}

function calendarDayUtc(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/**
 * All day-of-week/time-of-day arithmetic here is done in UTC
 * (`getUTCDay`/`getUTCHours`/`getUTCMinutes`), deliberately, so a given ISO
 * timestamp resolves to the same verdict regardless of which timezone this
 * code happens to run in (browser or CI) — every ISO datetime this package
 * builds treats its literal wall-clock digits as the schedule-relevant
 * local time, recorded with a `Z` suffix for a stable, environment-
 * independent parse, exactly mirroring how the real household's schedule
 * facts (`ADR-015`'s "HH:MM, 24-hour, local time") are meant to read.
 */
function windowsOverlap(window: ParsedScheduleWindow, candidateStart: Date, candidateEnd: Date): boolean {
  if (calendarDayUtc(candidateStart) !== calendarDayUtc(candidateEnd)) {
    // A candidate window spanning midnight is out of scope for this simple
    // overlap check — conservatively treated as *not* overlapping, mirroring
    // the Python port's own documented limitation.
    return false;
  }
  const dayAbbreviation = JS_WEEKDAY_TO_ABBREVIATION[candidateStart.getUTCDay()];
  if (!window.daysOfWeek.has(dayAbbreviation)) return false;
  const candidateStartMinutes = candidateStart.getUTCHours() * 60 + candidateStart.getUTCMinutes();
  const candidateEndMinutes = candidateEnd.getUTCHours() * 60 + candidateEnd.getUTCMinutes();
  return candidateStartMinutes < window.endMinutes && candidateEndMinutes > window.startMinutes;
}

/**
 * The real, deterministic ADR-015 availability check for one person against
 * one candidate window — a faithful port of
 * `schedule_parsing.person_availability_for_window`.
 *
 * @param scheduleConstraints Every constraint linked to this person
 *   (unfiltered by kind is fine — non-`schedule` constraints are ignored).
 * @param candidateStart Window start.
 * @param candidateEnd Window end.
 * @returns `"hard_blocked"` if any parseable `hard` schedule constraint
 *   overlaps the window; else `"soft_avoid"` if any parseable `soft` one
 *   overlaps; else `"available"` if either at least one `schedule`-kind
 *   constraint parsed cleanly and none overlapped, or this person has no
 *   `schedule`-kind constraint on file at all (no evidence of a block is
 *   treated as available, not as unknown); else `"cannot_determine"` only
 *   when this person has at least one real `schedule`-kind constraint but
 *   every one of them was unparseable.
 */
export function personAvailabilityForWindow(
  scheduleConstraints: readonly ScheduleConstraintInput[],
  candidateStart: Date,
  candidateEnd: Date,
): AvailabilityVerdict {
  const parsedWindows = scheduleConstraints
    .map((constraint) => parseScheduleConstraint(constraint))
    .filter((window): window is ParsedScheduleWindow => window !== null);
  const scheduleKindCount = scheduleConstraints.filter((c) => c.kind === "schedule").length;

  if (parsedWindows.length === 0) {
    return scheduleKindCount > 0 ? "cannot_determine" : "available";
  }

  let hardBlocked = false;
  let softAvoid = false;
  for (const window of parsedWindows) {
    if (!windowsOverlap(window, candidateStart, candidateEnd)) continue;
    if (window.severity === "hard") {
      hardBlocked = true;
    } else {
      softAvoid = true;
    }
  }

  if (hardBlocked) return "hard_blocked";
  if (softAvoid) return "soft_avoid";
  return "available";
}
