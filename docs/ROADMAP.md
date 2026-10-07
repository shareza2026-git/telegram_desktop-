# Roadmap

## R0 — Release/documentation architecture

State: IMPLEMENTED IN PR #2; CI PASS; awaiting integration authorization.

Outcome:

- tag-driven SemVer release
- synchronized manifests
- concise `AGENTS.md` + durable `docs/`
- explicit dev/live/review process

## S1 — Fresh-machine session hardening

State: IMPLEMENTED IN PR #3; CI PASS; local Windows/Telegram validation pending.

Outcome:

- no implicit portable/session authorization seeding
- explicit-only import paths
- independent fresh-machine session location
- approved API credentials are supplied independently
- secret/runtime Git exclusions hardened

## S2 — Identity / connectivity correctness

State: IMPLEMENTED IN PR #3; local tunnel/Telegram validation pending.

Outcome:

- real Windows computer name used as Telegram device model
- `TELEGRAM_ALLOW_DIRECT=false` remains authoritative unless explicitly opted in
- stale direct selection cannot bypass policy
- Xray can be provided explicitly for managed VLESS routes
- post-login verification checks current Telegram Device

## LOGIN1 — New-machine local validation

State: NEXT.

Run from `Desktop Telegram\dev`:

```powershell
.\scripts\bootstrap-new-machine.ps1
```

Complete phone/code/2FA only inside the application when Telegram reaches that step.

While the app is still running:

```powershell
.\scripts\verify-local-session.ps1
```

Also manually validate profile photo, dialogs/messages, and live/WebSocket behavior.

## SEC1 — Dependency/security audit

State: OPEN before release.

Targets:

- classify npm findings as direct/transitive and runtime/build-only
- determine actual exposure
- select safe fixes without blind force upgrades
- re-check packaged artifact secret exclusions

## REL1 — Pre-live gate

State: READY FOR LOCAL USE after LOGIN1.

Run:

```powershell
.\scripts\release-gate.ps1
```

This must not alter `live`, create a tag, or publish a release.

Before promotion, identify and preserve the exact current `live` baseline and rollback path.

## REL2 — Promotion and official version

State: BLOCKED ON USER APPROVAL + REL1 + security/live-baseline checks.

After explicit approval:

1. integrate reviewed branches in order;
2. promote the approved candidate to `live` with rollback protection;
3. validate the live copy;
4. preview the next tag with `tag-release.ps1 -Preview`;
5. create the official `vMAJOR.MINOR.PATCH` tag only after explicit authorization;
6. verify GitHub Actions installer/release.

## Future product work

Only when explicitly prioritized:

- audio/video playback
- calls
- Stories
- automatic updater
