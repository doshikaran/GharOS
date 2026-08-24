"""One-off driver for `docs/IMPLICATION_BASELINE.md`'s hand-scoring
worksheet — NOT a pytest test (underscore-prefixed, outside pytest's
`test_*.py` discovery pattern on purpose). Calls the same
`build_live_agent`/`render_report` functions `implication_eval.py`
already exports, running one document at a time and flushing each
outcome to disk immediately — this environment has proven interruption-
prone mid-run (a host sleep, then a session-limit reset, each losing an
all-at-the-end write), so incremental, resumable output is a real
requirement here, not a nicety.

    cd backend && GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=<project> \\
        uv run python tests/evaluation/_generate_report.py <output_path>

Safe to re-run: documents whose id already has a completed block in
<output_path> are skipped, so an interrupted run resumes from where it
left off rather than repeating (and re-billing) already-scored documents.
"""

from __future__ import annotations

import sys

from tests.evaluation.held_out_documents import EVAL_DOCUMENTS
from tests.evaluation.implication_eval import build_live_agent, render_report, run_document


def _already_completed_doc_ids(output_path: str) -> set[str]:
    """Doc ids that already have a rendered block in `output_path` from a
    prior (possibly interrupted) run — each block starts with a line of
    `=` characters followed by `<doc_id> — <title>` (see
    `implication_eval.render_report`'s exact format)."""
    try:
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return set()
    return {document.doc_id for document in EVAL_DOCUMENTS if f"\n{document.doc_id} — " in content}


def main(output_path: str) -> None:
    done = _already_completed_doc_ids(output_path)
    if done:
        print(f"resuming: {len(done)}/{len(EVAL_DOCUMENTS)} documents already completed in {output_path}")

    agent = build_live_agent()
    with open(output_path, "a", encoding="utf-8") as f:
        for document in EVAL_DOCUMENTS:
            if document.doc_id in done:
                continue
            outcome = run_document(agent, document)
            f.write(render_report((outcome,)))
            f.flush()
            print(f"completed and flushed: {document.doc_id}")

    print(f"done — {len(EVAL_DOCUMENTS)}/{len(EVAL_DOCUMENTS)} documents in {output_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "implication_eval_report.txt")
