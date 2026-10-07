# Engineering Workflow

## Parent directory model

Preferred Windows project root:

```text
C:\Users\<USER>\Desktop\Desktop Telegram\
  live\
  dev\
  review\
  prompts\
  tools\
  launchers\
```

The screenshot-confirmed core separation is `dev\` vs `live\`.

### live

Last user-approved runnable version.

Do not develop inside it, run destructive tests against it, reuse its runtime DB for automated tests, or overwrite it as a side effect of coding.

Promotion into `live` is an explicit operation.

### dev

Main Git working copy. Normal agent/Codex work happens here.

### review

Outside the Git repo. Intended for sanitized reports, patches, review ZIPs, and offline Git bundles.

### prompts / tools / launchers

Create/use only when the project actually needs them. Do not add empty structure merely for appearance.

## Repository branch adaptation

This repository has an established history that differs from the generic `develop` naming.

Mapping:

```text
generic DEVELOP  -> feature/telegram-desktop-foundation
generic WORK     -> work/*
generic MAIN     -> not currently used for active development
release version  -> vMAJOR.MINOR.PATCH tag
```

Do not continue from `main`.

## Normal task flow

```text
feature/telegram-desktop-foundation
  -> work/<focused-name>
  -> investigate
  -> implement narrowly
  -> focused tests
  -> full relevant validation
  -> review
  -> at most one normal targeted correction round
  -> approval
  -> integrate to feature/telegram-desktop-foundation
  -> update checkpoint docs when meaningful
```

Remote work branches may be used when review/CI collaboration requires them.

## Before coding

State internally:

- current behavior
- required behavior
- root cause/design gap
- authoritative source of truth
- must-remain-unchanged behavior
- expected files
- blast radius
- validation strategy

Trace the affected path end-to-end before editing.

## Scope control

One branch/task has one primary goal.

Unrelated findings go to `docs/KNOWN_ISSUES.md` unless they block correctness, security, data integrity, or the explicit exit criteria.

## Review discipline

Default:

implementation → tests → one review → at most one normal correction round → final approve/block.

Blockers include correctness, security, data loss, invalid migration, serious race/durability failure, or explicit requirement failure.

Polish/naming/speculative refactor is normally non-blocking and deferred.

## Database changes

Design first.

Define identity, uniqueness, foreign keys/checks/indexes, migration behavior, old-data behavior, restart behavior, idempotency, and rollback/downgrade policy.

Test with temporary databases, never live data.

## Review artifacts

When useful, place sanitized artifacts outside the repo under:

`Desktop Telegram\review\...`

Typical contents:

- report
- changed-file inventory
- complete patch
- changed source/test/docs
- optional review ZIP

Never include sessions, secrets, runtime DBs, logs, dependency folders, build caches, or personal runtime configuration.

## Session start

1. identify goal
2. read `AGENTS.md`
3. read `docs/CURRENT_STATUS.md`
4. read relevant contract/design docs
5. inspect branch/status/HEAD
6. inspect only relevant code/tests
7. continue from documented checkpoint

## Session end

Record tests/results, meaningful blockers, exact branch/state, whether changes are uncommitted/committed/pushed/merged/released, and update `CURRENT_STATUS.md` only when the checkpoint materially changed.
