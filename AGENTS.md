# AGENTS.md — Telegram Desktop Engineering & Release Contract

This file is the first operational reference for any engineer, coding agent, or automation working in this repository.

Read it before changing code, creating tags, building releases, touching Telegram sessions, or using dashboard configuration.

---

## 1. Project identity

Repository:

`https://github.com/shareza2026-git/telegram_desktop-.git`

Primary development branch:

`feature/telegram-desktop-foundation`

Do not continue normal development from `main`.

`main` is the early baseline. The active development branch is intentionally far ahead of it.

The Telegram Desktop project and the trading dashboard are separate repositories.

---

## 2. Product architecture

- Frontend: React + TypeScript + Vite
- Desktop shell: Tauri 2
- Backend: Python 3.12 + FastAPI
- Telegram client: Telethon
- Live updates: WebSocket
- Local persistence: SQLite
- Windows installer: Tauri / NSIS
- Packaged backend: PyInstaller sidecar

Current product scope includes normal Telegram desktop messaging workflows such as dialogs, history, send, reply, edit, delete, forward, reactions, typing, read receipts, pinned messages, drafts, notifications, account settings, profiles, and Devices.

Audio/video playback, calls, and Stories remain out of scope unless explicitly requested later.

---

## 3. Git branch model

### Development

All normal development continues on:

`feature/telegram-desktop-foundation`

Feature/fix work may use temporary work branches, but the integration target is the development branch above.

### Main

Do not use `main` as the active development source.

Do not push release work to `main`.

### Release branches

`release/v*` branches are not part of the normal release flow.

Do not create release branches just to publish a version.

### Release tags

Official releases are tag-driven.

The only supported official release tag format is:

`vMAJOR.MINOR.PATCH`

Examples:

- `v0.1.26`
- `v0.2.0`
- `v1.0.0`

A release tag must point to a commit that belongs to the history of:

`feature/telegram-desktop-foundation`

---

## 4. Release architecture

The release flow is:

```text
feature/telegram-desktop-foundation
        |
        | normal development + commits
        v
release is ready
        |
        v
scripts/tag-release.ps1
        |
        +-- verify correct branch
        +-- verify clean working tree
        +-- fetch current remote branch and tags
        +-- refuse behind/diverged local state
        +-- verify synchronized version manifests
        +-- calculate next semantic version
        +-- create annotated tag
        +-- atomically push branch + tag
                    |
                    v
GitHub Actions: Windows installer
                    |
                    +-- verify tag source
                    +-- derive exact version from tag
                    +-- synchronize release manifests in CI checkout
                    +-- run backend tests
                    +-- run frontend tests
                    +-- build frontend
                    +-- build backend sidecar
                    +-- smoke-test packaged backend
                    +-- build NSIS installer
                    +-- publish GitHub Release
```

The release tag is the authoritative release version.

If the tag is:

`v0.1.26`

the release build must use:

`0.1.26`

for the application/package manifests and the produced installer must be staged as:

`Telegram-Desktop-Setup-v0.1.26.exe`

---

## 5. Creating the next release

Preferred command from a clean local checkout of `feature/telegram-desktop-foundation`:

```powershell
.\scripts\tag-release.ps1
```

Default behavior is a patch bump.

Example:

`v0.1.25 -> v0.1.26`

Preview only:

```powershell
.\scripts\tag-release.ps1 -Preview
```

Minor bump:

```powershell
.\scripts\tag-release.ps1 -Bump minor
```

Example:

`v0.1.25 -> v0.2.0`

Major bump:

```powershell
.\scripts\tag-release.ps1 -Bump major
```

Example:

`v0.1.25 -> v1.0.0`

Do not manually invent a different release numbering scheme.

---

## 6. Release safety rules

The release helper must fail rather than guess.

It must refuse release when:

- the current branch is not `feature/telegram-desktop-foundation`;
- the working tree is dirty;
- the local development branch is behind or diverged from its remote branch;
- release manifests disagree;
- the next calculated tag already exists;
- semantic version syntax is invalid.

The helper uses an atomic push:

`git push --atomic`

The development branch update and release tag must either both reach the remote or neither should.

Do not replace this with separate non-atomic pushes without a strong reason and explicit review.

The helper must never:

- push `main`;
- run `git reset --hard`;
- run broad `git clean`;
- discard unrelated local changes;
- silently rewrite an existing release tag.

---

## 7. Version sources and synchronization

Historically this repository had version drift across multiple files.

Release-version manifests now must stay synchronized.

