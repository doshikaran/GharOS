import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfidenceMeter } from "./ConfidenceMeter";

describe("ConfidenceMeter", () => {
  it("renders the confidence as a percentage, not a raw 0-1 number", () => {
    render(<ConfidenceMeter confidence={0.88} />);
    expect(screen.getByText("88%")).toBeInTheDocument();
    expect(screen.queryByText("0.88")).not.toBeInTheDocument();
  });

  it("labels high confidence distinctly from a bare number", () => {
    render(<ConfidenceMeter confidence={0.93} />);
    expect(screen.getByText("High confidence")).toBeInTheDocument();
  });

  it("labels moderate confidence distinctly", () => {
    render(<ConfidenceMeter confidence={0.71} />);
    expect(screen.getByText("Moderate confidence")).toBeInTheDocument();
  });

  it("labels low confidence distinctly", () => {
    render(<ConfidenceMeter confidence={0.4} />);
    expect(screen.getByText("Low confidence")).toBeInTheDocument();
  });

  it("exposes a progressbar role carrying the real percentage for assistive tech", () => {
    render(<ConfidenceMeter confidence={0.68} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "68");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("clamps out-of-range confidence values rather than rendering nonsense", () => {
    render(<ConfidenceMeter confidence={1.4} />);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });
});
