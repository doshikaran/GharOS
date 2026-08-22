"""GharOS frozen contracts — CTO-owned. See PHASES.md §1.1 and §0.3.

No submodule in this package may import Firestore, FastAPI, ADK, or any
other infrastructure library. This package must remain importable in total
isolation from `backend/` and `frontend/`.
"""
