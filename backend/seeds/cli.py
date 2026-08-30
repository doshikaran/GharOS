"""`python -m seeds` — load / reset the full demo household against a
running Firestore (the local emulator, or a real project).

    python -m seeds load                 # write the full demo dataset
    python -m seeds reset                 # wipe the graph, then write it
    python -m seeds reset --yes-live      # allow reset against real Firestore

`load` and `reset` both go through the real provenance-guarded
`FirestoreGraphWriter` (`seeds.seed_loader.load_full_demo`) and then run
`FirestoreGraphIntegrityChecker` + `unexplained("all")` and print the
result — a non-clean graph exits non-zero, so `make seed-demo` fails
loudly rather than leaving a broken graph.

`reset` deletes every graph collection (`app.persistence.collections.
NODE_TYPE_TO_COLLECTION` + `edges` + `node_index`). GharOS is single-
household by design (spec §3.1), so "the graph" *is* the demo household —
there is no other household's data to protect. It still refuses to run
against a target that is not the local emulator unless `--yes-live` is
passed explicitly, and never touches the append-only audit log or the
local raw-payload store.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import structlog
from google.cloud import firestore

from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.collections import (
    EDGES_COLLECTION,
    NODE_INDEX_COLLECTION,
    NODE_TYPE_TO_COLLECTION,
)
from app.persistence.firestore_client import create_firestore_client
from app.persistence.firestore_store import FirestoreGraphStore
from app.settings import get_settings
from seeds.seed_loader import load_full_demo

logger = structlog.get_logger(__name__)

_GRAPH_COLLECTIONS: tuple[str, ...] = (
    *sorted(NODE_TYPE_TO_COLLECTION.values()),
    EDGES_COLLECTION,
    NODE_INDEX_COLLECTION,
)


def _running_against_emulator() -> bool:
    return bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))


def _client() -> firestore.Client:
    return create_firestore_client(get_settings())


def _wipe_graph(client: firestore.Client) -> int:
    """Recursively deletes every graph collection (documents + their
    `versions` subcollections). Returns the number of top-level collections
    cleared."""
    for name in _GRAPH_COLLECTIONS:
        client.recursive_delete(client.collection(name))
    return len(_GRAPH_COLLECTIONS)


def _load_and_verify(client: firestore.Client) -> int:
    store = FirestoreGraphStore(client)
    seed = load_full_demo(FirestoreGraphWriter(store))

    node_ids = [str(n.id) for n in seed.nodes]  # type: ignore[attr-defined]
    print(f"loaded full demo: {len(node_ids)} nodes, {len(seed.edges)} edges")

    reader = FirestoreGraphReader(store)
    unexplained = reader.unexplained("all")
    violations = FirestoreGraphIntegrityChecker(store).check("all")

    if unexplained:
        print(f"FAIL: unexplained() returned {len(unexplained)} node(s): {list(unexplained)[:10]}")
    if violations:
        print(f"FAIL: integrity checker found {len(violations)} violation(s):")
        for violation in violations[:20]:
            print(f"  - {violation}")
    if unexplained or violations:
        return 1

    print("OK: unexplained() empty, integrity checker clean")
    return 0


def _cmd_load(_args: argparse.Namespace) -> int:
    return _load_and_verify(_client())


def _cmd_reset(args: argparse.Namespace) -> int:
    if not _running_against_emulator() and not args.yes_live:
        print(
            "refusing to reset: FIRESTORE_EMULATOR_HOST is not set and --yes-live was not passed.\n"
            "Start the emulator (`make emulators`) or pass --yes-live to target real Firestore."
        )
        return 2
    client = _client()
    target = "emulator" if _running_against_emulator() else f"REAL Firestore (project={client.project})"
    print(f"reset: wiping the graph on {target} ...")
    cleared = _wipe_graph(client)
    print(f"reset: cleared {cleared} collections; reloading ...")
    return _load_and_verify(client)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seeds", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("load", help="write the full demo dataset (adds versions if run twice)")

    reset = sub.add_parser("reset", help="wipe every graph collection, then reload — idempotent")
    reset.add_argument(
        "--yes-live",
        action="store_true",
        help="allow reset when FIRESTORE_EMULATOR_HOST is not set (targets real Firestore)",
    )

    args = parser.parse_args(argv)
    handler = {"load": _cmd_load, "reset": _cmd_reset}[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
