"""Шифрование выгрузок на диске (AES-GCM). Без ключа файлы остаются как есть."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

MAGIC = b"ALMABIENC1"
_NONCE_LEN = 12
_KEY: bytes | None = None


def configure_data_key(key: bytes | None) -> None:
    global _KEY
    _KEY = key


def current_data_key() -> bytes | None:
    return _KEY


def read_key_material(path: Path) -> bytes:
    raw = path.read_bytes().strip()
    if len(raw) == 32:
        return raw
    text = raw.decode("utf-8").strip()
    if len(text) < 32:
        raise ValueError("data key file must contain 32 raw bytes or at least 32 characters")
    return hashlib.sha256(text.encode("utf-8")).digest()


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(_NONCE_LEN)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, None)


def is_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not is_encrypted(data):
        raise ValueError("file is not encrypted")
    body = data[len(MAGIC) :]
    nonce, ciphertext = body[:_NONCE_LEN], body[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def append_protected_line(path: Path, line: str) -> None:
    """Дописать строку журнала. При заданном ключе строка шифруется, консоль не трогается."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = line.rstrip("\n")
    key = current_data_key()
    if key is None:
        payload = text + "\n"
    else:
        payload = base64.b64encode(encrypt_bytes(text.encode("utf-8"), key)).decode("ascii") + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(payload)


def read_protected_text(path: Path, key: bytes | None = None) -> str:
    if key is None:
        key = current_data_key()
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw:
            continue
        decoded = b""
        try:
            decoded = base64.b64decode(raw, validate=True)
        except ValueError:
            decoded = b""
        if key is not None and is_encrypted(decoded):
            lines.append(decrypt_bytes(decoded, key).decode("utf-8"))
        else:
            lines.append(raw)
    return "\n".join(lines)


def store_upload_bytes(path: Path, contents: bytes) -> None:
    key = current_data_key()
    if key is None:
        path.write_bytes(contents)
        return
    path.write_bytes(encrypt_bytes(contents, key))


def _plaintext_dir(stored: Path) -> Path:
    directory = stored.parent / ".plaintext"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def purge_plaintext_temps(uploads_root: Path, *, max_age_seconds: int = 15 * 60) -> None:
    import time

    if not uploads_root.exists():
        return
    cutoff = time.time() - max_age_seconds
    for directory in uploads_root.rglob(".plaintext"):
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink(missing_ok=True)
            except OSError:
                continue


def materialize_plaintext(path: Path) -> Path:
    """Вернуть путь к открытому xlsx. Шифротекст расшифровывается во временный файл."""
    purge_plaintext_temps(path.parent)
    try:
        header = path.read_bytes()[: len(MAGIC)]
    except OSError:
        return path
    if header != MAGIC:
        return path
    key = current_data_key()
    if key is None:
        raise ValueError("Файл зашифрован, но ключ данных не задан")
    plain = decrypt_bytes(path.read_bytes(), key)
    temp = _plaintext_dir(path) / f"{os.urandom(8).hex()}.xlsx"
    temp.write_bytes(plain)
    return temp


def reencrypt_log_file(path: Path, old_key: bytes, new_key: bytes) -> int:
    """Перешифровать построчный журнал. Открытые строки тоже закрываются новым ключом."""
    if not path.is_file():
        return 0
    lines = read_protected_text(path, old_key).splitlines()
    path.write_text("", encoding="utf-8")
    previous = current_data_key()
    configure_data_key(new_key)
    try:
        for line in lines:
            if line:
                append_protected_line(path, line)
    finally:
        configure_data_key(previous)
    return len([line for line in lines if line])


def reencrypt_tree(uploads_root: Path, old_key: bytes, new_key: bytes) -> int:
    count = 0
    if not uploads_root.exists():
        return 0
    for path in uploads_root.rglob("*"):
        if not path.is_file() or ".plaintext" in path.parts:
            continue
        data = path.read_bytes()
        plain = decrypt_bytes(data, old_key) if is_encrypted(data) else data
        path.write_bytes(encrypt_bytes(plain, new_key))
        count += 1
    return count
