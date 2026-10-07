from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.telegram.transport import TransportCatalog


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Store one private Telegram proxy/VLESS route without printing its secret."
    )
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--xray-core", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw = sys.stdin.readline().strip()
    if not raw:
        print("proxy-config: no proxy link was provided", file=sys.stderr)
        return 2

    catalog = TransportCatalog(
        args.catalog.resolve(),
        xray_core_path=args.xray_core.resolve() if args.xray_core else None,
    )
    try:
        result = catalog.add_proxy_link(raw)
    except ValueError as exc:
        print(f"proxy-config: {exc}", file=sys.stderr)
        return 2

    # Never echo the proxy/VLESS URI, host, credentials, or secret.
    print(f"configured_index={int(result['index'])}")
    print(f"configured_type={result['type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
