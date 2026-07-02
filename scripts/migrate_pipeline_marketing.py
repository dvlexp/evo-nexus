#!/usr/bin/env python3
"""
Migração de pipeline_items do funil RXP Marketing
type='contact' → type='conversation'

Pipeline ID: e18fbb10-e56f-478b-bc5b-1b84df8296f6
"""

import json
import time
import requests
from datetime import datetime

# --- Configuração ---
BASE_URL = "https://api-crm.resultadosexponenciais.com.br"
TOKEN = "52637b57342e0268f539931e897e12dbb9d1fc02577b2bfb63baecf25dec9862"
PIPELINE_ID = "e18fbb10-e56f-478b-bc5b-1b84df8296f6"
HEADERS = {
    "api_access_token": TOKEN,
    "Content-Type": "application/json"
}

BATCH_SIZE = 20
BATCH_SLEEP = 1.0
RETRY_SLEEP = 3.0
MAX_RETRIES = 3

# --- Nomes dos estágios (para o relatório) ---
STAGE_NAMES = {
    "042139cf-d2c7-4d87-bd06-e22863b8ea74": "Lead",
    "d9105e3f-e8bb-4d52-bd9e-dcdc12dc4227": "Nutrição",
    "dd6b0623-5171-4671-a42b-c52c6680b7bd": "Qualificado",
    "918231df-a3a7-4937-8b3e-d285f9a122bf": "Convertido",
}

# --- HTTP helpers ---

