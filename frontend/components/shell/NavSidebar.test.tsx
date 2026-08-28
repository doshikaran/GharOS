import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NAV_SECTIONS } from "./navConfig";
import { NavSidebar } from "./NavSidebar";

const { usePathnameMock } = vi.hoisted(() => ({ usePathnameMock: vi.fn(() => "/graph") }));

vi.mock("next/navigation", () => ({
  usePathname: usePathnameMock,
}));

// Same reference instant `ApprovalsBoard.test.tsx` and
// `useApprovalQueueCount.test.tsx` use — the fixture is date-stamped
// relative to this instant, so a fixed clock (not the real one) is what
// makes the badge-count assertion below deterministic regardless of the
// wall-clock date the test suite happens to run on.
const NOW = new Date("2026-08-22T09:30:00Z");

describe("NavSidebar", () => {
  it("renders both sections in ADR-018's specified order with every nav item", () => {
    render(<NavSidebar collapsed={false} />);

    const headings = screen.getAllByText(/Overview|Subsystems/);
    expect(headings.map((el) => el.textContent)).toEqual(["Overview", "Subsystems"]);

    for (const section of NAV_SECTIONS) {
      for (const item of section.items) {
        expect(screen.getByRole("link", { name: new RegExp(item.label) })).toHaveAttribute("href", item.href);
      }
    }
  });

  it("marks the active route's link with aria-current, and no other link", () => {
    usePathnameMock.mockReturnValue("/fair-allocator");
    render(<NavSidebar collapsed={false} />);

    expect(screen.getByRole("link", { name: "Fair Allocator" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Household Graph" })).not.toHaveAttribute("aria-current");
  });

  it("shows the live pending-approval badge on the Approvals item, with the real pending count", () => {
    usePathnameMock.mockReturnValue("/graph");
    render(<NavSidebar collapsed={false} now={NOW} />);

    // At NOW, the fixture has exactly 2 items needing a decision (same
    // instant ApprovalsBoard.test.tsx and useApprovalQueueCount.test.tsx
    // assert against) — same source, same predicate, same number.
    const approvalsLink = screen.getByRole("link", { name: /Approvals/ });
    expect(approvalsLink).toHaveAccessibleName("Approvals, 2 pending approvals");
  });

  it("omits the badge once every pending item has expired or resolved", () => {
    usePathnameMock.mockReturnValue("/graph");
    // Well past every fixture item's expiresAt, R4 excluded by design.
    render(<NavSidebar collapsed={false} now={new Date("2030-01-01T00:00:00Z")} />);

    const approvalsLink = screen.getByRole("link", { name: "Approvals" });
    expect(approvalsLink).not.toHaveAccessibleName(/pending approval/);
  });

  it("reflects the collapsed prop as a data attribute for icon-rail / drawer styling", () => {
    usePathnameMock.mockReturnValue("/graph");
    const { container, rerender } = render(<NavSidebar collapsed={false} />);
    expect(container.querySelector("nav")).toHaveAttribute("data-collapsed", "false");

    rerender(<NavSidebar collapsed={true} />);
    expect(container.querySelector("nav")).toHaveAttribute("data-collapsed", "true");
  });

  it("links out to /tokens from the footer, not as a primary nav item", () => {
    usePathnameMock.mockReturnValue("/graph");
    render(<NavSidebar collapsed={false} />);

    const tokensLink = screen.getByRole("link", { name: "Design system" });
    expect(tokensLink).toHaveAttribute("href", "/tokens");
    // Not one of the primary nav items enumerated in NAV_SECTIONS.
    expect(NAV_SECTIONS.flatMap((s) => s.items.map((i) => i.href))).not.toContain("/tokens");
  });

  it("includes the theme switcher in the sidebar footer", () => {
    usePathnameMock.mockReturnValue("/graph");
    render(<NavSidebar collapsed={false} />);
    expect(screen.getByRole("radiogroup", { name: "Colour theme" })).toBeInTheDocument();
  });
});
