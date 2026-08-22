import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Card } from "./Card";

describe("Card", () => {
  it("renders without crashing, with a title and children", () => {
    render(<Card title="Ledger entry">Recovered ₹4,200 last month</Card>);
    expect(screen.getByRole("heading", { name: "Ledger entry" })).toBeInTheDocument();
    expect(screen.getByText("Recovered ₹4,200 last month")).toBeInTheDocument();
  });

  it("renders without a title", () => {
    render(<Card>No title here</Card>);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByText("No title here")).toBeInTheDocument();
  });
});
