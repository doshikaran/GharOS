import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { getAaravToothacheCall, getDadiCleaningCall } from "@/lib/concierge";
import { LiveCallTranscript } from "./LiveCallTranscript";

describe("LiveCallTranscript", () => {
  it("shows only the honesty note and disclosure turn immediately, before the rest reveals", () => {
    const call = getAaravToothacheCall();
    render(
      <LiveCallTranscript turns={call.conversation.turns} outcomeReport={call.outcomeReport} counterpartyName="QuickCare Dental Walk-in" />,
    );
    expect(screen.getByText(/real, sandboxed text conversation/i)).toBeInTheDocument();
    expect(screen.getByText(/not synthesized audio/i)).toBeInTheDocument();
    expect(screen.getByText(call.conversation.turns[0]!.utterance)).toBeInTheDocument();
    expect(screen.queryByText(call.conversation.turns[2]!.utterance)).not.toBeInTheDocument();
  });

  it("reveals every turn once 'Show full transcript' is used, and shows the real outcome summary", () => {
    const call = getAaravToothacheCall();
    render(
      <LiveCallTranscript turns={call.conversation.turns} outcomeReport={call.outcomeReport} counterpartyName="QuickCare Dental Walk-in" />,
    );
    fireEvent.click(screen.getByRole("button", { name: /show full transcript/i }));
    for (const turn of call.conversation.turns) {
      expect(screen.getByText(turn.utterance)).toBeInTheDocument();
    }
    expect(screen.getByText(call.outcomeReport.claimedOutcomeSummary)).toBeInTheDocument();
  });

  it("marks turn zero as the unmissable disclosure turn", () => {
    const call = getAaravToothacheCall();
    render(
      <LiveCallTranscript turns={call.conversation.turns} outcomeReport={call.outcomeReport} counterpartyName="QuickCare Dental Walk-in" />,
    );
    expect(screen.getByText("Disclosure, every call, no exceptions")).toBeInTheDocument();
  });

  it("shows a distinct escalation badge on the turn where the agent escalates, never glossed over", () => {
    const call = getDadiCleaningCall();
    render(
      <LiveCallTranscript turns={call.conversation.turns} outcomeReport={call.outcomeReport} counterpartyName="Bright Smiles Dental" />,
    );
    fireEvent.click(screen.getByRole("button", { name: /show full transcript/i }));
    expect(screen.getByTestId("noteworthy-badge")).toHaveTextContent("Escalated to a human");
  });

  it("never renders any word implying literal audio or a phone ringing", () => {
    const call = getAaravToothacheCall();
    const { container } = render(
      <LiveCallTranscript turns={call.conversation.turns} outcomeReport={call.outcomeReport} counterpartyName="QuickCare Dental Walk-in" />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/ringing|dial(l|)ing|voicemail beep|audio recording/i);
  });
});