def api_get(url, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
            if r.status_code in (502, 503):
                print(f"    [RETRY] {r.status_code} em GET {url} — tentativa {attempt+1}/{MAX_RETRIES}")
                time.sleep(RETRY_SLEEP)
                continue
            return r
        except requests.RequestException as e:
            print(f"    [ERRO] GET {url}: {e}")
            time.sleep(RETRY_SLEEP)
    return None


def api_post(url, payload):
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
            if r.status_code in (502, 503):
                print(f"    [RETRY] {r.status_code} em POST {url} — tentativa {attempt+1}/{MAX_RETRIES}")
                time.sleep(RETRY_SLEEP)
                continue
            return r
        except requests.RequestException as e:
            print(f"    [ERRO] POST {url}: {e}")
            time.sleep(RETRY_SLEEP)
    return None


def api_patch(url, payload):
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.patch(url, headers=HEADERS, json=payload, timeout=30)
            if r.status_code in (502, 503):
                print(f"    [RETRY] {r.status_code} em PATCH {url} — tentativa {attempt+1}/{MAX_RETRIES}")
                time.sleep(RETRY_SLEEP)
                continue
            return r
        except requests.RequestException as e:
            print(f"    [ERRO] PATCH {url}: {e}")
            time.sleep(RETRY_SLEEP)
    return None


def api_delete(url):
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.delete(url, headers=HEADERS, timeout=30)
            if r.status_code in (502, 503):
                print(f"    [RETRY] {r.status_code} em DELETE {url} — tentativa {attempt+1}/{MAX_RETRIES}")
                time.sleep(RETRY_SLEEP)
                continue
            return r
        except requests.RequestException as e:
            print(f"    [ERRO] DELETE {url}: {e}")
            time.sleep(RETRY_SLEEP)
    return None


# --- Lógica principal ---

def get_blind_items():
    """Retorna todos os items do pipeline sem conversation_id."""
    url = f"{BASE_URL}/api/v1/pipelines/{PIPELINE_ID}/pipeline_items"
    r = api_get(url)
    if not r or r.status_code != 200:
        raise RuntimeError(f"Falha ao buscar pipeline_items: {r.status_code if r else 'sem resposta'}")
    data = r.json()
    all_items = data["data"]
    blind = [i for i in all_items if not i.get("conversation_id")]
    print(f"Total itens no pipeline: {len(all_items)}")
    print(f"Itens sem conversation_id: {len(blind)}")
    return blind


def get_conversations_for_contact(contact_id):
    """
    Busca conversas do contato via POST /api/v1/conversations/filter.
    Retorna lista de conversas, ordenada por last_activity_at desc.
    """
    url = f"{BASE_URL}/api/v1/conversations/filter"
    payload = {
        "payload": [
            {
                "attribute_key": "contact_id",
                "filter_operator": "equal_to",
                "values": [contact_id],
                "query_operator": None
            }
        ]
    }
    r = api_post(url, payload)
    if not r:
        return None
    if r.status_code == 204 or not r.content:
        return []
    if r.status_code != 200:
        return None
    data = r.json()
    convs = data.get("data", [])
    # Ordenar por last_activity_at desc (mais recente primeiro)
    convs.sort(key=lambda c: c.get("last_activity_at", 0), reverse=True)
    return convs


def get_existing_conversation_ids_in_pipeline():
    """
    Retorna um set com todos os conversation_ids já existentes no pipeline
    (itens do tipo conversation). Usado para evitar duplicatas.
    """
    url = f"{BASE_URL}/api/v1/pipelines/{PIPELINE_ID}/pipeline_items"
    r = api_get(url)
    if not r or r.status_code != 200:
        return set()
    data = r.json()
    return {i["conversation_id"] for i in data["data"] if i.get("conversation_id")}


def migrate_item(item, existing_conv_ids):
    """
    Migra um item cego (type=contact) para type=conversation.
    Retorna: ("migrated", conv_id) | ("no_conv", None) | ("skip_dup", conv_id) | ("error", msg)
    """
    item_id = item["id"]         # UUID do pipeline_item
    contact_id = item["item_id"] # UUID do contato (item_id no item cego)
    stage_id = item["pipeline_stage_id"]
    contact_name = item.get("contact", {}).get("name", "?")

    # 1. Buscar conversas do contato
    convs = get_conversations_for_contact(contact_id)
    if convs is None:
        return ("error", f"falha ao buscar conversas para contato {contact_id}")

    if len(convs) == 0:
        return ("no_conv", None)

    # 2. Escolher a conversa (mais recente)
    chosen_conv = convs[0]
    conv_id = chosen_conv["id"]

    # 3. Verificar duplicata
    if conv_id in existing_conv_ids:
        return ("skip_dup", conv_id)

    # 4. Deletar item cego
    del_url = f"{BASE_URL}/api/v1/pipelines/{PIPELINE_ID}/pipeline_items/{item_id}"
    del_r = api_delete(del_url)
    if not del_r or del_r.status_code not in (200, 204):
        return ("error", f"falha ao deletar item {item_id}: {del_r.status_code if del_r else 'sem resposta'}")

    # 5. Recriar com type=conversation
    post_url = f"{BASE_URL}/api/v1/pipelines/{PIPELINE_ID}/pipeline_items"
    post_r = api_post(post_url, {"item_id": conv_id, "type": "conversation"})
    if not post_r or post_r.status_code not in (200, 201):
        return ("error", f"falha ao criar item conversation {conv_id}: {post_r.status_code if post_r else 'sem resposta'}")

    new_item = post_r.json().get("data", {})
    new_item_id = new_item.get("id")

    # 6. Mover para o estágio original (se diferente de Lead)
    lead_stage = "042139cf-d2c7-4d87-bd06-e22863b8ea74"
    if stage_id != lead_stage and new_item_id:
        patch_url = f"{BASE_URL}/api/v1/pipelines/{PIPELINE_ID}/pipeline_items/{new_item_id}"
        patch_r = api_patch(patch_url, {"pipeline_stage_id": stage_id})
        if not patch_r or not patch_r.json().get("success"):
            # Item foi criado mas não moveu de estágio — registra como warning mas não falha
            return ("migrated_wrong_stage", conv_id)

    # Registrar no set para evitar duplicatas futuras nesta execução
    existing_conv_ids.add(conv_id)
    return ("migrated", conv_id)


def run_migration():
    print("=" * 60)
    print("MIGRAÇÃO RXP Marketing — contact → conversation")
    print(f"Início: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Buscar itens cegos
    blind_items = get_blind_items()

    # Carregar conversation_ids já no pipeline (para evitar duplicatas)
    print("Carregando conversation_ids existentes no pipeline...")
    existing_conv_ids = get_existing_conversation_ids_in_pipeline()
    print(f"Conversation_ids já presentes: {len(existing_conv_ids)}")

    # Contadores
    total = len(blind_items)
    migrated = 0
    no_conv = 0
    skip_dup = 0
    errors = 0
    wrong_stage = 0

    # Listas de detalhes para o relatório
    migrated_list = []
    no_conv_list = []
    error_list = []
    skip_list = []

    # Distribuição final por estágio
    stage_distribution = {sid: 0 for sid in STAGE_NAMES}

    print(f"\nProcessando {total} itens em lotes de {BATCH_SIZE}...\n")

    for batch_start in range(0, total, BATCH_SIZE):
        batch = blind_items[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"--- Lote {batch_num}/{total_batches} ({batch_start+1}-{min(batch_start+BATCH_SIZE, total)}/{total}) ---")

        for item in batch:
            contact_name = item.get("contact", {}).get("name", "?")
            stage_id = item["pipeline_stage_id"]
            stage_name = STAGE_NAMES.get(stage_id, stage_id[:8])

            result, extra = migrate_item(item, existing_conv_ids)

            if result == "migrated":
                migrated += 1
                stage_distribution[stage_id] = stage_distribution.get(stage_id, 0) + 1
                migrated_list.append({
                    "contact": contact_name,
                    "contact_id": item["item_id"],
                    "conv_id": extra,
                    "stage": stage_name
                })
                print(f"  ✓ [{stage_name}] {contact_name} → conv {extra[:8]}...")

            elif result == "migrated_wrong_stage":
                migrated += 1
                wrong_stage += 1
                stage_distribution[stage_id] = stage_distribution.get(stage_id, 0) + 1
                migrated_list.append({
                    "contact": contact_name,
                    "contact_id": item["item_id"],
                    "conv_id": extra,
                    "stage": stage_name,
                    "warning": "stage não atualizado"
                })
                print(f"  ✓⚠ [{stage_name}] {contact_name} → conv {extra[:8]}... (estágio não movido)")

            elif result == "no_conv":
                no_conv += 1
                no_conv_list.append({
                    "contact": contact_name,
                    "contact_id": item["item_id"],
                    "stage": stage_name,
                    "item_id": item["id"]
                })
                print(f"  - [{stage_name}] {contact_name} → sem conversa (mantido)")

            elif result == "skip_dup":
                skip_dup += 1
                skip_list.append({
                    "contact": contact_name,
                    "contact_id": item["item_id"],
                    "conv_id": extra,
                    "stage": stage_name
                })
                print(f"  ~ [{stage_name}] {contact_name} → duplicata {extra[:8]}... (pulado)")

            else:  # error
                errors += 1
                error_list.append({
                    "contact": contact_name,
                    "contact_id": item["item_id"],
                    "stage": stage_name,
                    "item_id": item["id"],
                    "error": extra
                })
                print(f"  ✗ [{stage_name}] {contact_name} → ERRO: {extra}")

        if batch_start + BATCH_SIZE < total:
            time.sleep(BATCH_SLEEP)

    # Contagem final de itens por estágio
    print("\nBuscando distribuição final...")
    url = f"{BASE_URL}/api/v1/pipelines/{PIPELINE_ID}/pipeline_items"
    r = api_get(url)
    final_stage_counts = {}
    if r and r.status_code == 200:
        all_items = r.json()["data"]
        for it in all_items:
            sid = it.get("pipeline_stage_id", "?")
            final_stage_counts[sid] = final_stage_counts.get(sid, 0) + 1

    # Resultados
    results = {
        "total_processados": total,
        "migrados": migrated,
        "sem_conversa": no_conv,
        "duplicatas_puladas": skip_dup,
        "erros": errors,
        "migrados_com_warning_stage": wrong_stage,
        "migrated_list": migrated_list,
        "no_conv_list": no_conv_list,
        "error_list": error_list,
        "skip_list": skip_list,
        "final_stage_counts": final_stage_counts,
    }

    # Salvar JSON de resultados
    json_path = "/home/daniel/evo-nexus/workspace/sales/migration_results_rxp_marketing.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResultados JSON salvos em: {json_path}")

    return results


if __name__ == "__main__":
    results = run_migration()

    total = results["total_processados"]
    migrated = results["migrados"]
    no_conv = results["sem_conversa"]
    skip_dup = results["duplicatas_puladas"]
    errors = results["erros"]
    wrong_stage = results["migrados_com_warning_stage"]
    final_counts = results["final_stage_counts"]

    print("\n" + "=" * 60)
    print("RESUMO FINAL")
    print("=" * 60)
    print(f"Total processados:       {total}")
    print(f"Migrados com sucesso:    {migrated} ({wrong_stage} com warning de estágio)")
    print(f"Sem conversa (mantidos): {no_conv}")
    print(f"Duplicatas puladas:      {skip_dup}")
    print(f"Erros:                   {errors}")
    print()
    print("Distribuição final por estágio:")
    for sid, count in sorted(final_counts.items(), key=lambda x: x[1], reverse=True):
        name = STAGE_NAMES.get(sid, sid[:8])
        print(f"  {name}: {count} itens")

    print("\nMigração concluída:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
