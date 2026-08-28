import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getAaravToothacheClarification } from "@/lib/concierge";
import { ClarificationDisplay } from "./ClarificationDisplay";

describe("ClarificationDisplay", () => {
  it("renders every graph-known fact with its real source", () => {
    const result = getAaravToothacheClarification();
    render(<ClarificationDisplay result={result} personName="Aarav" />);
    for (const fact of result.resolvedFromGraph) {
      expect(screen.getByText(fact.value)).toBeInTheDocument();
      expect(screen.getByText(fact.source)).toBeInTheDocument();
    }
  });

  it("renders exactly the real questions asked, never more than the ceiling", () => {
    const result = getAaravToothacheClarification();
    render(<ClarificationDisplay result={result} personName="Aarav" />);
    for (const question of result.questions) {
      expect(screen.getByText(question.text)).toBeInTheDocument();
    }
    expect(screen.getByText("2 / 2 max")).toBeInTheDocument();
  });

  it("renders the assumptions surfaced past the ceiling, proving it is real", () => {
    const result = getAaravToothacheClarification();
    render(<ClarificationDisplay result={result} personName="Aarav" />);
    expect(screen.getByText(/past the 2-question ceiling/i)).toBeInTheDocument();
    for (const assumption of result.assumptions) {
      expect(screen.getByText(assumption)).toBeInTheDocument();
    }
  });

  it("renders the elevated urgency and its real reasoning", () => {
    const result = getAaravToothacheClarification();
    render(<ClarificationDisplay result={result} personName="Aarav" />);
    expect(screen.getByText("Elevated")).toBeInTheDocument();
    expect(screen.getByText(result.urgencyReasoning)).toBeInTheDocument();
  });

  it("renders the household's own request text", () => {
    const result = getAaravToothacheClarification();
    render(<ClarificationDisplay result={result} personName="Aarav" />);
    expect(screen.getByText(new RegExp(result.householdRequestText.slice(0, 20)))).toBeInTheDocument();
  });
});
