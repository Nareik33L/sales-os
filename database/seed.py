"""Fictional demo dataset. Never insert real customer data.

Companies: Acme, Beta Corp, Gamma, Delta. Clock frozen at 2026-09-14T08:00:00Z
so SOS-06c's seeded_db fixture can reuse these rows.
"""

from __future__ import annotations

import sqlite3

DEMO_NOW = "2026-09-14T08:00:00Z"
DEMO_TODAY = "2026-09-14"
SETTINGS_KEY = "demo_seeded"

COMPANY_NAMES = ("Acme", "Beta Corp", "Gamma", "Delta")


def _exec(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    conn.execute(sql, params)


def seed_demo(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert fictional rows. Idempotent (stable demo-* ids, INSERT OR IGNORE).

    Returns a map of table -> row count after seeding.
    """
    now = DEMO_NOW

    companies = [
        ("demo-company-acme", "Acme", "acme", "acme-example.test", 1),
        ("demo-company-beta", "Beta Corp", "beta", "beta-example.test", 0),
        ("demo-company-gamma", "Gamma", "gamma", "gamma-example.test", 0),
        ("demo-company-delta", "Delta", "delta", "delta-example.test", 0),
    ]
    for cid, name, normalised, domain, strategic in companies:
        _exec(
            conn,
            """INSERT OR IGNORE INTO companies(
                   id, name, normalised_name, primary_domain, is_strategic, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, name, normalised, domain, strategic, now, now),
        )
        _exec(
            conn,
            """INSERT OR IGNORE INTO company_aliases(
                   id, company_id, alias_type, value, source, created_at
               ) VALUES (?, ?, 'DOMAIN', ?, 'USER', ?)""",
            (f"demo-alias-{cid.removeprefix('demo-company-')}", cid, domain, now),
        )

    contacts = [
        (
            "demo-contact-acme",
            "demo-company-acme",
            "Avery",
            "Pike",
            "Avery Pike",
            "avery.pike@acme-example.test",
            "DECISION_MAKER",
        ),
        (
            "demo-contact-beta",
            "demo-company-beta",
            "Morgan",
            "Ellison",
            "Morgan Ellison",
            "morgan.ellison@beta-example.test",
            "PROCUREMENT",
        ),
        (
            "demo-contact-gamma",
            "demo-company-gamma",
            "Riley",
            "Cho",
            "Riley Cho",
            "riley.cho@gamma-example.test",
            "CHAMPION",
        ),
        (
            "demo-contact-delta",
            "demo-company-delta",
            "Quinn",
            "Marsh",
            "Quinn Marsh",
            "quinn.marsh@delta-example.test",
            "OTHER",
        ),
    ]
    for row in contacts:
        cid, company_id, first, last, full, email, role = row
        _exec(
            conn,
            """INSERT OR IGNORE INTO contacts(
                   id, company_id, first_name, last_name, full_name, email, role_in_deal,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, company_id, first, last, full, email, role, now, now),
        )

    # Acme matches the doc 03 worked example: £75k, close in 4 days, last activity 9 days ago.
    deals = [
        (
            "demo-deal-acme-xodo",
            "demo-hs-acme-xodo",
            "HUBSPOT",
            "XODO_SIGN",
            "Acme — Xodo Sign",
            "demo-company-acme",
            "Acme",
            75000.0,
            "2026-09-18",
            "2026-09-05T10:00:00Z",
            "Proposal",
        ),
        (
            "demo-deal-beta-product-b",
            "demo-excel-beta-product-b",
            "EXCEL",
            "PRODUCT_B",
            "Beta Corp — Product B rollout",
            "demo-company-beta",
            "Beta Corp",
            42000.0,
            "2026-10-01",
            "2026-09-10T09:00:00Z",
            "Negotiation",
        ),
        (
            "demo-deal-gamma-xodo",
            "demo-hs-gamma-xodo",
            "HUBSPOT",
            "XODO_SIGN",
            "Gamma — Xodo Sign trial",
            "demo-company-gamma",
            "Gamma",
            18000.0,
            "2026-11-15",
            "2026-09-12T16:00:00Z",
            "Qualified",
        ),
        (
            "demo-deal-delta-product-b",
            "demo-excel-delta-product-b",
            "EXCEL",
            "PRODUCT_B",
            "Delta — Product B renewal",
            "demo-company-delta",
            "Delta",
            9500.0,
            "2026-09-30",
            "2026-08-20T11:00:00Z",
            "Renewal",
        ),
    ]
    for row in deals:
        (
            did,
            external_id,
            source,
            product,
            name,
            company_id,
            company_name,
            value,
            close_date,
            last_activity,
            stage,
        ) = row
        _exec(
            conn,
            """INSERT OR IGNORE INTO deals(
                   id, external_id, source, product, name, company_id, company_name,
                   deal_value, currency, deal_value_gbp, stage, close_date, last_activity_at,
                   first_seen_at, last_seen_at, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'GBP', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                did,
                external_id,
                source,
                product,
                name,
                company_id,
                company_name,
                value,
                value,
                stage,
                close_date,
                last_activity,
                now,
                now,
                now,
                now,
            ),
        )

    _exec(
        conn,
        """INSERT OR IGNORE INTO deal_changes(
               id, deal_id, field, old_value, new_value, changed_at
           ) VALUES ('demo-change-beta-stage', 'demo-deal-beta-product-b',
                     'stage', 'Qualified', 'Negotiation', ?)""",
        (now,),
    )

    pricing_quote = "I will send the revised pricing tomorrow."
    _exec(
        conn,
        """INSERT OR IGNORE INTO evidence(
               id, type, source, source_id, company_id, deal_id, contact_id,
               occurred_at, direction, title, content, extraction_status, created_at
           ) VALUES (
               'demo-evidence-acme-email', 'EMAIL', 'email_files', 'demo-msg-acme-pricing',
               'demo-company-acme', 'demo-deal-acme-xodo', 'demo-contact-acme',
               '2026-09-12T17:30:00Z', 'OUTBOUND', 'Re: Acme pricing',
               ?, 'DONE', ?
           )""",
        (f"Hi Avery, {pricing_quote} Best, Sam.", now),
    )
    _exec(
        conn,
        """INSERT OR IGNORE INTO evidence(
               id, type, source, source_id, company_id, deal_id, contact_id,
               occurred_at, direction, title, content, extraction_status, created_at
           ) VALUES (
               'demo-evidence-gamma-call', 'ZOOM_TRANSCRIPT', 'transcripts', 'demo-vtt-gamma',
               'demo-company-gamma', 'demo-deal-gamma-xodo', 'demo-contact-gamma',
               '2026-09-12T16:00:00Z', 'UNKNOWN', 'Gamma intro call',
               'Riley: we want to roll this out to the whole team next quarter.',
               'DONE', ?
           )""",
        (now,),
    )

    _exec(
        conn,
        """INSERT OR IGNORE INTO memories(
               id, type, basis, status, subject, content, company_id, contact_id, deal_id,
               direction, owner_label, due_date, due_text, confidence, valid_from,
               created_by, created_at, updated_at
           ) VALUES (
               'demo-memory-acme-pricing', 'COMMITMENT', 'OBSERVED', 'ACTIVE',
               'Revised pricing', 'Send revised pricing to Acme',
               'demo-company-acme', 'demo-contact-acme', 'demo-deal-acme-xodo',
               'USER_TO_CUSTOMER', 'me', '2026-09-13', 'tomorrow', 0.85, ?,
               'demo', ?, ?
           )""",
        (now, now, now),
    )
    _exec(
        conn,
        """INSERT OR IGNORE INTO memory_evidence(
               memory_id, evidence_id, quote, relation, created_at
           ) VALUES (
               'demo-memory-acme-pricing', 'demo-evidence-acme-email', ?, 'SUPPORTS', ?
           )""",
        (pricing_quote, now),
    )
    _exec(
        conn,
        """INSERT OR IGNORE INTO memories(
               id, type, basis, status, subject, content, company_id, deal_id,
               confidence, valid_from, created_by, created_at, updated_at
           ) VALUES (
               'demo-memory-beta-budget', 'DEAL_STATE', 'OBSERVED', 'ACTIVE',
               'Budget approved', 'Beta Corp procurement approved the Product B budget.',
               'demo-company-beta', 'demo-deal-beta-product-b',
               0.7, ?, 'demo', ?, ?
           )""",
        (now, now, now),
    )
    _exec(
        conn,
        """INSERT OR IGNORE INTO memories(
               id, type, basis, status, subject, content, company_id, deal_id,
               confidence, valid_from, created_by, created_at, updated_at
           ) VALUES (
               'demo-memory-gamma-signal', 'BUYING_SIGNAL', 'OBSERVED', 'ACTIVE',
               'Team rollout', 'Gamma wants to roll Xodo Sign out to the whole team next quarter.',
               'demo-company-gamma', 'demo-deal-gamma-xodo',
               0.8, ?, 'demo', ?, ?
           )""",
        (now, now, now),
    )

    _exec(
        conn,
        """INSERT OR IGNORE INTO meetings(
               id, source, external_id, title, start_at, end_at, duration_minutes, status,
               company_id, deal_id, contact_id, created_at, updated_at
           ) VALUES (
               'demo-meeting-acme-held', 'CALENDLY', 'demo-cal-acme-held',
               'Acme pricing review', '2026-09-13T10:00:00Z', '2026-09-13T10:30:00Z', 30,
               'HELD', 'demo-company-acme', 'demo-deal-acme-xodo', 'demo-contact-acme', ?, ?
           )""",
        (now, now),
    )
    _exec(
        conn,
        """INSERT OR IGNORE INTO meetings(
               id, source, external_id, title, start_at, end_at, duration_minutes, status,
               company_id, deal_id, contact_id, created_at, updated_at
           ) VALUES (
               'demo-meeting-gamma-upcoming', 'CALENDLY', 'demo-cal-gamma-upcoming',
               'Gamma trial follow-up', '2026-09-15T09:00:00Z', '2026-09-15T09:30:00Z', 30,
               'SCHEDULED', 'demo-company-gamma', 'demo-deal-gamma-xodo',
               'demo-contact-gamma', ?, ?
           )""",
        (now, now),
    )

    actions = [
        (
            "demo-action-acme-pricing",
            "Send revised pricing to Acme",
            "COMMITMENT",
            1,
            "memory",
            "demo-memory-acme-pricing",
            "demo-company-acme",
            "demo-deal-acme-xodo",
            "demo-contact-acme",
            None,
            "2026-09-13",
        ),
        (
            "demo-action-acme-followup",
            "Follow up after Acme pricing review",
            "MEETING_FOLLOWUP",
            1,
            "calendly",
            "demo-cal-acme-held-followup",
            "demo-company-acme",
            "demo-deal-acme-xodo",
            "demo-contact-acme",
            "demo-meeting-acme-held",
            DEMO_TODAY,
        ),
        (
            "demo-action-beta-task",
            "Send Beta Corp Product B order form",
            "HUBSPOT_TASK",
            1,
            "hubspot",
            "demo-hs-task-beta",
            "demo-company-beta",
            "demo-deal-beta-product-b",
            "demo-contact-beta",
            None,
            "2026-09-16",
        ),
        (
            "demo-action-gamma-prep",
            "Prepare for Gamma trial follow-up",
            "MEETING_PREP",
            1,
            "calendly",
            "demo-cal-gamma-upcoming-prep",
            "demo-company-gamma",
            "demo-deal-gamma-xodo",
            "demo-contact-gamma",
            "demo-meeting-gamma-upcoming",
            "2026-09-15",
        ),
        (
            "demo-action-prospecting",
            "Intro email to Epsilon (fictional prospect)",
            "PROSPECTING",
            3,
            "google_sheets",
            "demo-sheet-epsilon-intro",
            None,
            None,
            None,
            None,
            "2026-09-17",
        ),
    ]
    for row in actions:
        (
            aid,
            title,
            atype,
            tier,
            source,
            source_id,
            company_id,
            deal_id,
            contact_id,
            meeting_id,
            due,
        ) = row
        _exec(
            conn,
            """INSERT OR IGNORE INTO actions(
                   id, title, type, tier, status, source, source_id, origin_memory_id,
                   company_id, deal_id, contact_id, meeting_id, due_date,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                aid,
                title,
                atype,
                tier,
                source,
                source_id,
                "demo-memory-acme-pricing" if atype == "COMMITMENT" else None,
                company_id,
                deal_id,
                contact_id,
                meeting_id,
                due,
                now,
                now,
            ),
        )

    _exec(
        conn,
        """UPDATE meetings SET followup_action_id = 'demo-action-acme-followup'
           WHERE id = 'demo-meeting-acme-held' AND followup_action_id IS NULL""",
    )

    _exec(
        conn,
        """INSERT OR IGNORE INTO prospecting_items(
               id, row_key, company_name, contact_name, step, subject, due_date,
               first_seen_at, last_seen_at, created_at, updated_at
           ) VALUES (
               'demo-prospect-epsilon', 'demo-sheet-epsilon-intro', 'Epsilon',
               'Jordan Hale', 'Intro email', 'Intro to Epsilon', '2026-09-17',
               ?, ?, ?, ?
           )""",
        (now, now, now, now),
    )

    _exec(
        conn,
        """INSERT OR REPLACE INTO settings(key, value_json, updated_at)
           VALUES (?, '{"seed": "fictional-demo"}', ?)""",
        (SETTINGS_KEY, now),
    )

    conn.commit()
    counts = {
        "companies": "SELECT count(*) FROM companies",
        "contacts": "SELECT count(*) FROM contacts",
        "deals": "SELECT count(*) FROM deals",
        "memories": "SELECT count(*) FROM memories",
        "meetings": "SELECT count(*) FROM meetings",
        "actions": "SELECT count(*) FROM actions",
        "evidence": "SELECT count(*) FROM evidence",
    }
    return {name: conn.execute(sql).fetchone()[0] for name, sql in counts.items()}
