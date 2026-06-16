"""Generate SVG highlight cards for social media sharing."""

from xml.sax.saxutils import escape


def _wrap_text(text, max_chars=45):
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


def generate_card(highlight_text, book_title="", book_author="",
                  note="", highlight_id=0):
    W = 1200
    H = 630
    lines = _wrap_text(highlight_text, 42)
    if len(lines) > 8:
        lines = lines[:7]
        lines[-1] = lines[-1] + "\u2026"

    line_height = 58
    text_start_y = 260 if len(lines) <= 3 else 220
    attr_y = text_start_y + len(lines) * line_height + 50

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
  <text x="80" y="140" font-family="Georgia,serif" font-size="120" fill="#334155" opacity="0.4">\u201c</text>
  <g font-family="Georgia,serif" font-size="44" fill="#e2e8f0" font-style="italic">
'''
    for i, line in enumerate(lines):
        y = text_start_y + i * line_height
        s += f'    <text x="100" y="{y}">{escape(line)}</text>\n'

    s += f'''  </g>
  <line x1="100" y1="{attr_y}" x2="400" y2="{attr_y}" stroke="url(#accent)" stroke-width="3" stroke-linecap="round"/>
'''
    if book_title:
        s += f'  <text x="100" y="{attr_y + 40}" font-family="Georgia,serif" font-size="28" fill="#cbd5e1" font-weight="bold">{escape(book_title)}</text>\n'
    if book_author:
        s += f'  <text x="100" y="{attr_y + 72}" font-family="Arial,sans-serif" font-size="20" fill="#64748b">{escape(book_author)}</text>\n'

    s += f'  <text x="{W - 200}" y="{H - 40}" font-family="Arial,sans-serif" font-size="14" fill="#475569" text-anchor="end">Marginalia</text>\n'
    s += '</svg>\n'
    return s
