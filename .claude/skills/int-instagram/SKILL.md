---
name: int-instagram
description: "Query Instagram Graph API — profile stats, recent posts, engagement, insights. Supports multi-account (OAuth via Social Auth App). Use when user asks about Instagram metrics, followers, posts, engagement, or any reference to Instagram analytics."
---

# Instagram Graph API

Instagram integration to monitor company and user profiles. Supports multiple accounts via OAuth (Social Auth App).

## Setup

Accounts configured via `make social-auth` (OAuth login with Facebook). Saved in `.env`:
```env
SOCIAL_INSTAGRAM_1_LABEL=your_account
SOCIAL_INSTAGRAM_1_ACCESS_TOKEN=YOUR_TOKEN
SOCIAL_INSTAGRAM_1_ACCOUNT_ID=YOUR_ACCOUNT_ID
SOCIAL_INSTAGRAM_1_PAGE_TOKEN=YOUR_PAGE_TOKEN
```

## Setup alternativo — EvoHub Proxy

Caminho alternativo via proxy EvoHub (`https://api.evohub.ai/meta`), util quando nao se quer manter o app OAuth do Social Auth ou quando ja existe um token de canal EvoHub provisionado.

**Configuracao no `.env`:**
- `EVOHUB_INSTAGRAM_TOKEN` — token de canal do EvoHub (NAO copiar o valor literal; sempre referenciar a env var)
- `EVOHUB_INSTAGRAM_ID=26802799379390086` — Instagram Business Account ID

**Conta atualmente conectada:** `@danielvalladaresexp` (Daniel Valladares) — account type `MEDIA_CREATOR`.

**Base URL:** `https://api.evohub.ai/meta`
**Auth header:** `Authorization: Bearer {EVOHUB_INSTAGRAM_TOKEN}`

O proxy converte o token de canal automaticamente para o token Meta apropriado e aceita qualquer endpoint da Meta Graph API v23.0 (basta substituir `https://graph.facebook.com/v23.0` por `https://api.evohub.ai/meta`).

### Exemplos curl

```bash
# Perfil
curl -s -H "Authorization: Bearer $EVOHUB_INSTAGRAM_TOKEN" \
  "https://api.evohub.ai/meta/v23.0/$EVOHUB_INSTAGRAM_ID?fields=id,username,name,account_type,followers_count,media_count"

# Conversas (DMs)
curl -s -H "Authorization: Bearer $EVOHUB_INSTAGRAM_TOKEN" \
  "https://api.evohub.ai/meta/v23.0/$EVOHUB_INSTAGRAM_ID/conversations?platform=instagram&fields=id,updated_time,participants"

# Send message (responder DM)
curl -s -X POST -H "Authorization: Bearer $EVOHUB_INSTAGRAM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"recipient":{"id":"IGSID_DO_DESTINATARIO"},"message":{"text":"Ola!"}}' \
  "https://api.evohub.ai/meta/v23.0/$EVOHUB_INSTAGRAM_ID/messages"
```

### Helpers prontos

Existe skill dedicada `custom-int-evohub-instagram` com helpers Python (perfil, conversas, send message, insights). Para uso programatico, prefira essa skill em vez de montar curl na mao.

### Limitacao atual

A conta `@danielvalladaresexp` esta como `MEDIA_CREATOR`, o que **bloqueia publish** (criacao de posts/reels/stories via API). Leitura de perfil, conversas e insights funciona normalmente. Para habilitar publish, e necessario migrar a conta para `BUSINESS`.

## API Client

```bash
python3 {project-root}/.claude/skills/int-instagram/scripts/instagram_client.py <command> [args]
```

### Commands

```bash
# List configured accounts
instagram_client.py accounts

# Profile (followers, bio, media count)
instagram_client.py profile [account_label]

# Last N posts with engagement
instagram_client.py recent_posts [account] [N]

# Top N posts by engagement
instagram_client.py top_posts [account] [N]

# Insights for a specific post
instagram_client.py post_insights POST_ID [account]

# Account insights (impressions, reach, profile views — 30d)
instagram_client.py account_insights [account]

# Summary of all accounts
instagram_client.py summary
```

## Key metrics
- Followers (delta via daily snapshots)
- Engagement rate: (likes + comments) / followers
- Reach and impressions (via account insights)
- Profile views
- Best post of the period
- Reels vs static posts
- Publishing frequency

## Rate Limits
- Instagram Platform endpoints: `4800 × impressions` per 24h
- Business Discovery / Hashtag: 200 calls/hour/user
