---
name: int-youtube
description: "Query YouTube Data API v3 — channel stats, recent videos, top videos, comments. Supports multi-account (OAuth or API Key). Use when user asks about YouTube metrics, YouTube channel, subscribers, views, videos, engagement, or any reference to YouTube analytics."
---

# YouTube Data API v3

YouTube integration to monitor Evolution channels and others. Supports multiple accounts via OAuth (Social Auth App) or API Key.

## Setup

### Conta Principal (autenticada via OAuth)

Configurada via `.env` (gitignored):

```env
YOUTUBE_OAUTH_CLIENT_ID=<seu_client_id>.apps.googleusercontent.com
YOUTUBE_OAUTH_CLIENT_SECRET=<seu_client_secret>
YOUTUBE_REFRESH_TOKEN=<seu_refresh_token>
```

Scopes: `youtube`, `youtube.readonly`, `yt-analytics.readonly`, `yt-analytics-monetary.readonly`

### Contas adicionais (SOCIAL_YOUTUBE_N_*)

Configuráveis via `make social-auth` (OAuth login) ou manualmente no `.env`:
```env
SOCIAL_YOUTUBE_1_LABEL=Evolution API
SOCIAL_YOUTUBE_1_ACCESS_TOKEN=ya29...
SOCIAL_YOUTUBE_1_CHANNEL_ID=UC9kZHm3TnEt41ztGOLyQO9g
SOCIAL_YOUTUBE_1_REFRESH_TOKEN=1//0h...
```

### Auth Helper

```python
import os, urllib.request, urllib.parse, json

def get_youtube_token() -> str:
    data = urllib.parse.urlencode({
        "client_id":     os.environ["YOUTUBE_OAUTH_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_OAUTH_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return json.loads(urllib.request.urlopen(req).read())["access_token"]

def ytapi(path: str) -> dict:
    at = get_youtube_token()
    req = urllib.request.Request(
        f"https://www.googleapis.com/youtube/v3{path}",
        headers={"Authorization": f"Bearer {at}"}
    )
    return json.loads(urllib.request.urlopen(req).read())

# Canal próprio
# ytapi("/channels?part=snippet,statistics&mine=true")
# Últimos vídeos
# ytapi("/search?part=snippet&forMine=true&type=video&order=date&maxResults=10")
```

## API Client

```bash
python3 {project-root}/.claude/skills/int-youtube/scripts/youtube_client.py <command> [args]
```

### Commands

```bash
# List configured accounts
youtube_client.py accounts

# Channel stats (subscribers, views, total videos)
youtube_client.py channel_stats [account_label_or_index]

# Last N videos with metrics (via playlistItems — 3 units)
youtube_client.py recent_videos [account] [N]

# Top N videos by views
youtube_client.py top_videos [account] [N]

# Stats for specific videos
youtube_client.py video_stats VIDEO_ID [VIDEO_ID...]

# Comments on a video
youtube_client.py comments VIDEO_ID [N]

# Summary of all accounts
youtube_client.py summary
```

### Output JSON exemplo
```json
{
  "account": "Evolution API",
  "channel_id": "UC9kZHm3TnEt41ztGOLyQO9g",
  "subscribers": 7450,
  "total_views": 132462,
  "video_count": 27,
  "videos": [
    {
      "id": "abc",
      "title": "...",
      "published": "2026-...",
      "views": 7180,
      "likes": 500,
      "comments": 164,
      "engagement_rate": 9.25,
      "url": "https://youtube.com/watch?v=abc"
    }
  ]
}
```

## Key metrics
- Subscribers (daily/weekly/monthly delta)
- Total views and per video
- Engagement rate: (likes + comments) / views
- Best video of the period
- Publishing frequency
- Recent comments (sentiment)

## Quota
- 10,000 units/day (resets at midnight Pacific Time)
- `playlistItems`: 1 unit (used instead of `search` which costs 100)
- `channels`, `videos`, `commentThreads`: 1 unit each
- Each pagination is charged again
