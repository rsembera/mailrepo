# docs/archive/

Plan documents and session notes from work that has shipped. Kept here
rather than deleted because they document design decisions and the
reasoning behind shipped behavior — useful when a future change needs to
re-litigate one of those decisions.

Live planning happens in `docs/` (one level up); this directory is
read-only history.

## Contents

- **Refactoring_Plan.md** — original codebase refactor. Status when archived: Complete.
- **Refactoring_Plan_V2.md** — follow-up refactor pass. Status when archived: Complete.
- **Retention_Vault_Plan.md** — soft-delete + retention design. Status when archived: Implemented.
- **Crypto_Refactor_Plan.md** — May 2026 PBKDF2/Fernet → Argon2id/AES-256-GCM migration plan. The migration ran May 29, 2026 (see `docs/Session_Log.md`); v1 code was removed May 30. Status when archived: Shipped.
- **Bulk_Export_Plan.md** — encrypted bulk export feature design (pyzipper-based ZIP with per-export password). Status when archived: Shipped.
- **SESSION_NOTES.md** — one-shot session writeup from Session 43 (Feb 22, 2026) marking the original "production ready" milestone. Predates the May 2026 crypto work that became the actual 1.0. Kept as historical context; superseded by `docs/Session_Log.md` as the running narrative.
