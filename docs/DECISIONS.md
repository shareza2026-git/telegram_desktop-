# Decisions

Durable product/architecture decisions belong here. New evidence may justify revisiting a decision, but do not silently reopen settled choices.

---

## D-001 — Development and live are separate workspaces

Date: 2026-10-07

Decision:

Use separate parent folders for development and the last approved runnable version. Normal coding happens in `Desktop Telegram\dev`; `Desktop Telegram\live` is protected from ordinary development.

Why:

Prevents half-finished work, tests, migrations, or runtime artifacts from damaging the known-good user version.

Alternatives rejected:

Develop directly in the live copy.

Consequences:

Promotion to live is explicit and reversible/recoverable.

---

## D-002 — Existing feature branch is the development integration branch

Date: 2026-10-07

Decision:

`feature/telegram-desktop-foundation` is the authoritative integration/development branch for this repository.

Why:

The repository's `main` branch is an early baseline and the feature branch contains the actual developed history.

Alternatives rejected:

Restart active development from `main`; rename/rewrite branch history solely to match a generic template.

Consequences:

Generic `develop` references map to `feature/telegram-desktop-foundation`. Focused work uses `work/*`.

---

## D-003 — Official versions are tag-driven

Date: 2026-10-07

Decision:

Use immutable `vMAJOR.MINOR.PATCH` tags as the authoritative official release version.

Why:

The project previously had version drift across npm/Python/Tauri/Cargo and release scripts.

Alternatives rejected:

Independent manual version edits; release branches as a second version source.

Consequences:

`release/v*` is not required. CI derives package version from the tag and builds the matching installer. Local live promotion remains separate.

---

## D-004 — Fresh machines use a new independent Telegram session

Date: 2026-10-07

Decision:

Do not silently import/copy an old machine's Telegram session. Use approved API credentials and normal phone/code/2FA login for a new independent app session unless the user explicitly requests import/reuse.

Why:

Session authorization is sensitive durable identity state and should not be transferred by assumption.

Alternatives rejected:

Automatic use of old `telegram-portable.json` or source session.

Consequences:

Old session bootstrap behavior that can happen automatically is a blocker to harden before fresh-machine login.

---

## D-005 — Trading dashboard integration is read-only

Date: 2026-10-07

Decision:

Telegram Desktop and the trading dashboard remain separate repositories/products. Only explicitly allowed connection/proxy inputs may be read.

Why:

Protects dashboard runtime/session/database state and prevents accidental coupling.

Alternatives rejected:

Shared writable DB/session/config state.

Consequences:

Integration work must prove no dashboard writes occurred.

---

## D-006 — Direct Telegram connectivity is opt-in

Date: 2026-10-07

Decision:

`TELEGRAM_ALLOW_DIRECT=false` by default. Do not enable direct fallback automatically.

Why:

Route/security behavior is an explicit user decision.

Alternatives rejected:

Automatically falling back to direct connectivity whenever configured proxy routes fail or are absent.

Consequences:

Any code path that auto-enables direct connectivity must be corrected before relying on it.
