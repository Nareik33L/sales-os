# Release database fixtures

Fictional data only (Acme, Beta Corp, Gamma, Delta). Never copy a real `data/salesos.db` here.

| File | Meaning |
|---|---|
| `db_v0.2.0.sqlite` | Phase 2 baseline. Schema `001_initial` + `python run.py --demo` seed. First populated fixture — there was no `db_v0.1.0`. |

Phase 3+ should copy this file, apply new migrations, assert row counts on existing tables are unchanged, then save the result as `db_v0.N.0.sqlite`.

Regenerate the Phase 2 file (does not start Streamlit):

```bash
python -c "from tests.release.helpers import build_v020_fixture; print(build_v020_fixture())"
```
