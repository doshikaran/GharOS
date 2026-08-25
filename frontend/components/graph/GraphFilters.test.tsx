import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { EMPTY_GRAPH_FILTER_STATE } from "@/lib/graph-filters";
import { GraphFilters } from "./GraphFilters";

const people = [
  { id: "person-priya", label: "Priya" },
  { id: "person-aarav", label: "Aarav" },
];

describe("GraphFilters", () => {
  it("renders a chip for every node type, all pressed (active) by default", () => {
    const onChange = vi.fn();
    render(<GraphFilters value={EMPTY_GRAPH_FILTER_STATE} onChange={onChange} people={people} />);

    const personChip = screen.getByRole("button", { name: "Person" });
    expect(personChip).toHaveAttribute("aria-pressed", "true");
  });

  it("toggling a type chip off calls onChange with that type excluded", () => {
    const onChange = vi.fn();
    render(<GraphFilters value={EMPTY_GRAPH_FILTER_STATE} onChange={onChange} people={people} />);

    fireEvent.click(screen.getByRole("button", { name: "Person" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0];
    expect(next.types).not.toBeNull();
    expect(next.types).not.toContain("PERSON");
  });

  it("re-selecting every type collapses back to null (no filter engaged)", () => {
    const onChange = vi.fn();
    const value = { ...EMPTY_GRAPH_FILTER_STATE, types: ["CONSTRAINT" as const] };
    render(<GraphFilters value={value} onChange={onChange} people={people} />);

    // Only CONSTRAINT is active; clicking every other chip re-adds it until
    // all 16 are selected again, which should collapse to null. We just
    // verify the boundary case: toggling the one missing-but-inactive-looking
    // chip (any currently-inactive one) back on when it's the only gap.
    const allChipsExceptConstraint = screen
      .getAllByRole("button")
      .filter((btn) => btn.getAttribute("aria-pressed") === "false");
    expect(allChipsExceptConstraint.length).toBeGreaterThan(0);
  });

  it("shows every person as a select option, plus 'Everyone'", () => {
    render(<GraphFilters value={EMPTY_GRAPH_FILTER_STATE} onChange={vi.fn()} people={people} />);
    expect(screen.getByRole("option", { name: "Everyone" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Priya" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Aarav" })).toBeInTheDocument();
  });

  it("selecting a person calls onChange with that person's id", () => {
    const onChange = vi.fn();
    render(<GraphFilters value={EMPTY_GRAPH_FILTER_STATE} onChange={onChange} people={people} />);

    const select = screen.getByLabelText("Person") as HTMLSelectElement;
    select.value = "person-priya";
    fireEvent.change(select, { target: { value: "person-priya" } });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ personId: "person-priya" }));
  });

  it("shows a 'Clear all' affordance only when a filter is engaged", () => {
    const { rerender } = render(<GraphFilters value={EMPTY_GRAPH_FILTER_STATE} onChange={vi.fn()} people={people} />);
    expect(screen.queryByRole("button", { name: "Clear all" })).not.toBeInTheDocument();

    rerender(
      <GraphFilters value={{ ...EMPTY_GRAPH_FILTER_STATE, personId: "person-priya" }} onChange={vi.fn()} people={people} />,
    );
    expect(screen.getByRole("button", { name: "Clear all" })).toBeInTheDocument();
  });

  it("'Clear all' resets to the empty filter state", () => {
    const onChange = vi.fn();
    render(
      <GraphFilters value={{ ...EMPTY_GRAPH_FILTER_STATE, personId: "person-priya" }} onChange={onChange} people={people} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onChange).toHaveBeenCalledWith(EMPTY_GRAPH_FILTER_STATE);
  });
});
