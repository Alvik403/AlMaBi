from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from almabi_auth_store import AuthStore  # noqa: E402
from settings import get_settings  # noqa: E402


def _password(prompt: str) -> str:
    value = getpass.getpass(prompt)
    if len(value) < 12:
        raise SystemExit("Пароль должен содержать не менее 12 символов")
    if value != getpass.getpass("Повторите пароль: "):
        raise SystemExit("Пароли не совпадают")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление локальными пользователями AlMaBi")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap", help="Создать первого администратора")
    bootstrap.add_argument("username")
    create = commands.add_parser("create", help="Создать пользователя")
    create.add_argument("username")
    create.add_argument("role", choices=("admin", "uploader", "viewer"))
    password = commands.add_parser("password", help="Сменить пароль")
    password.add_argument("username")
    disable = commands.add_parser("disable", help="Отключить пользователя")
    disable.add_argument("username")
    commands.add_parser("list", help="Показать пользователей")
    args = parser.parse_args()

    store = AuthStore(get_settings().resolved_auth_db)
    if args.command == "bootstrap":
        user = store.bootstrap(args.username, _password("Пароль администратора: "))
        print(f"Создан {user.username} ({user.role})")
    elif args.command == "create":
        user = store.create_user(args.username, _password("Пароль: "), args.role)
        print(f"Создан {user.username} ({user.role})")
    elif args.command == "password":
        store.update_password(args.username, _password("Новый пароль: "))
        print("Пароль изменён; активные сессии отозваны")
    elif args.command == "disable":
        store.disable_user(args.username)
        print("Пользователь отключён; активные сессии отозваны")
    else:
        for user in store.list_users():
            status = "active" if user.enabled else "disabled"
            print(f"{user.username}\t{user.role}\t{status}")


if __name__ == "__main__":
    main()