The checked-in version is represented in:

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src-tauri/tauri.conf.json`
- `frontend/src-tauri/Cargo.toml`
- `frontend/src-tauri/Cargo.lock`
- `pyproject.toml`

Check consistency with:

```powershell
python scripts/sync-version.py --check
```

Synchronize explicitly when needed with:

```powershell
python scripts/sync-version.py --set 1.2.3
```

Do not edit one version manifest and leave the others stale.

Development CI checks manifest consistency before running the rest of the test suite.

For an official tag build, CI derives the release version from the tag and synchronizes the release checkout before packaging.

---

## 8. GitHub Actions behavior

Development workflow:

`.github/workflows/development-ci.yml`

Normal pushes to:

`feature/telegram-desktop-foundation`

and pull requests run development checks.

They must not publish an official release.

Release workflow:

`.github/workflows/windows-installer.yml`

Official publishing is triggered by tags matching:

`v*`

A manually dispatched installer workflow may be used for build validation, but manual dispatch must not create an official GitHub Release.

Official GitHub Release publishing is tag-only.

---

## 9. Validation before integration

At minimum, run or verify:

```powershell
python scripts/sync-version.py --check
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-handoff
cd frontend
npm.cmd test
npm.cmd run build
```

Use focused tests while implementing and the relevant full suite before handoff.

Do not claim success if a relevant validation step was skipped without saying why.

---

## 10. Telegram session policy

Telegram authorization is sensitive durable state.

Never commit or expose:

- API hash;
- authorization/session keys;
- login codes;
- 2FA passwords;
- phone numbers when not required for the immediate interactive step;
- full V2Ray links;
- proxy passwords;
- `.session` files;
- runtime databases;
- private logs.

On a new computer, do not assume a Telegram session from another machine is valid or authorized for automatic reuse.

For a new machine, the intended safe flow is:

1. use valid approved Telegram API credentials;
2. create a new independent application session;
3. perform normal Telegram login using phone number, OTP, and 2FA if enabled;
4. keep the new session under the application's private data root;
5. verify Telegram status and Devices after login.

Do not silently import an old Telegram session, `telegram-portable.json`, or dashboard session unless the user explicitly requests that behavior.

`TELEGRAM_AUTO_IMPORT_SOURCE=false` must remain the safe default.

---

## 11. Dashboard isolation

The trading dashboard is a separate repository and separate product.

Telegram Desktop may only consume explicitly allowed dashboard connection configuration through read-only integration.

Do not modify dashboard:

- files;
- database;
- Telegram session;
- settings;
- runtime state.

Proxy/V2Ray configuration from the dashboard is read-only input.

If dashboard paths are used, verify that Telegram Desktop cannot write through them.

Before final handoff of work that touches integration, verify the dashboard repository has no unexpected diff.

---

## 12. Direct Telegram connectivity

`TELEGRAM_ALLOW_DIRECT` must remain `false` by default.

Do not automatically enable direct Telegram connectivity merely because proxy routes are unavailable.

Direct connectivity may be enabled only when explicitly requested by the user.

---

## 13. Local/runtime files that must not enter Git

Do not commit:

- `.env`
- `*.session`
- `telegram-portable.json`
- `settings.env`
- runtime databases
- `data/` runtime state
- private logs
- generated credentials
- packaged personal session bundles

Before committing or releasing, inspect the staged filenames and diff for secrets/runtime artifacts.

---

## 14. Message rendering invariant

Displayed message text must be trimmed before rendering.

Leading/trailing blank lines or whitespace must not enlarge message bubbles unnecessarily.

Preserve the existing trim behavior unless the product contract explicitly changes.

---

## 15. Working-tree discipline

Before changing code, inspect:

```powershell
git status
git log -1 --oneline
git branch --show-current
git fetch
```

Do not destroy unexplained user changes.

Do not use destructive cleanup merely to get a clean workspace.

Avoid unless explicitly authorized:

- `git reset --hard`
- broad `git clean`
- blanket stash
- broad restore

If unrelated user changes exist, preserve them and work around them safely.

---

## 16. Change discipline

Understand before changing.

Investigate broadly; change narrowly.

Each task should have one primary goal.

Do not mix unrelated:

- refactors;
- dependency upgrades;
- formatting sweeps;
- UX redesign;
- cleanup;
- architecture rewrites

into a focused fix.

Preserve durable/authoritative state over temporary UI state.

For persistence/networking/side effects, reason about restart, retries, duplicate delivery, partial failure, stale state, and ordering.

---

## 17. Release checklist

Before creating a release tag:

1. Be on `feature/telegram-desktop-foundation`.
2. Fetch remote state.
3. Confirm working tree is clean.
4. Confirm no unrelated/uncommitted work.
5. Run version-manifest check.
6. Run backend tests.
7. Run frontend tests.
8. Run frontend build.
9. Review diff.
10. Verify no secrets/runtime state are staged.
11. Use `tag-release.ps1 -Preview` if unsure which version will be created.
12. Create the release tag with the release helper.
13. Let GitHub Actions build and publish.
14. Verify the release installer name and tag match exactly.

Do not create a release merely to test whether the release workflow works. Use manual workflow dispatch for installer/build validation instead.

---

## 18. Handoff expectations

For a significant change, report:

- task / goal;
- behavior before;
- behavior after;
- root cause;
- files changed;
- tests added/updated;
- exact validation commands;
- exact results;
- skipped checks and why;
- invariants verified;
- known risks;
- unrelated issues found;
- git diff summary;
- git status;
- `SAFE TO REVIEW: YES/NO`.

Do not merge, push protected branches, or create official release tags unless the user explicitly authorizes that action.

---

## 19. Current release contract summary

Use this mental model:

```text
MAIN
  = historical baseline, not active development

FEATURE/TELEGRAM-DESKTOP-FOUNDATION
  = authoritative development branch

WORK/*
  = temporary implementation/review branches when useful

vMAJOR.MINOR.PATCH
  = authoritative official release version

release/v*
  = deprecated / not required for release

TAG
  -> validates source
  -> defines exact version
  -> runs tests/build
  -> creates versioned installer
  -> publishes GitHub Release
```

If a future task conflicts with this contract, stop and explain the conflict before changing release or Git semantics.
