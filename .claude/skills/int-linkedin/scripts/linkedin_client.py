#!/usr/bin/env python3
"""LinkedIn API Client — multi-account, versioned API."""

import json
import os
import sys
import re
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


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

API_VERSION = "202603"


# ── Account discovery ────────────────────────────────

def _get_accounts() -> list[dict]:
    accounts = []
    pattern = re.compile(r"^SOCIAL_LINKEDIN_(\d+)_LABEL$")
    for key, value in sorted(os.environ.items()):
        m = pattern.match(key)
        if m:
            idx = m.group(1)
            accounts.append({
                "index": idx,
                "label": value,
                "access_token": os.environ.get(f"SOCIAL_LINKEDIN_{idx}_ACCESS_TOKEN", ""),
                "person_urn": os.environ.get(f"SOCIAL_LINKEDIN_{idx}_PERSON_URN", ""),
                "org_urn": os.environ.get(f"SOCIAL_LINKEDIN_{idx}_ORG_URN", ""),
            })
    return accounts


def _get_account(label_or_index: str = None) -> dict:
    accounts = _get_accounts()
    if not accounts:
        return {}
    if not label_or_index:
        return accounts[0]
    for a in accounts:
        if a["index"] == label_or_index or a["label"].lower() == label_or_index.lower():
            return a
    return accounts[0]


# ── API calls ────────────────────────────────────────

def _api_get(url: str, token: str, versioned: bool = True) -> dict:
    """Make GET request to LinkedIn API."""
    headers = {
        "Authorization": f"Bearer {token}",
    }
    if versioned:
        headers["Linkedin-Version"] = API_VERSION
        headers["X-Restli-Protocol-Version"] = "2.0.0"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}", "detail": body[:500]}
    except Exception as e:
        return {"error": str(e)}


# ── Commands ─────────────────────────────────────────

def profile(account: dict) -> dict:
    """Get LinkedIn profile via OpenID Connect userinfo."""
    token = account.get("access_token", "")
    if not token:
        return {"error": "No access token configured"}

    data = _api_get("https://api.linkedin.com/v2/userinfo", token, versioned=False)
    if "error" in data:
        return data

    return {
        "account": account.get("label", ""),
        "person_urn": account.get("person_urn", ""),
        "name": data.get("name", ""),
        "given_name": data.get("given_name", ""),
        "family_name": data.get("family_name", ""),
        "email": data.get("email", ""),
        "picture": data.get("picture", ""),
        "locale": data.get("locale", ""),
    }


def my_posts(account: dict, count: int = 10) -> dict:
    """Get recent posts by the authenticated user."""
    token = account.get("access_token", "")
    person_urn = account.get("person_urn", "")
    if not token or not person_urn:
        return {"error": "No access token or person URN"}

    encoded_urn = urllib.parse.quote(person_urn, safe="")
    url = f"https://api.linkedin.com/rest/posts?q=author&author={encoded_urn}&count={count}&sortBy=LAST_MODIFIED"

    data = _api_get(url, token, versioned=True)
    if "error" in data:
        return data

    posts = []
    for p in data.get("elements", []):
        posts.append({
            "id": p.get("id", ""),
            "text": (p.get("commentary", "") or p.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {}).get("shareCommentary", {}).get("text", ""))[:150],
            "created": p.get("createdAt", 0),
            "visibility": p.get("visibility", ""),
            "lifecycle_state": p.get("lifecycleState", ""),
        })

    return {
        "account": account.get("label", ""),
        "person_urn": person_urn,
        "posts": posts,
        "total": len(posts),
    }


def post_stats(account: dict, post_urn: str) -> dict:
    """Get reactions and comments for a specific post."""
    token = account.get("access_token", "")
    if not token:
        return {"error": "No access token"}

    encoded_urn = urllib.parse.quote(post_urn, safe="")
    url = f"https://api.linkedin.com/rest/socialMetadata/{encoded_urn}"

    data = _api_get(url, token, versioned=True)
    if "error" in data:
        return data

    return {
        "post_urn": post_urn,
        "reactions": data.get("totalShareStatistics", {}).get("reactionCount", 0) if "totalShareStatistics" in data else data.get("reactionsCount", 0),
        "comments": data.get("totalShareStatistics", {}).get("commentCount", 0) if "totalShareStatistics" in data else data.get("commentsCount", 0),
        "shares": data.get("totalShareStatistics", {}).get("shareCount", 0) if "totalShareStatistics" in data else 0,
    }


def org_followers(account: dict) -> dict:
    """Get organization follower statistics (requires r_organization_admin)."""
    token = account.get("access_token", "")
    org_urn = account.get("org_urn", "")
    if not token or not org_urn:
        return {"error": "No access token or org URN. Organization scopes require Advertising API approval."}

    encoded_urn = urllib.parse.quote(org_urn, safe="")
    url = f"https://api.linkedin.com/rest/organizationalEntityFollowerStatistics?q=organizationalEntity&organizationalEntity={encoded_urn}"

    data = _api_get(url, token, versioned=True)
    if "error" in data:
        return data

    elements = data.get("elements", [])
    if not elements:
        return {"org_urn": org_urn, "followers": 0}

    return {
        "org_urn": org_urn,
        "followers": elements[0].get("followerCounts", {}).get("organicFollowerCount", 0),
        "paid_followers": elements[0].get("followerCounts", {}).get("paidFollowerCount", 0),
    }


