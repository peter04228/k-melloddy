# Development rules

Preserve all existing research files and previous run artifacts. Never infer scientific records or counts.
Keep execution in src/k_melloddy; project folders contain inputs, documentation and outputs only.
Every module and every numbered step must have a README covering inputs, outputs, algorithm,
states, units, audit events, validation, retries, resume, commands, tests and limitations.
All changes to collection must pass offline tests. Real collection is opt-in.
DB_Select implementation is authorized by the DB_Select v1 specification. Keep its LLM unconfigured
until the user selects a provider. DB_Download and DB_Preprocessing remain contracts only.
Ledger events and finalized artifacts are append-only. IDs must remain stable across runs.
