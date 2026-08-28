import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AppShell } from "./AppShell";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/graph"),
}));

describe("AppShell", () => {
  it("renders the sidebar, the top bar, and its children", () => {
    render(
      <AppShell>
        <p>Page content</p>
      </AppShell>,
    );

    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByText("Page content")).toBeInTheDocument();
  });

  it("starts expanded (not collapsed)", () => {
    const { container } = render(
      <AppShell>
        <p>Page content</p>
      </AppShell>,
    );
    expect(container.firstChild).toHaveAttribute("data-collapsed", "false");
  });

  it("toggles the collapsed state when the top bar's hamburger is clicked", () => {
    const { container } = render(
      <AppShell>
        <p>Page content</p>
      </AppShell>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(container.firstChild).toHaveAttribute("data-collapsed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
    expect(container.firstChild).toHaveAttribute("data-collapsed", "false");
  });

  it("collapses again when the backdrop is clicked (narrow-viewport drawer dismiss)", () => {
    const { container } = render(
      <AppShell>
        <p>Page content</p>
      </AppShell>,
    );

    // Open first (backdrop is only meaningful, CSS-wise, while open).
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(container.firstChild).toHaveAttribute("data-collapsed", "true");

    // Re-open, then dismiss via the backdrop.
    fireEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
    expect(container.firstChild).toHaveAttribute("data-collapsed", "false");

    const backdrop = container.querySelector('button[aria-hidden="true"]');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop as Element);
    expect(container.firstChild).toHaveAttribute("data-collapsed", "true");
  });
});
