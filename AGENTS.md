# AGENTS.md — Telegram Desktop

This is the operational entry point for every future engineering session.

## Read first

Before changing code, read:

1. `docs/CURRENT_STATUS.md`
2. `docs/PROJECT_CONTRACT.md`
3. `docs/ARCHITECTURE.md`
4. `docs/ENGINEERING_WORKFLOW.md`
5. `docs/RELEASE_PROCESS.md`
6. `docs/DECISIONS.md`
7. `docs/KNOWN_ISSUES.md`
8. `docs/ROADMAP.md`

Read only the additional code/tests relevant to the current task.

## Workspace model

Expected parent project layout on Windows:

```text
Desktop Telegram/
  live/      last user-approved runnable version
  dev/       Git development working copy
  review/    reports, patches, review ZIPs, Git bundles; outside repo
  prompts/   reusable handoff/prompt material when needed
  tools/     external project tools
  launchers/ stable user-facing launchers when needed
```

Normal coding happens in `dev`, never in `live`.

## Git model for this repository

This project adapts the generic develop/main model to its established history:

- `feature/telegram-desktop-foundation` = authoritative integration/development branch.
- `work/*` = focused task/review branches.
- `main` = old baseline; do not continue active development from it.
- `release/v*` = not used by the current release flow.
- `vMAJOR.MINOR.PATCH` = authoritative official release version.

Do not merge, tag, publish, or promote `live` without explicit user authorization.

## Before modifying anything

Verify:

```powershell
git status
git branch --show-current
git log -1 --oneline
git fetch
```

Stop if the workspace is wrong, unexplained changes exist, secrets/runtime data are exposed, or continuing risks overwriting user work.

Never use destructive cleanup just to get a clean tree. Avoid `git reset --hard`, broad `git clean`, blanket stash, and broad restore unless explicitly authorized.

## Engineering rules

Understand before changing. Investigate broadly; change narrowly. Preserve correct existing behavior.

Each task has one primary goal. Do not mix unrelated refactors, dependency upgrades, formatting sweeps, UX redesign, architecture rewrites, or cleanup.

For persistence/networking/side effects, reason about retries, duplicate delivery, partial failure, restart/recovery, stale state, ordering, and isolation.

Durable/authoritative state wins over UI or temporary state.

If important product semantics are ambiguous, stop and report the ambiguity.

## Security / privacy

Never print, commit, package, or place in review artifacts:

- `.env`
- API hash / API secrets
- Telegram login code or 2FA password
- Telegram authorization/session keys or `*.session`
- full V2Ray links or proxy passwords
- runtime SQLite databases / WAL / SHM
- private logs or real personal data

The trading dashboard is a separate repository. Its allowed proxy/V2Ray inputs are read-only. Do not modify dashboard files, DBs, sessions, settings, or runtime state.

`TELEGRAM_ALLOW_DIRECT` stays false unless the user explicitly asks for direct connectivity.

## Telegram session rule

On a new computer, do not silently reuse/import a session from another machine.

Prefer a new independent app session and normal phone/code/2FA login. Ask for phone, OTP, or 2FA only when the login flow actually reaches that step.

## Validation

At minimum, before integration:

```powershell
python scripts/sync-version.py --check
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-handoff
cd frontend
npm.cmd test
npm.cmd run build
```

Use focused tests during implementation. Do not claim PASS for skipped relevant validation.

## Release

Read `docs/RELEASE_PROCESS.md` before creating a tag.

Normal release helper:

```powershell
.\scripts\tag-release.ps1 -Preview
.\scripts\tag-release.ps1
```

The tag is the release version. Never rewrite an existing release tag.

## Handoff

For meaningful work, report exact branch/base/head, files changed, tests/results, skipped checks, known risks, unrelated issues, diff/status, and:

`SAFE TO REVIEW: YES/NO`

Update `docs/CURRENT_STATUS.md` only at meaningful checkpoints.

Protect `live`. Never make the user depend on a half-finished development state.
