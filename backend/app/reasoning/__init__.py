"""GharOS reasoning layer — owned exclusively by E2 (Agents & Reasoning).

Phase 2 (PHASES.md "PHASE 2 — MANDATORY STACK PROOF") introduces this
package with the two pieces of infrastructure every later reasoning agent
(Phase 3 onward, spec §15's 69-agent roster) builds on:

- `model_router` — Flash/Pro-tier routing with a code-enforced Pro-tier
  allowlist (spec §21.1, gharos-standards "cost control" rule 3). A
  Pro-tier call from an agent not on the allowlist is a typed error, not a
  warning.
- `gemini_client` — a thin, dependency-injected wrapper around the Vertex
  AI Gemini SDK (`google.genai`), built on top of `model_router` so every
  agent that needs a live model call goes through the same allowlist-
  enforcing path rather than constructing its own `google.genai.Client`.

Typed errors for this layer live in `reasoning.errors`, not
`contracts.errors` — that module is frozen and CTO-only.
"""

from __future__ import annotations
