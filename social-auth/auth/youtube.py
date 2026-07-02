"""YouTube auth — OAuth login (primary) + API Key fallback."""

from flask import Blueprint, request, redirect, session
import json
import urllib.request
import urllib.error
import urllib.parse
import secrets

bp = Blueprint("youtube", __name__)


def _redirect_uri():
    from env_manager import read_env
    env = read_env()
    ngrok = env.get("NGROK_URL", "")
    if ngrok:
        return ngrok.rstrip("/") + "/callback/youtube"
    return request.host_url.rstrip("/") + "/callback/youtube"


@bp.route("/connect/youtube")
def connect():
    from env_manager import read_env
    env = read_env()
    client_id = env.get("YOUTUBE_OAUTH_CLIENT_ID", "")

    # If OAuth creds available, show choice
    if client_id:
        return f"""
        <html><body style="background:#0C111D;color:#F9FAFB;font-family:Inter,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;">
        <div style="background:#182230;border:1px solid #344054;border-radius:12px;padding:40px;max-width:500px;width:100%;">
            <h2 style="color:#00FFA7;margin-bottom:24px;">YouTube — Adicionar Conta</h2>

            <a href="/connect/youtube/oauth" style="display:block;width:100%;padding:14px;background:#00FFA7;color:#0C111D;border:none;border-radius:8px;font-weight:700;font-size:14px;cursor:pointer;text-align:center;text-decoration:none;margin-bottom:16px;">Login com Google (recomendado)</a>

            <div style="text-align:center;color:#667085;font-size:12px;margin-bottom:16px;">— ou —</div>

            <form action="/save/youtube" method="POST">
                <input name="label" type="text" placeholder="Nome da conta (ex: Evolution Foundation)" style="width:100%;padding:12px;background:#0C111D;border:1px solid #344054;border-radius:8px;color:#F9FAFB;font-size:14px;margin-bottom:12px;">
                <input name="api_key" type="text" placeholder="API Key (AIza...)" style="width:100%;padding:12px;background:#0C111D;border:1px solid #344054;border-radius:8px;color:#F9FAFB;font-size:14px;margin-bottom:12px;">
                <input name="channel_id" type="text" placeholder="Channel ID (UC...)" style="width:100%;padding:12px;background:#0C111D;border:1px solid #344054;border-radius:8px;color:#F9FAFB;font-size:14px;margin-bottom:20px;">
                <button type="submit" style="width:100%;padding:12px;background:rgba(0,255,167,0.15);color:#00FFA7;border:1px solid rgba(0,255,167,0.3);border-radius:8px;font-weight:600;font-size:14px;cursor:pointer;">Salvar API Key</button>
            </form>
            <a href="/" style="color:#667085;font-size:12px;display:block;text-align:center;margin-top:16px;">Voltar</a>
        </div></body></html>
        """

    # No OAuth creds — API Key only
    return """
    <html><body style="background:#0C111D;color:#F9FAFB;font-family:Inter,sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;">
    <div style="background:#182230;border:1px solid #344054;border-radius:12px;padding:40px;max-width:500px;width:100%;">
        <h2 style="color:#00FFA7;margin-bottom:20px;">YouTube — API Key</h2>
        <p style="color:#D0D5DD;margin-bottom:20px;">Cole sua API Key do Google Console:</p>
        <form action="/save/youtube" method="POST">
            <input name="label" type="text" placeholder="Nome da conta" style="width:100%;padding:12px;background:#0C111D;border:1px solid #344054;border-radius:8px;color:#F9FAFB;font-size:14px;margin-bottom:12px;">
            <input name="api_key" type="text" placeholder="API Key (AIza...)" style="width:100%;padding:12px;background:#0C111D;border:1px solid #344054;border-radius:8px;color:#F9FAFB;font-size:14px;margin-bottom:12px;">
            <input name="channel_id" type="text" placeholder="Channel ID (UC...)" style="width:100%;padding:12px;background:#0C111D;border:1px solid #344054;border-radius:8px;color:#F9FAFB;font-size:14px;margin-bottom:20px;">
            <button type="submit" style="width:100%;padding:12px;background:#00FFA7;color:#0C111D;border:none;border-radius:8px;font-weight:700;font-size:14px;cursor:pointer;">Salvar</button>
        </form>
        <p style="color:#667085;font-size:12px;margin-top:16px;text-align:center;">Dica: configure YOUTUBE_OAUTH_CLIENT_ID no .env pra habilitar Login com Google</p>
        <a href="/" style="color:#667085;font-size:12px;display:block;text-align:center;margin-top:8px;">Voltar</a>
    </div></body></html>
    """


@bp.route("/connect/youtube/oauth")
def oauth_start():
    """Start Google OAuth flow."""
    from env_manager import read_env
    env = read_env()
    client_id = env.get("YOUTUBE_OAUTH_CLIENT_ID", "")
    if not client_id:
        return "YOUTUBE_OAUTH_CLIENT_ID not configured", 400

    state = secrets.token_urlsafe(32)
    session["oauth_state_youtube"] = state

    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/yt-analytics.readonly",
        "access_type": "offline",
        "state": state,
        "prompt": "consent",
    })
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@bp.route("/callback/youtube")
def callback():
    """Handle Google OAuth callback."""
    from env_manager import read_env, save_account, next_index

    env = read_env()
    state = request.args.get("state", "")
    if state != session.get("oauth_state_youtube"):
        return "Invalid state — CSRF protection", 403

    code = request.args.get("code", "")
    if not code:
        error = request.args.get("error", "no code")
        return f"Error: {error}", 400

    # Exchange code for tokens
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": env.get("YOUTUBE_OAUTH_CLIENT_ID", ""),
        "client_secret": env.get("YOUTUBE_OAUTH_CLIENT_SECRET", ""),
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return f"Token exchange failed: {e.read().decode()}", 500

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    # Get channel info
    channel_name = "YouTube"
    channel_id = ""
    try:
        url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true&access_token={access_token}"
        with urllib.request.urlopen(url) as resp:
            channels = json.loads(resp.read())
        if channels.get("items"):
            ch = channels["items"][0]
            channel_name = ch["snippet"]["title"]
            channel_id = ch["id"]
    except Exception:
        pass

    idx = next_index("youtube")
    fields = {
        "ACCESS_TOKEN": access_token,
        "CHANNEL_ID": channel_id,
    }
    if refresh_token:
        fields["REFRESH_TOKEN"] = refresh_token

    save_account("youtube", idx, channel_name, fields)
    return redirect(f"/?saved=YouTube ({channel_name})")


@bp.route("/save/youtube", methods=["POST"])
def save():
    """Save API Key manually."""
    from env_manager import save_account, next_index

    label = request.form.get("label", "").strip() or "YouTube"
    api_key = request.form.get("api_key", "").strip()
    channel_id = request.form.get("channel_id", "").strip()

    idx = next_index("youtube")
    fields = {}
    if api_key:
        fields["API_KEY"] = api_key
    if channel_id:
        fields["CHANNEL_ID"] = channel_id

    save_account("youtube", idx, label, fields)
    return redirect("/?saved=YouTube")
