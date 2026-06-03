"""Aurora bot toggle endpoint.

Receives EvoCRM automation webhook payloads and toggles the Aurora bot
pause state via Partenon API. Used by two EvoCRM automations:
- label "aurora-pausar" added  → ?action=pause
- label "aurora-retomar" added → ?action=unpause

The endpoint is unauthenticated but validates a shared secret via the
X-Aurora-Secret header to prevent abuse.
"""

from __future__ import annotations

import logging
import os
import re

import requests
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("aurora_bot_control", __name__)

PARTENON_URL = "https://labs.xmacna.ai/partenon/api/bot-control/pause"
PARTENON_SECRET = "AqGnlq8HfhRSWGp5UjyCJzTysNZ16Z0Q3cxyuLgUXn8="
CHATWOOT_ACCOUNT_ID = 99  # numeric ID used by Aurora's self_pause tool

_SHARED_SECRET = os.getenv("AURORA_WEBHOOK_SECRET", "")


def _phone_to_jid(phone: str) -> str | None:
    """Convert +5511999999999 → 5511999999999@s.whatsapp.net."""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    return f"{digits}@s.whatsapp.net"


@bp.route("/api/aurora/bot-control", methods=["POST"])
def aurora_bot_control():
    # Optional shared secret validation
    if _SHARED_SECRET:
        incoming = request.headers.get("X-Aurora-Secret", "")
        if incoming != _SHARED_SECRET:
            return jsonify({"error": "unauthorized"}), 401

    action = request.args.get("action", "").lower()
    if action not in ("pause", "unpause"):
        return jsonify({"error": "action must be pause or unpause"}), 400

    payload = request.get_json(silent=True) or {}
    meta = payload.get("meta") or {}
    sender = meta.get("sender") or {}
    phone = sender.get("phone_number") or ""

    if not phone:
        logger.warning("aurora_bot_control: no phone_number in payload")
        return jsonify({"error": "phone_number missing in sender"}), 422

    remote_jid = _phone_to_jid(phone)
    if not remote_jid:
        return jsonify({"error": "could not parse phone number"}), 422

    conversation_id = payload.get("id")
    paused = action == "pause"

    try:
        resp = requests.post(
            PARTENON_URL,
            json={
                "account_id": CHATWOOT_ACCOUNT_ID,
                "remote_jid": remote_jid,
                "paused": paused,
                "paused_by": "human:evocrm_automation",
                "conversation_id": conversation_id,
            },
            headers={
                "Content-Type": "application/json",
                "x-partenon-secret": PARTENON_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:
        logger.error("aurora_bot_control: partenon error: %s", exc)
        return jsonify({"error": str(exc)}), 502

    if result.get("ok") is not True:
        logger.warning("aurora_bot_control: partenon rejected: %s", result)
        return jsonify({"error": "partenon rejected", "detail": result}), 502

    logger.info(
        "aurora_bot_control: %s for %s (conv %s)",
        action, remote_jid, conversation_id,
    )
    return jsonify({
        "ok": True,
        "action": action,
        "remote_jid": remote_jid,
        "paused": paused,
    })
