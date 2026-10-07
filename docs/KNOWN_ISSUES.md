# Known Issues

Only issues with evidence belong here. Unrelated findings are recorded rather than silently expanding the current task.

| ID | Summary | Status | Severity | Evidence | Target |
|---|---|---|---|---|---|
| K-001 | Packaged/portable startup paths can seed/restore prior Telegram authorization despite the fresh-machine policy. | OPEN | High | `app/main.py` applies portable config; `app/telegram/portable.py` can seed auth; packaged transfer paths can restore `telegram-session.session`. | Fresh-machine session hardening |
| K-002 | Telegram device model is currently generic rather than the real Windows computer name. | OPEN | Medium | `app/telegram/client.py` sets `device_model="Desktop"`. | Fresh-machine session hardening |
| K-003 | Runtime configuration may enable direct Telegram connectivity when no transport routes exist. | OPEN | High | `set_runtime_config()` derives direct allowance from existing routes instead of requiring explicit user opt-in. | Connectivity policy hardening |
| K-004 | Sensitive local release/runtime filenames are not all explicitly ignored. | OPEN | High | `.gitignore` covers `.env`, sessions, DBs and `telegram-portable.json`, but needs review for `settings.env`, `telegram-api.env`, `telegram-proxies.json` and similar generated private files. | Secret-hygiene hardening |
| K-005 | npm reports 4 vulnerabilities in the current dependency graph. | OPEN | High pending triage | Development CI reported 1 moderate, 1 high and 2 critical findings. Exposure/direct-vs-transitive status has not yet been classified. | Dependency/security audit before release |
| K-006 | Exact approved version currently present in the local `live\` folder is not documented in the repository. | OPEN | Medium process risk | Local folder exists, but repo checkpoint does not identify its exact approved tag/commit. | Establish before first live promotion |

## Handling rules

- Do not fix these automatically during unrelated work.
- A known issue blocks a task only when it threatens correctness, security, data integrity, or the task's explicit exit criteria.
- K-001/K-003 are blockers for claiming a safe fresh-machine login policy.
- K-005 must be triaged before an official release.
- K-006 must be resolved before overwriting/promoting the local live installation.