def all_accounts_summary() -> dict:
    accounts = _get_accounts()
    summaries = []
    for acc in accounts:
        prof = profile(acc)
        if "error" not in prof:
            summaries.append(prof)
    return {"accounts": summaries, "total": len(summaries)}


def post_text(account: dict, text: str, visibility: str = "PUBLIC") -> dict:
    """Publish a text-only post to LinkedIn using UGC Posts API."""
    token = account.get("access_token", "")
    person_urn = account.get("person_urn", "")
    if not token or not person_urn:
        return {"error": "No access token or person URN"}

    url = "https://api.linkedin.com/v2/ugcPosts"
    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            post_id = resp.headers.get("x-restli-id", "")
            body = resp.read().decode("utf-8") or "{}"
            return {
                "ok": True,
                "post_id": post_id,
                "post_url": f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else "",
                "response": json.loads(body) if body.strip().startswith("{") else body,
            }
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode("utf-8", "replace")[:500]}
    except Exception as e:
        return {"error": str(e)}


def post_article(account: dict, text: str, article_url: str, title: str = "", description: str = "", visibility: str = "PUBLIC") -> dict:
    """Publish a post with an article link (auto-renders preview card)."""
    token = account.get("access_token", "")
    person_urn = account.get("person_urn", "")
    if not token or not person_urn:
        return {"error": "No access token or person URN"}

    media = {"status": "READY", "originalUrl": article_url}
    if title:
        media["title"] = {"text": title}
    if description:
        media["description"] = {"text": description}

    url = "https://api.linkedin.com/v2/ugcPosts"
    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "ARTICLE",
                "media": [media],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            post_id = resp.headers.get("x-restli-id", "")
            body = resp.read().decode("utf-8") or "{}"
            return {
                "ok": True,
                "post_id": post_id,
                "post_url": f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else "",
                "response": json.loads(body) if body.strip().startswith("{") else body,
            }
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode("utf-8", "replace")[:500]}
    except Exception as e:
        return {"error": str(e)}


# ── CLI ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: linkedin_client.py <command> [args]")
        print("\nCommands:")
        print("  accounts                    # List configured accounts")
        print("  profile [account]           # Profile info (name, email, picture)")
        print("  my_posts [account] [N]      # Recent N posts")
        print("  post_stats POST_URN         # Reactions/comments for a post")
        print("  org_followers [account]     # Org follower stats (needs Advertising API)")
        print("  summary                     # Summary of all accounts")
        print("  post_text [account] --text TEXT [--visibility PUBLIC|CONNECTIONS]")
        print("  post_article [account] --text TEXT --url URL [--title T] [--description D]")
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    try:
        if cmd == "accounts":
            result = {"accounts": [{"index": a["index"], "label": a["label"],
                                     "person_urn": a["person_urn"],
                                     "has_org": bool(a["org_urn"])} for a in _get_accounts()]}
        elif cmd == "profile":
            acc = _get_account(args[0] if args else None)
            result = profile(acc)
        elif cmd == "my_posts":
            acc = _get_account(args[0] if args else None)
            n = int(args[1]) if len(args) > 1 else 10
            result = my_posts(acc, n)
        elif cmd == "post_stats":
            acc = _get_account()
            result = post_stats(acc, args[0] if args else "")
        elif cmd == "org_followers":
            acc = _get_account(args[0] if args else None)
            result = org_followers(acc)
        elif cmd == "summary":
            result = all_accounts_summary()
        elif cmd == "post_text":
            # post_text [account] --text TEXT [--visibility V]
            acc_label = args[0] if args and not args[0].startswith("--") else None
            acc = _get_account(acc_label)
            text = ""
            visibility = "PUBLIC"
            i = 0
            while i < len(args):
                if args[i] == "--text":
                    text = args[i+1]; i += 2
                elif args[i] == "--visibility":
                    visibility = args[i+1]; i += 2
                else:
                    i += 1
            result = post_text(acc, text, visibility)
        elif cmd == "post_article":
            acc_label = args[0] if args and not args[0].startswith("--") else None
            acc = _get_account(acc_label)
            text = ""; url_a = ""; title = ""; description = ""; visibility = "PUBLIC"
            i = 0
            while i < len(args):
                if args[i] == "--text": text = args[i+1]; i += 2
                elif args[i] == "--url": url_a = args[i+1]; i += 2
                elif args[i] == "--title": title = args[i+1]; i += 2
                elif args[i] == "--description": description = args[i+1]; i += 2
                elif args[i] == "--visibility": visibility = args[i+1]; i += 2
                else: i += 1
            result = post_article(acc, text, url_a, title, description, visibility)
        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)
