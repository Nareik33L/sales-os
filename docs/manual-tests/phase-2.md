# Phase 2 manual test — HubSpot → Today            est. ≤15 min

## Before you start

- `git pull && python run.py` — opens http://localhost:8501 (Today).
- Env vars for live HubSpot steps: `HUBSPOT_ACCESS_TOKEN` in `.env` (copy from `.env.example` if you do not have one yet).
- Optional: `python run.py --demo` first if you want fictional cards on screen before the live refresh. Demo data is Acme / Beta Corp only — never real customers.
- Leave Excel / Sheets / Calendly blank unless you already use them. Phase 2 does not require them.

## Steps

| # | Do | Expect | ✓/✗ + note |
|---|----|--------|------------|
| 1 | After `python run.py`, open http://localhost:8501 | Today loads: “Good morning”, START HERE, and the sidebar (Today · Deals · Inbox · Settings). No crash, no traceback. | |
| 2 | Confirm `HUBSPOT_ACCESS_TOKEN` is set. Click **↻ Refresh** on Today | HubSpot shows **✓** with a line like “n checked”. The page still renders. Excel / Sheets / Calendly may show **⚠** or **–** (not built or not connected) — that is fine. | |
| 3 | Look at **#1** on START HERE | It is a live deal or task you would also put first this morning. The **Why:** bullets match what you know (value, close date, stale activity, something you owe). Nothing made up. | |
| 4 | On a real card you have actually finished, click **Complete** (say yes if it asks about a commitment) | The card leaves the open list. Today does not crash. | |
| 5 | On another real card, click **Snooze** and pick tomorrow | The card leaves Today for now. The rest of the list stays. | |
| 6 | Stop the app (`Ctrl+C`). Blank or comment out `HUBSPOT_ACCESS_TOKEN` in `.env`, start `python run.py` again, click **↻ Refresh** | HubSpot shows **⚠** and a “Not connected” / “set HUBSPOT_ACCESS_TOKEN” line. Today still renders (demo or last-saved cards are OK). No crash. | |
| 7 | Leave `EXCEL_SYNCED_FILE_PATH` blank. Look at the source row after Refresh | Excel shows **⚠** or **–** (often “No run yet” — the Excel importer is Phase 3). The page still renders. A crash here is a fail. | |
| 8 | Click **Deals**, then **Inbox**, then **Settings** in the sidebar | Each is a short stub (“ships in SOS-…”). None of them error. | |
| 9 | Restore `HUBSPOT_ACCESS_TOKEN`, restart, click **↻ Refresh** | HubSpot **✓** returns. The card you completed in step 4 is still gone from the open list. | |

## Tell us

- Anything that was wrong or surprising (one line each).
- Any bullet in “Why” that was untrue.
- Anything the tool asked you that it should have known.
