"""`backend/app/tools/` — concrete tool implementations by permission tier
(spec §16), owned by E3.

`ToolRegistry` (`registry.py`) is what every agent is wired against at
construction time; concrete tools live one module per tier/tool. T4/T5/T6
(gated) concrete tools do not live here — they live under
`backend/app/arbitration/`, the Approval Gate's own package, per
`contracts.tools.ApprovalGatedTool`'s docstring and spec §16.3 invariant 2.
"""

from __future__ import annotations
