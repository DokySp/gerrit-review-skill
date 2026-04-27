---
name: gerrit-review
description: Analyze Gerrit patch set reviews from a local git checkout, especially AI reviewer comments. Use when Codex needs to configure Gerrit account settings, identify the Gerrit change for the current HEAD or a provided change number, fetch patch set metadata and inline comments, validate comments against real code and call paths, classify false positives, draft Gerrit replies, or prepare/post draft or actual review comments.
---

# Gerrit Review

## Overview

Use this skill to inspect Gerrit reviews from a local repository, validate AI reviewer comments against the current code, and prepare comment replies. Keep reading, draft creation, draft publishing, and actual comment publishing as separate modes. If the user asks for drafts, stop after draft creation and do not publish those drafts unless the user later gives an explicit publish request.

## Workflow

0. Check account configuration first:
   - Run `scripts/configure_account.py --show` or use scripts that load the skill-local `config/account.json`.
   - If account config is missing or incomplete, stop immediately. Do not collect repo context, query Gerrit, build draft requests, or post anything.
   - Guide the user to configure the account:
     `scripts/configure_account.py --user <gerrit-user> --base-url <gerrit-rest-base-url> --prompt-password`.
   - Distribute `config/account.json` as an empty placeholder. It must contain no real user, password, or base URL values.
   - Before committing or publishing the skill, verify `config/account.json` is still empty and contains only blank `account.user`, `account.password`, and `account.base_url` fields.
   - Store Gerrit account and REST authentication in the skill-local config file, not environment variables. Use `account.user`, `account.password`, and `account.base_url`, or `account.auth_header` formatted as `Header-Name: value`.
   - Prefer `--prompt-password` for password setup because it avoids putting the password directly in shell history. `--password <value>` is supported only for non-interactive automation.
   - If `account.user` and `account.base_url` are already configured, `scripts/configure_account.py --prompt-password` may be used by itself to update only `account.password`.
   - Reuse `account.user` for both SSH and REST. Do not store a separate `ssh.user` or `rest.user`.
   - Do not store Gerrit SSH host, SSH port, project, or package in the account config. Infer SSH host/port from `git remote -v`; use `scripts/gerrit_query.py --host <host> --port <port>` only as an explicit override.
   - Keep any required Gerrit REST context path in `account.base_url`, but redact this value from normal output. This is different from storing a project/package name.
   - Change lookup uses local `HEAD`, `Change-Id`, or an explicit change number.
   - Redact `account.user`, `account.base_url`, `account.password`, and `account.auth_header` in all normal config-inspection output.

1. Collect local context:
   - `git rev-parse HEAD`
   - `git log -1 --pretty=format:%B`
   - `git remote -v`
   - `git branch -vv`
   - Extract `Change-Id:` from the latest commit message.

2. Diagnose Gerrit SSH access:
   - Prefer `scripts/gerrit_query.py --diagnose`.
   - Equivalent command: `ssh -o BatchMode=yes -o ConnectTimeout=10 -p <port> <user>@<host> gerrit version`.
   - Separate SSH authentication, host/port, and Gerrit permission failures in the response.

3. Query the review:
   - Prefer `scripts/gerrit_query.py` to fetch and normalize the change.
   - Query priority: user-provided change number, local commit SHA, then `change:<Change-Id>`.
   - The underlying Gerrit query is:
     `gerrit query --format=JSON --current-patch-set --patch-sets --all-approvals --comments --all-reviewers --submit-records <query> limit:1`.

4. Check patch set consistency:
   - Compare `currentPatchSet.revision` with local `HEAD`.
   - Warn before analysis if they differ.
   - Do not post actual comments when they differ unless the user explicitly accepts the mismatch.

5. Classify comments:
   - Separate change-level messages from inline comments.
   - Identify AI reviewer comments by reviewer name/email/username containing AI reviewer signals.
   - Normalize each inline comment with `patchSet`, `file`, `line`, `reviewer`, `severity`, `message`, and `suspectedIssueType`.

6. Validate each AI comment against code:
   - Open the target file and surrounding lines.
   - Trace call sites, dispatcher/thread context, lifecycle constraints, nullability, collection size invariants, cast invariants, and concurrency assumptions as needed.
   - Do not accept the reviewer message at face value.
   - Use one verdict: `valid`, `partially_valid`, `false_positive`, or `needs_more_context`.
   - Mark `false_positive` only when there is concrete file/line evidence.
   - If evidence is incomplete, use `needs_more_context`.

7. Draft replies:
   - Keep replies short, factual, and non-confrontational.
   - Prefix every Gerrit comment written by Codex with `[Codex로 생성됨]`. This is mandatory for draft comments, actual review comments, and change-level review messages.
   - For `false_positive`, explain the real code path and why the reported risk is not reachable.
   - For `valid`, acknowledge the issue and propose the smallest viable fix.
   - For `partially_valid`, split the real issue from the overstated assumption.

