# Current Status

Checkpoint date: 2026-10-07

## Repository

Repository: `shareza2026-git/telegram_desktop-`

Authoritative development branch:

`feature/telegram-desktop-foundation`

Current integrated development baseline remains:

`0243352dbd9b41175998d1ecbc5cf21e7050f851`

No pending work below has been merged into that branch without explicit approval.

## Pending release/documentation work

Branch:

`work/release-tag-versioning`

PR #2:

`Make releases tag-driven and version-safe`

Head before the child fresh-machine work:

`ee252a50100f644ec02b3f398b460c33c8a7087c`

Status:

- tag-driven SemVer release architecture implemented
- release/version manifests synchronized at `0.1.25`
- durable project docs established
- CI passed
- not merged; no official tag created

## Current fresh-machine work

Branch:

`work/fresh-machine-bootstrap`

PR #3:

`Harden fresh-machine Telegram bootstrap`

Latest implementation/correction head before this documentation checkpoint:

`b5534a141ff0a7b07eb8bc8e12085eecf9ce089b`

Validated in CI:

- PowerShell automation syntax: PASS
- release version manifest check: PASS
- backend suite: PASS
- frontend tests: PASS
- frontend production build: PASS

Implemented:

- no implicit old executable-folder session/API/proxy bootstrap
- no automatic dashboard API credential import
- independent fresh-machine session paths
- real Windows computer name sent as Telegram device model
- direct connectivity remains opt-in
- explicit Xray path support
- private VLESS configuration without echoing secrets
- development desktop shortcut creation
- local session verification script
- pre-live release gate that does not modify `live`
- secret/runtime ignore hardening

## Local directory model

Expected parent root:

`C:\Users\<USER>\Desktop\Desktop Telegram\`

Observed:

- `dev\`
- `live\`

The exact approved tag/commit currently represented by `live\` is still unknown. Do not overwrite it.

## Immediate next action

Local Windows validation is now required because repository CI cannot operate the user's desktop, Telegram account, or local tunnel.

The intended order is:

1. clone `work/fresh-machine-bootstrap` into `Desktop Telegram\dev`;
2. run `scripts\bootstrap-new-machine.ps1`;
3. provide API_ID/API_HASH locally when requested;
4. provide a VLESS/REALITY route locally or an explicitly chosen read-only proxy catalog;
5. let the app open and perform phone/code/2FA login inside the app;
6. while it is running, run `scripts\verify-local-session.ps1`;
7. review real UI/dialog/WebSocket behavior;
8. only after approval, run `scripts\release-gate.ps1`;
9. establish the current `live` baseline before any promotion;
10. promote/tag only with explicit user approval.

## Known release blockers

- npm vulnerability findings still require classification.
- current local `live` baseline must be identified before replacement/promotion.

## Deferred product scope

- audio/video playback
- calls
- Stories
- automatic updater
