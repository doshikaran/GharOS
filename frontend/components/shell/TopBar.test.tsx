import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { TopBar } from "./TopBar";

const { usePathnameMock } = vi.hoisted(() => ({ usePathnameMock: vi.fn(() => "/graph") }));

vi.mock("next/navigation", () => ({
  usePathname: usePathnameMock,
}));

describe("TopBar", () => {
  it("derives the section title from the active route via the static route map", () => {
    usePathnameMock.mockReturnValue("/fair-allocator");
    render(<TopBar collapsed={false} onToggleCollapse={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Fair Allocator" })).toBeInTheDocument();
  });

  it("falls back to the default title for a route with no nav entry (e.g. the home page)", () => {
    usePathnameMock.mockReturnValue("/");
    render(<TopBar collapsed={false} onToggleCollapse={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "GharOS" })).toBeInTheDocument();
  });

  it("calls onToggleCollapse when the hamburger toggle is clicked", () => {
    usePathnameMock.mockReturnValue("/graph");
    const onToggleCollapse = vi.fn();
    render(<TopBar collapsed={false} onToggleCollapse={onToggleCollapse} />);

    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(onToggleCollapse).toHaveBeenCalledOnce();
  });

  it("reflects the collapsed state in the toggle's accessible name and aria-expanded", () => {
    usePathnameMock.mockReturnValue("/graph");
    render(<TopBar collapsed={true} onToggleCollapse={vi.fn()} />);

    const toggle = screen.getByRole("button", { name: "Expand navigation" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
