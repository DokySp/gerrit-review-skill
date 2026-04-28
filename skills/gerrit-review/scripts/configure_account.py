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


def prompt_text(label: str, existing: str = "") -> str:
    suffix = " [keep existing]" if existing else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or existing


def prompt_secret(label: str, existing: str = "") -> str:
    suffix = " [leave blank to keep existing]" if existing else ""
    value = getpass.getpass(f"{label}{suffix}: ")
    return value or existing


def build_interactive_config(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    account = dict((existing or {}).get("account") or {})

    account["user"] = prompt_text("Gerrit account username", str(account.get("user", "")))
    account["base_url"] = prompt_text("Gerrit REST base URL", str(account.get("base_url", "")))

    existing_auth_header = str(account.get("auth_header", ""))
    existing_password = str(account.get("password", ""))
    default_method = "auth-header" if existing_auth_header else "password"
    method = input(
        "REST authentication method [password/auth-header/none] "
        f"(default {default_method}): "
    ).strip().lower() or default_method

    if method == "password":
        account["password"] = prompt_secret("Gerrit HTTP password", existing_password)
        account.pop("auth_header", None)
    elif method == "auth-header":
        account["auth_header"] = prompt_secret(
            "REST auth header, formatted as 'Header-Name: value'",
            existing_auth_header,
        )
        account["password"] = ""
    elif method == "none":
        account["password"] = ""
        account.pop("auth_header", None)
    else:
        raise ValueError("authentication method must be password, auth-header, or none")

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
    args = parser.parse_args()

    path = config_path(args.config)
    if args.show:
        if not path.exists():
            print(
                json.dumps(
                    {
                        "configured": False,
                        "config_path": display_path(path),
                        "next_step": "Run scripts/configure_account.py and enter values at the prompts",
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
    try:
        config = build_interactive_config(existing)
    except ValueError as error:
        parser.error(str(error))
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
