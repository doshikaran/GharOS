import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getAaravFollowupFallback, getDadiCleaningFallback } from "@/lib/concierge";
import { ConciergeFallbackSurface } from "./ConciergeFallbackSurface";

describe("ConciergeFallbackSurface", () => {
  it("renders the real retryAfter time for a RETRY decision, with no evidence bundle or resolve button", () => {
    const retry = {
      action: "retry" as const,
      reasoning: "The line rang out with no answer.",
      retryAfter: "2026-09-01T09:15:00Z",
      escalationPayload: null,
    };
    render(<ConciergeFallbackSurface title="Sunrise Family Dental" decision={retry} />);
    expect(screen.getByText("Retrying")).toBeInTheDocument();
    expect(screen.getByText(retry.reasoning)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a full ESCALATE brief, summary, risk tier, and every evidenceConsulted entry", () => {
    const fallback = getDadiCleaningFallback();
    render(<ConciergeFallbackSurface title="Dadi's cleaning" decision={fallback} />);
    expect(screen.getByText("Escalated, a human decides")).toBeInTheDocument();
    expect(screen.getByText(fallback.escalationPayload!.summary)).toBeInTheDocument();
    for (const evidence of fallback.escalationPayload!.evidenceBundle.evidenceConsulted) {
      expect(screen.getByText(evidence)).toBeInTheDocument();
    }
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("frames the escalation as presenting options for a human, never auto-resolving", () => {
    const fallback = getAaravFollowupFallback();
    render(<ConciergeFallbackSurface title="Aarav's follow-up" decision={fallback} />);
    expect(screen.getByText(/presenting options for a household member to decide/i)).toBeInTheDocument();
  });
});
