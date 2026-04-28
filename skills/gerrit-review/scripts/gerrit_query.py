#!/usr/bin/env python3
"""Query Gerrit review data over SSH and normalize comments."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CHANGE_ID_RE = re.compile(r"^Change-Id:\s*(I[0-9a-fA-F]+)\s*$", re.MULTILINE)
AI_REVIEWER_RE = re.compile(r"\b(ai[-_\s]?reviewer|ai[-_.]?review|ai)\b", re.IGNORECASE)
SEVERITY_RE = re.compile(r"\[(Critical|Major|Minor|Nit|Info|Warning)\]", re.IGNORECASE)
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_DIR / "config" / "account.json"
DEFAULT_CONFIG_LABEL = "config/account.json"


@dataclass
class GerritRemote:
    user: str
    host: str
    port: str
    project: str


class MissingAccountConfig(Exception):
    pass


def account_config_path(value: str | None = None) -> Path:
    return Path(value or DEFAULT_CONFIG_PATH).expanduser()


def display_config_path(path: Path) -> str:
    if path.resolve() == DEFAULT_CONFIG_PATH.resolve():
        return DEFAULT_CONFIG_LABEL
    return str(path)


def redact(value: str | None) -> str | None:
    if not value:
        return value
    return "<set>"


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


def remote_from_config(config: dict[str, Any]) -> GerritRemote:
    account = config.get("account") or {}
    return GerritRemote(
        user=str(account.get("user", "")),
        host="",
        port="29418",
        project="",
    )


def remote_from_context(context: dict[str, Any]) -> GerritRemote | None:
    remote = context.get("remote")
    if not isinstance(remote, dict):
        return None
    return GerritRemote(
        user=str(remote.get("user", "")),
        host=str(remote.get("host", "")),
        port=str(remote.get("port", "29418") or "29418"),
        project=str(remote.get("project", "")),
    )


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check)


def git(args: list[str]) -> str:
    return run(["git", *args]).stdout.strip()


def parse_change_id(message: str) -> str | None:
    match = CHANGE_ID_RE.search(message)
    return match.group(1) if match else None


def parse_remote(remote_text: str) -> GerritRemote | None:
    for line in remote_text.splitlines():
        if "(fetch)" not in line:
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        url = fields[1]
        if "gerrit" not in url.lower():
            continue
        if url.startswith("ssh://"):
            parsed = urlparse(url)
            if not parsed.hostname:
                continue
            return GerritRemote(
                user=parsed.username or "",
                host=parsed.hostname,
                port=str(parsed.port or 29418),
                project=parsed.path.lstrip("/"),
            )
        scp_like = re.match(r"(?:(?P<user>[^@]+)@)?(?P<host>[^:]+):(?P<project>.+)", url)
        if scp_like:
            return GerritRemote(
                user=scp_like.group("user") or "",
                host=scp_like.group("host"),
                port="29418",
                project=scp_like.group("project"),
            )
    return None


def ssh_gerrit(remote: GerritRemote, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    destination = f"{remote.user}@{remote.host}" if remote.user else remote.host
    return run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-p",
            remote.port,
            destination,
            "gerrit",
            *args,
        ],
        check=check,
    )


def parse_json_lines(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("type") == "stats":
            continue
        rows.append(row)
    return rows


def reviewer_name(reviewer: dict[str, Any] | None) -> str:
    if not reviewer:
        return ""
    return reviewer.get("name") or reviewer.get("username") or reviewer.get("email") or ""


def is_ai_reviewer(reviewer: dict[str, Any] | None) -> bool:
    if not reviewer:
        return False
    text = " ".join(str(reviewer.get(key, "")) for key in ("name", "username", "email"))
    return bool(AI_REVIEWER_RE.search(text))


def infer_severity(message: str) -> str | None:
    match = SEVERITY_RE.search(message)
    return match.group(1).lower() if match else None


def normalize_inline_comments(change: dict[str, Any]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for patch_set in change.get("patchSets", []):
        patch_number = patch_set.get("number")
        for comment in patch_set.get("comments", []):
            reviewer = comment.get("reviewer")
            message = comment.get("message", "")
            comments.append(
                {
                    "patchSet": patch_number,
                    "file": comment.get("file"),
                    "line": comment.get("line"),
                    "reviewer": reviewer_name(reviewer),
                    "reviewerRaw": reviewer,
                    "isAiReviewer": is_ai_reviewer(reviewer),
                    "severity": infer_severity(message),
                    "message": message,
                }
            )
    current = change.get("currentPatchSet", {})
    current_number = current.get("number")
    current_existing = {
        (item.get("patchSet"), item.get("file"), item.get("line"), item.get("message"))
        for item in comments
    }
    for comment in current.get("comments", []):
        reviewer = comment.get("reviewer")
        message = comment.get("message", "")
        key = (current_number, comment.get("file"), comment.get("line"), message)
        if key in current_existing:
            continue
        comments.append(
            {
                "patchSet": current_number,
                "file": comment.get("file"),
                "line": comment.get("line"),
                "reviewer": reviewer_name(reviewer),
                "reviewerRaw": reviewer,
                "isAiReviewer": is_ai_reviewer(reviewer),
                "severity": infer_severity(message),
                "message": message,
            }
        )
    return comments


def collect_local_context() -> dict[str, Any]:
    head = git(["rev-parse", "HEAD"])
    commit_message = git(["log", "-1", "--pretty=format:%B"])
    remote_text = git(["remote", "-v"])
    branch_text = git(["branch", "-vv"])
    remote = parse_remote(remote_text)
    return {
        "head": head,
        "commitMessage": commit_message,
        "changeId": parse_change_id(commit_message),
        "remoteText": remote_text,
        "branchText": branch_text,
        "remote": remote.__dict__ if remote else None,
    }


def build_queries(args: argparse.Namespace, context: dict[str, Any]) -> list[str]:
    queries: list[str] = []
    if args.change:
        queries.append(str(args.change))
    if args.query:
        queries.append(args.query)
    if context.get("head"):
        queries.append(context["head"])
    if context.get("changeId"):
        queries.append(f"change:{context['changeId']}")
    return list(dict.fromkeys(queries))


def query_change(remote: GerritRemote, query: str) -> dict[str, Any] | None:
    result = ssh_gerrit(
        remote,
        [
            "query",
            "--format=JSON",
            "--current-patch-set",
            "--patch-sets",
            "--all-approvals",
            "--comments",
            "--all-reviewers",
            "--submit-records",
            query,
            "limit:1",
        ],
    )
    rows = parse_json_lines(result.stdout)
    return rows[0] if rows else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change", help="Gerrit change number to query")
    parser.add_argument("--query", help="Raw Gerrit query expression")
    parser.add_argument("--host", help="Override Gerrit SSH host")
    parser.add_argument("--port", default=None, help="Override Gerrit SSH port")
    parser.add_argument("--user", help="Override Gerrit SSH username")
    parser.add_argument("--project", help="Override Gerrit project name")
    parser.add_argument("--config", help=f"Account config path. Defaults to skill-local {DEFAULT_CONFIG_LABEL}")
    parser.add_argument("--show-config", action="store_true", help="Show loaded account config with non-secret fields")
    parser.add_argument("--diagnose", action="store_true", help="Only test Gerrit SSH access")
    parser.add_argument("--raw", action="store_true", help="Include raw Gerrit change JSON")
    args = parser.parse_args()

    config_path = account_config_path(args.config)
    try:
        config = load_account_config(config_path)
    except MissingAccountConfig as error:
        print(str(error), file=sys.stderr)
        return 2

    config_remote = remote_from_config(config)
    if args.show_config:
        account = config.get("account") or {}
        print(
            json.dumps(
                {
                    "config_path": display_config_path(config_path),
                    "account": {
                        "user": redact(account.get("user")),
                        "base_url": redact(account.get("base_url")),
                        "password": redact(account.get("password")) or "",
                        "auth_header": redact(account.get("auth_header")) or "",
                    },
                    "ssh": "inferred from git remote or --host/--port",
                },
                indent=2,
            )
        )
        return 0

    context = collect_local_context()
    local_remote = remote_from_context(context)
    remote = GerritRemote(
        user=args.user or config_remote.user or (local_remote.user if local_remote else ""),
        host=args.host or (local_remote.host if local_remote else "") or config_remote.host,
        port=args.port or (local_remote.port if local_remote else "") or config_remote.port,
        project=args.project or (local_remote.project if local_remote else "") or config_remote.project,
    )
    if not remote.host:
        print("Could not infer Gerrit host from git remote. Pass --host.", file=sys.stderr)
        return 2

    if args.diagnose:
        result = ssh_gerrit(remote, ["version"], check=False)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        return result.returncode

    change = None
    used_query = None
    errors: list[dict[str, str]] = []
    for query in build_queries(args, context):
        try:
            change = query_change(remote, query)
        except subprocess.CalledProcessError as error:
            errors.append({"query": query, "stderr": error.stderr.strip()})
            continue
        if change:
            used_query = query
            break

    if not change:
        print(json.dumps({"local": context, "errors": errors, "change": None}, indent=2))
        return 1

    current = change.get("currentPatchSet", {})
    output: dict[str, Any] = {
        "local": context,
        "remote": remote.__dict__,
        "query": used_query,
        "change": {
            "project": change.get("project"),
            "branch": change.get("branch"),
            "id": change.get("id"),
            "number": change.get("number"),
            "subject": change.get("subject"),
            "url": change.get("url"),
            "status": change.get("status"),
            "open": change.get("open"),
            "currentPatchSet": {
                "number": current.get("number"),
                "revision": current.get("revision"),
                "ref": current.get("ref"),
                "kind": current.get("kind"),
                "approvals": current.get("approvals", []),
            },
            "submitRecords": change.get("submitRecords", []),
            "allReviewers": change.get("allReviewers", []),
            "messages": change.get("comments", []),
            "inlineComments": normalize_inline_comments(change),
        },
        "isHeadCurrentPatchSet": context.get("head") == current.get("revision"),
    }
    if args.raw:
        output["rawChange"] = change
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
