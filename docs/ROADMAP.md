# Roadmap

This roadmap is intentionally high-level. Each implementation phase should still have one focused outcome.

## R0 — Release/documentation architecture

Goal:

Make release/version semantics deterministic and leave durable project instructions for future sessions.

Current state:

In review on PR #2.

Exit:

- tag-driven release/versioning reviewed
- manifest consistency enforced
- `AGENTS.md` concise
- durable `docs/` contract/workflow/release/status/decisions/issues established
- CI passes

## S1 — Fresh-machine session hardening

Goal:

Guarantee that a new machine does not silently reuse an old Telegram authorization.

Design/implementation targets:

- disable automatic portable/session authorization seeding for fresh-machine flow
- preserve explicit user-authorized import paths only where intentionally supported
- keep `TELEGRAM_AUTO_IMPORT_SOURCE=false`
- ensure independent private session path
- prevent secret exposure

Exit:

Automated tests prove no silent old-session reuse.

## S2 — Identity / connectivity correctness

Goal:

Make new Telegram authorization accurately represent the new PC and obey route policy.

Targets:

- real Windows computer name in Telegram Devices
- `TELEGRAM_ALLOW_DIRECT=false` unless explicitly opted in
- status/devices validation after login
- proxy catalog remains read-only

## SEC1 — Secret and dependency audit

Goal:

Establish release security hygiene.

Targets:

- harden ignore/packaging rules for generated private config
- classify npm vulnerability findings: direct/transitive, runtime/build-only, exposure, available fix
- avoid blind force upgrades
- verify release artifacts exclude secrets/runtime state

## LOGIN1 — New-machine login validation

Goal:

Perform actual approved Telegram login on the new machine after S1/S2 pass.

Requires user interaction only when needed for:

- API credentials if absent
- phone number
- OTP
- 2FA password

Validate:

- `/health`
- Telegram configured/connected/authorized status
- Devices/current device naming
- avatar/profile
- dialogs/messages
- WebSocket/live updates

## REL1 — Release gate

Goal:

Prepare the next approved release candidate.

Gate:

- full relevant backend/frontend tests
- production frontend build
- packaging validation
- secret scan/review
- dependency audit decision
- known blockers resolved
- live rollback/promotion plan known

Then preview next tag with `tag-release.ps1 -Preview`.

Creating the official tag still requires explicit user authorization.

## Future product work

Only when explicitly prioritized:

- audio/video playback
- calls
- Stories
- automatic updater
