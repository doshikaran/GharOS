import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "./Badge";

describe("Badge", () => {
  it("renders without crashing with its content", () => {
    render(<Badge variant="success">Verified</Badge>);
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("defaults to the neutral variant", () => {
    render(<Badge>Untitled</Badge>);
    expect(screen.getByText("Untitled").className).toContain("neutral");
  });
});