8. Build dry-run JSON:
   - Prefer `scripts/build_review_input.py` for actual published review comments.
   - Use `notify: NONE`, `omit_duplicate_comments: true`, and `tag: autogenerated:codex-gerrit-review`.
   - Show the change number, patch set, comment count, and notify value before any write.

9. Create drafts only on explicit draft request:
   - Treat requests such as `draft로 달아줘`, `draft comment 생성해줘`, and `초안으로 올려줘` as draft creation only.
   - Use only `scripts/create_draft_comments.py` for draft creation. It calls `PUT /drafts`; it must not publish comments.
   - After draft creation, report the draft count and stop. Do not call `/review` with `drafts: PUBLISH` in the same task.
   - If REST auth is not present in `config/account.json`, provide the dry-run JSON and explain that draft creation is unavailable until the config file contains `account.user` plus `account.password`, or `account.auth_header`.

10. Publish only with explicit publish intent and confirmation:
   - Do not treat follow-ups such as `진행해`, `올려`, `게릿에 올려`, `계속해`, or `go ahead` as permission to publish when the prior requested mode was draft.
   - Publish existing drafts only when the user explicitly says `draft를 실제 게시해줘`, `draft를 publish해줘`, or an equivalent phrase that contains both draft and publish/actual-post intent.
   - Publish new actual review comments only when the user explicitly says `실제 코멘트로 게시해줘` or an equivalent phrase that clearly excludes draft mode.
   - Before any publish operation, show the exact target change, patch set, comment count, notify value, and dry-run payload. Then require a second explicit confirmation before executing.
   - Use `scripts/publish_drafts.py` for publishing existing drafts; it requires `--execute` and an exact `--confirm PUBLISH_DRAFTS:<change>,<revision>` value.
   - Do not manually call the Gerrit REST `/review` endpoint with `drafts: PUBLISH`, and do not use `gerrit review --json`, unless the explicit publish mode and confirmation above are satisfied.

## Safety Rules

- Default to read-only analysis and dry-run output.
- Require explicit Gerrit account config before any Gerrit operation. If missing, stop and print setup guidance.
- Do not post anything to Gerrit unless the user explicitly asks for draft creation, draft publishing, or actual comment publishing.
- Draft creation is not publishing. If the user asked for drafts, never convert those drafts into published comments from a generic follow-up.
- Ambiguous continuation phrases are not publish approval. Ask for a publish-specific instruction instead.
- Do not run `submit`, `abandon`, `restore`, `rebase`, `move`, or label votes as part of this skill.
- Keep actual publishing comment-only unless the user explicitly asks for a label vote.
- Always show dry-run JSON before posting.
- For actual publishing, require a second explicit confirmation after the dry-run summary.
- Do not publish comments when local `HEAD` and Gerrit `currentPatchSet.revision` differ, unless the user explicitly accepts the mismatch.
- Do not classify a comment as `false_positive` without concrete code references.
- Every Gerrit comment generated by this skill must start with `[Codex로 생성됨]`. If a bundled script creates comment JSON, it must enforce this prefix itself.
- Keep `facts` and `inferences` separate in the answer. If the user requires Korean labels, use `사실` and `추측`.

## Output

Use this structure for review analysis:

- Summary
- Patch set information
- Comment verdicts
- False positives
- Valid issues
- Gerrit reply drafts
- Dry-run JSON
- Posting status
- For draft creation: explicitly state `draft only, not published`.
- For publishing: explicitly state the confirmation phrase used and whether publish succeeded.

When responding in this user's repositories, split final answers into `사실` and `추측`.

## Resources

- Use `scripts/configure_account.py` to create or inspect Gerrit account config at the skill-local `config/account.json`; use `--config` only when an explicit alternate file is needed.
- Use `scripts/gerrit_query.py` to detect local Gerrit context, run SSH query, parse JSON lines, remove stats rows, and normalize comments.
- Use `scripts/build_review_input.py` to convert reply drafts into Gerrit `ReviewInput` JSON.
- Use `scripts/create_draft_comments.py` to turn reply drafts into REST draft `CommentInput` requests and optionally create them.
- Use `scripts/publish_drafts.py` only when explicitly publishing already-created drafts after the second confirmation.
- Read `references/account_config.md` when account setup, config path, or REST auth fields are needed.
- Read `references/gerrit_commands.md` when exact Gerrit SSH, REST draft, `ReviewInput`, or `CommentInput` syntax is needed.

## Posting Commands

Actual review comment publishing:

```bash
ssh -p <port> <user>@<host> gerrit review --json <change>,<patchset>
```

Only use this after explicit actual-comment publish intent and second confirmation.

Draft comment creation:

```bash
PUT /changes/{change-id}/revisions/{revision-id}/drafts
```

Use draft creation only when REST authentication for the Gerrit host is known to work.

Existing draft publishing:

```bash
scripts/publish_drafts.py --change <change> --revision <patchset>
scripts/publish_drafts.py --change <change> --revision <patchset> --execute --confirm PUBLISH_DRAFTS:<change>,<patchset>
```

Use only after explicit draft-publish intent and second confirmation. Never infer this from `진행해` or `게릿에 올려`.
