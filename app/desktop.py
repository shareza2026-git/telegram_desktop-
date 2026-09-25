import argparse
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram Desktop local backend")
    parser.add_argument("--data-root", required=True, help="Writable private client data directory")
    parser.add_argument("--portable-config", help="Canonical writable portable Telegram bundle")
    parser.add_argument("--portable-mirror", help="Optional external mirror of the portable Telegram bundle")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = Path(args.data_root).expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)

    # Load secrets from a user-owned file outside the installed application.
    # Existing process environment variables keep priority over file values.
    from dotenv import load_dotenv

    load_dotenv(data_root / "settings.env", override=False)
    os.environ["TELEGRAM_CLIENT_DATA_ROOT"] = str(data_root)
    if args.portable_config:
        os.environ["TELEGRAM_PORTABLE_CONFIG"] = str(Path(args.portable_config).expanduser().resolve())
    if args.portable_mirror:
        os.environ["TELEGRAM_PORTABLE_MIRROR_CONFIG"] = str(Path(args.portable_mirror).expanduser().resolve())
    os.environ.setdefault(
        "TELEGRAM_SESSION_PATH",
        str(data_root / "accounts" / "default" / "client"),
    )
    os.environ.setdefault(
        "TELEGRAM_DATABASE_PATH",
        str(data_root / "accounts" / "default" / "client.db"),
    )

    import uvicorn
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8110, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
