"""Smoke tests for the SOS-06c shared fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database.db import table_names
from tests.fakes import SOURCE_TEXT, VARIANTS
from tests.seed import COMPANY_NAMES

EXPECTED_CORE_TABLES = {
    "companies",
    "contacts",
    "deals",
    "evidence",
    "memories",
    "actions",
    "meetings",
    "schema_migrations",
}

FORBIDDEN_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "yahoo.co.uk",
    "icloud.com",
    "hubspot.com",
    "microsoft.com",
    "google.com",
}


def test_db_has_migrated_tables(db):
    names = set(table_names(db))
    missing = EXPECTED_CORE_TABLES - names
    assert not missing, f"migrations did not create tables: {missing}"
    versions = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
    assert 1 in versions
    applied = db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
    assert applied >= 1


def test_seeded_db_has_four_fictional_companies(seeded_db):
    names = [row["name"] for row in seeded_db.execute("SELECT name FROM companies ORDER BY name")]
    assert set(names) == set(COMPANY_NAMES)
    assert len(names) == 4

    domains = [
        row["primary_domain"]
        for row in seeded_db.execute("SELECT primary_domain FROM companies")
    ]
    assert all(d and d.endswith(".test") for d in domains)
    assert {d.split(".")[0] for d in domains} == {
        "acme-example",
        "beta-example",
        "gamma-example",
        "delta-example",
    }

    emails = [
        row["email"]
        for row in seeded_db.execute("SELECT email FROM contacts WHERE email IS NOT NULL")
    ]
    assert emails
    assert all(e.endswith(".test") for e in emails)
    for email in emails:
        domain = email.rsplit("@", 1)[1].lower()
        assert domain not in FORBIDDEN_EMAIL_DOMAINS
        assert domain.endswith("-example.test")

    products = {
        row["product"] for row in seeded_db.execute("SELECT DISTINCT product FROM deals")
    }
    assert products == {"XODO_SIGN", "PRODUCT_B"}

    assert seeded_db.execute("SELECT count(*) FROM memories").fetchone()[0] >= 1
    assert seeded_db.execute("SELECT count(*) FROM meetings").fetchone()[0] >= 1
    assert seeded_db.execute("SELECT count(*) FROM actions").fetchone()[0] >= 1


def test_frozen_now_is_expected_instant(frozen_now):
    assert frozen_now == datetime(2026, 9, 14, 8, 0, 0, tzinfo=timezone.utc)
    london = frozen_now.astimezone(ZoneInfo("Europe/London"))
    assert london.year == 2026
    assert london.month == 9
    assert london.day == 14
    assert london.hour == 9
    assert london.minute == 0
    assert datetime.now(timezone.utc) == frozen_now


def test_fake_provider_valid_and_invalid_variants(fake_provider):
    valid = fake_provider.payload("extract_memory", "valid")
    assert valid["items"]
    quote = valid["items"][0]["quote"]
    assert quote in SOURCE_TEXT

    invalid = fake_provider.payload("extract_memory", "schema-invalid")
    item = invalid["items"][0]
    assert "quote" not in item or item.get("type") == "NOT_A_TYPE"

    hallucinated = fake_provider.payload("extract_memory", "hallucinated-quote")
    bad_quote = hallucinated["items"][0]["quote"]
    assert bad_quote not in SOURCE_TEXT

    uncited = fake_provider.payload("generate_deal_summary", "uncited-summary-sentence")
    cites = [cite for sentence in uncited["sentences"] for cite in sentence["cites"]]
    assert "not-a-supplied-id" in cites

    via_complete = fake_provider.complete_json(purpose="extract_actions", variant="valid")
    assert via_complete["items"][0]["title"]

    assert set(VARIANTS) <= {
        "valid",
        "schema-invalid",
        "hallucinated-quote",
        "uncited-summary-sentence",
    }
