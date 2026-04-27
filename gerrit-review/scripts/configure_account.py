#!/usr/bin/env python3
"""Create, update, or inspect the local Gerrit Review account configuration."""

from __future__ import annotations

import argparse
import getpass
import json
import stat
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_DIR / "config" / "account.json"
DEFAULT_CONFIG_LABEL = "config/account.json"


def config_path(value: str | None = None) -> Path:
    return Path(value or DEFAULT_CONFIG_PATH).expanduser()


def display_path(path: Path) -> str:
    if path.resolve() == DEFAULT_CONFIG_PATH.resolve():
        return DEFAULT_CONFIG_LABEL
    return str(path)


def redact(value: str | None) -> str | None:
    if not value:
        return value
    return "<set>"


def read_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_config(args: argparse.Namespace, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    account = dict((existing or {}).get("account") or {})

    if args.user is not None:
        account["user"] = args.user
    if args.base_url is not None:
        account["base_url"] = args.base_url
    if args.password is not None:
        account["password"] = args.password
    if args.prompt_password:
        account["password"] = getpass.getpass("Gerrit HTTP password: ")
    account.setdefault("password", "")

    if args.auth_header:
        account["auth_header"] = args.auth_header
    return {"account": account}


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    account = config.get("account") or {}
    for key in ("user", "base_url"):
        if not account.get(key):
            errors.append(f"missing account.{key}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help=f"Config path. Defaults to skill-local {DEFAULT_CONFIG_LABEL}")
    parser.add_argument("--show", action="store_true", help="Show the current config with secrets redacted")
    parser.add_argument("--user", help="Gerrit account username used for both SSH and REST")
    parser.add_argument("--base-url", help="Gerrit account base URL")
    parser.add_argument("--password", help="Gerrit HTTP password for REST authentication")
    parser.add_argument("--auth-header", help="Full REST auth header value, formatted as 'Header-Name: value'")
    parser.add_argument(
        "--prompt-password",
        action="store_true",
        help="Prompt for a Gerrit HTTP password and store it in the skill-local config",
    )
    args = parser.parse_args()

    path = config_path(args.config)
    if args.show:
        if not path.exists():
            print(
                json.dumps(
                    {
                        "configured": False,
                        "config_path": display_path(path),
                        "next_step": (
                            "Run scripts/configure_account.py --user <user> --base-url <url> --prompt-password"
                        ),
                    },
                    indent=2,
                )
            )
            return 1
        config = read_config(path)
        redacted = json.loads(json.dumps(config))
        account = redacted.get("account") or {}
        account["user"] = redact(account.get("user"))
        account["password"] = redact(account.get("password"))
        account["base_url"] = redact(account.get("base_url"))
        account["auth_header"] = redact(account.get("auth_header"))
        errors = validate_config(config)
        print(
            json.dumps(
                {
                    "configured": not errors,
                    "config_path": display_path(path),
                    "missing": errors,
                    "config": redacted,
                },
                indent=2,
            )
        )
        return 0

    existing = read_config(path) if path.exists() else {}
    has_update = any(
        value is not None
        for value in (args.user, args.base_url, args.password, args.auth_header)
    ) or args.prompt_password
    if not has_update:
        parser.error("provide at least one setting to update, or use --show")

    config = build_config(args, existing)
    errors = validate_config(config)
    if errors:
        parser.error("; ".join(errors))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(json.dumps({"configured": True, "config_path": display_path(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
