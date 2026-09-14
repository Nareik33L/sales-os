"""Exceptions raised by the approval gate. None of these should reach a Streamlit page
unwrapped; UI/connectors map them to audit rows and user-visible status.
"""

from __future__ import annotations


class AuditError(Exception):
    """Base class for approval-gate failures."""


class AuditNotFoundError(AuditError):
    """No ``audit_log`` row exists for the given id."""


class ApprovalRequiredError(AuditError):
    """``execute_approved`` was called without ``approval_status=APPROVED``."""


class InvalidAuditStateError(AuditError):
    """The row exists but is not in a state that allows this transition."""


class WriterNotConfiguredError(AuditError):
    """``execute_approved`` has no injected writer/callback."""


class AuditExecutionError(AuditError):
    """The injected writer raised; the audit row has been marked ``FAILED``."""
