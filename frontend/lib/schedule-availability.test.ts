import { describe, expect, it } from "vitest";
import {
  parseScheduleConstraint,
  personAvailabilityForWindow,
  type ScheduleConstraintInput,
} from "./schedule-availability";

/** Real, live seed data (`backend/seeds/demo_household.py`'s
 * `constraint-dadi-nap`, post-ADR-015 migration) — Dadi's SOFT, daily
 * 14:00-16:00 nap window. Used directly so this test proves the TS port
 * against the exact real constraint, not an invented one. */
const DADI_NAP_CONSTRAINT: ScheduleConstraintInput = {
  id: "constraint-dadi-nap",
  kind: "schedule",
  severity: "soft",
  structured: { days_of_week: "daily", start_time: "14:00", end_time: "16:00" },
};

const HARD_WEEKDAY_MORNING_CONSTRAINT: ScheduleConstraintInput = {
  id: "constraint-fixture-hard",
  kind: "schedule",
  severity: "hard",
  structured: { days_of_week: "mon,tue,wed,thu,fri", start_time: "09:00", end_time: "11:00" },
};

const LEGACY_MALFORMED_CONSTRAINT: ScheduleConstraintInput = {
  id: "constraint-fixture-legacy",
  kind: "schedule",
  severity: "soft",
  // Pre-ADR-015 shape — no `days_of_week`/`start_time`/`end_time` keys.
  structured: { quiet_hours: "20:00-22:00" },
};

/** Constructed in UTC deliberately — see `schedule-availability.ts`'s own
 * `windowsOverlap` doc comment for why this keeps the test's verdicts
 * stable regardless of which timezone the test runner happens to be in. */
function utcDate(dateIso: string, time: string): Date {
  return new Date(`${dateIso}T${time}:00Z`);
}

describe("parseScheduleConstraint", () => {
  it("parses the real Dadi nap constraint under ADR-015's formal schema", () => {
    const parsed = parseScheduleConstraint(DADI_NAP_CONSTRAINT);
    expect(parsed).not.toBeNull();
    expect(parsed?.daysOfWeek.size).toBe(7);
    expect(parsed?.startMinutes).toBe(14 * 60);
    expect(parsed?.endMinutes).toBe(16 * 60);
  });

  it("returns null for a non-schedule-kind constraint", () => {
    expect(
      parseScheduleConstraint({
        id: "c",
        kind: "dietary",
        severity: "hard",
        structured: { days_of_week: "daily", start_time: "14:00", end_time: "16:00" },
      }),
    ).toBeNull();
  });

  it("returns null for a legacy pre-ADR-015 entry, never guessing", () => {
    expect(parseScheduleConstraint(LEGACY_MALFORMED_CONSTRAINT)).toBeNull();
  });

  it("returns null when start >= end (no crosses-midnight convention)", () => {
    expect(
      parseScheduleConstraint({
        id: "c",
        kind: "schedule",
        severity: "hard",
        structured: { days_of_week: "daily", start_time: "16:00", end_time: "14:00" },
      }),
    ).toBeNull();
  });

  it("returns null for an unrecognised day abbreviation", () => {
    expect(
      parseScheduleConstraint({
        id: "c",
        kind: "schedule",
        severity: "hard",
        structured: { days_of_week: "funday", start_time: "09:00", end_time: "10:00" },
      }),
    ).toBeNull();
  });
});

describe("personAvailabilityForWindow", () => {
  it("is AVAILABLE with no schedule constraint on file at all, no evidence of a block, not unknown", () => {
    const verdict = personAvailabilityForWindow([], utcDate("2026-08-24", "10:00"), utcDate("2026-08-24", "10:30"));
    expect(verdict).toBe("available");
  });

  it("is SOFT_AVOID against the real Dadi nap window when the candidate overlaps it", () => {
    // 2026-08-24 is a Monday.
    const verdict = personAvailabilityForWindow(
      [DADI_NAP_CONSTRAINT],
      utcDate("2026-08-24", "14:30"),
      utcDate("2026-08-24", "15:00"),
    );
    expect(verdict).toBe("soft_avoid");
  });

  it("is AVAILABLE against the real Dadi nap window when the candidate does not overlap it", () => {
    const verdict = personAvailabilityForWindow(
      [DADI_NAP_CONSTRAINT],
      utcDate("2026-08-24", "10:00"),
      utcDate("2026-08-24", "10:30"),
    );
    expect(verdict).toBe("available");
  });

  it("is HARD_BLOCKED when a hard constraint overlaps, even alongside a non-overlapping soft one", () => {
    const verdict = personAvailabilityForWindow(
      [DADI_NAP_CONSTRAINT, HARD_WEEKDAY_MORNING_CONSTRAINT],
      utcDate("2026-08-24", "09:30"),
      utcDate("2026-08-24", "10:00"),
    );
    expect(verdict).toBe("hard_blocked");
  });

  it("is CANNOT_DETERMINE when every schedule-kind constraint on file is unparseable", () => {
    const verdict = personAvailabilityForWindow(
      [LEGACY_MALFORMED_CONSTRAINT],
      utcDate("2026-08-24", "20:30"),
      utcDate("2026-08-24", "21:00"),
    );
    expect(verdict).toBe("cannot_determine");
  });

  it("prefers HARD_BLOCKED over CANNOT_DETERMINE when at least one constraint parses and blocks", () => {
    const verdict = personAvailabilityForWindow(
      [LEGACY_MALFORMED_CONSTRAINT, HARD_WEEKDAY_MORNING_CONSTRAINT],
      utcDate("2026-08-24", "09:30"),
      utcDate("2026-08-24", "10:00"),
    );
    expect(verdict).toBe("hard_blocked");
  });

  it("treats a candidate window on a day outside the constraint's days_of_week as available", () => {
    // 2026-08-29 is a Saturday — outside the mon-fri hard constraint.
    const verdict = personAvailabilityForWindow(
      [HARD_WEEKDAY_MORNING_CONSTRAINT],
      utcDate("2026-08-29", "09:30"),
      utcDate("2026-08-29", "10:00"),
    );
    expect(verdict).toBe("available");
  });
});
