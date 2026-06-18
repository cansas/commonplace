"""Readwise-style share cards with book cover, quote, and attribution.

Generates 1200x630 SVG cards (optionally with embedded cover image as data URL),
then converts to PNG via cairosvg for maximum compatibility.
"""

from xml.sax.saxutils import escape
import base64
import os
import re
from typing import Optional

import httpx


# ── Cover image helpers ──────────────────────────────────────────────────

COVERS_DIR = os.environ.get(
    "COVERS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "covers"),
)

_COVER_CACHE: dict[str, str] = {}  # url -> data_uri (in-memory, per-process)


def _data_uri_from_bytes(data: bytes, url: str) -> str:
    """Build a data: URI from raw bytes, guessing MIME type from the URL."""
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".svg": "image/svg+xml"}.get(ext, "image/png")
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _resolve_cover_path(cover_url: str) -> Optional[str]:
    """If cover_url is a relative path like /static/covers/..., resolve to disk path."""
    m = re.match(r"^/static/covers/(.+)", cover_url)
    if m:
        fpath = os.path.join(COVERS_DIR, m.group(1))
        if os.path.isfile(fpath):
            return fpath
    return None


async def fetch_cover_data(cover_url: str) -> Optional[str]:
    """Return a data: URI for the cover image, or None if unavailable.

    Caches results in-memory so repeated card generation for the same
    cover doesn't re-fetch.
    """
    if not cover_url:
        return None
    if cover_url in _COVER_CACHE:
        return _COVER_CACHE[cover_url]

    # Local file
    local = _resolve_cover_path(cover_url)
    if local:
        try:
            with open(local, "rb") as f:
                data = f.read()
            uri = _data_uri_from_bytes(data, cover_url)
            _COVER_CACHE[cover_url] = uri
            return uri
        except OSError:
            return None

    # External HTTP(S) URL
    if cover_url.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(cover_url)
                if resp.status_code == 200:
                    uri = _data_uri_from_bytes(resp.content, cover_url)
                    _COVER_CACHE[cover_url] = uri
                    return uri
        except Exception:
            return None

    return None


# ── Text wrapping ────────────────────────────────────────────────────────

_CHAR_W = 18  # approximate px per character at 32px font


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current += (" " if current else "") + word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _fit_text(text: str, avail_w: int, avail_h: int, font_size: int,
              line_h_ratio: float = 1.4) -> tuple[list[str], int, int]:
    """Scale text to fit available space, returning (lines, font_size, line_h)."""
    max_chars = max(10, int(avail_w / _CHAR_W))
    line_h = int(font_size * line_h_ratio)

    for attempt in range(5):
        lines = _wrap_text(text, max_chars)
        total_h = len(lines) * line_h
        if total_h <= avail_h or font_size <= 16:
            return lines, font_size, line_h

        # Scale down
        ratio = avail_h / total_h
        font_size = max(16, int(font_size * ratio))
        line_h = int(font_size * line_h_ratio)
        max_chars = max(10, int(avail_w / (_CHAR_W * (font_size / 32))))

    lines = _wrap_text(text, max_chars)
    if len(lines) > 12:
        lines = lines[:11]
        lines.append(lines[-1] + "\u2026")
    return lines, font_size, line_h


# ── Card layout constants ───────────────────────────────────────────────

W = 1200
H = 630
COVER_W = 320
COVER_H = 480
LEFT_PAD = 40    # left margin
RIGHT_PAD = 40   # right margin
COVER_GAP = 40   # gap between cover and text
GUTTER = 40      # top/bottom margin

QUOTE_W = W - LEFT_PAD - COVER_W - COVER_GAP - RIGHT_PAD  # ~760
QUOTE_START_X = LEFT_PAD + COVER_W + COVER_GAP
QUOTE_TOP = GUTTER + 10
QUOTE_BOTTOM = H - GUTTER - 50  # room for branding
QUOTE_AVAIL_H = QUOTE_BOTTOM - QUOTE_TOP

# Colors
BG = "#fafaf9"          # stone-50 warm off-white
TEXT = "#1e293b"        # slate-800
TITLE = "#475569"       # slate-600
AUTHOR = "#94a3b8"      # slate-400
ACCENT = "#6366f1"      # indigo-500
BRAND = "#a1a1aa"       # zinc-400
QUOTE_MARK = "#c7d2fe"  # indigo-200


# ── SVG generation ───────────────────────────────────────────────────────

def _cover_svg(data_uri: str) -> str:
    """SVG fragment for the book cover image with shadow and rounded corners."""
    shadow = (
        '<filter id="shadow" x="-10%" y="-10%" width="130%" height="130%">'
        '  <feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#000" flood-opacity="0.15"/>'
        '</filter>'
    )
    cx, cy = LEFT_PAD + COVER_W // 2, H // 2
    rx, ry = COVER_W // 2, COVER_H // 2
    return (
        f'{shadow}'
        f'<image x="{cx - rx}" y="{cy - ry}" width="{COVER_W}" height="{COVER_H}"'
        f'  href="{escape(data_uri)}" preserveAspectRatio="xMidYMid slice"'
        f'  filter="url(#shadow)" clip-path="url(#cover-clip)"/>'
    )


