"""Typed errors for the fourteen `ExtractionStrategy` implementations."""

from __future__ import annotations


class MappingInputIncomplete(RuntimeError):
    """Raised when a strategy cannot honestly build a node because a
    required field (per `DocumentTypeSpec.field_schema`) was never
    extracted, or was dropped by A3 for an invalid region/unknown name.

    A strategy never fabricates a placeholder value to fill the gap (a
    `0.0` amount, an empty merchant name) — that would be exactly the
    kind of silent invention spec §15.2 A3 is forbidden from, one layer
    downstream. Raising this routes the document to human triage instead
    (the same "never silently proceed" discipline as a registry gap).
    """

    def __init__(self, *, type_id: str, missing_fields: tuple[str, ...]) -> None:
        self.type_id = type_id
        self.missing_fields = missing_fields
        super().__init__(f"'{type_id}' mapping incomplete — missing required field(s): {missing_fields}")


__all__ = ["MappingInputIncomplete"]
