---
name: int-kommo
description: "Kommo CRM (ex-amoCRM) API v4 integration. Multi-tenant support for 20+ client accounts. Manage leads, contacts, tasks, pipelines, webhooks. Use when users ask about Kommo data, leads, contacts, deals, or CRM automation. Integração com Kommo CRM: leads, contatos, tarefas, pipelines, webhooks."
---

# Kommo CRM Skill

Integration with Kommo CRM via REST API v4 (Bearer Token).

## When to use

- List or create leads, contacts, or deals
- Query or update pipeline stages
- Manage tasks and activities
- Configure webhooks and automations
- Query any client's Kommo account

## Multi-Tenant Architecture

This workspace manages 20+ Kommo accounts. Each uses env vars with a prefix:

| Client | Prefix | Base URL | Account ID |
|--------|--------|----------|------------|
| Redigir | `REDIGIR_KOMMO_` | plataformaredigir.kommo.com | 34920299 |
| Nogueira Resolve | `NOGUEIRA_KOMMO_` | nogueiraresolveadv.kommo.com | 35241960 |
| BabyGym Brooklin | `BABYGYM_KOMMO_` | babygymbrooklin.kommo.com | 35465543 |
| Futuro Eventos | `FUTURO_KOMMO_` | futuroeventos.kommo.com | 36141863 |
| Yamatec | `YAMATEC_KOMMO_` | yamatec.kommo.com | (TBD) |

Each client needs these env vars set:
```bash
{PREFIX}TOKEN=eyJ...          # Long-lived JWT (5+ years)
{PREFIX}BASE_URL=https://x.kommo.com
{PREFIX}ACCOUNT_ID=12345678
```

## Setup

### Getting a Long-Lived Token

Kommo uses JWT tokens that can last years. To generate one:

1. Go to `https://{subdomain}.kommo.com`
2. Navigate to **Settings → Integrations**
3. Click **+ Create Integration**
4. Name: "API Integration" (or similar)
5. Grant permissions: CRM, Files, Notifications
6. Save and copy the **Long-lived access token**

### Add to `.env`

```bash
# Example for Redigir
REDIGIR_KOMMO_TOKEN=eyJ0eXAiOiJKV1QiLC...
REDIGIR_KOMMO_BASE_URL=https://plataformaredigir.kommo.com
REDIGIR_KOMMO_ACCOUNT_ID=34920299
```

### Using the Client

```bash
# Generic format
python3 .claude/skills/int-kommo/scripts/kommo_client.py \
  --account redigir \
  GET /leads --params limit=10

# Or with explicit env prefix
python3 .claude/skills/int-kommo/scripts/kommo_client.py \
  --prefix REDIGIR_KOMMO_ \
  GET /leads?limit=10
```

---

## Base URL

```
https://{subdomain}.kommo.com/api/v4
```

---

## Leads

### List leads

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/leads?limit=50&page=1" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `limit` | number | Items per page (max 250) |
| `page` | number | Page number |
| `query` | string | Search by name/email/phone |
| `filter[pipeline_id]` | number | Filter by pipeline |
| `filter[statuses][0][pipeline_id]` | number | Filter by pipeline + status |
| `filter[statuses][0][status_id]` | number | Status within pipeline |
| `filter[responsible_user_id]` | number | Filter by owner |
| `with` | string | Include relations: `contacts,catalog_elements,loss_reason` |

### Get single lead

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/leads/12345?with=contacts" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

### Create lead

```bash
curl -s -X POST \
  "https://plataformaredigir.kommo.com/api/v4/leads" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '[{
    "name": "New Lead",
    "price": 5000,
    "status_id": 89341147,
    "pipeline_id": 11632495,
    "responsible_user_id": 9592603,
    "custom_fields_values": [
      {
        "field_id": 774614,
        "values": [{"value": true}]
      }
    ],
    "_embedded": {
      "contacts": [{"id": 67890}]
    }
  }]'
```

### Update lead

```bash
curl -s -X PATCH \
  "https://plataformaredigir.kommo.com/api/v4/leads" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '[{
    "id": 12345,
    "status_id": 89341155,
    "custom_fields_values": [
      {
        "field_id": 774620,
        "values": [{"value": true}]
      }
    ]
  }]'
```

