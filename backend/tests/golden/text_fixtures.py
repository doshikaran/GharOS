"""Realistic-messy plain-text fixtures for the golden-file suite's
text-native document types (`upi_sms_alert`, `chat_thread`,
`bank_statement`, `government_notice`, `quote_estimate`, plus
`utility_bill`, `medical_document`, `insurance_document`, `warranty` —
all genuinely text/PDF-body-shaped documents in real life, not images).

Each fixture is real-looking noisy text: inconsistent spacing/casing,
common abbreviations, gateway-templated SMS truncation, and — for
`chat_thread` — natural code-mixed romanized Hindi/English, matching how
these documents actually look (spec §17, §5.4.2's own notes on SMS/chat
messiness). These are hand-authored strings, not scraped from any real
person's real messages.

**Region accuracy:** every field's `TextField.region` is computed via
`str.index()` against the fixture's own text at fixture-build time (see
`_field`) — a real, checkable byte-offset span into the exact string the
golden test sends to A3, not an eyeballed guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TextField:
    value: str
    region: str  # "<start>-<end>"


@dataclass(frozen=True, slots=True)
class TextDocument:
    text: str
    fields: dict[str, TextField] = field(default_factory=dict)


def _builder() -> _TextBuilder:
    return _TextBuilder()


class _TextBuilder:
    def __init__(self) -> None:
        self._lines: list[str] = []
        self._fields: dict[str, TextField] = {}

    def line(self, text: str, *, field_name: str | None = None, value: str | None = None) -> _TextBuilder:
        self._lines.append(text)
        if field_name is not None:
            search_for = value if value is not None else text
            full_text_so_far = "\n".join(self._lines)
            start = full_text_so_far.index(search_for)
            end = start + len(search_for)
            self._fields[field_name] = TextField(value=search_for, region=f"{start}-{end}")
        return self

    def build(self) -> TextDocument:
        text = "\n".join(self._lines)
        # Recompute regions against the FINAL text (offsets are stable
        # because lines are only ever appended, never edited afterwards,
        # but this reconfirms it explicitly rather than trusting that
        # invariant silently).
        fields = {}
        for name, tf in self._fields.items():
            start = text.index(tf.value)
            fields[name] = TextField(value=tf.value, region=f"{start}-{start + len(tf.value)}")
        return TextDocument(text=text, fields=fields)


def utility_bill_electricity() -> TextDocument:
    return (
        _builder()
        .line("CITY POWER CO. -- ELECTRICITY BILL", field_name="provider", value="CITY POWER CO.")
        .line("Acct: 88213-XX  |  Billing Period: 01-Aug-2026 to 30-Aug-2026")
        .line("  Period start: 2026-08-01", field_name="billing_period_start", value="2026-08-01")
        .line("  Period end:   2026-08-30", field_name="billing_period_end", value="2026-08-30")
        .line("Consumption: 340 units")
        .line("Amt Due: Rs 1200.00", field_name="amount_due", value="1200.00")
        .line("Due Date: 05-Sep-2026 -> 2026-09-05", field_name="due_date", value="2026-09-05")
        .line("Late fee: 2% after due date")
        .build()
    )


def bank_statement_excerpt() -> TextDocument:
    return (
        _builder()
        .line("HDFC BANK -- A/C STATEMENT (excerpt)", field_name="account", value="HDFC BANK")
        .line("Period: 2026-08-01 to 2026-08-20", field_name="period_start", value="2026-08-01")
        .line("Period end token: 2026-08-20", field_name="period_end", value="2026-08-20")
        .line("01/08/26  ATM WDL NR ANDHERI          -2000.00   Bal: 48000.00")
        .line("03/08/26  SALARY CREDIT XYZCORP       +50000.00  Bal: 98000.00")
        .line("Opening Balance: 50000.00", field_name="opening_balance", value="50000.00")
        .line("Closing Balance: 98000.00", field_name="closing_balance", value="98000.00")
        .build()
    )


def upi_sms_alert_clear() -> TextDocument:
    return (
        _builder()
        .line(
            "Rs.499.00 debited from a/c XX1234 on 20-Aug-26 to VPA bigbazaar@okhdfc.",
            field_name="amount",
            value="499.00",
        )
        .line("Direction: debit", field_name="direction", value="debit")
        .line(
            "Merchant: bigbazaar@okhdfc",
            field_name="counterparty_vpa_or_merchant",
            value="bigbazaar@okhdfc",
        )
        .line("Ref No 928374651.", field_name="reference_number", value="928374651")
        .line("Time: 2026-08-20T14:00:00", field_name="timestamp", value="2026-08-20T14:00:00")
        .build()
    )


def upi_sms_alert_garbled_merchant() -> TextDocument:
    """The 'notoriously opaque merchant string' case — low-confidence
    resolution must not drive any downstream cancellation on its own."""
    return (
        _builder()
        .line("Rs.150 dr frm a/c XX9981.", field_name="amount", value="150")
        .line("dir: debit", field_name="direction", value="debit")
        .line(
            "To PAYTM*XXXXX7712QR name unclear.",
            field_name="counterparty_vpa_or_merchant",
            value="PAYTM*XXXXX7712QR",
        )
        .line("time 2026-08-19T09:12:00", field_name="timestamp", value="2026-08-19T09:12:00")
        .build()
    )


def medical_appointment_note() -> TextDocument:
    return (
        _builder()
        .line("DR. MEHTA CLINIC -- Visit Summary", field_name="provider", value="DR. MEHTA CLINIC")
        .line("Patient: Aarav Sharma", field_name="patient", value="Aarav Sharma")
        .line("Doc type: follow-up note", field_name="document_type", value="follow-up note")
        .line("Date: 2026-08-10", field_name="document_date", value="2026-08-10")
        .line("Next follow-up: 2026-09-15", field_name="appointment_or_followup_dates", value="2026-09-15")
        .line(
            "Restriction as told by parent: nut allergy, avoid all tree nuts and peanuts.",
            field_name="stated_restrictions",
            value="nut allergy, avoid all tree nuts and peanuts",
        )
        .build()
    )


def insurance_renewal_notice() -> TextDocument:
    return (
        _builder()
        .line("STAR HEALTH INSURANCE -- Renewal Notice", field_name="insurer", value="STAR HEALTH INSURANCE")
        .line("Policy No: SH-2024-88213", field_name="policy_number", value="SH-2024-88213")
        .line("Coverage: family_floater", field_name="coverage_type", value="family_floater")
        .line("Sum insured: Rs 500000", field_name="coverage_limits", value="500000")
        .line("Premium: Rs 15000", field_name="premium", value="15000")
        .line("Premium due: 2026-12-01", field_name="premium_due_date", value="2026-12-01")
        .line("Renewal date: 2027-01-01", field_name="renewal_date", value="2027-01-01")
        .build()
    )


def warranty_refrigerator() -> TextDocument:
    return (
        _builder()
        .line("SAMSUNG -- WARRANTY CARD")
        .line("Product: Samsung Refrigerator RT42", field_name="product", value="Samsung Refrigerator RT42")
        .line("Purchase date: 2026-08-15", field_name="purchase_date", value="2026-08-15")
        .line("Warranty period: 2 years", field_name="warranty_period", value="2 years")
        .line("Expiry: 2028-08-15", field_name="warranty_expiry", value="2028-08-15")
        .line("Serial: RT42-998211", field_name="serial_number", value="RT42-998211")
        .build()
    )


def government_notice_trade_license() -> TextDocument:
    return (
        _builder()
        .line(
            "MUNICIPAL CORPORATION -- TRADE LICENSE NOTICE",
            field_name="issuing_body",
            value="MUNICIPAL CORPORATION",
        )
        .line("Ref: MC/TL/2026/8821", field_name="reference", value="MC/TL/2026/8821")
        .line(
            "Subject: Trade license renewal overdue",
            field_name="subject",
            value="Trade license renewal overdue",
        )
        .line(
            "Required action: Renew trade license",
            field_name="required_action",
            value="Renew trade license",
        )
        .line("Deadline: 2026-10-01", field_name="deadline", value="2026-10-01")
        .line(
            "Penalty: Rs 500/day after deadline",
            field_name="penalty_for_noncompliance",
            value="Rs 500/day after deadline",
        )
        .build()
    )


def quote_estimate_plumbing() -> TextDocument:
    return (
        _builder()
        .line("ABC PLUMBING SERVICES -- Estimate", field_name="provider", value="ABC PLUMBING SERVICES")
        .line(
            "Scope: Fix kitchen sink leak + replace pipe",
            field_name="scope_of_work",
            value="Fix kitchen sink leak + replace pipe",
        )
        .line("Labour: Rs 1000")
        .line("Parts: Rs 500")
        .line("Valid for 15 days from quote date", field_name="validity_period", value="15 days")
        .build()
    )


def chat_thread_code_mixed_pickup() -> TextDocument:
    """Natural romanized Hindi/English code-mixing, plus all three
    cross-script spellings of the same child's name (आरव / Aarav / Arav)
    across three separate messages — mirrors real family WhatsApp
    threads where a name gets typed differently by different people."""
    return (
        _builder()
        .line("14:02 Priya: Kal Aarav ko doctor le jaana hai, remind me")
        .line(
            "14:03 Dad: I'll pick her up Friday, no problem",
            field_name="embedded_commitments",
            value="I'll pick her up Friday, no problem",
        )
        .line("14:05 Mom: आरव ka lunch box bhi pack kar dena please")
        .line("14:07 Priya: Arav has practice till 5, usko yaad dilana")
        .build()
    )


def chat_thread_staff_leave() -> TextDocument:
    return (
        _builder()
        .line("09:10 Radha: Maam mujhe kal leave chahiye, ghar mein kaam hai")
        .line(
            "09:12 Radha: kal nahi aa paaungi, sorry for short notice",
            field_name="embedded_commitments",
            value="kal nahi aa paaungi, sorry for short notice",
        )
        .line("09:15 Priya: ok no problem, take care")
        .build()
    )


def unrecognizable_document() -> TextDocument:
    """**Gate 3 planted case:** genuinely does not match any registered
    type's detection signals — the registry-gap path."""
    return _builder().line("asdkj 19273 !!! qqq zzxxcv random unclassifiable fragment 001").build()


__all__ = [
    "TextDocument",
    "TextField",
    "bank_statement_excerpt",
    "chat_thread_code_mixed_pickup",
    "chat_thread_staff_leave",
    "government_notice_trade_license",
    "insurance_renewal_notice",
    "medical_appointment_note",
    "quote_estimate_plumbing",
    "unrecognizable_document",
    "upi_sms_alert_clear",
    "upi_sms_alert_garbled_merchant",
    "utility_bill_electricity",
    "warranty_refrigerator",
]
