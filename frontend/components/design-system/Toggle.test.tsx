import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Toggle } from "./Toggle";

describe("Toggle", () => {
  it("renders without crashing as an accessible switch", () => {
    render(<Toggle checked={false} onChange={vi.fn()} label="Dark mode" />);
    const toggle = screen.getByRole("switch", { name: "Dark mode" });
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("reflects checked state via aria-checked", () => {
    render(<Toggle checked onChange={vi.fn()} label="Dark mode" />);
    expect(screen.getByRole("switch", { name: "Dark mode" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("calls onChange with the flipped value on click", () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="Dark mode" />);
    fireEvent.click(screen.getByRole("switch", { name: "Dark mode" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("does not call onChange when disabled", () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="Dark mode" disabled />);
    fireEvent.click(screen.getByRole("switch", { name: "Dark mode" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
