# Secrets Policy

Inviolable rules for handling credentials in the EvoNexus workspace.
Created 2026-06-22 after the 2026-06-20 leak (9 credentials found in
tracked source by the Vault audit).

This document is the canonical secrets policy. It is intended to be
loaded by every engineering agent (Bolt, Apex, Hawk, Lens, Vault) and
referenced from `.claude/rules/integrations.md`.

---

## Hard rules

### 1. Never hardcode credentials in source

Wrong (any of these patterns):

```python
TOKEN = os.getenv("KIWIFY_TOKEN", "<actual-value-here>")
SECRET = "<actual-base64-secret-here>"
PASSWORD = "<actual-password-here>"
```

Right:

```python
TOKEN = os.environ["KIWIFY_TOKEN"]
```

The pattern `os.getenv("X", "<literal>")` versions the literal in the
repo. Once committed, the value is leaked forever via the SHA, even
if a later commit removes it. Always use `os.environ[X]` (bracket
access) without a default for any secret value.

Public identifiers (UUIDs, public URLs, template names) are fine as
literals. The line is: would I be uncomfortable if a stranger saw
this in the repo on GitHub? If yes, env var. If no, literal.

### 2. Never commit `.env` (or any variant)

`.env` is already in `.gitignore`. Same goes for `.env.local`,
`.env.production`, `secrets.json`, `credentials.json`, `*.pem`,
`*.key`, `service-account.json`. If a tool insists on a config file,
gitignore the real file and ship a `.env.example` template with empty
values.

### 3. Run `gitleaks detect` before opening a PR

Local pre-commit hook (`scripts/git-hooks/pre-commit`) runs gitleaks
automatically when staging. Install it once:

```bash
bash scripts/git-hooks/install.sh
```

If you must bypass the hook (e.g. documented false positive), use
`--no-verify` and explain in the PR description why. Bypassing
silently is treated as a leak in incident review.

To re-scan the full history manually:

```bash
gitleaks detect --source . --config .gitleaks.toml --no-banner --redact
```

### 4. Brain Repo: do NOT sync these paths

The `memory/` → GitHub Brain Repo auto-sync is gitignored already,
but when you configure `config/brain-repo.yaml`, the following paths
must be on the deny-list. They contain content that is not safe to
mirror to even a private GitHub repo:

- `workspace/data/` — runtime data, scratch DBs
- `workspace/audit/` — secrets findings, hashes
- `.env` and any `.env.*` variant
- `~/.ssh/` references (any path under user home with credentials)
- `chat-logs/` and `.claude/projects/` — raw chat transcripts often
  contain credentials pasted by the user
- `memory/raw-transcripts/` — already excluded; do not move under any
  other tracked dir
- Anything matching the `.gitleaks.toml` rules at scan time

When in doubt, run `gitleaks detect --source <path-to-brain-repo>`
before pushing.

### 5. Fork-network awareness

GitHub forks share the underlying object database with the upstream
public repo. A commit pushed to a fork of a public repo is reachable
from the public repo via the SHA, even if the fork itself is private
or the branch is later deleted. There is no way to make a leaked
commit unreachable except by contacting GitHub support to purge the
SHA.

Consequence: if you push secret-bearing commits to a fork of any
`EvolutionAPI/*` repo (which are public), the secret is effectively
public the moment the push completes. The only safe path is:

1. Rotate the credential immediately
2. Open a GitHub support ticket to purge the SHA from the fork
   network
3. Do not rely on `git push --force` or branch deletion to "hide" it

The `evo-nexus` workspace repo (this one) is private and is its own
remote. Do not push it to a fork of any public Evolution repo.

---

## Workflow when you find a leaked secret

1. Rotate first, audit second. Generate a new credential and update
   the consumer. Do not pause to write a postmortem before the
   rotation is complete.
2. After rotation: run `git log -p -S '<partial-leaked-value>' --all`
   to find every commit that touched the value.
3. If the leak is in a private repo with no fork: rewrite history
   with `git filter-repo` and force-push. Notify any clones.
4. If the leak is in a public repo (or fork of one): rotate is the
   only durable fix. Filter-repo + GitHub support ticket reduces (does
   not eliminate) the window.
5. Add a regex to `.gitleaks.toml` so future occurrences are blocked.
6. File a finding in `workspace/audit/` describing what leaked, where,
   and what was rotated. Brain Repo: do NOT sync that path.

---

## Why these rules exist

The 2026-06-20 audit found 9 leaked credentials, including:

- A shared-secret literal in `dashboard/backend/routes/aurora_bot_control.py`
- A webhook-secret as `os.getenv(..., "<literal>")` fallback
- RXP VPS transport configuration (host, port, key path, container
  name) as defaults in 7 places of
  `dashboard/backend/integrations/aurora_db.py`
- A Kommo account ID hardcoded in
  `dashboard/backend/integrations/kommo_nogueira.py`
- A Telegram chat ID hardcoded in
  `scripts/routines/kiwify_post_sale/config.py`
- Other historical leaks (`Bearer ...` literals, generic API keys in
  test files) in commits going back several months

Root cause: developer convenience (fallback default = "works on my
machine without setting env vars") created a documented secret-leak
surface. The fix is mechanical: bracket access, no fallbacks, pre-
commit gate.

---

## Reference

- Vault audit findings: `workspace/audit/[C]vazamentos-historicos.md`
- Client/asset inventory:
  `workspace/audit/[C]inventario-por-cliente.md`
- Gitleaks config: `.gitleaks.toml`
- Hook installer: `scripts/git-hooks/install.sh`
- Client-isolation rule (related): see Trail's recommendation R1 in
  the vazamentos-historicos audit.
