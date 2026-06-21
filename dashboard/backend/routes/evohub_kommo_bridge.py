"""EvoHub → Kommo Notes Bridge.

Recebe webhooks do EvoHub (Chatwoot-based) e espelha mensagens como notas
nos leads correspondentes da Kommo Nogueira Resolve.

Endpoint: POST /api/evohub/kommo-bridge?secret=<EVOHUB_KOMMO_BRIDGE_SECRET>

Idempotência: a tabela evohub_kommo_bridge_events garante que o par
(conversation_id, message_id) só seja processado uma vez.

Payload esperado (subset do Chatwoot webhook message_created):
{
  "event": "message_created",
  "id": <message_id>,
  "content": "texto da mensagem",
  "message_type": "incoming" | "outgoing",
  "conversation": {
    "id": <conversation_id>,
    "meta": {
      "sender": {
        "phone_number": "+5511999999999",
        "name": "Nome do Contato"
      }
    }
  }
}

Apenas mensagens do tipo "incoming" (cliente → EvoHub) são espelhadas.
"""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3
from pathlib import Path

from flask import Blueprint, jsonify, request

from integrations.kommo_nogueira import add_lead_note, find_lead_by_phone

logger = logging.getLogger(__name__)

bp = Blueprint("evohub_kommo_bridge", __name__)

_SECRET = os.getenv("EVOHUB_KOMMO_BRIDGE_SECRET", "")
_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "dashboard" / "data" / "evonexus.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _is_duplicate(conversation_id: int, message_id: int) -> bool:
    with _get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM evohub_kommo_bridge_events WHERE conversation_id=? AND message_id=?",
            (conversation_id, message_id),
        ).fetchone()
    return row is not None


def _mark_processed(conversation_id: int, message_id: int, lead_id: int | None, status: str) -> None:
    with _get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO evohub_kommo_bridge_events
               (conversation_id, message_id, lead_id, status)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, message_id, lead_id, status),
        )
        conn.commit()


@bp.route("/api/evohub/kommo-bridge", methods=["POST"])
def evohub_kommo_bridge():
    # Valida o segredo via query param (mesmo padrão do aurora_bot_control)
    if _SECRET:
        incoming = request.args.get("secret", "")
        if not secrets.compare_digest(incoming, _SECRET):
            return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    event = payload.get("event", "")

    # Só processa mensagens criadas do tipo incoming
    if event != "message_created":
        return jsonify({"ok": True, "skipped": f"event={event}"}), 200

    message_type = payload.get("message_type", "")
    if message_type != "incoming":
        return jsonify({"ok": True, "skipped": f"message_type={message_type}"}), 200

    content = (payload.get("content") or "").strip()
    if not content:
        return jsonify({"ok": True, "skipped": "empty_content"}), 200

    message_id = payload.get("id") or 0
    conversation = payload.get("conversation") or {}
    conversation_id = conversation.get("id") or 0

    if not message_id or not conversation_id:
        logger.warning("Payload inválido: message_id=%s conversation_id=%s", message_id, conversation_id)
        return jsonify({"error": "missing message_id or conversation_id"}), 400

    # Idempotência
    if _is_duplicate(conversation_id, message_id):
        return jsonify({"ok": True, "skipped": "duplicate"}), 200

    # Extrai telefone do remetente
    meta = conversation.get("meta") or {}
    sender = meta.get("sender") or {}
    phone = sender.get("phone_number") or ""
    sender_name = sender.get("name") or "Contato"

    if not phone:
        logger.warning("Sem telefone no payload da conversa %d", conversation_id)
        _mark_processed(conversation_id, message_id, None, "no_phone")
        return jsonify({"ok": True, "skipped": "no_phone"}), 200

    # Busca lead no Kommo pelo telefone
    lead = find_lead_by_phone(phone)
    if not lead:
        logger.info("Nenhum lead encontrado para %s (conversa %d)", phone, conversation_id)
        _mark_processed(conversation_id, message_id, None, "lead_not_found")
        return jsonify({"ok": True, "skipped": "lead_not_found", "phone": phone}), 200

    lead_id = lead["id"]

    # Formata a nota
    note_text = (
        f"[EvoHub] Mensagem de {sender_name} ({phone}):\n"
        f"{content}\n"
        f"— Conversa #{conversation_id}"
    )

    success = add_lead_note(lead_id, note_text)
    status = "synced" if success else "note_failed"
    _mark_processed(conversation_id, message_id, lead_id, status)

    if not success:
        return jsonify({"error": "falha ao criar nota no Kommo", "lead_id": lead_id}), 502

    logger.info(
        "Mensagem %d da conversa %d espelhada como nota no lead %d",
        message_id, conversation_id, lead_id,
    )
    return jsonify({"ok": True, "lead_id": lead_id, "status": "synced"}), 200
