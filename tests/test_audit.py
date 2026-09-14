"""Approval gate (SOS-06): propose / approve / reject / execute / config_change.

Fictional fixtures only (Acme, hs-task-acme-1). The injected writer is a stub —
no HubSpot or other connector is imported or called.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from core.audit import (
    ApprovalRequiredError,
    AuditEvent,
    AuditExecutionError,
    AuditNotFoundError,
    InvalidAuditStateError,
    WriterNotConfiguredError,
    approve,
    execute_approved,
    propose,
    record_config_change,
    reject,
    set_writer,
)
from core.models import ApprovalStatus, get_audit_log, list_audit_log_evidence

NOW = "2026-09-14T08:00:00Z"

ACME_PAYLOAD = {
    "task_id": "hs-task-acme-1",
    "hs_task_status": "COMPLETED",
}


class StubWriter:
    """Minimal injectable callback. Never talks to HubSpot."""

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result if result is not None else {"written": True, "stub": True}
        self.error = error

    def __call__(
        self, capability: str, payload: dict[str, Any], *, audit_id: str
    ) -> dict[str, Any]:
        self.calls.append(
            {"capability": capability, "payload": payload, "audit_id": audit_id}
        )
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def _clear_default_writer():
    set_writer(None)
    yield
    set_writer(None)


def _propose_acme(db, **overrides):
    kwargs = {
        "external_system": "HUBSPOT",
        "capability": "complete_task",
        "payload": ACME_PAYLOAD,
        "actor": "system",
        "external_ref": "hs-task-acme-1",
        "reasoning": "Mark the Acme follow-up task complete after revised pricing was sent.",
    }
    kwargs.update(overrides)
    return propose(db, **kwargs)


def test_happy_path_propose_approve_execute(db, frozen_now):
    writer = StubWriter(result={"written": True, "task_id": "hs-task-acme-1"})
    proposed = _propose_acme(db)

    assert proposed.event == AuditEvent.PROPOSE_EXTERNAL_WRITE
    assert proposed.approval_status == ApprovalStatus.PENDING
    assert proposed.approved_at is None
    assert proposed.executed_at is None
    envelope = json.loads(proposed.proposed_change_json)
    assert envelope["capability"] == "complete_task"
    assert envelope["payload"] == ACME_PAYLOAD
    assert proposed.timestamp == NOW
    assert proposed.external_system == "HUBSPOT"
    assert proposed.external_ref == "hs-task-acme-1"

    approved = approve(db, proposed.id)
    assert approved.id == proposed.id
    assert approved.event == AuditEvent.APPROVE
    assert approved.approval_status == ApprovalStatus.APPROVED
    assert approved.approved_at == NOW
    assert json.loads(approved.proposed_change_json)["payload"] == ACME_PAYLOAD

    executed = execute_approved(db, proposed.id, writer=writer)
    assert executed.id == proposed.id
    assert executed.event == AuditEvent.EXECUTE
    assert executed.approval_status == ApprovalStatus.EXECUTED
    assert executed.executed_at == NOW
    result = json.loads(executed.result_json)
    assert result["ok"] is True
    assert result["written"] is True

    assert len(writer.calls) == 1
    call = writer.calls[0]
    assert call["capability"] == "complete_task"
    assert call["payload"] == ACME_PAYLOAD
    assert call["audit_id"] == proposed.id


def test_reject_records_rejected_and_blocks_execute(db, frozen_now):
    writer = StubWriter()
    proposed = _propose_acme(db)
    rejected = reject(db, proposed.id)

    assert rejected.event == AuditEvent.REJECT
    assert rejected.approval_status == ApprovalStatus.REJECTED
    assert rejected.approved_at is None

    with pytest.raises(ApprovalRequiredError, match="APPROVED"):
        execute_approved(db, proposed.id, writer=writer)
    assert writer.calls == []
    assert get_audit_log(db, proposed.id).approval_status == ApprovalStatus.REJECTED


@pytest.mark.parametrize(
    "setup",
    ["missing", "pending", "rejected", "config", "executed"],
)
def test_execute_approved_refuses_without_approved(db, frozen_now, setup):
    writer = StubWriter()

    if setup == "missing":
        audit_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"  # well-formed ULID, not in DB
        with pytest.raises(AuditNotFoundError, match=audit_id):
            execute_approved(db, audit_id, writer=writer)
        assert writer.calls == []
        return

    if setup == "pending":
        audit_id = _propose_acme(db).id
        match = "PENDING"
    elif setup == "rejected":
        row = _propose_acme(db)
        reject(db, row.id)
        audit_id = row.id
        match = "REJECTED"
    elif setup == "config":
        row = record_config_change(
            db,
            change={"file": "priority_weights.yaml", "field": "staleness_half_life_days"},
            reasoning="Acme scoring preview: lower staleness half-life.",
            external_ref="priority_weights.yaml",
        )
        audit_id = row.id
        match = "NOT_REQUIRED"
    else:
        row = _propose_acme(db)
        approve(db, row.id)
        execute_approved(db, row.id, writer=StubWriter())
        audit_id = row.id
        match = "EXECUTED"
        writer = StubWriter()

    with pytest.raises(ApprovalRequiredError, match="APPROVED"):
        execute_approved(db, audit_id, writer=writer)
    with pytest.raises(ApprovalRequiredError, match=match):
        execute_approved(db, audit_id, writer=writer)
    assert writer.calls == []


def test_execute_without_writer_leaves_approved(db, frozen_now):
    row = _propose_acme(db)
    approve(db, row.id)
    with pytest.raises(WriterNotConfiguredError):
        execute_approved(db, row.id)
    stored = get_audit_log(db, row.id)
    assert stored.approval_status == ApprovalStatus.APPROVED
    assert stored.executed_at is None


def test_execute_writer_failure_marks_failed(db, frozen_now):
    writer = StubWriter(error=RuntimeError("stub HubSpot 429"))
    row = _propose_acme(db)
    approve(db, row.id)

    with pytest.raises(AuditExecutionError, match="stub HubSpot 429"):
        execute_approved(db, row.id, writer=writer)

    stored = get_audit_log(db, row.id)
    assert stored.event == AuditEvent.EXECUTE
    assert stored.approval_status == ApprovalStatus.FAILED
    assert stored.executed_at == NOW
    result = json.loads(stored.result_json)
    assert result["ok"] is False
    assert result["type"] == "RuntimeError"
    assert "429" in result["error"]
    assert len(writer.calls) == 1


def test_cannot_approve_or_reject_non_pending(db, frozen_now):
    row = _propose_acme(db)
    approve(db, row.id)
    with pytest.raises(InvalidAuditStateError, match="cannot be approved"):
        approve(db, row.id)
    with pytest.raises(InvalidAuditStateError, match="cannot be rejected"):
        reject(db, row.id)

    pending = _propose_acme(db)
    reject(db, pending.id)
    with pytest.raises(InvalidAuditStateError, match="cannot be approved"):
        approve(db, pending.id)


def test_approve_and_reject_unknown_id(db):
    missing = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    with pytest.raises(AuditNotFoundError):
        approve(db, missing)
    with pytest.raises(AuditNotFoundError):
        reject(db, missing)


def test_record_config_change_not_required(db, frozen_now):
    row = record_config_change(
        db,
        change={
            "file": "priority_weights.yaml",
            "before": {"deal_value": 0.25},
            "after": {"deal_value": 0.30},
        },
        reasoning="Settings form save for Acme scoring weights preview.",
        external_ref="priority_weights.yaml",
        actor="user",
    )
    assert row.event == AuditEvent.CONFIG_CHANGE
    assert row.approval_status == ApprovalStatus.NOT_REQUIRED
    assert row.timestamp == NOW
    assert row.actor == "user"
    stored = json.loads(row.proposed_change_json)
    assert stored["file"] == "priority_weights.yaml"
    assert stored["after"]["deal_value"] == 0.30


def test_propose_links_evidence_from_seed(seeded_db, frozen_now):
    row = _propose_acme(seeded_db, evidence_ids=["ev_acme_email"], action_id="ac_acme_pricing")
    links = list_audit_log_evidence(seeded_db, audit_id=row.id)
    assert [link.evidence_id for link in links] == ["ev_acme_email"]
    assert row.action_id == "ac_acme_pricing"


def test_set_writer_default_is_used(db, frozen_now):
    writer = StubWriter(result={"via": "default"})
    set_writer(writer)
    row = _propose_acme(db)
    approve(db, row.id)
    executed = execute_approved(db, row.id)
    assert json.loads(executed.result_json)["via"] == "default"
    assert writer.calls[0]["audit_id"] == row.id


def test_audit_package_does_not_import_connectors():
    """ADR-005: core.audit must not import connectors (direct or transitive).

    Do not inspect this process's ``sys.modules`` — SOS-07 tests already load
    ``connectors.*`` and would false-fail a polluted session.
    """
    repo = Path(__file__).resolve().parents[1]
    audit_dir = repo / "core" / "audit"
    leaked_direct: list[str] = []
    for path in sorted(audit_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "connectors" or alias.name.startswith("connectors."):
                        leaked_direct.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "connectors" or node.module.startswith("connectors."):
                    leaked_direct.append(f"{path.name}: from {node.module}")
    assert leaked_direct == []

    script = (
        "import sys, core.audit; "
        "leaked = [n for n in sys.modules "
        "if n == 'connectors' or n.startswith('connectors.')]; "
        "sys.stderr.write(','.join(leaked)); "
        "raise SystemExit(2 if leaked else 0)"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo), env["PYTHONPATH"]] if env.get("PYTHONPATH") else [str(repo)]
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "core.audit loaded connectors in a clean interpreter: "
        f"{result.stderr or result.stdout}"
    )
