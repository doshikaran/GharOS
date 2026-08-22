import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Button } from "./Button";

describe("Button", () => {
  it("renders without crashing and shows its label", () => {
    render(<Button>Approve</Button>);
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("applies the requested variant class", () => {
    render(<Button variant="danger">Deny</Button>);
    const button = screen.getByRole("button", { name: "Deny" });
    expect(button.className).toContain("danger");
  });

  it("fires onClick and respects disabled", () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        Disabled
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Disabled" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});
