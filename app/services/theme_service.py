"""Theme discovery — scans data/themes/ for custom CSS theme files.

Custom themes are dropped as ``.css`` files in ``data/themes/``.
Each file defines a ``.theme-{name}`` class with CSS custom property
overrides matching the built-in variables in ``app/static/themes.css``.

File naming convention:  ``{theme-name}.css``
  - Lowercase, hyphens only for spaces.
  - Theme name is the filename without ``.css``.

Optional first-line comment (``/* Description */``) is used as the theme's
human-readable label in the settings UI.  If absent the name is capitalised.

Example ``data/themes/forest.css``::

    /* Forest — Earthy greens for long reading sessions */
    .theme-forest {
      --bg-page: #f0f7f0;
      --bg-sidebar: #e8f0e8;
      --bg-card: #ffffff;
      ...
    }

Built-in themes (modern, reader, dark) are always available and
live in ``app/static/themes.css``.
"""

import os
import re
from typing import TypedDict

# Built-in themes — always available, defined in app/static/themes.css


CUSTOM_THEMES_DIR = os.environ.get(
    "CUSTOM_THEMES_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "themes"),
)


class ThemeInfo(TypedDict):
    name: str
    label: str
    description: str
    builtin: bool


BUILTIN_THEMES: list[ThemeInfo] = [
    {"name": "modern", "label": "Modern", "description": "Clean, Linear-inspired. Zinc grays, Inter font.", "builtin": True},
    {"name": "reader", "label": "Reader", "description": "Warm, cozy. Cream tones, Source Serif.", "builtin": True},
    {"name": "dark", "label": "Dark", "description": "Deep charcoal, amber accent, easy on the eyes.", "builtin": True},
    {"name": "glass", "label": "Glass", "description": "Deep navy, indigo glow, frosted glass cards.", "builtin": True},
    {"name": "contemporary", "label": "Contemporary", "description": "Magenta accent, Jost font, bento-modern light.", "builtin": True},
    {"name": "contemporary-dark", "label": "Contemporary Dark", "description": "Deep purple base, magenta glow, Jost font.", "builtin": True},
]


def _parse_description(filepath: str) -> str:
    """Extract description from first CSS comment line, or return capitalised name."""
    try:
        with open(filepath) as f:
            first = f.read(200)  # read enough for a header comment
        m = re.search(r"/\*\s*(.+?)\s*\*/", first)
        if m:
            desc = m.group(1).strip()
            # Only use it if it looks like a description (starts with a letter, not a CSS rule)
            if desc and re.match(r"^[A-Za-z]", desc):
                return desc
    except OSError:
        pass
    return ""


def discover_custom_themes() -> list[ThemeInfo]:
    """Scan ``data/themes/`` for ``.css`` files and return theme metadata.

    Returns a list of dicts with keys: ``name``, ``label``, ``description``,
    ``builtin`` (always False).
    """
    themes: list[ThemeInfo] = []
    if not os.path.isdir(CUSTOM_THEMES_DIR):
        return themes

    try:
        entries = sorted(os.listdir(CUSTOM_THEMES_DIR))
    except OSError:
        return themes

    for entry in entries:
        if not entry.endswith(".css"):
            continue
        name = entry[:-4]  # strip .css
        if not re.match(r"^[a-z0-9][a-z0-9_-]*$", name):
            continue  # skip invalid filenames

        filepath = os.path.join(CUSTOM_THEMES_DIR, entry)
        description = _parse_description(filepath)
        label = description.split("—")[0].strip() if "—" in description else name.capitalize()
        if not description:
            description = f"Custom theme from {entry}"

        themes.append({
            "name": name,
            "label": label,
            "description": description,
            "builtin": False,
        })

    return themes


def get_all_themes() -> list[ThemeInfo]:
    """Return built-in + custom themes combined."""
    return BUILTIN_THEMES + discover_custom_themes()


def get_theme_url(name: str) -> str | None:
    """Return the static URL path for a custom theme CSS file, or None for built-in."""
    for t in BUILTIN_THEMES:
        if t["name"] == name:
            return None  # built-in — already in themes.css
    filepath = os.path.join(CUSTOM_THEMES_DIR, f"{name}.css")
    if os.path.isfile(filepath):
        return f"/static/themes/{name}.css"
    return None
