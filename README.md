# commonplace

## I am working on a multi-user version of Commonplace cansas/commonplace-multi is the repo. It has a migration nuilt in (backup your current dbase!).

A self-hosted Readwise alternative — capture, browse, review, and resurface your highlights.

- **Capture**: Import from KOReader, Kindle, Obsidian, Readwise API, or manual entry
- **Browse**: Full-text search, filter by source/tag/favorites, book view with covers
- **Review**: Daily review
- **Achievements**: Unlock witty milestones as you build your review streak
- **Sync**: Push highlights from KOReader via custom plugin, sync to Obsidian via plugin, or auto-sync from BookOrbit (kobo, koreader, and web annotations)
- **Self-hosted**: Single Docker container, SQLite database, no external services required

## Quick Start

```bash
docker run -d --name commonplace -p 8765:8765 \
  -v ./data:/app/data \
  ghcr.io/cansas/commonplace:latest
```

Then open `http://localhost:8765` and the setup wizard will walk you through creating your admin account.

For full setup instructions, see [INSTALL.md](INSTALL.md).

## Documentation

| Document | Description |
|----------|-------------|
| [API.md](API.md) | Full API reference — all 62 endpoints with auth, params, and examples |
| [ENV.md](ENV.md) | Environment variables reference |
| [INSTALL.md](INSTALL.md) | Server, KOReader plugin, and Obsidian plugin setup |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Bug reports, PR workflow, AI code policy |
## Features

- **Highlights** — add, edit, delete, search, filter by source/favorites/book
- **Books view** — browse by book with covers (HardCover.app + Open Library), rename/merge/delete
- **Book metadata** — set HardCover ID or ISBN for reliable cover lookups
- **Tag management** — create, rename, merge, delete tags with optional color coding
- **Import** — Readwise Obsidian .md, KOReader JSON, Kindle My Clippings, Readwise-compatible API
- **Export** — batch export all highlights as JSON
- **Backup & Restore** — ZIP download with database + covers, restore from ZIP
- **Share cards** — PNG/SVG share cards per highlight with OpenGraph meta tags
- **Themes** — Modern, Reader, Dark, plus unlimited **custom themes** — drop a `.css` file into `data/themes/` or upload via Settings → Appearance ([documentation](THEMES.md))
- **Streaks** — track daily review streaks with current and best counters
- **BookOrbit Sync** — auto-import annotations from BookOrbit (kobo, koreader, web) with SHA256 fingerprint dedup. Configure in Settings → BookOrbit tab
- **First-run wizard** — web-based admin creation, no env vars required

## Screenshots

| | |
|---|---|
| **Home** — recent & favorite highlights at a glance | **Daily Review** — SM-2 spaced repetition with 4 rating levels |
| ![Home](screenshots/homescreen.png) | ![Daily Review](screenshots/daily_review.png) |
| **Settings (Modern theme)** | **Settings (Reader theme)** |
| ![Modern Theme](screenshots/setting_modern_theme.png) | ![Reader Theme](screenshots/settings_reader_theme.png) |
| **Settings (Dark theme)** | **Import** — KOReader, Kindle, Readwise, Obsidian |
| ![Dark Theme](screenshots/settings_dark_theme.png) | ![Import](screenshots/settings_import.png) |

## License

MIT No Attribution
