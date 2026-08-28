"use client";

import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/design-system/Button";
import { answerFollowup, type DecisionBrief } from "@/lib/simulator";
import styles from "./InterrogationPanel.module.css";

export interface InterrogationPanelProps {
  readonly brief: DecisionBrief;
}

interface Exchange {
  readonly question: string;
  readonly answer: string;
}

/**
 * Interrogation mode (this phase's brief: "a simple question-input +
 * answer-list UI against `DecisionBrief`, calling a stubbed
 * `answerFollowup(brief, question)` client function"). `answerFollowup`
 * is a deterministic, fixture-backed stand-in for a real follow-up-agent
 * call — see `lib/simulator.ts`'s own doc comment on that function for
 * the seam; this component only ever calls it, never re-implements
 * answering logic itself.
 */
export function InterrogationPanel({ brief }: InterrogationPanelProps) {
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<readonly Exchange[]>([]);
  const inputId = useId();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (trimmed.length === 0) return;
    const answer = answerFollowup(brief, trimmed);
    setExchanges((prev) => [...prev, { question: trimmed, answer }]);
    setQuestion("");
  }

  return (
    <div className={styles.panel}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label htmlFor={inputId} className={styles.srOnly}>
          Ask a follow-up question about this decision
        </label>
        <input
          id={inputId}
          className={styles.input}
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. What if the budget were 15% higher?"
        />
        <Button type="submit" variant="secondary">
          Ask
        </Button>
      </form>
      <p className={styles.hint}>
        Answers only ever surface what is already in this decision&apos;s trade-offs and open questions above —
        never a new claim, and never a verdict.
      </p>

      {exchanges.length > 0 && (
        <ul className={styles.answerList} aria-label="Interrogation history">
          {exchanges.map((exchange, index) => (
            <li key={index} className={styles.exchange}>
              <p className={styles.question}>{exchange.question}</p>
              <p className={styles.answer}>{exchange.answer}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
