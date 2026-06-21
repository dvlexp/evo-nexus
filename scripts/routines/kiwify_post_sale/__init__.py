"""Kiwify Post-Sale Orchestrator (Fase 2 do feature kiwify-post-sale-restructure).

Substitui os 4 sub-workflows quebrados do n8n por scripts Python nativos:
    - evocrm_sync         (antes "Kommo Sync")
    - whatsapp_confirm    (antes "WhatsApp Confirmacao")
    - mautic_tag          (antes "Mautic Tag")
    - directus_provision  (antes "Directus Provision")

Cada sub-step roda isolado: uma falha nao mata o resto. Estado persiste em
public.kiwify_post_sale_runs no Postgres rxp_outbound. Notificacao Telegram
consolidada vai pro Daniel (chat_id 8860803037) ao final.
"""
