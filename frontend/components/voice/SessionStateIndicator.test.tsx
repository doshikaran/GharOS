import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SessionStateIndicator } from "./SessionStateIndicator";

describe("SessionStateIndicator", () => {
  it.each([
    ["listening", "Listening"],
    ["processing", "Thinking"],
    ["speaking", "Speaking"],
    ["closed", "Not connected"],
  ] as const)("renders the %s state with label %s", (state, label) => {
    render(<SessionStateIndicator state={state} interrupted={false} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("exposes the state in an aria-live=polite status region so screen readers hear every transition", () => {
    render(<SessionStateIndicator state="listening" interrupted={false} />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("shows a visible interruption callout only when a real barge-in happened", () => {
    const { rerender } = render(<SessionStateIndicator state="speaking" interrupted={false} />);
    expect(screen.queryByTestId("barge-in-indicator")).not.toBeInTheDocument();

    rerender(<SessionStateIndicator state="speaking" interrupted={true} />);
    expect(screen.getByTestId("barge-in-indicator")).toHaveTextContent(/Interrupted/);
  });
});
