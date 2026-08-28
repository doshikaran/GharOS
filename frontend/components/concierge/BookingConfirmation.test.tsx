import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  getAaravFollowupBookingOutcome,
  getAaravToothacheBookingOutcome,
  getDadiCleaningBookingOutcome,
} from "@/lib/concierge";
import { BookingConfirmation } from "./BookingConfirmation";

describe("BookingConfirmation", () => {
  it("renders a confirmed booking only for a real, verified outcome", () => {
    const outcome = getAaravToothacheBookingOutcome();
    expect(outcome.kind).toBe("confirmed");
    render(<BookingConfirmation outcome={outcome} providerName="QuickCare Dental Walk-in" title="Aarav's dentist visit" />);
    expect(screen.getByText("Booked & verified")).toBeInTheDocument();
    expect(screen.queryByText(/could not verify/i)).not.toBeInTheDocument();
  });

  it("never renders a 'booked' confirmation for an unverified outcome (no slot at all)", () => {
    const outcome = getDadiCleaningBookingOutcome();
    expect(outcome.kind).toBe("not_recorded");
    render(<BookingConfirmation outcome={outcome} providerName="Bright Smiles Dental" title="Dadi's cleaning" />);
    expect(screen.getByText("Could not verify — not recorded")).toBeInTheDocument();
    expect(screen.queryByText("Booked & verified")).not.toBeInTheDocument();
    expect(screen.getByText(/no slot was claimed booked/i)).toBeInTheDocument();
  });

  it("never renders a 'booked' confirmation for a real slot-mismatch discrepancy", () => {
    const outcome = getAaravFollowupBookingOutcome();
    expect(outcome.kind).toBe("not_recorded");
    render(<BookingConfirmation outcome={outcome} providerName="Sunrise Family Dental" title="Aarav's follow-up" />);
    expect(screen.getByText("Could not verify — not recorded")).toBeInTheDocument();
    expect(screen.getByText(/is not one of the authorised preferred_slots/)).toBeInTheDocument();
  });

  it("renders the confirmed slot, price, and verifying agent for a real booking", () => {
    const outcome = getAaravToothacheBookingOutcome();
    render(<BookingConfirmation outcome={outcome} providerName="QuickCare Dental Walk-in" title="Aarav's dentist visit" />);
    if (outcome.kind === "confirmed") {
      expect(screen.getByText(`₹${outcome.booking.confirmedPrice?.toFixed(0)}`)).toBeInTheDocument();
      expect(screen.getByText(outcome.booking.verifiedByAgent)).toBeInTheDocument();
    }
  });

  it("states plainly when no reliability signal exists yet, never fabricating one", () => {
    const outcome = getAaravToothacheBookingOutcome();
    render(<BookingConfirmation outcome={outcome} providerName="QuickCare Dental Walk-in" title="Aarav's dentist visit" />);
    expect(screen.getByText(/No reliability signal recorded yet/)).toBeInTheDocument();
  });
});
