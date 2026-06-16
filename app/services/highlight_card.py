"""Generate SVG highlight cards with dynamic font sizing."""

from xml.sax.saxutils import escape


def _wrap_text(text, max_chars):
    words = text.split()
    lines = []
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


def _calc_sizes(num_lines):
    """Pick font size, line height, and wrap width based on line count."""
    if num_lines <= 2:
        return 64, 82, 35, 90   # font, line_h, wrap, quote_size
    elif num_lines <= 3:
        return 56, 72, 38, 90
    elif num_lines <= 4:
        return 48, 64, 40, 80
    elif num_lines <= 5:
        return 44, 58, 42, 70
    elif num_lines <= 6:
        return 40, 54, 44, 65
    else:
        return 36, 50, 48, 60


def generate_card(highlight_text, book_title="", book_author="",
                  note="", highlight_id=0):
    W = 1200
    H = 630

    # Estimate lines with widest wrap first, then refine
    font_size, line_h, wrap_chars, quote_size = _calc_sizes(99)
    lines = _wrap_text(highlight_text, wrap_chars)
    font_size, line_h, wrap_chars, quote_size = _calc_sizes(len(lines))
    lines = _wrap_text(highlight_text, wrap_chars)

    if len(lines) > 8:
        lines = lines[:8]
        lines[-1] = lines[-1] + "\u2026"
    total_lines = len(lines)

    # Recalculate if line count changed due to wrap adjustment
    if total_lines >= 1:
        font_size, line_h, wrap_chars, quote_size = _calc_sizes(total_lines)
        lines = _wrap_text(highlight_text, wrap_chars)
        if len(lines) > 8:
            lines = lines[:8]
            lines[-1] = lines[-1] + "\u2026"

    # Vertical positioning: quote block centered, attribution below
    quote_block_h = len(lines) * line_h
    avail_h = H - 180  # leave room for top margin + attribution area
    avail_h_for_quote = avail_h * 0.75
    if quote_block_h > avail_h_for_quote:
        ratio = avail_h_for_quote / quote_block_h
        font_size = int(font_size * ratio)
        line_h = int(line_h * ratio)
        quote_block_h = len(lines) * line_h

    quote_start_y = int((H - quote_block_h) / 2) - 30
    attr_y = quote_start_y + quote_block_h + 30

    # Keep attribution in lower portion
    if attr_y < H - 160:
        attr_y = H - 160

    s = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1e293b"/>
      <stop offset="100%" stop-color="#0f172a"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <rect x="40" y="40" width="{W-80}" height="{H-80}" rx="12" fill="none" stroke="#334155" stroke-width="1"/>
  <text x="80" y="120" font-family="Georgia,serif" font-size="{quote_size}" fill="#334155" opacity="0.35">\u201c</text>
  <g font-family="Georgia,serif" font-size="{font_size}" fill="#e2e8f0" font-style="italic">
'''
    for i, line in enumerate(lines):
        y = quote_start_y + i * line_h
        s += f'    <text x="100" y="{y}">{escape(line)}</text>\n'

    s += '  </g>\n'

    if book_title or book_author:
        s += f'  <line x1="100" y1="{attr_y}" x2="400" y2="{attr_y}" stroke="url(#accent)" stroke-width="3" stroke-linecap="round"/>\n'
        ts = max(20, min(28, font_size - 16))
        if book_title:
            s += f'  <text x="100" y="{attr_y + ts + 8}" font-family="Georgia,serif" font-size="{ts}" fill="#cbd5e1" font-weight="bold">{escape(book_title)}</text>\n'
        if book_author:
            ay = attr_y + ts + 8 + (ts + 4 if book_title else 0)
            asize = max(14, ts - 4)
            s += f'  <text x="100" y="{ay}" font-family="Arial,sans-serif" font-size="{asize}" fill="#64748b">{escape(book_author)}</text>\n'

    s += '</svg>\n'
    return s
