"""`FirestorePersonRepository` — real, Firestore-backed
`contracts.repositories.PersonRepository`."""

from __future__ import annotations

from contracts.graph_types import NodeId, Person

from app.persistence.firestore_store import FirestoreGraphStore


class FirestorePersonRepository:
    """Structurally satisfies `contracts.repositories.PersonRepository`."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    def get(self, person_id: NodeId) -> Person | None:
        node = self._store.get_node(person_id)
        return node if isinstance(node, Person) else None

    def find_by_alias(self, alias: str) -> tuple[Person, ...]:
        needle = alias.strip().casefold()
        return tuple(
            person
            for person in self._store.all_current_nodes((Person,))
            if needle == person.display_name.casefold() or any(needle == a.casefold() for a in person.aliases)
        )
