"""Local administration only; roles and employee bindings cannot be chosen via HTTP."""
import argparse
import getpass

from .auth import Auth
from .config import Settings
from .engine_port import DomainError
from .storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create an account; password is requested privately")
    create.add_argument("username")
    create.add_argument("--role", choices=["employee", "hr"], required=True)
    create.add_argument("--employee-id")
    reset = commands.add_parser("set-password", help="Replace password and revoke all sessions")
    reset.add_argument("username")
    disable = commands.add_parser("disable", help="Disable account and revoke all sessions")
    disable.add_argument("username")
    args = parser.parse_args()
    settings = Settings.from_env()
    store = Store(settings.db_path)
    store.initialize()
    auth = Auth(store, settings.session_ttl_seconds)
    try:
        if args.command == "disable":
            auth.disable_user(args.username)
        else:
            password = getpass.getpass("Пароль (12–256 символов): ")
            if password != getpass.getpass("Повторите пароль: "):
                parser.exit(2, "Пароли не совпадают\n")
            if args.command == "create":
                user = auth.create_user(args.username, password, args.role, args.employee_id)
                print(user.model_dump_json())
            else:
                auth.set_password(args.username, password)
        print("Готово")
    except (ValueError, DomainError) as exc:
        parser.exit(2, f"Ошибка: {exc}\n")


if __name__ == "__main__":
    main()
