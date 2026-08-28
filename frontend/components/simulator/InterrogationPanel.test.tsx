import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { InterrogationPanel } from "./InterrogationPanel";
import { getDecisionBrief } from "@/lib/simulator";

function askQuestion(inputText: string) {
  const input = screen.getByPlaceholderText(/what if the budget/i);
  fireEvent.change(input, { target: { value: inputText } });
  fireEvent.click(screen.getByRole("button", { name: /ask/i }));
  return input as HTMLInputElement;
}

describe("InterrogationPanel", () => {
  it("submits a question and appends the question + answer to the history list", () => {
    const brief = getDecisionBrief();
    render(<InterrogationPanel brief={brief} />);

    askQuestion("What about the dialysis centre?");

    expect(screen.getByText("What about the dialysis centre?")).toBeInTheDocument();
    expect(screen.getByText(/Mehta Dialysis Centre/)).toBeInTheDocument();
  });

  it("clears the input after submitting", () => {
    render(<InterrogationPanel brief={getDecisionBrief()} />);
    const input = askQuestion("Any question at all");
    expect(input.value).toBe("");
  });

  it("does not submit an empty or whitespace-only question", () => {
    render(<InterrogationPanel brief={getDecisionBrief()} />);
    fireEvent.click(screen.getByRole("button", { name: /ask/i }));
    expect(screen.queryByLabelText("Interrogation history")).not.toBeInTheDocument();
  });

  it("supports multiple questions accumulating in order", () => {
    render(<InterrogationPanel brief={getDecisionBrief()} />);

    askQuestion("First question");
    askQuestion("Second question");

    const history = screen.getByLabelText("Interrogation history");
    const items = history.querySelectorAll("li");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("First question");
    expect(items[1].textContent).toContain("Second question");
  });

  it("never renders a recommendation or verdict word in any answer", () => {
    render(<InterrogationPanel brief={getDecisionBrief()} />);
    askQuestion("Which branch should we pick?");
    const history = screen.getByLabelText("Interrogation history");
    expect(history.textContent?.toLowerCase()).not.toContain("you should choose");
    expect(history.textContent?.toLowerCase()).not.toContain("the best branch is");
  });
});
