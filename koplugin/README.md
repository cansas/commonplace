# Commonplace KOReader Exporter

Export highlights from KOReader directly to your Commonplace server.

## Installation

1. Connect your KOReader device via USB (or copy wirelessly)
2. Copy `commonplace.lua` to the exporter targets directory:

   ```
   koreader/plugins/exporter.koplugin/target/commonplace.lua
   ```

3. Eject and reopen a book on your KOReader device
4. Open the **Tools** menu (wrench icon) → **Export** → **Commonplace**
5. Set your server URL (e.g., `https://commonplace.yourdomain.com`)
6. Set your API token (from Commonplace's Settings page)
7. Toggle **Export to Commonplace** on
8. Export highlights from the **Export** submenu

## Usage

The plugin supports the same export options as the built-in Readwise exporter:

- **Current book** — Export highlights only for the book you're reading
- **All books** — Export highlights from all books in your KOReader library

## Cloudflare Tunnel

If your Commonplace server is behind a Cloudflare Access tunnel, make sure you have a **Bypass** policy for paths starting with `/api/` so KOReader can reach the API without browser login.

## Format

Highlights are sent as:

```json
POST /api/v2/highlights
Authorization: Token <your-token>

{
  "highlights": [{
    "text": "highlighted text",
    "title": "Book Title",
    "author": "Author Name",
    "source_type": "koreader",
    "category": "books",
    "note": "user note",
    "location": 42,
    "location_type": "order",
    "highlighted_at": "2024-01-15T10:30:00Z"
  }]
}
```

This matches the Readwise API v2 format, so Commonplace handles it identically.
