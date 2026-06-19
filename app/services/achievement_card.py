"""Achievement share card — SVG card for a unlocked achievement.

Generates a 1200x630 SVG card with a dark gradient background,
the achievement icon, label, and a witty message.
"""

from xml.sax.saxutils import escape
import os

# ── Card layout constants ───────────────────────────────────────────────

W = 1200
H = 630

# Colors (dark gradient theme, same as highlight cards' dark variant)
BG_START = "#0f172a"   # slate-900
BG_END = "#1e1b4b"     # indigo-950
ACCENT = "#818cf8"     # indigo-400
TEXT_MAIN = "#f1f5f9"  # slate-100
TEXT_SUB = "#94a3b8"   # slate-400
TEXT_MUTED = "#64748b" # slate-500
BRAND = "#475569"      # slate-600


# ── SVG generation ──────────────────────────────────────────────────────


def generate_achievement_card(label: str, message: str, icon: str) -> str:
    """Generate a 1200x630 SVG share card for an achievement.

    Parameters
    ----------
    label : str
        The achievement's display name (e.g. "Streak Starter").
    message : str
        The witty unlock message.
    icon : str
        A single emoji or short text used as the achievement icon.
    """
    # ── Layout ──────────────────────────────────────────────────────────
    center_x = W // 2

    # Vertical positions
    icon_y = 170
    subtitle_y = 250
    label_y = 320
    message_y = 380
    brand_y = H - 50

    # ── Escaped text ────────────────────────────────────────────────────
    safe_label = escape(label)
    safe_message = escape(message)
    safe_icon = escape(icon)

    # ── Build SVG ───────────────────────────────────────────────────────
    s = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg-grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{BG_START}"/>
      <stop offset="100%" stop-color="{BG_END}"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
      <feMerge>
        <feMergeNode in="coloredBlur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <!-- Background -->
  <rect width="{W}" height="{H}" fill="url(#bg-grad)"/>

  <!-- Subtle decorative border -->
  <rect x="8" y="8" width="{W - 16}" height="{H - 16}" rx="16" fill="none" stroke="{ACCENT}" stroke-width="1" stroke-opacity="0.25"/>

  <!-- Achievement icon -->
  <text x="{center_x}" y="{icon_y}" text-anchor="middle" font-size="72" filter="url(#glow)">{safe_icon}</text>

  <!-- "Achievement Unlocked!" subtitle -->
  <text x="{center_x}" y="{subtitle_y}" text-anchor="middle"
    font-family="Arial,Helvetica,sans-serif" font-size="16" fill="{TEXT_SUB}" letter-spacing="3" font-weight="600">ACHIEVEMENT UNLOCKED!</text>

  <!-- Achievement label (bold) -->
  <text x="{center_x}" y="{label_y}" text-anchor="middle"
    font-family="Georgia,'Times New Roman',serif" font-size="36" fill="{TEXT_MAIN}" font-weight="bold">{safe_label}</text>

  <!-- Decorative divider -->
  <line x1="{center_x - 60}" y1="{label_y + 20}" x2="{center_x + 60}" y2="{label_y + 20}" stroke="{ACCENT}" stroke-width="2" stroke-linecap="round" stroke-opacity="0.6"/>

  <!-- Witty message (italic) -->
  <text x="{center_x}" y="{message_y}" text-anchor="middle"
    font-family="Georgia,'Times New Roman',serif" font-size="20" fill="{TEXT_MUTED}" font-style="italic">"{safe_message}"</text>

  <!-- Branding -->
  <text x="{center_x}" y="{brand_y}" text-anchor="middle"
    font-family="Arial,Helvetica,sans-serif" font-size="12" fill="{BRAND}" letter-spacing="2">commonplace</text>
</svg>
'''
    return s
