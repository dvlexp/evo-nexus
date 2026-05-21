"""Instagram/Meta OAuth flow — multi-account."""

from flask import Blueprint, request, redirect, session
import json
import urllib.request
import urllib.error
import urllib.parse
import secrets
from datetime import datetime, timezone

bp = Blueprint("instagram", __name__)


def _callback_url():
    """Get callback URL — use ngrok if configured, otherwise localhost."""
    from env_manager import read_env
    env = read_env()
    ngrok = env.get("NGROK_URL", "")
    if ngrok:
        return f"{ngrok.rstrip('/')}/callback/instagram"
    return request.host_url.rstrip("/") + "/callback/instagram"


@bp.route("/connect/instagram")
def connect():
    from env_manager import read_env
    env = read_env()
    app_id = env.get("META_APP_ID", "")
    if not app_id:
        return _missing("META_APP_ID and META_APP_SECRET")

    state = secrets.token_urlsafe(32)
    session["oauth_state_instagram"] = state

    params = urllib.parse.urlencode({
        "client_id": app_id,
        "redirect_uri": _callback_url(),
        "scope": "pages_show_list,pages_read_engagement,instagram_manage_insights,instagram_manage_comments",
        "response_type": "code",
        "state": state,
    })
    return redirect(f"https://www.facebook.com/v25.0/dialog/oauth?{params}")


@bp.route("/callback/instagram")
def callback():
    from env_manager import read_env, save_account, next_index

    env = read_env()
    state = request.args.get("state", "")
    if state != session.get("oauth_state_instagram"):
        return "Invalid state — CSRF protection", 403

    code = request.args.get("code", "")
    if not code:
        return f"Error: {request.args.get('error_description', 'no code')}", 400

    # Exchange code → short-lived → long-lived token
    params = urllib.parse.urlencode({
        "client_id": env.get("META_APP_ID", ""),
        "client_secret": env.get("META_APP_SECRET", ""),
        "redirect_uri": _callback_url(),
        "code": code,
    })
    try:
        with urllib.request.urlopen(f"https://graph.facebook.com/v25.0/oauth/access_token?{params}") as resp:
            short_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return f"Short token failed: {e.read().decode()}", 500

    params2 = urllib.parse.urlencode({
        "grant_type": "fb_exchange_token",
        "client_id": env.get("META_APP_ID", ""),
        "client_secret": env.get("META_APP_SECRET", ""),
        "fb_exchange_token": short_data.get("access_token", ""),
    })
    try:
        with urllib.request.urlopen(f"https://graph.facebook.com/v25.0/oauth/access_token?{params2}") as resp:
            long_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return f"Long-lived token failed: {e.read().decode()}", 500

    long_token = long_data.get("access_token", "")
    now = datetime.now(timezone.utc).isoformat()

    # Get Pages + Instagram Business Accounts
    try:
        url = f"https://graph.facebook.com/v25.0/me/accounts?access_token={long_token}&fields=id,name,access_token,instagram_business_account{{id,username}}"
        with urllib.request.urlopen(url) as resp:
            pages_data = json.loads(resp.read())
    except Exception:
        pages_data = {"data": []}

    # Save each Instagram Business Account as a separate account
    saved_count = 0
    for page in pages_data.get("data", []):
        ig = page.get("instagram_business_account", {})
        if ig.get("id"):
            idx = next_index("instagram")
            label = ig.get("username", page.get("name", f"Account {idx}"))
            fields = {
                "ACCESS_TOKEN": long_token,
                "ACCOUNT_ID": ig["id"],
                "TOKEN_CREATED_AT": now,
            }
            # Page Access Token (permanent)
            page_token = page.get("access_token", "")
            if page_token:
                fields["PAGE_TOKEN"] = page_token
            save_account("instagram", idx, label, fields)
            saved_count += 1

    if saved_count == 0:
        # No IG business accounts found — save token anyway
        idx = next_index("instagram")
        save_account("instagram", idx, "Instagram", {
            "ACCESS_TOKEN": long_token,
            "TOKEN_CREATED_AT": now,
        })

    return redirect(f"/?saved=Instagram ({saved_count} account{'s' if saved_count != 1 else ''})")


def _missing(keys):
    return f"""
    <html><body style="background:#0C111D;color:#F9FAFB;font-family:Inter,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;">
    <div style="background:#182230;border:1px solid #344054;border-radius:12px;padding:40px;max-width:500px;">
        <h2 style="color:#F04438;">Configuration required</h2>
        <p style="color:#D0D5DD;">Configure <code>{keys}</code> in <code>.env</code></p>
        <a href="/" style="color:#00FFA7;">Back</a>
    </div></body></html>
    """
