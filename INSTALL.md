# commonplace — Setup Guide

commonplace is a self-hosted Readwise alternative. This covers everything from
scratch: server, KOReader plugin, and Obsidian plugin.

## Contents

- [Server (Docker)](#server-docker)
- [First-Time Setup](#first-time-setup)
- [KOReader Plugin](#koreader-plugin)
- [Obsidian Plugin](#obsidian-plugin)
- [BookOrbit Sync](#bookorbit-sync)
- [Updating](#updating)

---

## Server (Docker)

### Prerequisites

- Docker & Docker Compose on your server (Unraid, NAS, VPS, etc.)
- A `.env` file with your secrets

### Quick start

```bash
# 1. Create a directory
mkdir -p /opt/commonplace && cd /opt/commonplace

# 2. Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  commonplace:
    image: ghcr.io/cansas/commonplace:latest
    ports:
      - "8765:8765"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
EOF

# 3. Start
docker compose up -d
```

The server is now running on `http://your-server:8765`. Open it in a browser and the **setup wizard** will walk you through creating your admin account.

### Advanced: pre-configure credentials via env vars

If you want to skip the setup wizard, create a `.env` file alongside `docker-compose.yml`:

```bash
COMMONPLACE_USERNAME=admin
COMMONPLACE_PASSWORD=your-secure-password
SESSION_SECRET=your-random-hex-string-at-least-32-chars
```

And uncomment the `env_file` line in `docker-compose.yml`. On first run the admin account is created automatically.

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMMONPLACE_USERNAME` | No | — | Admin username (only used if you want to skip the setup wizard) |
| `COMMONPLACE_PASSWORD` | No | — | Admin password (only used with COMMONPLACE_USERNAME) |
| `SESSION_SECRET` | No | auto-generated | Secret key for session cookies |
| `DATABASE_URL` | No | `sqlite+aiosqlite:////app/data/commonplace.db` | Database connection string |

### First run

On the very first launch, the server creates an admin user from the
`COMMONPLACE_USERNAME` / `COMMONPLACE_PASSWORD` env vars. Subsequent starts
ignore those vars. If no user exists and the vars are missing, the server
refuses to start with a clear error message.

---

## First-Time Setup

1. Open `http://your-server:8765` in a browser
2. Log in with the username and password from your `.env`
3. Go to **Settings → Device Tokens**
4. Create one token per device/app:

   | Token name | Used by |
   |------------|---------|
   | `koreader-pocketbook` | Your KOReader device |
   | `koreader-remarkable` | (if you have a second device) |
   | `obsidian` | Obsidian sync plugin |
   | `ios-app` | (future iOS app) |

5. **Copy each token immediately** — it's shown once and never again
6. Configure each device with its token (see plugin sections below)

---

## KOReader Plugin

### Installation

1. Download `commonkore-plugin.zip` from the
   [latest release](https://github.com/cansas/commonplace/releases/latest)
2. Extract it to your KOReader device:
   ```
   koreader/plugins/commonkore.koplugin/main.lua
   ```
3. Restart KOReader

### Configuration

1. Open any book
2. **Tools (wrench icon) → Export → commonplace**
3. Set **server URL** — your server address, e.g.:
   - Docker on LAN: `http://192.168.1.130:8765`
   - Cloudflare tunnel: `https://commonplace.yourdomain.com`
   - **Do not** add a trailing slash
4. Set **API token** — the token you created for KOReader in Settings
5. Toggle **Export to commonplace** on

### Usage

- Export highlights for the current book or all books via
  **Tools → Export → Export Current Notes / Export All Notes**

---

## Obsidian Plugin

### Installation

1. Download `commonplace-sync.zip` from the
   [latest release](https://github.com/cansas/commonplace/releases/latest)
2. Extract into your Obsidian vault:
   ```
   <vault>/.obsidian/plugins/commonplace-sync/
   ```
3. In Obsidian: **Settings → Community Plugins → commonplace Sync → Enable**

### Configuration

1. **Settings → Community Plugins → commonplace Sync**
2. Set **Server URL** (same as KOReader above)
3. Set **API Token** — the token you created for Obsidian in Settings
4. Choose an **Output Folder** (default: `commonplace/`)
5. Configure **Auto-sync** and **Periodic sync interval** as desired

### Usage

- **Ribbon icon** (download arrow) — click to sync
- **Command palette** — "Sync highlights from commonplace"
- **Settings page** — "Sync Now" button

---

## BookOrbit Sync

If you run [BookOrbit](https://github.com/bookorbit/bookorbit) next to commonplace,
commonplace can pull its annotations (kobo, koreader, web) on a timer. Everything is
configured in **Settings → BookOrbit**: server URL (for example
`http://192.168.1.130:3000`), credentials, and the auto-sync toggle. Sync runs every
15 minutes while enabled; **Sync Now** runs it on demand.

Two credential styles are supported, and the API key wins whenever both are set.

### API key (recommended)

1. In BookOrbit, open **Settings → You → API keys** and create a key with access
   **Read**. Pick an expiry. The key starts with `bok_` and is shown once.
2. In commonplace, paste it into **Settings → BookOrbit → API Key** and save.
3. **Test Connection** should answer `Connected using API key (<your name>)`.

A read key with no extra permissions is enough — the sync only performs `GET`s. Give
each tool its own key so one can be revoked without breaking the others, and keep
libraries and permissions as narrow as you can afford. See BookOrbit's own
`docs/API_KEYS.md` for the full key model.

### Username and password

Leave **API Key** blank and fill in **Username** and **Password** instead. The sync
then logs in with `POST /api/v1/auth/login` and reuses the session cookie, exactly as it
did before BookOrbit had API keys. Setups that were configured this way keep working
with no change.

Either way, a rejected credential is reported in the settings page (for example
`Sync disabled: auth_failed: Invalid API key`) rather than showing a misleading
"0 imported" result.

---

## Updating

### Server

```bash
docker compose pull
docker compose up -d
```

The GitHub Actions workflow automatically builds and pushes a new Docker image
on every push to `main`. There's no migration step — SQLite schema changes
are applied automatically on startup.

### Plugins

Download the latest `commonkore-plugin.zip` or `commonplace-sync.zip` from
the [releases page](https://github.com/cansas/commonplace/releases) and
replace the files on your device / in your vault.

---

## Troubleshooting

### Server won't start — "Set COMMONPLACE_USERNAME and COMMONPLACE_PASSWORD"

First run: set both env vars and restart. If you already have a user in the
database but removed the vars, the server works fine — these are only checked
when the users table is empty.

### KOReader export succeeds but no highlights appear

Check the server logs for field name issues. The `/api/v2/highlights` endpoint
accepts both Readwise field names (`title`, `author`, `location`) and internal
names (`book_title`, `book_author`, `page`).

### 401 Unauthorized on API calls

The token was revoked or mistyped. Go to **Settings → Device Tokens** and
create a fresh one, then update your device.

### Forgot your password?

You can't recover it from the web UI. Either:
- **Directly in the database:** Use `sqlite3` to update the `users` table
  with a new bcrypt hash, or
- **Delete the database** and start fresh (wipes all highlights too)
