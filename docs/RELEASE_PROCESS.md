# Release Process

## Release state model

For this project:

```text
LIVE APPROVED
  local Desktop Telegram/live folder; last user-approved runnable version

DEVELOP
  feature/telegram-desktop-foundation

WORK
  work/* focused implementation/review branches

RELEASE CANDIDATE
  reviewed, validated commit on the development branch ready to tag

PUBLISHED RELEASE
  immutable vMAJOR.MINOR.PATCH tag + GitHub Release/installer

LIVE PROMOTED
  published artifact explicitly accepted for the local live installation
```

Publishing a tag must not silently overwrite the local `live` directory.

## Version contract

Official tags use:

`vMAJOR.MINOR.PATCH`

The tag is the authoritative package/release version.

Version manifests must stay synchronized across:

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src-tauri/tauri.conf.json`
- `frontend/src-tauri/Cargo.toml`
- `frontend/src-tauri/Cargo.lock`
- `pyproject.toml`

Check:

```powershell
python scripts/sync-version.py --check
```

## Before release

Do not tag merely to see whether packaging works.

Before an official tag:

1. planned work is integrated into `feature/telegram-desktop-foundation`;
2. review has no blocker;
3. working tree is clean;
4. branch is not behind/diverged from remote;
5. version manifests are consistent;
6. backend tests pass;
7. frontend tests pass;
8. frontend production build passes;
9. relevant packaging/security checks pass;
10. no secrets/runtime state are staged;
11. known release-blocking issues are resolved or explicitly accepted.

For installer-only validation without publishing a release, use the manual GitHub Actions dispatch path.

## Preview next version

```powershell
.\scripts\tag-release.ps1 -Preview
```

Default bump is patch.

## Publish next patch

```powershell
.\scripts\tag-release.ps1
```

Other bumps:

```powershell
.\scripts\tag-release.ps1 -Bump minor
.\scripts\tag-release.ps1 -Bump major
```

The helper validates branch/workspace/version state, creates an annotated tag, and atomically pushes development branch + tag.

## GitHub Actions

Tag workflow:

`.github/workflows/windows-installer.yml`

For a tag such as `v0.1.26`, CI:

1. verifies the tagged commit belongs to development history;
2. derives `0.1.26` from the tag;
3. synchronizes release manifests in the CI checkout;
4. installs dependencies;
5. runs backend tests;
6. runs frontend tests/build;
7. builds PyInstaller backend sidecar;
8. smoke-tests `/health` and private DB creation;
9. stages Xray;
10. builds Tauri/NSIS installer;
11. stages `Telegram-Desktop-Setup-v0.1.26.exe`;
12. publishes/updates the matching GitHub Release.

## Release safety

Never:

- rewrite an existing release tag;
- push release work to `main`;
- create a tag from an unrelated branch;
- package real sessions or credentials;
- overwrite `live` as a side effect of CI/tagging;
- run destructive Git cleanup to force a release.

## Local live promotion

Promotion into `Desktop Telegram\live` is separate from coding/tagging.

Before promotion:

- identify the exact tag/commit;
- validate the downloaded/built artifact;
- preserve the previous approved live version or rollback path;
- understand any persistence/schema compatibility;
- use the smallest safe smoke test.

If live validation fails, the previous approved live version must remain recoverable.

For schema/persistence changes, document rollback before promotion. A forward-only migration may require restoring pre-migration data before running older binaries.
