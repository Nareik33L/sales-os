-- Sales OS — initial schema (V1)
-- SQLite. Applied by database/db.py. See docs/02-data-model.md for rationale.
--
-- Conventions
--   * ids are TEXT ULIDs generated in Python (sortable, no autoincrement coupling).
--   * timestamps are ISO-8601 UTC strings ("2026-09-14T08:42:00Z").
--   * dates (close_date, due_date) are ISO dates "YYYY-MM-DD" in the user's timezone.
--   * *_json columns hold JSON text; kept for flexible metadata only, never for
--     relationships that must be queried (those use link tables).
--   * enums are enforced with CHECK constraints so bad data fails loudly.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Entities
-- ---------------------------------------------------------------------------

CREATE TABLE companies (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    normalised_name     TEXT NOT NULL,                 -- lowercase, legal suffixes stripped; used for matching
    hubspot_id          TEXT UNIQUE,
    primary_domain      TEXT,
    industry            TEXT,
    is_strategic        INTEGER NOT NULL DEFAULT 0,    -- user-set flag; feeds prioritisation override
    notes               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_companies_normalised_name ON companies(normalised_name);
CREATE INDEX idx_companies_primary_domain ON companies(primary_domain);

-- Additional identifiers for a company: extra domains, name variants, Excel labels,
-- Calendly event names. Populated by connectors and by user confirmations in the
-- review queue. This is how matching "learns".
CREATE TABLE company_aliases (
    id                  TEXT PRIMARY KEY,
    company_id          TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    alias_type          TEXT NOT NULL CHECK (alias_type IN ('DOMAIN','NAME','EXCEL_LABEL','SHEET_LABEL','CALENDLY_LABEL','TRANSCRIPT_LABEL')),
    value               TEXT NOT NULL,                 -- stored normalised (lowercase, trimmed)
    source              TEXT NOT NULL,                 -- HUBSPOT | EXCEL | USER | MATCHER
    created_at          TEXT NOT NULL,
    UNIQUE (alias_type, value)
);
CREATE INDEX idx_company_aliases_company ON company_aliases(company_id);

CREATE TABLE contacts (
    id                  TEXT PRIMARY KEY,
    company_id          TEXT REFERENCES companies(id) ON DELETE SET NULL,
    hubspot_id          TEXT UNIQUE,
    first_name          TEXT,
    last_name           TEXT,
    full_name           TEXT NOT NULL,
    email               TEXT,                          -- lowercase
    phone               TEXT,
    title               TEXT,
    role_in_deal        TEXT,                          -- CHAMPION | DECISION_MAKER | PROCUREMENT | LEGAL | TECHNICAL | OTHER (free text, AI/user set)
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_contacts_email ON contacts(email) WHERE email IS NOT NULL;
CREATE INDEX idx_contacts_company ON contacts(company_id);

CREATE TABLE deals (
    id                  TEXT PRIMARY KEY,
    external_id         TEXT NOT NULL,                 -- HubSpot deal id, or Excel stable key (see excel_mapping.yaml)
    source              TEXT NOT NULL CHECK (source IN ('HUBSPOT','EXCEL','MANUAL')),
    product             TEXT NOT NULL,                 -- configured in config/sources.yaml (e.g. XODO_SIGN, PRODUCT_B)
    name                TEXT NOT NULL,
    company_id          TEXT REFERENCES companies(id) ON DELETE SET NULL,
    company_name        TEXT,                          -- denormalised copy from source; kept even if company_id is NULL
    deal_value          REAL,
    currency            TEXT NOT NULL DEFAULT 'GBP',
    deal_value_gbp      REAL,                          -- converted with config rates, for ranking only
    stage               TEXT,                          -- source's stage label (human readable)
    stage_key           TEXT,                          -- source's stage id
    is_closed           INTEGER NOT NULL DEFAULT 0,
    is_won              INTEGER,
    close_date          TEXT,                          -- ISO date
    owner               TEXT,
    last_activity_at    TEXT,                          -- max(source activity, local evidence) — see prioritisation doc for definition
    source_created_at   TEXT,
    source_updated_at   TEXT,
    summary             TEXT,                          -- "Current situation" — short, evidence-cited
    summary_updated_at  TEXT,
    summary_stale       INTEGER NOT NULL DEFAULT 1,    -- set when new evidence arrives; regenerated lazily
    attention_status    TEXT NOT NULL DEFAULT 'LOW' CHECK (attention_status IN ('HIGH','MEDIUM','LOW','NONE')),
    priority_score      REAL NOT NULL DEFAULT 0,
    priority_breakdown_json TEXT,                      -- {component: {score, weight, contribution, reason}} — powers "Why"
    priority_computed_at TEXT,
    user_pinned_rank    INTEGER,                       -- explicit override: force position in Today list
    user_boost          INTEGER NOT NULL DEFAULT 0,    -- cumulative ↑/↓ adjustments in points (bounded in config)
    source_record_json  TEXT,                          -- raw normalised source record for audit/debug
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,                 -- last sync where the record was present
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX idx_deals_company ON deals(company_id);
CREATE INDEX idx_deals_open_priority ON deals(is_closed, priority_score DESC);
CREATE INDEX idx_deals_close_date ON deals(close_date);

-- Field-level change history produced by connector diffs. Answers "what changed
-- since yesterday?" and drives "Recently changed deals" on Today.
CREATE TABLE deal_changes (
    id                  TEXT PRIMARY KEY,
    deal_id             TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    sync_run_id         TEXT REFERENCES sync_runs(id) ON DELETE SET NULL,
    field               TEXT NOT NULL,                 -- stage | close_date | deal_value | owner | is_closed | ...
    old_value           TEXT,
    new_value           TEXT,
    changed_at          TEXT NOT NULL
);
CREATE INDEX idx_deal_changes_deal_time ON deal_changes(deal_id, changed_at DESC);
CREATE INDEX idx_deal_changes_time ON deal_changes(changed_at DESC);

-- ---------------------------------------------------------------------------
-- Evidence — provenance for everything the brain believes
-- ---------------------------------------------------------------------------

CREATE TABLE evidence (
    id                  TEXT PRIMARY KEY,
    type                TEXT NOT NULL CHECK (type IN (
                            'EMAIL','ZOOM_TRANSCRIPT','HUBSPOT_ACTIVITY','HUBSPOT_DEAL','EXCEL_DEAL',
                            'PROSPECTING_ACTIVITY','CALENDLY_MEETING','TODO_TASK','USER_INPUT')),
    source              TEXT NOT NULL,                 -- connector name
    source_id           TEXT,                          -- external id if any (HubSpot engagement id, Calendly event uri, Message-ID)
    file_path           TEXT,                          -- data/processed/... for file-based evidence
    content_hash        TEXT,                          -- sha256 of raw content; dedupe
    company_id          TEXT REFERENCES companies(id) ON DELETE SET NULL,
    deal_id             TEXT REFERENCES deals(id) ON DELETE SET NULL,
    contact_id          TEXT REFERENCES contacts(id) ON DELETE SET NULL,
    match_confidence    REAL,                          -- 0..1 confidence of the company/deal association
    match_method        TEXT,                          -- EXTERNAL_ID | DOMAIN | ALIAS | CONTACT | NAME_FUZZY | CALENDAR | MEMORY | USER
    occurred_at         TEXT NOT NULL,                 -- when the thing happened (email sent, meeting held)
    direction           TEXT CHECK (direction IN ('INBOUND','OUTBOUND','INTERNAL','UNKNOWN')),
    participants_json   TEXT,                          -- [{name, email, role}] as parsed
    title               TEXT,                          -- subject / meeting topic
    content             TEXT,                          -- full text (body / transcript) — stays local
    summary             TEXT,                          -- short summary (AI or rule-based)
    metadata_json       TEXT,
    extraction_status   TEXT NOT NULL DEFAULT 'PENDING' CHECK (extraction_status IN ('PENDING','DONE','FAILED','SKIPPED','NOT_APPLICABLE')),
    extraction_provider TEXT,                          -- none | rules | openai:gpt-… — what produced memories/actions from this
    created_at          TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX idx_evidence_deal_time ON evidence(deal_id, occurred_at DESC);
CREATE INDEX idx_evidence_company_time ON evidence(company_id, occurred_at DESC);
CREATE INDEX idx_evidence_hash ON evidence(content_hash);
CREATE INDEX idx_evidence_extraction ON evidence(extraction_status);

-- Full-text search over evidence. Answers "what did we agree on the last call?"
-- without a vector database (ADR-006).
CREATE VIRTUAL TABLE evidence_fts USING fts5(
    title, content, summary,
    content='evidence', content_rowid='rowid'
);
CREATE TRIGGER evidence_ai AFTER INSERT ON evidence BEGIN
    INSERT INTO evidence_fts(rowid, title, content, summary) VALUES (new.rowid, new.title, new.content, new.summary);
END;
CREATE TRIGGER evidence_ad AFTER DELETE ON evidence BEGIN
    INSERT INTO evidence_fts(evidence_fts, rowid, title, content, summary) VALUES ('delete', old.rowid, old.title, old.content, old.summary);
END;
CREATE TRIGGER evidence_au AFTER UPDATE ON evidence BEGIN
    INSERT INTO evidence_fts(evidence_fts, rowid, title, content, summary) VALUES ('delete', old.rowid, old.title, old.content, old.summary);
    INSERT INTO evidence_fts(rowid, title, content, summary) VALUES (new.rowid, new.title, new.content, new.summary);
END;

-- ---------------------------------------------------------------------------
-- Memory — what the brain currently believes
-- ---------------------------------------------------------------------------

CREATE TABLE memories (
    id                  TEXT PRIMARY KEY,
    type                TEXT NOT NULL CHECK (type IN (
                            'FACT','COMMITMENT','CUSTOMER_PREFERENCE','OBJECTION','BUYING_SIGNAL','RELATIONSHIP',
                            'DEAL_STATE','NEXT_STEP','RISK','USER_PREFERENCE','LEARNED_PATTERN')),
    basis               TEXT NOT NULL DEFAULT 'OBSERVED' CHECK (basis IN ('OBSERVED','INFERRED','STATED_BY_USER')),
                                                       -- OBSERVED = directly supported by evidence text
                                                       -- INFERRED = hypothesis derived by AI/rules
                                                       -- STATED_BY_USER = user told the system
    status              TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','FULFILLED','SUPERSEDED','EXPIRED','RETRACTED','REJECTED')),
    subject             TEXT NOT NULL,                 -- short label: "Revised pricing"
    content             TEXT NOT NULL,                 -- one or two sentences, evidence-grounded
    dedupe_key          TEXT,                          -- type + deal + normalised subject; used to update instead of duplicate
    company_id          TEXT REFERENCES companies(id) ON DELETE SET NULL,
    contact_id          TEXT REFERENCES contacts(id) ON DELETE SET NULL,
    deal_id             TEXT REFERENCES deals(id) ON DELETE SET NULL,
    -- Commitment-specific
    direction           TEXT CHECK (direction IN ('USER_TO_CUSTOMER','CUSTOMER_TO_USER','CUSTOMER_INTERNAL','USER_INTERNAL')),
    owner_label         TEXT,                          -- who owes it: "me" or contact name
    due_date            TEXT,                          -- ISO date if stated/resolvable
    due_text            TEXT,                          -- original phrase: "Friday", "end of month"
    -- Belief bookkeeping
    confidence          REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    valid_from          TEXT NOT NULL,
    valid_until         TEXT,                          -- set when status leaves ACTIVE
    superseded_by_id    TEXT REFERENCES memories(id) ON DELETE SET NULL,
    resolution_note     TEXT,                          -- why it was fulfilled/superseded/rejected
    created_by          TEXT NOT NULL,                 -- rules | openai:gpt-… | user
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_memories_deal_status ON memories(deal_id, status, type);
CREATE INDEX idx_memories_company_status ON memories(company_id, status, type);
CREATE INDEX idx_memories_dedupe ON memories(dedupe_key);
CREATE INDEX idx_memories_due ON memories(status, due_date);

-- Many-to-many: which evidence supports a memory. Each link carries the
-- verbatim quote so "Why do you think this?" can show the exact passage.
CREATE TABLE memory_evidence (
    memory_id           TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    evidence_id         TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    quote               TEXT,                          -- verbatim span from evidence.content, verified by code
    relation            TEXT NOT NULL DEFAULT 'SUPPORTS' CHECK (relation IN ('SUPPORTS','FULFILS','CONTRADICTS','SUPERSEDES')),
    created_at          TEXT NOT NULL,
    PRIMARY KEY (memory_id, evidence_id, relation)
);
CREATE INDEX idx_memory_evidence_evidence ON memory_evidence(evidence_id);

-- ---------------------------------------------------------------------------
-- Actions — the unified working list
-- ---------------------------------------------------------------------------

CREATE TABLE actions (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    description         TEXT,
    type                TEXT NOT NULL CHECK (type IN (
                            'HUBSPOT_TASK','TODO_TASK','PROSPECTING','EMAIL_FOLLOWUP','TRANSCRIPT_ACTION',
                            'MEETING_PREP','MEETING_FOLLOWUP','COMMITMENT','DATA_HYGIENE','REVIEW','MANUAL')),
    tier                INTEGER NOT NULL DEFAULT 2 CHECK (tier IN (1,2,3)),
                                                       -- 1 = active deal work, 2 = follow-ups/admin, 3 = prospecting.
                                                       -- Sorting is tier first, then score. Prospecting can never outrank deal work.
    status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','COMPLETED','DISMISSED','SNOOZED')),
    source              TEXT NOT NULL,                 -- connector or subsystem that created it
    source_id           TEXT,                          -- HubSpot task id, sheet row key, memory id, meeting id …
    origin_memory_id    TEXT REFERENCES memories(id) ON DELETE SET NULL,
    company_id          TEXT REFERENCES companies(id) ON DELETE SET NULL,
    deal_id             TEXT REFERENCES deals(id) ON DELETE SET NULL,
    contact_id          TEXT REFERENCES contacts(id) ON DELETE SET NULL,
    meeting_id          TEXT REFERENCES meetings(id) ON DELETE SET NULL,
    due_date            TEXT,
    snoozed_until       TEXT,
    priority_score      REAL NOT NULL DEFAULT 0,
    priority_breakdown_json TEXT,
    system_rank         INTEGER,                       -- position the system assigned at last computation
    user_priority_override INTEGER,                    -- explicit rank chosen by the user (pin)
    user_boost          INTEGER NOT NULL DEFAULT 0,
    external_write_status TEXT CHECK (external_write_status IN ('NOT_APPLICABLE','PROPOSED','APPROVED','WRITTEN','REJECTED','FAILED')),
    completed_at        TEXT,
    dismissed_at        TEXT,
    dismissed_reason    TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX idx_actions_open ON actions(status, tier, priority_score DESC);
CREATE INDEX idx_actions_deal ON actions(deal_id, status);
CREATE INDEX idx_actions_due ON actions(status, due_date);

CREATE TABLE action_evidence (
    action_id           TEXT NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    evidence_id         TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    PRIMARY KEY (action_id, evidence_id)
);

-- ---------------------------------------------------------------------------
-- Meetings
-- ---------------------------------------------------------------------------

CREATE TABLE meetings (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL CHECK (source IN ('CALENDLY','HUBSPOT','TRANSCRIPT','MANUAL')),
    external_id         TEXT,
    title               TEXT,
    event_type          TEXT,
    start_at            TEXT NOT NULL,
    end_at              TEXT,
    duration_minutes    INTEGER,
    status              TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK (status IN ('SCHEDULED','HELD','CANCELLED','NO_SHOW')),
    company_id          TEXT REFERENCES companies(id) ON DELETE SET NULL,
    deal_id             TEXT REFERENCES deals(id) ON DELETE SET NULL,
    contact_id          TEXT REFERENCES contacts(id) ON DELETE SET NULL,
    invitees_json       TEXT,                          -- [{name, email}]
    join_url            TEXT,
    transcript_evidence_id TEXT REFERENCES evidence(id) ON DELETE SET NULL,
    followup_action_id  TEXT REFERENCES actions(id) ON DELETE SET NULL,
    metadata_json       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX idx_meetings_start ON meetings(start_at);
CREATE INDEX idx_meetings_deal ON meetings(deal_id);

-- ---------------------------------------------------------------------------
-- Prospecting (normalised Google Sheet rows). Each open row also yields one
-- action of type PROSPECTING (tier 3) keyed by row_key.
-- ---------------------------------------------------------------------------

CREATE TABLE prospecting_items (
    id                  TEXT PRIMARY KEY,
    row_key             TEXT NOT NULL UNIQUE,          -- stable hash: sequence_id | company | contact | step (see connector doc)
    sheet_row_number    INTEGER,                       -- last known row; not stable, informational only
    due_date            TEXT,
    priority            TEXT,
    company_name        TEXT,
    company_id          TEXT REFERENCES companies(id) ON DELETE SET NULL,
    contact_name        TEXT,
    contact_title       TEXT,
    channel             TEXT,
    step                TEXT,
    subject             TEXT,
    body                TEXT,
    phone               TEXT,
    zoominfo_url        TEXT,
    outcome             TEXT,
    done                INTEGER NOT NULL DEFAULT 0,
    actual_date         TEXT,
    notes               TEXT,
    sequence_id         TEXT,
    raw_row_json        TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_prospecting_open ON prospecting_items(done, due_date);

-- ---------------------------------------------------------------------------
-- Operations: sync tracking, processed files, review queue
-- ---------------------------------------------------------------------------

CREATE TABLE sync_runs (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    trigger             TEXT NOT NULL CHECK (trigger IN ('MORNING','MANUAL','STARTUP','FILE_DROP')),
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED','SKIPPED','NOT_CONFIGURED')),
    records_fetched     INTEGER NOT NULL DEFAULT 0,
    records_created     INTEGER NOT NULL DEFAULT 0,
    records_changed     INTEGER NOT NULL DEFAULT 0,
    records_unchanged   INTEGER NOT NULL DEFAULT 0,
    error_count         INTEGER NOT NULL DEFAULT 0,
    errors_json         TEXT,                          -- [{message, record_ref}] capped
    message             TEXT,                          -- human-readable status shown in UI
    cursor_json         TEXT                           -- incremental sync cursor (e.g. HubSpot lastmodified watermark)
);
CREATE INDEX idx_sync_runs_source_time ON sync_runs(source, started_at DESC);

-- Files seen in data/inbox. Prevents reprocessing; supports "reprocess" on demand.
CREATE TABLE processed_files (
    id                  TEXT PRIMARY KEY,
    inbox_kind          TEXT NOT NULL CHECK (inbox_kind IN ('EMAIL','TRANSCRIPT','EXCEL','PROSPECTING_CSV','TODO_EXPORT')),
    original_name       TEXT NOT NULL,
    stored_path         TEXT,                          -- location under data/processed/
    sha256              TEXT NOT NULL UNIQUE,
    size_bytes          INTEGER,
    status              TEXT NOT NULL CHECK (status IN ('PROCESSED','FAILED','DUPLICATE','UNSUPPORTED')),
    evidence_id         TEXT REFERENCES evidence(id) ON DELETE SET NULL,
    error               TEXT,
    processed_at        TEXT NOT NULL
);

-- Questions the system needs the user to answer instead of guessing.
-- Surfaced on Today ("2 questions") and Inbox.
CREATE TABLE review_items (
    id                  TEXT PRIMARY KEY,
    kind                TEXT NOT NULL CHECK (kind IN ('MATCH_COMPANY','MATCH_DEAL','MATCH_CONTACT','CONFLICTING_MEMORY','CONFIRM_MEMORY','STALE_COMMITMENT','CLOSE_DATE_PASSED')),
    status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED','DISMISSED')),
    question            TEXT NOT NULL,
    evidence_id         TEXT REFERENCES evidence(id) ON DELETE CASCADE,
    memory_id           TEXT REFERENCES memories(id) ON DELETE CASCADE,
    deal_id             TEXT REFERENCES deals(id) ON DELETE SET NULL,
    candidates_json     TEXT,                          -- [{id, label, confidence, reason}]
    resolution_json     TEXT,                          -- what the user chose
    created_at          TEXT NOT NULL,
    resolved_at         TEXT
);
CREATE INDEX idx_review_items_open ON review_items(status, created_at);

-- ---------------------------------------------------------------------------
-- Safety: audit / approval, AI transmission log
-- ---------------------------------------------------------------------------

CREATE TABLE audit_log (
    id                  TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    actor               TEXT NOT NULL,                 -- user | system
    event               TEXT NOT NULL,                 -- PROPOSE_EXTERNAL_WRITE | APPROVE | REJECT | EXECUTE | SYNC | USER_EDIT | CONFIG_CHANGE …
    external_system     TEXT,                          -- HUBSPOT | GOOGLE_SHEETS | MS_TODO
    external_ref        TEXT,                          -- id of the external object
    action_id           TEXT REFERENCES actions(id) ON DELETE SET NULL,
    reasoning           TEXT,
    proposed_change_json TEXT,                         -- exact payload that would be / was sent
    approval_status     TEXT CHECK (approval_status IN ('PENDING','APPROVED','REJECTED','EXECUTED','FAILED','NOT_REQUIRED')),
    approved_at         TEXT,
    executed_at         TEXT,
    result_json         TEXT
);
CREATE INDEX idx_audit_pending ON audit_log(approval_status, timestamp DESC);

CREATE TABLE audit_log_evidence (
    audit_id            TEXT NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
    evidence_id         TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    PRIMARY KEY (audit_id, evidence_id)
);

-- Every call to an external AI provider is logged so the user can see exactly
-- what left the machine (Section 30).
CREATE TABLE ai_calls (
    id                  TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT,
    purpose             TEXT NOT NULL,                 -- extract_memory | extract_actions | summarize | generate_deal_summary | answer_question
    evidence_id         TEXT REFERENCES evidence(id) ON DELETE SET NULL,
    deal_id             TEXT REFERENCES deals(id) ON DELETE SET NULL,
    input_chars         INTEGER NOT NULL,
    output_chars        INTEGER,
    redacted            INTEGER NOT NULL DEFAULT 0,
    latency_ms          INTEGER,
    status              TEXT NOT NULL CHECK (status IN ('OK','ERROR','REJECTED_OUTPUT')),
    error               TEXT
);

-- ---------------------------------------------------------------------------
-- Learning: behavioural signals only (no model training in V1)
-- ---------------------------------------------------------------------------

CREATE TABLE user_feedback (
    id                  TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    action_id           TEXT REFERENCES actions(id) ON DELETE SET NULL,
    deal_id             TEXT REFERENCES deals(id) ON DELETE SET NULL,
    event               TEXT NOT NULL CHECK (event IN ('COMPLETED','IGNORED','SNOOZED','DISMISSED','BOOST_UP','BOOST_DOWN','PINNED','UNPINNED','REORDERED','MEMORY_CONFIRMED','MEMORY_REJECTED','MATCH_CONFIRMED','MATCH_CORRECTED')),
    system_priority     INTEGER,                       -- rank the system gave at the time
    user_priority       INTEGER,                       -- rank the user implied/chose
    manual_override     INTEGER NOT NULL DEFAULT 0,
    context_json        TEXT                           -- snapshot: deal value, days to close, staleness, tier, is_strategic …
);
CREATE INDEX idx_user_feedback_time ON user_feedback(timestamp DESC);

CREATE TABLE settings (
    key                 TEXT PRIMARY KEY,
    value_json          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE schema_migrations (
    version             INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    applied_at          TEXT NOT NULL
);
