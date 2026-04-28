#!/usr/bin/env python3
"""Create or dry-run Gerrit draft comments through the REST API."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


XSSI_PREFIX = ")]}'"
CODEX_PREFIX = "[Codex로 생성됨]"
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_DIR / "config" / "account.json"
DEFAULT_CONFIG_LABEL = "config/account.json"


class MissingAccountConfig(Exception):
    pass


def account_config_path(value: str | None = None) -> Path:
    return Path(value or DEFAULT_CONFIG_PATH).expanduser()


def display_config_path(path: Path) -> str:
    if path.resolve() == DEFAULT_CONFIG_PATH.resolve():
        return DEFAULT_CONFIG_LABEL
    return str(path)


def redact_url(url: str) -> str:
    return "<redacted-base-url>" if url else ""


def redact_error(error: BaseException, base: str) -> str:
    return str(error).replace(base, redact_url(base)) if base else str(error)


def account_config_guidance(path: Path) -> dict[str, Any]:
    return {
        "configured": False,
        "config_path": display_config_path(path),
        "message": "Gerrit account config is required before using gerrit-review.",
        "next_step": "scripts/configure_account.py",
    }


def load_account_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingAccountConfig(json.dumps(account_config_guidance(path), indent=2))
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    account = config.get("account") or {}
    missing = [f"account.{key}" for key in ("user", "base_url") if not account.get(key)]
    if missing:
        guidance = account_config_guidance(path)
        guidance["missing"] = missing
        raise MissingAccountConfig(json.dumps(guidance, indent=2))
    return config


def load_json(path: str | None) -> Any:
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return json.load(sys.stdin)


def iter_replies(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("replies", "comments", "drafts"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("Input must be a list or an object with replies/comments/drafts list")


def ensure_codex_prefix(message: str) -> str:
    stripped = message.lstrip()
    if stripped.startswith(CODEX_PREFIX):
        return message
    return f"{CODEX_PREFIX} {message}"


def build_comment_input(reply: dict[str, Any]) -> dict[str, Any] | None:
    path = reply.get("file") or reply.get("path")
    message = reply.get("reply") or reply.get("draft") or reply.get("message")
    if not path or not message:
        return None
    body: dict[str, Any] = {
        "path": path,
        "message": ensure_codex_prefix(message),
        "unresolved": bool(reply.get("unresolved", False)),
    }
    if reply.get("line") is not None:
        body["line"] = int(reply["line"])
    if reply.get("range") is not None:
        body["range"] = reply["range"]
    if reply.get("in_reply_to") is not None:
        body["in_reply_to"] = reply["in_reply_to"]
    return body


def rest_request(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="PUT")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    for key, value in headers.items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("utf-8")
    if text.startswith(XSSI_PREFIX):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    return json.loads(text) if text.strip() else {}


def build_headers(config: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    account = config.get("account") or {}
    auth_header = account.get("auth_header")
    account_user = account.get("user")
    password = account.get("password")
    if auth_header:
        key, _, value = auth_header.partition(":")
        if not key or not value:
            raise ValueError("account.auth_header must be formatted as 'Header-Name: value'")
        headers[key.strip()] = value.strip()
    elif password:
        if not account_user:
            raise ValueError("account.password is set, but account.user is missing")
        token = base64.b64encode(f"{account_user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return headers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="JSON file containing reply drafts; defaults to stdin")
    parser.add_argument("--config", help=f"Account config path. Defaults to skill-local {DEFAULT_CONFIG_LABEL}")
    parser.add_argument("--base-url", help="Gerrit base URL override")
    parser.add_argument("--change", required=True, help="Change number or URL-encoded change id")
    parser.add_argument("--revision", required=True, help="Revision id, patch set number, or commit SHA")
    parser.add_argument("--execute", action="store_true", help="Create drafts. Without this, only print dry-run requests.")
    args = parser.parse_args()

    config_path = account_config_path(args.config)
    try:
        config = load_account_config(config_path)
    except MissingAccountConfig as error:
        print(str(error), file=sys.stderr)
        return 2

    headers = build_headers(config)
    if args.execute and not headers:
        print(
            json.dumps(
                {
                    "configured": True,
                    "config_path": display_config_path(config_path),
                    "message": "REST authentication is required for --execute.",
                    "next_step": (
                        "Run scripts/configure_account.py and enter REST authentication "
                        "at the prompt."
                    ),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    replies = iter_replies(load_json(args.input))
    requests: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    base = (args.base_url or (config.get("account") or {}).get("base_url", "")).rstrip("/")
    endpoint = f"{base}/a/changes/{args.change}/revisions/{args.revision}/drafts"

    for reply in replies:
        body = build_comment_input(reply)
        if body is None:
            skipped.append(reply)
            continue
        requests.append(
            {
                "method": "PUT",
                "url": endpoint,
                "display_url": f"{redact_url(base)}/a/changes/{args.change}/revisions/{args.revision}/drafts",
                "body": body,
            }
        )

    result: dict[str, Any] = {
        "dryRun": not args.execute,
        "summary": {
            "mode": "draft_create",
            "requestCount": len(requests),
            "skippedCount": len(skipped),
            "baseUrl": redact_url(base),
            "change": args.change,
            "revision": args.revision,
            "draftOnly": True,
            "published": False,
        },
        "requests": requests,
        "skipped": skipped,
    }

    if args.execute:
        responses = []
        for item in requests:
            try:
                responses.append(rest_request(item["url"], item["body"], headers))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                raise SystemExit(f"HTTP {error.code}: {detail.replace(base, redact_url(base))}") from error
            except Exception as error:
                raise SystemExit(f"REST draft creation failed: {redact_error(error, base)}") from error
        for item in requests:
            item["url"] = item.pop("display_url")
        result["responses"] = responses
    else:
        for item in requests:
            item["url"] = item.pop("display_url")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
