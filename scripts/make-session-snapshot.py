from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    if not source.is_file():
        raise SystemExit(f"missing source: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()

    check = sqlite3.connect(str(target))
    try:
        row = check.execute(
            "SELECT dc_id, server_address, port, length(auth_key) FROM sessions LIMIT 1"
        ).fetchone()
    finally:
        check.close()

    if not row or not row[3] or int(row[3]) < 64:
        target.unlink(missing_ok=True)
        raise SystemExit("session snapshot is incomplete")

    print(f"session snapshot ready: dc={row[0]} server={row[1]}:{row[2]} key_bytes={row[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
