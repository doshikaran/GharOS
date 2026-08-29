import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TranscriptView, type TranscriptEntry } from "./TranscriptView";

const CODE_MIXED_ENTRY: TranscriptEntry = {
  turnId: "turn-1",
  status: "final",
  spans: [
    { text: "Aarav ko Friday ko field trip hai,", language: "hi", confidence: 0.9 },
    { text: "permission slip sign karna hai", language: "hi", confidence: 0.85 },
    { text: "and paise dene hai", language: "en", confidence: 0.4 },
  ],
};

describe("TranscriptView", () => {
  it("shows guidance when there is no transcript yet", () => {
    render(<TranscriptView entries={[]} />);
    expect(screen.getByText(/No speech yet/)).toBeInTheDocument();
  });

  it("renders a per-span language tag for each span in a code-mixed utterance, not one tag for the whole turn", () => {
    render(<TranscriptView entries={[CODE_MIXED_ENTRY]} />);
    expect(screen.getAllByText("Hindi")).toHaveLength(2);
    expect(screen.getAllByText("English")).toHaveLength(1);
    expect(screen.getByText("Aarav ko Friday ko field trip hai,")).toBeInTheDocument();
    expect(screen.getByText("permission slip sign karna hai")).toBeInTheDocument();
    expect(screen.getByText("and paise dene hai")).toBeInTheDocument();
  });

  it("marks a partial turn distinctly from a final one", () => {
    const { container } = render(
      <TranscriptView
        entries={[{ turnId: "turn-2", status: "partial", spans: [{ text: "Society maintenance", language: "en", confidence: 0.8 }] }]}
      />,
    );
    expect(container.querySelector('[data-status="partial"]')).toBeInTheDocument();
    expect(screen.getByLabelText("still listening")).toBeInTheDocument();
  });

  it("exposes the transcript as a polite live region so a screen reader hears new turns without interrupting", () => {
    render(<TranscriptView entries={[CODE_MIXED_ENTRY]} />);
    const log = screen.getByRole("log", { name: "Live voice transcript" });
    expect(log).toHaveAttribute("aria-live", "polite");
  });

  it("applies elder-mode sizing via a data attribute, not inline styles", () => {
    const { container, rerender } = render(<TranscriptView entries={[]} elderMode={false} />);
    expect(container.querySelector('[data-elder-mode="false"]')).toBeInTheDocument();
    rerender(<TranscriptView entries={[]} elderMode={true} />);
    expect(container.querySelector('[data-elder-mode="true"]')).toBeInTheDocument();
  });
});
