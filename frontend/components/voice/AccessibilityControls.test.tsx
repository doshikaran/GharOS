import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AccessibilityControls } from "./AccessibilityControls";

describe("AccessibilityControls", () => {
  it("reflects the current elder-mode state and calls back on toggle", () => {
    const onElderModeChange = vi.fn();
    render(<AccessibilityControls elderMode={false} onElderModeChange={onElderModeChange} />);
    const toggle = screen.getByRole("switch", { name: "Elder-friendly pacing" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    expect(onElderModeChange).toHaveBeenCalledWith(true);
  });

  it("states there is no penalty for repeating or asking again", () => {
    render(<AccessibilityControls elderMode={true} onElderModeChange={vi.fn()} />);
    expect(screen.getByText(/never a penalty/)).toBeInTheDocument();
  });
});
