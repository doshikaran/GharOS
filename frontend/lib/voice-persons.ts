/**
 * Household members eligible for a voice/language profile — reused ids
 * from the same continuous demo household every other phase's fixtures
 * are grounded in (`lib/fair-allocator.ts`'s `PRIYA_ID`/`MAYA_ID`/
 * `DADI_ID`/`AARAV_ID`, `backend/seeds/demo_household.py`), never a
 * second, invented household.
 *
 * `relationshipToHousehold` exists so the language-profile settings screen
 * can explain, in one line, *why* each person's `literacy_mode` matters —
 * spec §14.11's own accessibility framing names Maya (household staff who
 * may not read English) and Dadi (an elder with limited literacy) as the
 * concrete cases this field exists for, not an abstract enum value.
 */

import { AARAV_ID, DADI_ID, MAYA_ID, PRIYA_ID } from "./fair-allocator";

export interface VoicePersonSummary {
  readonly personId: string;
  readonly displayName: string;
  readonly relationshipToHousehold: string;
}

export const VOICE_HOUSEHOLD_PERSONS: readonly VoicePersonSummary[] = [
  { personId: PRIYA_ID, displayName: "Priya", relationshipToHousehold: "Parent" },
  { personId: MAYA_ID, displayName: "Maya", relationshipToHousehold: "Household staff" },
  { personId: DADI_ID, displayName: "Dadi", relationshipToHousehold: "Elder" },
  { personId: AARAV_ID, displayName: "Aarav", relationshipToHousehold: "Child" },
] as const;

export function voicePersonLabel(personId: string): string {
  return VOICE_HOUSEHOLD_PERSONS.find((person) => person.personId === personId)?.displayName ?? personId;
}
