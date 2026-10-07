# Known Issues

Only issues with evidence belong here. Unrelated findings are recorded rather than silently expanding the current task.

| ID | Summary | Status | Severity | Evidence | Target |
|---|---|---|---|---|---|
| K-001 | Fresh packaged startup could silently seed/restore prior Telegram authorization. | RESOLVED ON `work/fresh-machine-bootstrap`; pending integration/local validation | High | Implicit executable-folder portable/session discovery and Tauri transfer bootstrap were removed; explicit opt-in paths remain. CI regression tests pass. | Local fresh-machine validation |
| K-002 | Telegram device model was generic rather than the real Windows computer name. | RESOLVED ON `work/fresh-machine-bootstrap`; pending live Telegram validation | Medium | Telethon device model now uses `COMPUTERNAME` / `platform.node()`; verification script checks Telegram Devices. | Local login verification |
| K-003 | API configuration/direct selection could enable or use direct Telegram connectivity without explicit opt-in. | RESOLVED ON `work/fresh-machine-bootstrap`; pending integration | High | API credential save no longer enables direct mode; stale direct selection is ignored and explicit direct selection is rejected while policy is false. | Local tunnel validation |
| K-004 | Sensitive local runtime filenames were not all explicitly ignored. | RESOLVED ON `work/fresh-machine-bootstrap` | High | `settings.env`, `telegram-api.env`, `telegram-proxies.json`, session/database/runtime data are excluded from Git; private proxy catalog remains ignored under data. | Final secret review before release |
| K-005 | npm reports 4 vulnerabilities in the current dependency graph. | OPEN | High pending triage | Development CI reports 1 moderate, 1 high and 2 critical findings. Exposure/direct-vs-transitive status has not yet been classified. | Dependency/security audit before release |
| K-006 | Exact approved version currently present in the local `live\` folder is not documented. | OPEN | Medium process risk | Local folder exists, but its exact approved tag/commit has not been established. | Establish before first live promotion |

## Handling rules

- Do not fix unrelated issues automatically during another task.
- A known issue blocks current work only when it threatens correctness, security, data integrity, or explicit exit criteria.
- K-001 through K-004 require local validation/integration before they are considered released behavior.
- K-005 must be triaged before an official release.
- K-006 must be resolved before overwriting/promoting the local live installation.
