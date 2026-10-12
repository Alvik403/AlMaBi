"""Re-encrypt stored uploads with a new data key and replace the key file."""

from __future__ import annotations

import argparse
import hashlib
import secrets
from pathlib import Path

from almabi_file_crypto import read_key_material, reencrypt_log_file, reencrypt_tree


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate the AlMaBi upload encryption key")
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--uploads", type=Path, default=Path("uploads"))
    parser.add_argument("--logs", type=Path, default=Path("logs"))
    args = parser.parse_args()
    old_key = read_key_material(args.key_file)
    new_secret = secrets.token_urlsafe(48)
    new_key = hashlib.sha256(new_secret.encode("utf-8")).digest()
    count = reencrypt_tree(args.uploads, old_key, new_key)
    if args.logs.is_dir():
        for name in ("app.log", "errors.log", "retention.jsonl"):
            count += reencrypt_log_file(args.logs / name, old_key, new_key)
    args.key_file.write_text(new_secret + "\n", encoding="utf-8")
    try:
        args.key_file.chmod(0o600)
    except OSError:
        pass
    print(f"Re-encrypted {count} files and wrote a new data key to {args.key_file}.")


if __name__ == "__main__":
    main()
