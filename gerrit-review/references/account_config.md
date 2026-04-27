# Account Configuration

The skill requires a skill-local Gerrit account config before any Gerrit query or draft operation.

Default config path:

```text
config/account.json
```

Distribute an empty `config/account.json` with the skill. It must not contain real user, password, or base URL values.

Use a non-default path only when explicitly requested:

```bash
scripts/configure_account.py --config /path/to/account.json --show
```

Create or update config:

```bash
scripts/configure_account.py \
  --user <gerrit-user> \
  --base-url <gerrit-rest-base-url> \
  --prompt-password
```

Show config:

```bash
scripts/configure_account.py --show
```

Expected shape:

```json
{
  "account": {
    "user": "<gerrit-user>",
    "password": "<HTTP_PASSWORD>",
    "base_url": "<gerrit-rest-base-url>"
  }
}
```

For SSH and REST, use one shared `account.user`. Do not store separate `ssh.user` or `rest.user` values.

Do not store SSH host, SSH port, Gerrit project, or package in account config. The skill infers SSH host and port from local `git remote -v`, and finds a change from local `HEAD`, `Change-Id`, or an explicit change number. Use `scripts/gerrit_query.py --host <host> --port <port>` only for explicit overrides.

An extra path in `account.base_url` is the Gerrit REST context path. It is not a project/package setting, so keep it when the Gerrit server serves REST under that path. This value is redacted from normal output.

For draft creation, store REST authentication in the skill-local config file. Use one of:

```json
{
  "account": {
    "user": "<gerrit-user>",
    "password": "<HTTP_PASSWORD>",
    "base_url": "<gerrit-rest-base-url>"
  }
}
```

```json
{
  "account": {
    "user": "<gerrit-user>",
    "base_url": "<gerrit-rest-base-url>",
    "auth_header": "Authorization: Basic <BASE64_USER_COLON_PASSWORD>"
  }
}
```

You can write or update `account.password` with an interactive prompt. If `account.user` and `account.base_url` are already configured, this updates only the password:

```bash
scripts/configure_account.py --prompt-password
```

For first-time setup:

```bash
scripts/configure_account.py \
  --user <gerrit-user> \
  --base-url <gerrit-rest-base-url> \
  --prompt-password
```

Use `--password <gerrit-http-password>` only for non-interactive automation. Prefer `--prompt-password` for normal use because command-line arguments can be saved in shell history.

If the config file is missing, stop immediately and show the create config command. Do not infer account data from `git remote` as a replacement for the explicit account config.
