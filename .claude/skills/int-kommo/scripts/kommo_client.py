#!/usr/bin/env python3
"""Kommo CRM API v4 Client — Multi-tenant support.

Supports 20+ Kommo accounts via env var prefixes (REDIGIR_KOMMO_, FUTURO_KOMMO_, etc).
Kommo uses long-lived JWT tokens (no refresh flow needed).

Usage:
    # By account name (maps to {UPPER}_KOMMO_ prefix)
    python3 kommo_client.py --account redigir GET /leads --params limit=10
    python3 kommo_client.py --account futuro GET /contacts?query=john

    # By explicit prefix
    python3 kommo_client.py --prefix REDIGIR_KOMMO_ GET /leads
    python3 kommo_client.py --prefix BABYGYM_KOMMO_ POST /leads --body '[{"name":"Test"}]'

    # Direct (uses KOMMO_ prefix by default)
    python3 kommo_client.py GET /leads/pipelines
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

# Account name to env prefix mapping
ACCOUNT_PREFIXES = {
    "redigir": "REDIGIR_KOMMO_",
    "nogueira": "NOGUEIRA_KOMMO_",
    "babygym": "BABYGYM_KOMMO_",
    "futuro": "FUTURO_KOMMO_",
    "yamatec": "YAMATEC_KOMMO_",
    # Default fallback
    "default": "KOMMO_",
}


def _load_dotenv():
    """Load .env from project root."""
    env_path = Path(__file__).resolve().parents[4] / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


def _get_config(prefix: str) -> tuple[str, str]:
    """Get token and base URL for a given prefix.

    Returns (token, base_url) or raises SystemExit if not configured.
    """
    token = os.environ.get(f"{prefix}TOKEN", "")
    base_url = os.environ.get(f"{prefix}BASE_URL", "")

    if not token:
        sys.stderr.write(f"[kommo] missing {prefix}TOKEN — configure in .env\n")
        sys.exit(1)

    if not base_url:
        sys.stderr.write(f"[kommo] missing {prefix}BASE_URL — configure in .env\n")
        sys.exit(1)

    # Ensure base_url doesn't have trailing slash
    base_url = base_url.rstrip("/")

    return token, base_url


def _api_call(token: str, base_url: str, method: str, path: str, params: dict = None, body: str = None):
    """Call Kommo API v4."""

    # Build URL
    if not path.startswith("/"):
        path = "/" + path

    # Handle paths that already have /api/v4 vs those that don't
    if path.startswith("/api/v4"):
        url = f"{base_url}{path}"
    else:
        url = f"{base_url}/api/v4{path}"

    # Parse any query params from path (e.g., /leads?limit=10)
    if "?" in url:
        url_base, query_string = url.split("?", 1)
        existing_params = urllib.parse.parse_qs(query_string)
        # Flatten single values
        existing_params = {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()}
        if params:
            existing_params.update(params)
        params = existing_params
        url = url_base

    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)

    # Prepare request
    data = None
    if body is not None:
        if isinstance(body, str):
            data = body.encode()
        else:
            data = json.dumps(body).encode()

    req = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", "replace")[:500]
        sys.stderr.write(f"[kommo] {method} {path} → HTTP {e.code}: {body_txt}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"[kommo] {method} {path} → {e}\n")
        sys.exit(1)


def _parse_params(args: list[str]) -> dict:
    """Parse key=value pairs into a dict."""
    out = {}
    for a in args:
        if "=" in a:
            k, v = a.split("=", 1)
            out[k] = v
    return out


def _count_kv(args: list[str]) -> int:
    """Count consecutive key=value args."""
    n = 0
    for a in args:
        if a.startswith("--") or "=" not in a:
            break
        n += 1
    return n


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(
            "Usage:\n"
            "  kommo_client.py --account redigir GET /leads --params limit=10\n"
            "  kommo_client.py --prefix REDIGIR_KOMMO_ GET /leads\n"
            "  kommo_client.py GET /leads/pipelines\n"
            "\n"
            "Available accounts: " + ", ".join(ACCOUNT_PREFIXES.keys()) + "\n"
        )
        sys.exit(1)

    # Parse args
    prefix = "KOMMO_"
    method = None
    path = None
    params = {}
    body = None

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]

        if arg == "--account":
            account = sys.argv[i + 1].lower()
            prefix = ACCOUNT_PREFIXES.get(account, f"{account.upper()}_KOMMO_")
            i += 2
        elif arg == "--prefix":
            prefix = sys.argv[i + 1]
            i += 2
        elif arg == "--params":
            kv_count = _count_kv(sys.argv[i + 1:])
            params = _parse_params(sys.argv[i + 1 : i + 1 + kv_count])
            i += 1 + kv_count
        elif arg == "--body":
            body = sys.argv[i + 1]
            # Parse as JSON if it looks like JSON
            if body.startswith("[") or body.startswith("{"):
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    pass  # Keep as string
            i += 2
        elif arg.upper() in ("GET", "POST", "PATCH", "PUT", "DELETE"):
            method = arg.upper()
            i += 1
        elif not method:
            # Might be method
            method = arg.upper()
            i += 1
        elif not path:
            path = arg
            i += 1
        else:
            i += 1

    if not method or not path:
        sys.stderr.write("[kommo] missing METHOD or PATH\n")
        sys.exit(1)

    token, base_url = _get_config(prefix)
    result = _api_call(token, base_url, method, path, params=params, body=body)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
