"""Fictional seed rows for ``seeded_db``. Companies: Acme, Beta Corp, Gamma, Delta.

Contact emails use ``@<company>-example.test`` domains only. No real customer,
colleague, or company names. Clock for all timestamps: 2026-09-14T08:00:00Z
(the ``frozen_now`` instant).
"""

from __future__ import annotations

import sqlite3

NOW = "2026-09-14T08:00:00Z"
# Civil dates in Europe/London relative to frozen_now (09:00 BST on 14 Sep 2026).
CLOSE_IN_FOUR_DAYS = "2026-09-18"
DUE_YESTERDAY = "2026-09-13"
LAST_ACTIVITY_NINE_DAYS_AGO = "2026-09-05T08:00:00Z"
MEETING_ACME_START = "2026-09-14T09:30:00Z"  # 10:30 Europe/London
MEETING_BETA_START = "2026-09-14T13:00:00Z"  # 14:00 Europe/London

COMPANY_NAMES = ("Acme", "Beta Corp", "Gamma", "Delta")


def seed_fictional(conn: sqlite3.Connection) -> None:
    """Insert the canonical fictional dataset. Caller owns the connection."""
    _companies(conn)
    _contacts(conn)
    _deals(conn)
    _evidence(conn)
    _memories(conn)
    _meetings(conn)
    _actions(conn)
    conn.commit()


def _companies(conn: sqlite3.Connection) -> None:
    rows = [
        ("co_acme", "Acme", "acme", "acme-example.test", 1),
        ("co_beta", "Beta Corp", "beta", "beta-example.test", 0),
        ("co_gamma", "Gamma", "gamma", "gamma-example.test", 0),
        ("co_delta", "Delta", "delta", "delta-example.test", 0),
    ]
    conn.executemany(
        """INSERT INTO companies(id, name, normalised_name, primary_domain, is_strategic, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(i, n, nn, d, s, NOW, NOW) for i, n, nn, d, s in rows],
    )
    aliases = [
        ("al_acme_domain", "co_acme", "DOMAIN", "acme-example.test", "HUBSPOT"),
        ("al_beta_domain", "co_beta", "DOMAIN", "beta-example.test", "HUBSPOT"),
        ("al_gamma_domain", "co_gamma", "DOMAIN", "gamma-example.test", "HUBSPOT"),
        ("al_delta_domain", "co_delta", "DOMAIN", "delta-example.test", "EXCEL"),
        ("al_beta_name", "co_beta", "NAME", "beta", "HUBSPOT"),
    ]
    conn.executemany(
        """INSERT INTO company_aliases(id, company_id, alias_type, value, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(*row, NOW) for row in aliases],
    )


