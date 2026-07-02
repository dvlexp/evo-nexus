---
name: int-evolution-go
description: "Manage Evolution Go instances and send WhatsApp messages via the Evolution Go REST API. Use when you need to list/create/connect instances, send messages (text, media, location, contact, link, sticker, poll), react/edit/delete messages, check connection status, or get QR codes. Calls the Evolution Go server directly with no third-party proxy."
metadata:
  openclaw:
    requires:
      env:
        - EVOLUTION_GO_URL
        - EVOLUTION_GO_KEY
      bins:
        - python3
    primaryEnv: EVOLUTION_GO_KEY
    files:
      - "scripts/*"
---

# Evolution Go

Interact with your Evolution Go (WhatsApp) server via the Evolution Go REST API.

## Setup (one-time)

1. Get your API key from your Evolution Go instance admin panel.
2. Set environment variables:
   ```
   EVOLUTION_GO_URL=https://go.evolution-api.com
   EVOLUTION_GO_KEY=your-api-key-here
   ```

## Instance Management

### List all instances
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py instances
```

### Create a new instance
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py create_instance my-instance --token optional-token
```

### Connect to instance
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py connect --phone 5511999999999 --webhook https://example.com/webhook
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py connect --phone 5511999999999 --webhook https://example.com/webhook --immediate --subscribe message,message.update
```

### Disconnect from instance
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py disconnect
```

### Get instance status
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py status
```

### Get QR code for pairing
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py qr
```

### Request pairing code
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py pair --phone 5511999999999
```

### Logout from instance
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py logout
```

### Delete an instance
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py delete_instance <instanceId>
```

### Remove proxy from instance
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py delete_proxy <instanceId>
```

### Overview of all instances with status
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py summary
```

## Export Contacts

List or export the address book of a specific instance. Useful for backups, audience builds, and outbound campaigns.

```bash
# 1. Print as JSON (default)
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py contacts dvl

# 2. Export to CSV (UTF-8 with BOM, Excel-friendly for accents)
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py contacts dvl --output csv:/tmp/dvl-contacts.csv

# 3. Export to a new Google Sheet (requires Google OAuth env vars)
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py contacts dvl --output gsheet:"DVL Contacts 2026-06"
```

### Notes

- **Per-instance token**: `contacts` is an instance-scoped endpoint. The client looks up the instance's own token via `/instance/all` (matched by `name`) and uses that as the `apikey` header — NOT the global `EVOLUTION_GO_KEY`.
- If the instance name is unknown the client errors with the list of available instances.
- A warning is printed (stderr) if the instance is disconnected, but the export still proceeds — cached contacts may exist.
- **CSV schema** (5 columns, lowercase snake_case): `jid, first_name, full_name, push_name, business_name`. Empty values are blank (not `None`).
- **Google Sheets**: uses the workspace OAuth refresh token (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`). Scopes requested: `spreadsheets` + `drive.file`. The created sheet is owned by the OAuth account.

## Send Messages

### Send text message
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_text 5511999999999 "Hello world"
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_text 5511999999999 "Hello" --delay 1000 --quoted '{"messageId":"ABC","participant":"5511..."}'
```

### Send media (image, video, audio, document)
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_media 5511999999999 --url https://example.com/photo.jpg --type image --caption "Check this out"
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_media 5511999999999 --url https://example.com/doc.pdf --type document --filename report.pdf
```

### Send location
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_location 5511999999999 --lat -19.9167 --lng -43.9345 --name "Office" --address "Av. Afonso Pena, 1000"
```

### Send contact (vCard)
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_contact 5511999999999 --fullName "John Doe" --phone 5511888888888 --org "Acme Corp"
```

### Send link preview
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_link 5511999999999 --url https://example.com --text "Check this link" --title "Example" --description "A great site" --imgUrl https://example.com/og.jpg
```

### Send sticker
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_sticker 5511999999999 --sticker https://example.com/sticker.webp
```

### Send poll
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py send_poll 5511999999999 --question "Favorite color?" --options "Red,Blue,Green" --maxAnswer 1
```

## Message Operations

### React to a message
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py react 5511999999999 --id MSG_ID --reaction "👍"
```

### Edit a sent message
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py edit_message --chat 5511999999999@s.whatsapp.net --id MSG_ID --message "Updated text"
```

### Delete message for everyone
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py delete_message --chat 5511999999999@s.whatsapp.net --id MSG_ID
```

### Mark messages as read
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py mark_read 5511999999999 --ids MSG_ID1,MSG_ID2
```

### Get message delivery status
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py message_status --id MSG_ID
```

### Set chat presence (composing/recording)
```bash
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py set_presence 5511999999999 --state composing
python3 /mnt/skills/user/int-evolution-go/scripts/evolution_go_client.py set_presence 5511999999999 --state composing --isAudio
```

## Output

JSON to stdout. Use `--json` flag for raw JSON on any command (default for single-object responses).

## Notes

- Evolution Go uses instance-scoped auth: the API key identifies a specific instance.
- Phone numbers accept plain format (e.g. `5511999999999`) — the client converts to JID internally.
- The `send_media` endpoint accepts a URL (not file upload).
- The `send_link` endpoint auto-generates link previews.
- All send commands support `--delay`, `--quoted`, `--mentionAll`, and `--mentionedJid`.