def _no_cover_svg() -> str:
    """Placeholder when no cover is available: a subtle empty-book icon area."""
    cx, cy = LEFT_PAD + COVER_W // 2, H // 2
    rx, ry = COVER_W // 2, COVER_H // 2
    return (
        f'<rect x="{cx - rx}" y="{cy - ry}" width="{COVER_W}" height="{COVER_H}"'
        f'  rx="6" fill="#f1f5f9" stroke="#e2e8f0" stroke-width="1"/>'
        f'<text x="{cx}" y="{cy - 10}" text-anchor="middle"'
        f'  font-family="Arial,sans-serif" font-size="48" fill="#cbd5e1">\U0001f4da</text>'
        f'<text x="{cx}" y="{cy + 30}" text-anchor="middle"'
        f'  font-family="Arial,sans-serif" font-size="14" fill="#cbd5e1">No Cover</text>'
    )


def generate_card(
    highlight_text: str,
    book_title: str = "",
    book_author: str = "",
    note: str = "",
    highlight_id: int = 0,
    cover_data_uri: Optional[str] = None,
) -> str:
    """Generate a 1200x630 SVG share card.

    If *cover_data_uri* is provided, the book cover is rendered on the
    left side (Readwise-style).  Otherwise a placeholder is shown.
    """
    # Fit quote text to available space
    lines, fs, lh = _fit_text(highlight_text, QUOTE_W, QUOTE_AVAIL_H, 32)

    quote_block_h = len(lines) * lh
    # Vertically center quote block in available space
    quote_start_y = QUOTE_TOP + (QUOTE_AVAIL_H - quote_block_h) // 2

    # Book info below quote
    info_y = quote_start_y + quote_block_h + 20
    gap_after_info = H - GUTTER - 50 - info_y
    if gap_after_info < 10:
        # Squeeze by reducing quote space
        pass  # already fit well enough via _fit_text

    # Make book info fit if it spills
    book_info_lines = []
    if book_title:
        book_info_lines.append(("title", book_title))
    if book_author:
        book_info_lines.append(("author", f"by {book_author}"))

    brand_y = H - GUTTER - 10

    # Cover
    cover_fragment = _cover_svg(cover_data_uri) if cover_data_uri else _no_cover_svg()

    s = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
  <defs>
    <clipPath id="cover-clip">
      <rect x="{LEFT_PAD}" y="{H // 2 - COVER_H // 2}" width="{COVER_W}" height="{COVER_H}" rx="6"/>
    </clipPath>
  </defs>
  <rect width="{W}" height="{H}" fill="{BG}"/>

  <!-- Subtle border -->
  <rect x="8" y="8" width="{W-16}" height="{H-16}" rx="12" fill="none" stroke="#e2e8f0" stroke-width="1"/>

  <!-- Cover -->
  {cover_fragment}

  <!-- Quote mark -->
  <text x="{QUOTE_START_X}" y="{quote_start_y + lh - 4}"
    font-family="Georgia,serif" font-size="{int(fs * 2.2)}" fill="{QUOTE_MARK}" font-weight="bold">\u201c</text>

  <!-- Quote lines -->
  <g font-family="Georgia,serif" font-size="{fs}" fill="{TEXT}" font-style="italic">
'''

    for i, line in enumerate(lines):
        y = quote_start_y + i * lh + int(fs * 0.15)  # slight baseline shift for italics
        s += f'    <text x="{QUOTE_START_X + 16}" y="{y}">{escape(line)}</text>\n'

    s += '  </g>\n'

    # Attribution line — subtle accent + book info
    if book_info_lines:
        s += f'  <line x1="{QUOTE_START_X + 16}" y1="{info_y}" x2="{QUOTE_START_X + 180}" y2="{info_y}" stroke="{ACCENT}" stroke-width="2" stroke-linecap="round"/>\n'
        ts = 20
        for kind, val in book_info_lines:
            if kind == "title":
                s += f'  <text x="{QUOTE_START_X + 16}" y="{info_y + ts + 8}" font-family="Georgia,serif" font-size="{ts}" fill="{TITLE}" font-weight="bold">{escape(val)}</text>\n'
                info_y += ts + 8
            else:
                s += f'  <text x="{QUOTE_START_X + 16}" y="{info_y + ts + 4}" font-family="Arial,sans-serif" font-size="{max(14, ts - 4)}" fill="{AUTHOR}">{escape(val)}</text>\n'
                info_y += max(14, ts - 4) + 4

    # Note if present
    if note:
        note_y = min(info_y + 30, H - GUTTER - 60)
        s += f'  <text x="{QUOTE_START_X + 16}" y="{note_y}" font-family="Arial,sans-serif" font-size="13" fill="#a1a1aa" font-style="italic">\u2014 {escape(note[:200])}</text>\n'

    # Branding
    s += f'  <image x="{W - RIGHT_PAD - 100}" y="{brand_y - 8}" width="16" height="16" href="data:image/png;base64,'
    with open(os.path.join(os.path.dirname(__file__), "..", "static", "logo-32.png"), "rb") as _f:
        s += base64.b64encode(_f.read()).decode()
    s += f'" preserveAspectRatio="xMidYMid meet"/>'
    s += f'  <text x="{W - RIGHT_PAD - 80}" y="{brand_y}" font-family="Arial,sans-serif" font-size="12" fill="{BRAND}">commonplace</text>\n'

    s += '</svg>\n'
    return s


# ── PNG export ───────────────────────────────────────────────────────────

def svg_to_png(svg_bytes: bytes) -> Optional[bytes]:
    """Convert SVG bytes to PNG bytes using cairosvg."""
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=svg_bytes, output_width=W, output_height=H)
    except ImportError:
        return None
