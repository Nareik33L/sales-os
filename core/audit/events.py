"""Audit event names matching ``audit_log.event`` (see ``001_initial.sql``)."""

from __future__ import annotations

from enum import StrEnum


class AuditEvent(StrEnum):
    PROPOSE_EXTERNAL_WRITE = "PROPOSE_EXTERNAL_WRITE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EXECUTE = "EXECUTE"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    USER_EDIT = "USER_EDIT"
    SYNC = "SYNC"