def _contacts(conn: sqlite3.Connection) -> None:
    rows = [
        ("ct_ada", "co_acme", "Ada", "Example", "Ada Example", "ada@acme-example.test", "Champion", "CHAMPION"),
        ("ct_ben", "co_beta", "Ben", "Tester", "Ben Tester", "ben@beta-example.test", "Buyer", "DECISION_MAKER"),
        ("ct_gina", "co_gamma", "Gina", "Sample", "Gina Sample", "gina@gamma-example.test", "Procurement", "PROCUREMENT"),
        ("ct_dan", "co_delta", "Dan", "Demo", "Dan Demo", "dan@delta-example.test", "Owner", "OTHER"),
    ]
    conn.executemany(
        """INSERT INTO contacts(id, company_id, first_name, last_name, full_name, email, title, role_in_deal, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(*row, NOW, NOW) for row in rows],
    )


def _deals(conn: sqlite3.Connection) -> None:
    # Both products: XODO_SIGN (HubSpot) and PRODUCT_B (Excel). Acme has one of each
    # so later matcher tests can exercise "which deal?" without extra seed work.
    deals = [
        (
            "dl_acme_sign", "hs-acme-sign", "HUBSPOT", "XODO_SIGN", "Acme — Xodo Sign",
            "co_acme", "Acme", 75000.0, "GBP", 75000.0, "Proposal", "proposal", 0, None,
            CLOSE_IN_FOUR_DAYS, LAST_ACTIVITY_NINE_DAYS_AGO, "HIGH", 82.4,
        ),
        (
            "dl_acme_b", "xl-acme-b", "EXCEL", "PRODUCT_B", "Acme — Product B",
            "co_acme", "Acme", 20000.0, "GBP", 20000.0, "Discovery", "discovery", 0, None,
            "2026-10-30", NOW, "LOW", 20.0,
        ),
        (
            "dl_beta_sign", "hs-beta-sign", "HUBSPOT", "XODO_SIGN", "Beta Corp — Xodo Sign",
            "co_beta", "Beta Corp", 42000.0, "GBP", 42000.0, "Negotiation", "negotiation", 0, None,
            "2026-09-21", "2026-09-10T08:00:00Z", "HIGH", 74.0,
        ),
        (
            "dl_gamma_sign", "hs-gamma-sign", "HUBSPOT", "XODO_SIGN", "Gamma — Xodo Sign",
            "co_gamma", "Gamma", 28000.0, "GBP", 28000.0, "Negotiation", "negotiation", 0, None,
            "2026-10-15", "2026-09-14T07:55:00Z", "MEDIUM", 50.0,
        ),
        (
            "dl_delta_b", "xl-delta-b", "EXCEL", "PRODUCT_B", "Delta — Product B",
            "co_delta", "Delta", 15000.0, "GBP", 15000.0, "Proposal", "proposal", 0, None,
            "2026-10-15", "2026-09-01T08:00:00Z", "MEDIUM", 40.0,
        ),
    ]
    conn.executemany(
        """INSERT INTO deals(
               id, external_id, source, product, name, company_id, company_name,
               deal_value, currency, deal_value_gbp, stage, stage_key, is_closed, is_won,
               close_date, last_activity_at, attention_status, priority_score,
               first_seen_at, last_seen_at, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(*row, NOW, NOW, NOW, NOW) for row in deals],
    )
    conn.execute(
        """INSERT INTO deal_changes(id, deal_id, field, old_value, new_value, changed_at)
           VALUES ('dc_gamma_stage', 'dl_gamma_sign', 'stage', 'Proposal', 'Negotiation', ?)""",
        ("2026-09-14T07:55:00Z",),
    )
    conn.execute(
        """INSERT INTO deal_changes(id, deal_id, field, old_value, new_value, changed_at)
           VALUES ('dc_delta_close', 'dl_delta_b', 'close_date', '2026-09-30', '2026-10-15', ?)""",
        ("2026-09-13T12:00:00Z",),
    )


