"""Encode/decode codecs between `contracts.graph_types` dataclasses and
Firestore-safe document dicts.

Firestore documents support: str, bool, int, float, timezone-aware
datetime, bytes, list, map (nested dict), None, and geo-point/reference
types we don't use here. `contracts.graph_types` dataclasses additionally
use: `Enum` members, `tuple`, frozen nested dataclasses, and `NewType(str)`
aliases (`NodeId`, `EdgeId`, `AgentId` — plain `str` at runtime). This
package is the single place that translation happens, so no other module
hand-rolls a `.value` or `dataclasses.astuple` call against a graph type.
"""

from __future__ import annotations
