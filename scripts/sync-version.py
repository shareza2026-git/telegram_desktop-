from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class VersionSyncError(RuntimeError):
    pass


def validate_version(value: str) -> str:
    value = value.strip()
    if not SEMVER.fullmatch(value):
        raise VersionSyncError(f"Release version must be MAJOR.MINOR.PATCH, got: {value!r}")
    return value


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _section_version(text: str, section: str, path: Path) -> str:
    match = re.search(
        rf"(?ms)^\[{re.escape(section)}\]\s*$.*?^version\s*=\s*\"([^\"]+)\"\s*$",
        text,
    )
    if not match:
        raise VersionSyncError(f"Could not find version in [{section}] of {path}")
    return match.group(1)


def _replace_section_version(text: str, section: str, version: str, path: Path) -> str:
    pattern = re.compile(
        rf"(?ms)(^\[{re.escape(section)}\]\s*$.*?^version\s*=\s*)\"[^\"]+\""
    )
    updated, count = pattern.subn(rf'\g<1>"{version}"', text, count=1)
    if count != 1:
        raise VersionSyncError(f"Could not update version in [{section}] of {path}")
    return updated


def _cargo_lock_version(text: str, path: Path) -> str:
    pattern = re.compile(
        r'(?ms)^\[\[package\]\]\s*$\nname\s*=\s*"telegram-desktop"\s*$\nversion\s*=\s*"([^"]+)"'
    )
    match = pattern.search(text)
    if not match:
        raise VersionSyncError(f"Could not find telegram-desktop package version in {path}")
    return match.group(1)


def _replace_cargo_lock_version(text: str, version: str, path: Path) -> str:
    pattern = re.compile(
        r'(?ms)(^\[\[package\]\]\s*$\nname\s*=\s*"telegram-desktop"\s*$\nversion\s*=\s*)"[^"]+"'
    )
    updated, count = pattern.subn(rf'\g<1>"{version}"', text, count=1)
    if count != 1:
        raise VersionSyncError(f"Could not update telegram-desktop package version in {path}")
    return updated


def collect_versions(root: Path) -> dict[str, str]:
    package_json_path = root / "frontend" / "package.json"
    package_lock_path = root / "frontend" / "package-lock.json"
    tauri_path = root / "frontend" / "src-tauri" / "tauri.conf.json"
    cargo_toml_path = root / "frontend" / "src-tauri" / "Cargo.toml"
    cargo_lock_path = root / "frontend" / "src-tauri" / "Cargo.lock"
    pyproject_path = root / "pyproject.toml"

    package_json = _read_json(package_json_path)
    package_lock = _read_json(package_lock_path)
    tauri = _read_json(tauri_path)
    cargo_toml = cargo_toml_path.read_text(encoding="utf-8")
    cargo_lock = cargo_lock_path.read_text(encoding="utf-8")
    pyproject = pyproject_path.read_text(encoding="utf-8")

    try:
        package_lock_root = package_lock["packages"][""]["version"]
    except (KeyError, TypeError) as exc:
        raise VersionSyncError(f"Could not find root package version in {package_lock_path}") from exc

    return {
        "frontend/package.json": str(package_json.get("version", "")),
        "frontend/package-lock.json": str(package_lock.get("version", "")),
        "frontend/package-lock.json#root": str(package_lock_root),
        "frontend/src-tauri/tauri.conf.json": str(tauri.get("version", "")),
        "frontend/src-tauri/Cargo.toml": _section_version(cargo_toml, "package", cargo_toml_path),
        "frontend/src-tauri/Cargo.lock": _cargo_lock_version(cargo_lock, cargo_lock_path),
        "pyproject.toml": _section_version(pyproject, "project", pyproject_path),
    }


def check_versions(root: Path) -> str:
    versions = collect_versions(root)
    unique = {validate_version(value) for value in versions.values()}
    if len(unique) != 1:
        details = ", ".join(f"{path}={value}" for path, value in versions.items())
        raise VersionSyncError(f"Version manifests are not synchronized: {details}")
    return unique.pop()


def set_version(root: Path, version: str) -> None:
    version = validate_version(version)

    package_json_path = root / "frontend" / "package.json"
    package_json = _read_json(package_json_path)
    package_json["version"] = version
    _write_json(package_json_path, package_json)

    package_lock_path = root / "frontend" / "package-lock.json"
    package_lock = _read_json(package_lock_path)
    package_lock["version"] = version
    try:
        package_lock["packages"][""]["version"] = version
    except (KeyError, TypeError) as exc:
        raise VersionSyncError(f"Could not find root package version in {package_lock_path}") from exc
    _write_json(package_lock_path, package_lock)

    tauri_path = root / "frontend" / "src-tauri" / "tauri.conf.json"
    tauri = _read_json(tauri_path)
    tauri["version"] = version
    _write_json(tauri_path, tauri)

    cargo_toml_path = root / "frontend" / "src-tauri" / "Cargo.toml"
    cargo_toml = cargo_toml_path.read_text(encoding="utf-8")
    cargo_toml_path.write_text(
        _replace_section_version(cargo_toml, "package", version, cargo_toml_path),
        encoding="utf-8",
    )

    cargo_lock_path = root / "frontend" / "src-tauri" / "Cargo.lock"
    cargo_lock = cargo_lock_path.read_text(encoding="utf-8")
    cargo_lock_path.write_text(
        _replace_cargo_lock_version(cargo_lock, version, cargo_lock_path),
        encoding="utf-8",
    )

    pyproject_path = root / "pyproject.toml"
    pyproject = pyproject_path.read_text(encoding="utf-8")
    pyproject_path.write_text(
        _replace_section_version(pyproject, "project", version, pyproject_path),
        encoding="utf-8",
    )

    actual = check_versions(root)
    if actual != version:
        raise VersionSyncError(f"Version synchronization produced {actual}, expected {version}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or synchronize release version manifests."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--set", dest="set_version_value", metavar="VERSION")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        if args.check:
            print(check_versions(root))
        else:
            set_version(root, args.set_version_value)
            print(args.set_version_value)
    except (OSError, json.JSONDecodeError, VersionSyncError) as exc:
        print(f"version-sync: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
