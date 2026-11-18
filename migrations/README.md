# One-off migration scripts

These are run-once scripts (schema changes, data backfills, renames) applied
directly against the Supabase Postgres database over the life of the project.
They live here purely for history/reference — most have already been run
against production and won't need to run again.

Each one imports from the project root (`database`, `models`, etc.), so run
them as a module from the repo root, not as a bare script:

```
python -m migrations.migrate_positions
```

(`python migrations/migrate_positions.py` will fail with
`ModuleNotFoundError: No module named 'database'` — the script's own
directory becomes sys.path[0] in that form, not the repo root.)
