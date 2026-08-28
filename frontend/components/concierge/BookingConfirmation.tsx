import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import { formatDateTime } from "@/lib/approvals";
import type { BookingOutcome } from "@/lib/concierge";
import styles from "./BookingConfirmation.module.css";

export interface BookingConfirmationProps {
  readonly outcome: BookingOutcome;
  readonly providerName: string;
  readonly title: string;
}

/**
 * Renders a `BookingOutcome` gated on real verification (this phase's
 * brief item 4) — the *only* way this component ever shows a "booked"
 * confirmation is `outcome.kind === "confirmed"`, which
 * `lib/concierge.ts`'s `buildBookingOutcome` only ever produces from a
 * genuinely positive `VerificationResult` with a real confirmed slot
 * (mirroring `app.tools.booking_write_tool`'s real structural guarantee).
 * There is no prop or branch here that can render a confirmed booking
 * from an unverified outcome — the `not_recorded` branch is explicit,
 * visible, and states plainly that nothing was written, matching Gate
 * 10's "unverified outcome never recorded," made visible.
 */
export function BookingConfirmation({ outcome, providerName, title }: BookingConfirmationProps) {
  if (outcome.kind === "not_recorded") {
    return (
      <Card
        className={styles.card}
        title={
          <span className={styles.titleRow}>
            <span>{title}</span>
            <Badge variant="danger">Could not verify — not recorded</Badge>
          </span>
        }
      >
        <p className={styles.notRecordedNote} role="status">
          Nothing was written to the household&apos;s graph for this call. A booking is only ever recorded once
          it is independently verified — this one was not.
        </p>
        {outcome.verification.discrepancies.length > 0 && (
          <>
            <h4 className={styles.sectionLabel}>Why verification failed</h4>
            <ul className={styles.discrepancyList}>
              {outcome.verification.discrepancies.map((discrepancy) => (
                <li key={discrepancy}>{discrepancy}</li>
              ))}
            </ul>
          </>
        )}
        <p className={styles.explanation}>{outcome.verification.explanation}</p>
      </Card>
    );
  }

  const { booking } = outcome;
  return (
    <Card
      className={styles.card}
      title={
        <span className={styles.titleRow}>
          <span>{title}</span>
          <Badge variant="success">Booked &amp; verified</Badge>
        </span>
      }
    >
      <dl className={styles.detailGrid}>
        <div className={styles.detailRow}>
          <dt>Provider</dt>
          <dd>{providerName}</dd>
        </div>
        <div className={styles.detailRow}>
          <dt>Confirmed slot</dt>
          <dd>{formatDateTime(booking.confirmedSlot)}</dd>
        </div>
        {booking.confirmedPrice !== null && (
          <div className={styles.detailRow}>
            <dt>Price</dt>
            <dd>₹{booking.confirmedPrice.toFixed(0)}</dd>
          </div>
        )}
        <div className={styles.detailRow}>
          <dt>Verified by</dt>
          <dd>{booking.verifiedByAgent}</dd>
        </div>
      </dl>

      <p className={styles.provenanceNote}>
        <DerivationBadge derivation="extracted" confidence={outcome.verification.confidence} /> from the call
        transcript, written only after verification passed.
      </p>

      {booking.attributionTags.length === 0 ? (
        <p className={styles.noReliabilitySignal}>
          No reliability signal recorded yet — the appointment hasn&apos;t happened. This provider&apos;s history
          updates for real once it does.
        </p>
      ) : (
        <div className={styles.attributionRow}>
          {booking.attributionTags.map((tag) => (
            <Badge key={tag} variant="info">
              {tag.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      )}
    </Card>
  );
}
