# Commonplace — Setup Guide

Commonplace is a self-hosted Readwise alternative. This covers everything from
scratch: server, KOReader plugin, and Obsidian plugin.

## Contents

- [Server (Docker)](#server-docker)
- [First-Time Setup](#first-time-setup)
- [KOReader Plugin](#koreader-plugin)
- [Obsidian Plugin](#obsidian-plugin)
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

# 2. Create .env (fill in your values)
cat > .env << 'EOF'
COMMONPLACE_USERNAME=admin
COMMONPLACE_PASSWORD=your-secure-password
SESSION_SECRET=your-random-hex-string-at-least-32-chars
EOF

# 3. Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  commonplace:
    image: ghcr.io/cansas/commonplace:latest
    ports:
      - "8765:8765"
    volumes:
      - ./data:/app/data
    env_file:
      - .env
    restart: unless-stopped
EOF

# 4. Start
docker compose up -d
```

The server is now running on `http://your-server:8765`.

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMMONPLACE_USERNAME` | Yes (first run) | — | Admin username, created on first launch |
| `COMMONPLACE_PASSWORD` | Yes (first run) | — | Admin password |
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
2. **Tools (wrench icon) → Export → Commonplace**
3. Set **server URL** — your server address, e.g.:
   - Docker on LAN: `http://192.168.1.130:8765`
   - Cloudflare tunnel: `https://commonplace.yourdomain.com`
   - **Do not** add a trailing slash
4. Set **API token** — the token you created for KOReader in Settings
5. Toggle **Export to Commonplace** on

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
3. In Obsidian: **Settings → Community Plugins → Commonplace Sync → Enable**

### Configuration

1. **Settings → Community Plugins → Commonplace Sync**
2. Set **Server URL** (same as KOReader above)
3. Set **API Token** — the token you created for Obsidian in Settings
4. Choose an **Output Folder** (default: `Commonplace/`)
5. Configure **Auto-sync** and **Periodic sync interval** as desired

### Usage

- **Ribbon icon** (download arrow) — click to sync
- **Command palette** — "Sync highlights from Commonplace"
- **Settings page** — "Sync Now" button

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
