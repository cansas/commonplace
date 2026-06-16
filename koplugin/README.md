# Commonkore — KOReader → Commonplace Exporter

A single-file exporter target for KOReader that sends your book highlights to your **Commonplace** server.

## Installation

1. Connect your KOReader device via USB
2. Copy `commonkore.lua` into the exporter targets directory:

   ```
   koreader/plugins/exporter.koplugin/target/commonkore.lua
   ```

3. Eject your device and open any book
4. Open the **Tools** menu (wrench icon) → **Export** → **Commonkore**
5. Set your **server URL** (e.g., `http://192.168.1.130:8765` or `https://commonplace.yourdomain.com`)
6. Set your **API token** (from Commonplace's Settings page)
7. Toggle **Export to Commonkore** on
8. Use the standard **Export** submenu to send highlights

## Usage

Same as the built-in Readwise exporter — export highlights for the current book or all books from the Export menu.

## Cloudflare Tunnel

If Commonplace is behind Cloudflare Access, add a **Bypass** policy for paths starting with `/api/` so KOReader can reach the API without browser authentication.

## How it works

Sends highlights to `{server_url}/api/v2/highlights` with `Authorization: Token {token}`, matching the Readwise API v2 format.
