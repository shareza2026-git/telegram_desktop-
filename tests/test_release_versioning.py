import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync-version.py"
spec = importlib.util.spec_from_file_location("sync_version", SCRIPT)
sync_version = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(sync_version)


def make_tree(root: Path, version: str = "0.1.25") -> None:
    (root / "frontend" / "src-tauri").mkdir(parents=True)
    (root / "frontend" / "package.json").write_text(
        json.dumps({"name": "telegram-desktop-ui", "version": version}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "frontend" / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "telegram-desktop-ui",
                "version": version,
                "packages": {"": {"version": version}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "frontend" / "src-tauri" / "tauri.conf.json").write_text(
        json.dumps({"version": version}, indent=2) + "\n", encoding="utf-8"
    )
    (root / "frontend" / "src-tauri" / "Cargo.toml").write_text(
        f'[package]\nname = "telegram-desktop"\nversion = "{version}"\n\n[dependencies]\ntauri = "2"\n',
        encoding="utf-8",
    )
    (root / "frontend" / "src-tauri" / "Cargo.lock").write_text(
        f'[[package]]\nname = "other"\nversion = "9.9.9"\n\n'
        f'[[package]]\nname = "telegram-desktop"\nversion = "{version}"\n'
        'dependencies = [\n "tauri",\n]\n',
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        f'[build-system]\nrequires = ["hatchling"]\n\n[project]\n'
        f'name = "telegram-desktop"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def test_checked_in_release_versions_are_synchronized():
    assert sync_version.check_versions(ROOT)


def test_check_rejects_manifest_drift(tmp_path: Path):
    make_tree(tmp_path)
    package = json.loads((tmp_path / "frontend" / "package.json").read_text(encoding="utf-8"))
    package["version"] = "0.1.24"
    (tmp_path / "frontend" / "package.json").write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(sync_version.VersionSyncError, match="not synchronized"):
        sync_version.check_versions(tmp_path)


def test_set_updates_every_release_manifest(tmp_path: Path):
    make_tree(tmp_path)
    sync_version.set_version(tmp_path, "1.2.3")
    assert set(sync_version.collect_versions(tmp_path).values()) == {"1.2.3"}
    cargo_lock = (tmp_path / "frontend" / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8")
    assert 'name = "other"\nversion = "9.9.9"' in cargo_lock


@pytest.mark.parametrize(
    "value",
    ["v1.2.3", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "1.2.03", "latest"],
)
def test_version_must_be_plain_semver(value: str):
    with pytest.raises(sync_version.VersionSyncError):
        sync_version.validate_version(value)


def test_release_workflow_is_tag_driven_and_uses_tag_version():
    workflow = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
    assert 'tags:\n      - "v*"' in workflow
    assert 'release/v*' not in workflow
    assert 'python scripts/sync-version.py --set $version' in workflow
    assert 'if: github.ref_type == \'tag\'' in workflow
    assert 'Telegram-Desktop-Setup-v${{ steps.release_version.outputs.version }}.exe' in workflow


def test_release_helper_is_atomic_and_never_pushes_main():
    helper = (ROOT / "scripts" / "tag-release.ps1").read_text(encoding="utf-8")
    assert '$ExpectedBranch = "feature/telegram-desktop-foundation"' in helper
    assert 'git status --porcelain=v1 --untracked-files=all' in helper
    assert 'push --atomic origin' in helper
    assert 'refs/heads/$ExpectedBranch' in helper
    assert 'refs/tags/$TagName' in helper
    assert 'refs/heads/main' not in helper
    assert 'reset --hard' not in helper
