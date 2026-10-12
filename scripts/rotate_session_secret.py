"""Write a new session secret file. Restart the app afterwards; existing sessions stop working."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate the AlMaBi session secret file")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
    try:
        args.path.chmod(0o600)
    except OSError:
        pass
    print(f"Wrote a new session secret to {args.path}. Restart web to apply it.")


if __name__ == "__main__":
    main()
