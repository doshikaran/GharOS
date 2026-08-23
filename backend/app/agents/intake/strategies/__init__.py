"""The fourteen `ExtractionStrategy` implementations (spec §5.4.2,
ADR-008) — one module per `document_type_ids` constant, each a plain
class satisfying `contracts.graph_types.ExtractionStrategy`.

`register_all_strategies` wires all fourteen into a caller-supplied
`DocumentTypeRegistry` alongside E3's matching `DocumentTypeSpec`
(`app.adapters.document_type_specs.DOCUMENT_TYPE_SPECS_BY_ID`) — the one
place this package's strategies and E3's specs are joined. Adding a
fifteenth document type means one new spec (E3) + one new strategy module
(E2) + one new line in `_STRATEGIES_BY_TYPE_ID` below; nothing else in the
pipeline changes (ADR-008's whole point, proven by
`test_pipeline_extensibility.py`'s ad-hoc 15th-type test).
"""

from __future__ import annotations

from contracts.graph_types import ExtractionStrategy

from ....adapters import document_type_ids as type_id
from ....adapters.document_registry import DocumentTypeRegistry
from ....adapters.document_type_specs import DOCUMENT_TYPE_SPECS_BY_ID
from .attendance_register_strategy import AttendanceRegisterExtractionStrategy
from .bank_statement_strategy import BankStatementExtractionStrategy
from .chat_thread_strategy import ChatThreadExtractionStrategy
from .government_notice_strategy import GovernmentNoticeExtractionStrategy
from .insurance_document_strategy import InsuranceDocumentExtractionStrategy
from .medical_document_strategy import MedicalDocumentExtractionStrategy
from .permission_slip_strategy import PermissionSlipExtractionStrategy
from .quote_estimate_strategy import QuoteEstimateExtractionStrategy
from .receipt_strategy import ReceiptExtractionStrategy
from .school_communication_strategy import SchoolCommunicationExtractionStrategy
from .society_notice_strategy import SocietyNoticeExtractionStrategy
from .upi_sms_alert_strategy import UpiSmsAlertExtractionStrategy
from .utility_bill_strategy import UtilityBillExtractionStrategy
from .warranty_strategy import WarrantyExtractionStrategy

_STRATEGIES_BY_TYPE_ID: dict[str, ExtractionStrategy] = {
    type_id.RECEIPT: ReceiptExtractionStrategy(),
    type_id.UTILITY_BILL: UtilityBillExtractionStrategy(),
    type_id.SOCIETY_NOTICE: SocietyNoticeExtractionStrategy(),
    type_id.SCHOOL_COMMUNICATION: SchoolCommunicationExtractionStrategy(),
    type_id.PERMISSION_SLIP: PermissionSlipExtractionStrategy(),
    type_id.ATTENDANCE_REGISTER: AttendanceRegisterExtractionStrategy(),
    type_id.BANK_STATEMENT: BankStatementExtractionStrategy(),
    type_id.UPI_SMS_ALERT: UpiSmsAlertExtractionStrategy(),
    type_id.MEDICAL_DOCUMENT: MedicalDocumentExtractionStrategy(),
    type_id.INSURANCE_DOCUMENT: InsuranceDocumentExtractionStrategy(),
    type_id.WARRANTY: WarrantyExtractionStrategy(),
    type_id.GOVERNMENT_NOTICE: GovernmentNoticeExtractionStrategy(),
    type_id.QUOTE_ESTIMATE: QuoteEstimateExtractionStrategy(),
    type_id.CHAT_THREAD: ChatThreadExtractionStrategy(),
}


def register_all_strategies(registry: DocumentTypeRegistry) -> None:
    """Registers every one of the fourteen canonical document types (spec
    and its matching strategy into `registry` — the standard composition-
    root wiring call. Idempotent only in the sense that calling it twice
    on the same registry instance raises `DuplicateRegistration` (by
    design, per `DocumentTypeRegistry.register`'s own docstring) — callers
    construct one fresh registry and call this once.
    """
    for a_type_id in type_id.ALL_TYPE_IDS:
        spec = DOCUMENT_TYPE_SPECS_BY_ID[a_type_id]
        strategy = _STRATEGIES_BY_TYPE_ID[a_type_id]
        registry.register(a_type_id, spec, strategy)


__all__ = ["register_all_strategies"]
