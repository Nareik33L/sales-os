"""Approval gate: the only path to an external write (docs/08-security.md §5).

One ``audit_log`` row is created at ``propose`` and mutated through
PENDING → APPROVED|REJECTED → EXECUTED|FAILED. ``record_config_change`` inserts
a separate row with ``approval_status=NOT_REQUIRED``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from core.audit.events import AuditEvent
from core.audit.exceptions import (
    ApprovalRequiredError,
    AuditExecutionError,
    AuditNotFoundError,
    InvalidAuditStateError,
    WriterNotConfiguredError,
)
from core.audit.writer import ExternalWriter, get_writer
from core.models.common import utcnow
from core.models.repos import add_audit_log_evidence, get_audit_log, upsert_audit_log
from core.models.schemas import ApprovalStatus, AuditLog

_VALID_ACTORS = frozenset({"user", "system"})


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _require_actor(actor: str) -> str:
    if actor not in _VALID_ACTORS:
        raise ValueError("actor must be 'user' or 'system'")
    return actor


def _get_row(conn: sqlite3.Connection, audit_id: str) -> AuditLog:
    row = get_audit_log(conn, audit_id)
    if row is None:
        raise AuditNotFoundError(f"no audit_log row for id {audit_id!r}")
    return row


def _status(row: AuditLog) -> ApprovalStatus | None:
    status = row.approval_status
    if status is None:
        return None
    if isinstance(status, ApprovalStatus):
        return status
    return ApprovalStatus(status)


def _envelope(*, capability: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not capability:
        raise ValueError("capability is required")
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    return {"capability": capability, "payload": dict(payload)}


def _parse_envelope(raw: str | None) -> tuple[str, dict[str, Any]]:
    if not raw:
        raise InvalidAuditStateError("approved row has no proposed_change_json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidAuditStateError("proposed_change_json is not valid JSON") from exc
    if not isinstance(data, dict):
        raise InvalidAuditStateError("proposed_change_json must be a JSON object")
    capability = data.get("capability")
    payload = data.get("payload")
    if not capability or not isinstance(payload, dict):
        raise InvalidAuditStateError(
            "proposed_change_json must contain 'capability' and object 'payload'"
        )
    return str(capability), payload


def propose(
    conn: sqlite3.Connection,
    *,
    external_system: str,
    capability: str,
    payload: Mapping[str, Any],
    actor: str = "system",
    action_id: str | None = None,
    external_ref: str | None = None,
    reasoning: str | None = None,
    evidence_ids: Sequence[str] = (),
) -> AuditLog:
    """Record a proposed external write. Status starts at ``PENDING``."""
    actor = _require_actor(actor)
    envelope = _envelope(capability=capability, payload=payload)
    row = upsert_audit_log(
        conn,
        AuditLog(
            actor=actor,
            event=AuditEvent.PROPOSE_EXTERNAL_WRITE,
            external_system=external_system,
            external_ref=external_ref,
            action_id=action_id,
            reasoning=reasoning,
            proposed_change_json=_dumps(envelope),
            approval_status=ApprovalStatus.PENDING,
        ),
    )
    for evidence_id in evidence_ids:
        add_audit_log_evidence(conn, row.id, evidence_id)
    return row


def approve(conn: sqlite3.Connection, audit_id: str) -> AuditLog:
    """Mark a pending proposal ``APPROVED`` and stamp ``approved_at``."""
    row = _get_row(conn, audit_id)
    if _status(row) != ApprovalStatus.PENDING:
        raise InvalidAuditStateError(
            f"audit_log {audit_id!r} cannot be approved "
            f"(status={_status(row)})"
        )
    return upsert_audit_log(
        conn,
        row.model_copy(
            update={
                "event": AuditEvent.APPROVE,
                "approval_status": ApprovalStatus.APPROVED,
                "approved_at": utcnow(),
            }
        ),
    )


def reject(conn: sqlite3.Connection, audit_id: str) -> AuditLog:
    """Mark a pending proposal ``REJECTED``. No external write will run."""
    row = _get_row(conn, audit_id)
    if _status(row) != ApprovalStatus.PENDING:
        raise InvalidAuditStateError(
            f"audit_log {audit_id!r} cannot be rejected "
            f"(status={_status(row)})"
        )
    return upsert_audit_log(
        conn,
        row.model_copy(
            update={
                "event": AuditEvent.REJECT,
                "approval_status": ApprovalStatus.REJECTED,
            }
        ),
    )


def execute_approved(
    conn: sqlite3.Connection,
    audit_id: str,
    *,
    writer: ExternalWriter | None = None,
) -> AuditLog:
    """Invoke the injected writer iff the row is ``APPROVED``.

    Never imports or calls a real connector. On writer success the row becomes
    ``EXECUTED``; on writer exception it becomes ``FAILED`` and
    ``AuditExecutionError`` is raised. Missing / non-APPROVED rows refuse
    before the writer is called.
    """
    row = _get_row(conn, audit_id)
    status = _status(row)
    if status != ApprovalStatus.APPROVED:
        raise ApprovalRequiredError(
            f"execute_approved refuses audit_id={audit_id!r}: "
            f"approval_status must be APPROVED, got {status}"
        )

    callback = writer if writer is not None else get_writer()
    if callback is None:
        raise WriterNotConfiguredError(
            f"execute_approved has no writer for audit_id={audit_id!r}"
        )

    capability, payload = _parse_envelope(row.proposed_change_json)
    now = utcnow()
    try:
        result = callback(capability, payload, audit_id=audit_id)
    except Exception as exc:
        upsert_audit_log(
            conn,
            row.model_copy(
                update={
                    "event": AuditEvent.EXECUTE,
                    "approval_status": ApprovalStatus.FAILED,
                    "executed_at": now,
                    "result_json": _dumps(
                        {
                            "ok": False,
                            "error": str(exc),
                            "type": type(exc).__name__,
                        }
                    ),
                }
            ),
        )
        raise AuditExecutionError(
            f"writer failed for audit_id={audit_id!r}: {exc}"
        ) from exc

    result_payload: dict[str, Any]
    if result is None:
        result_payload = {"ok": True}
    elif isinstance(result, Mapping):
        result_payload = dict(result)
        result_payload.setdefault("ok", True)
    else:
        result_payload = {"ok": True, "result": result}

    return upsert_audit_log(
        conn,
        row.model_copy(
            update={
                "event": AuditEvent.EXECUTE,
                "approval_status": ApprovalStatus.EXECUTED,
                "executed_at": now,
                "result_json": _dumps(result_payload),
            }
        ),
    )


def record_config_change(
    conn: sqlite3.Connection,
    *,
    change: Mapping[str, Any],
    actor: str = "user",
    reasoning: str | None = None,
    external_ref: str | None = None,
) -> AuditLog:
    """Record a local config edit (weights, mappings). No approval required."""
    actor = _require_actor(actor)
    if not isinstance(change, Mapping):
        raise TypeError("change must be a mapping")
    return upsert_audit_log(
        conn,
        AuditLog(
            actor=actor,
            event=AuditEvent.CONFIG_CHANGE,
            external_ref=external_ref,
            reasoning=reasoning,
            proposed_change_json=_dumps(dict(change)),
            approval_status=ApprovalStatus.NOT_REQUIRED,
        ),
    )