---

## Contacts

### List contacts

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/contacts?limit=50" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

**Query params:**
| Param | Type | Description |
|-------|------|-------------|
| `limit` | number | Items per page |
| `page` | number | Page number |
| `query` | string | Search name/email/phone |
| `filter[id]` | number | Filter by ID |

### Create contact

```bash
curl -s -X POST \
  "https://plataformaredigir.kommo.com/api/v4/contacts" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '[{
    "name": "John Doe",
    "first_name": "John",
    "last_name": "Doe",
    "responsible_user_id": 9592603,
    "custom_fields_values": [
      {
        "field_code": "EMAIL",
        "values": [{"value": "john@example.com", "enum_code": "WORK"}]
      },
      {
        "field_code": "PHONE",
        "values": [{"value": "+5511999999999", "enum_code": "WORK"}]
      }
    ]
  }]'
```

---

## Tasks

### List tasks

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/tasks?limit=50" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

### Create task

```bash
curl -s -X POST \
  "https://plataformaredigir.kommo.com/api/v4/tasks" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '[{
    "text": "Follow up call",
    "complete_till": 1735689600,
    "entity_type": "leads",
    "entity_id": 12345,
    "responsible_user_id": 9592603,
    "task_type_id": 1
  }]'
```

**Task types:**
| ID | Type |
|----|------|
| 1 | Call |
| 2 | Meeting |
| 3 | Email |

---

## Pipelines

### List pipelines

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/leads/pipelines" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

Returns all pipelines with their statuses (stages).

---

## Custom Fields

### List lead custom fields

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/leads/custom_fields" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

### List contact custom fields

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/contacts/custom_fields" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

---

## Users

### List users

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/users" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

---

## Webhooks

### List webhooks

```bash
curl -s -X GET \
  "https://plataformaredigir.kommo.com/api/v4/webhooks" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}"
```

### Create webhook

```bash
curl -s -X POST \
  "https://plataformaredigir.kommo.com/api/v4/webhooks" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "https://your-endpoint.com/webhook",
    "settings": ["add_lead", "update_lead", "add_contact"]
  }'
```

**Available events:**
- `add_lead`, `update_lead`, `delete_lead`
- `add_contact`, `update_contact`, `delete_contact`
- `add_task`, `complete_task`
- `status_lead`, `responsible_lead`

---

## Notes

### Add note to lead

```bash
curl -s -X POST \
  "https://plataformaredigir.kommo.com/api/v4/leads/12345/notes" \
  -H "Authorization: Bearer ${REDIGIR_KOMMO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '[{
    "note_type": "common",
    "params": {
      "text": "Called the customer, will follow up tomorrow."
    }
  }]'
```

**Note types:** `common`, `call_in`, `call_out`, `service_message`, `message_cashier`, `sms_in`, `sms_out`

---

## Auth Model

- **Type:** Bearer Token (JWT)
- **Header:** `Authorization: Bearer <token>`
- **Token lifetime:** Long-lived (configured per integration, can be 5+ years)
- **No refresh flow:** Tokens don't expire frequently; regenerate in Kommo UI if needed

## Pagination

All list endpoints use:
- `limit` — items per page (default 50, max 250)
- `page` — page number (1-indexed)

## Rate Limits

- **7 requests/second** per account
- Back off on HTTP 429 responses
- Use batch endpoints when possible (POST/PATCH accept arrays)

## Error Handling

| Code | Meaning |
|------|---------|
| 400 | Validation error (check request body) |
| 401 | Invalid or expired token |
| 403 | Insufficient permissions |
| 429 | Rate limit exceeded |

## API Domains

Kommo uses region-specific API domains. The JWT token includes `api_domain`:
- `api-b.kommo.com` — Brazil
- `api-c.kommo.com` — Colombia/Chile
- `api-g.kommo.com` — Global
- `api-e.kommo.com` — Europe

Use the `api_domain` from the JWT payload, or default to the base URL's subdomain.

## Notes

- Client-specific documentation is in `custom-int-kommo-{client}/SKILL.md`
- For bulk operations, prefer batch endpoints (POST/PATCH arrays up to 250 items)
- Kommo API v4 replaced v2 in 2022; v2 is deprecated
