"""Approval gate: propose → approve/reject → execute_approved.

The only path to an external write (ADR-005, docs/08-security.md §5). Connector
``write()`` is never imported here; callers inject a callback.
"""

from core.audit.events import AuditEvent
from core.audit.exceptions import (
    ApprovalRequiredError,
    AuditError,
    AuditExecutionError,
    AuditNotFoundError,
    InvalidAuditStateError,
    WriterNotConfiguredError,
)
from core.audit.gate import (
    approve,
    execute_approved,
    propose,
    record_config_change,
    reject,
)
from core.audit.writer import ExternalWriter, get_writer, set_writer

__all__ = [
    "ApprovalRequiredError",
    "AuditError",
    "AuditEvent",
    "AuditExecutionError",
    "AuditNotFoundError",
    "ExternalWriter",
    "InvalidAuditStateError",
    "WriterNotConfiguredError",
    "approve",
    "execute_approved",
    "get_writer",
    "propose",
    "record_config_change",
    "reject",
    "set_writer",
]
