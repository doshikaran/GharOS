import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BranchCard } from "./BranchCard";
import { getBranchCritiques, getBranchProjections, getGroundingResults } from "@/lib/simulator";

describe("BranchCard", () => {
  const projection = getBranchProjections()[0];
  const grounding = getGroundingResults().find((g) => g.branchLabel === projection.label);
  const critique = getBranchCritiques().find((c) => c.branchId === projection.branchId);

  it("renders the branch label as a heading and every projected impact", () => {
    render(<BranchCard projection={projection} grounding={grounding} critique={critique} />);
    expect(screen.getByRole("heading", { name: projection.label })).toBeInTheDocument();
    for (const impact of Object.values(projection.projectedImpacts)) {
      expect(screen.getByText(impact)).toBeInTheDocument();
    }
  });

  it("renders every blast-radius node id", () => {
    render(<BranchCard projection={projection} grounding={grounding} critique={critique} />);
    for (const nodeId of projection.blastRadiusNodeIds) {
      expect(screen.getByText(nodeId)).toBeInTheDocument();
    }
  });

  it("renders projection, grounding, and critique as three separate labelled sections", () => {
    render(<BranchCard projection={projection} grounding={grounding} critique={critique} />);
    expect(screen.getByLabelText("Projected impacts")).toBeInTheDocument();
    expect(screen.getByLabelText("Grounding")).toBeInTheDocument();
    expect(screen.getByLabelText("Consistency critique")).toBeInTheDocument();
  });
});
