"""Canonical `type_id` strings for the Document-Type Registry (spec §5.4.2).

Defined once, here, so no call site (this package's own
`document_type_specs.py`, tests, or E2's fourteen `ExtractionStrategy`
implementations and A2 Intake Router) ever repeats these as ad hoc string
literals (gharos-standards rule 3: no magic values).

**These exact fourteen snake_case strings are a cross-role contract by
convention, not by `contracts/` enforcement** — PHASES.md Phase 3's E3/E2
split names this precise list so both roles land on the same identifiers
without a `contracts/` round-trip. Do not rename any of these without
checking who else has landed work against them.
"""

from __future__ import annotations

RECEIPT = "receipt"
UTILITY_BILL = "utility_bill"
SOCIETY_NOTICE = "society_notice"
SCHOOL_COMMUNICATION = "school_communication"
PERMISSION_SLIP = "permission_slip"
ATTENDANCE_REGISTER = "attendance_register"
BANK_STATEMENT = "bank_statement"
UPI_SMS_ALERT = "upi_sms_alert"
MEDICAL_DOCUMENT = "medical_document"
INSURANCE_DOCUMENT = "insurance_document"
WARRANTY = "warranty"
GOVERNMENT_NOTICE = "government_notice"
QUOTE_ESTIMATE = "quote_estimate"
CHAT_THREAD = "chat_thread"

ALL_TYPE_IDS: tuple[str, ...] = (
    RECEIPT,
    UTILITY_BILL,
    SOCIETY_NOTICE,
    SCHOOL_COMMUNICATION,
    PERMISSION_SLIP,
    ATTENDANCE_REGISTER,
    BANK_STATEMENT,
    UPI_SMS_ALERT,
    MEDICAL_DOCUMENT,
    INSURANCE_DOCUMENT,
    WARRANTY,
    GOVERNMENT_NOTICE,
    QUOTE_ESTIMATE,
    CHAT_THREAD,
)
"""All fourteen, in spec §5.4.2's presentation order. Tests assert this
tuple has exactly 14 unique entries and that every one of them ends up
registered — see `test_document_type_specs.py`."""

__all__ = [
    "ALL_TYPE_IDS",
    "ATTENDANCE_REGISTER",
    "BANK_STATEMENT",
    "CHAT_THREAD",
    "GOVERNMENT_NOTICE",
    "INSURANCE_DOCUMENT",
    "MEDICAL_DOCUMENT",
    "PERMISSION_SLIP",
    "QUOTE_ESTIMATE",
    "RECEIPT",
    "SCHOOL_COMMUNICATION",
    "SOCIETY_NOTICE",
    "UPI_SMS_ALERT",
    "UTILITY_BILL",
    "WARRANTY",
]