def _evidence(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO evidence(
               id, type, source, source_id, company_id, deal_id, contact_id,
               occurred_at, direction, title, content, extraction_status, created_at
           ) VALUES (
               'ev_acme_email', 'EMAIL', 'email_files', '<msg-acme-pricing>',
               'co_acme', 'dl_acme_sign', 'ct_ada', ?, 'INBOUND',
               'Re: pricing',
               'Thanks. I will send the revised pricing tomorrow. We are reviewing internally with procurement.',
               'DONE', ?
           )""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO evidence(
               id, type, source, source_id, company_id, deal_id,
               occurred_at, direction, title, content, extraction_status, created_at
           ) VALUES (
               'ev_acme_zoom', 'ZOOM_TRANSCRIPT', 'transcripts', 'acme-2026-09-13',
               'co_acme', 'dl_acme_sign', ?, 'UNKNOWN',
               'Acme call',
               'Ada Example: We received the pricing and are reviewing internally with procurement.',
               'PENDING', ?
           )""",
        ("2026-09-13T14:00:00Z", NOW),
    )


def _memories(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO memories(
               id, type, basis, status, subject, content, company_id, contact_id, deal_id,
               direction, owner_label, due_date, due_text, confidence, valid_from,
               created_by, created_at, updated_at
           ) VALUES (
               'mem_acme_pricing', 'COMMITMENT', 'OBSERVED', 'ACTIVE', 'Revised pricing',
               'Send revised pricing to Acme.', 'co_acme', 'ct_ada', 'dl_acme_sign',
               'USER_TO_CUSTOMER', 'me', ?, 'tomorrow', 0.85, ?,
               'rules', ?, ?
           )""",
        (DUE_YESTERDAY, NOW, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO memory_evidence(memory_id, evidence_id, quote, relation, created_at)
           VALUES ('mem_acme_pricing', 'ev_acme_email', 'I will send the revised pricing tomorrow.', 'SUPPORTS', ?)""",
        (NOW,),
    )
    conn.execute(
        """INSERT INTO memories(
               id, type, basis, status, subject, content, company_id, deal_id,
               confidence, valid_from, created_by, created_at, updated_at
           ) VALUES (
               'mem_gamma_state', 'DEAL_STATE', 'OBSERVED', 'ACTIVE', 'Moved to negotiation',
               'Gamma deal stage moved from Proposal to Negotiation.', 'co_gamma', 'dl_gamma_sign',
               0.7, ?, 'rules', ?, ?
           )""",
        (NOW, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO memories(
               id, type, basis, status, subject, content, company_id, contact_id, deal_id,
               confidence, valid_from, created_by, created_at, updated_at
           ) VALUES (
               'mem_beta_signal', 'BUYING_SIGNAL', 'OBSERVED', 'ACTIVE', 'Pricing review booked',
               'Beta Corp booked a pricing review meeting.', 'co_beta', 'ct_ben', 'dl_beta_sign',
               0.65, ?, 'rules', ?, ?
           )""",
        (NOW, NOW, NOW),
    )


def _meetings(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO meetings(
               id, source, external_id, title, event_type, start_at, duration_minutes, status,
               company_id, deal_id, contact_id, invitees_json, created_at, updated_at
           ) VALUES (
               'mt_acme_followup', 'CALENDLY', 'cal-acme-1', 'Acme — Discovery follow-up',
               'discovery', ?, 30, 'SCHEDULED', 'co_acme', 'dl_acme_sign', 'ct_ada',
               '[{"name":"Ada Example","email":"ada@acme-example.test"}]', ?, ?
           )""",
        (MEETING_ACME_START, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO meetings(
               id, source, external_id, title, event_type, start_at, duration_minutes, status,
               company_id, deal_id, contact_id, invitees_json, created_at, updated_at
           ) VALUES (
               'mt_beta_pricing', 'CALENDLY', 'cal-beta-1', 'Beta Corp — Pricing review',
               'pricing', ?, 45, 'SCHEDULED', 'co_beta', 'dl_beta_sign', 'ct_ben',
               '[{"name":"Ben Tester","email":"ben@beta-example.test"}]', ?, ?
           )""",
        (MEETING_BETA_START, NOW, NOW),
    )


def _actions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO actions(
               id, title, type, tier, status, source, source_id, origin_memory_id,
               company_id, deal_id, contact_id, due_date, priority_score, created_at, updated_at
           ) VALUES (
               'ac_acme_pricing', 'Send revised pricing', 'COMMITMENT', 1, 'OPEN',
               'memory', 'mem_acme_pricing', 'mem_acme_pricing',
               'co_acme', 'dl_acme_sign', 'ct_ada', ?, 86.2, ?, ?
           )""",
        (DUE_YESTERDAY, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO actions(
               id, title, type, tier, status, source, source_id, meeting_id,
               company_id, deal_id, contact_id, due_date, priority_score, created_at, updated_at
           ) VALUES (
               'ac_acme_prep', 'Prepare for Acme 10:30', 'MEETING_PREP', 1, 'OPEN',
               'calendly', 'mt_acme_followup', 'mt_acme_followup',
               'co_acme', 'dl_acme_sign', 'ct_ada', '2026-09-14', 80.0, ?, ?
           )""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO actions(
               id, title, type, tier, status, source, source_id,
               company_id, deal_id, due_date, priority_score, created_at, updated_at
           ) VALUES (
               'ac_gamma_follow', 'Check Gamma negotiation next step', 'EMAIL_FOLLOWUP', 2, 'OPEN',
               'rules', 'dl_gamma_sign-followup',
               'co_gamma', 'dl_gamma_sign', '2026-09-15', 45.0, ?, ?
           )""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO prospecting_items(
               id, row_key, sheet_row_number, due_date, priority, company_name, contact_name,
               step, subject, done, first_seen_at, last_seen_at, created_at, updated_at
           ) VALUES (
               'pr_zeta', 'seq-1|zeta example|zee example|intro', 12, '2026-09-16', 'B',
               'Zeta Example', 'Zee Example', 'Intro email', 'Intro to Zeta Example',
               0, ?, ?, ?, ?
           )""",
        (NOW, NOW, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO actions(
               id, title, type, tier, status, source, source_id, due_date, priority_score,
               created_at, updated_at
           ) VALUES (
               'ac_zeta_intro', 'Intro email — Zeta Example', 'PROSPECTING', 3, 'OPEN',
               'google_sheets', 'seq-1|zeta example|zee example|intro', '2026-09-16', 10.0, ?, ?
           )""",
        (NOW, NOW),
    )
    conn.execute(
        "UPDATE meetings SET followup_action_id = 'ac_acme_prep' WHERE id = 'mt_acme_followup'"
    )
    conn.execute(
        """INSERT INTO action_evidence(action_id, evidence_id)
           VALUES ('ac_acme_pricing', 'ev_acme_email')"""
    )
