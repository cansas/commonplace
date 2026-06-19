#!/usr/bin/env python3
"""
Seed commonplace from the Obsidian vault's Readwise exports.
Usage: python3 seed_from_obsidian.py http://localhost:8765 my-api-token
"""

import sys
import os
import json
import glob
import urllib.request

VAULT_PATH = os.path.expanduser("~/obsidianvault")


def parse_readwise_directory(vault_path):
    """Scan Readwise/Books/ directory and parse all .md files."""
    books_dir = os.path.join(vault_path, "Readwise", "Books")
    if not os.path.isdir(books_dir):
        print(f"❌ Readwise/Books/ not found at {books_dir}")
        return []

    highlights = []
    md_files = glob.glob(os.path.join(books_dir, "*.md"))
    print(f"Found {len(md_files)} book files in Readwise/Books/")

    for md_path in md_files:
        filename = os.path.basename(md_path)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        parsed = _parse_content(content, filename)
        highlights.extend(parsed)
        print(f"  {filename}: {len(parsed)} highlights")

    return highlights


def _parse_content(content, filename):
    """Minimal parser for Readwise Obsidian export format."""
    import re

    highlights = []
    book_title = ""
    book_author = ""

    # Title
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if m:
        book_title = m.group(1).strip()

    # Author
    m = re.search(r"^-\s+Author:\s+\[\[(.+?)\]\]", content, re.MULTILINE)
    if m:
        book_author = m.group(1).strip()

    # Highlights section
    parts = re.split(r"^##\s+Highlights", content, flags=re.MULTILINE)
    if len(parts) < 2:
        return highlights

    body = parts[1]
    current = {}

    for line in body.split("\n"):
        stripped = line.strip()

        if current and stripped.startswith("- Tags:"):
            tags = re.findall(r"\[\[(.+?)\]\]", stripped)
            current.setdefault("tags", []).extend(tags)
            continue

        m = re.match(r"^-\s+(.+?)(?:\s*\(Location\s+(\d+).*?\))?\s*$", stripped)
        if m and not stripped.startswith("- Tags:"):
            if current and current.get("text"):
                highlights.append(current)
            text = m.group(1).strip()
            text = re.sub(r"\s*\(\[?[Ll]ocation\s+\d+\]?\([^)]+\)\)?\s*$", "", text)
            current = {
                "text": text,
                "book_title": book_title,
                "book_author": book_author,
                "source_type": "readwise",
                "tags": [],
            }
            if m.group(2):
                current["page"] = int(m.group(2))
            continue

    if current and current.get("text"):
        highlights.append(current)

    return highlights


def send_highlights(highlights, api_url, api_token):
    """Send highlights to commonplace's Readwise-compatible API endpoint."""
    url = f"{api_url.rstrip('/')}/api/v2/highlights"
    headers = {
        "Authorization": f"Token {api_token}",
        "Content-Type": "application/json",
    }

    # Batch in groups of 50
    batch_size = 50
    total = 0
    for i in range(0, len(highlights), batch_size):
        batch = highlights[i:i + batch_size]
        payload = json.dumps({"highlights": batch}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req)
            result = json.loads(resp.read())
            total += result.get("imported", 0)
            print(f"  Batch {i//batch_size + 1}: imported {result.get('imported', 0)}")
        except urllib.error.HTTPError as e:
            print(f"  Batch {i//batch_size + 1}: ERROR {e.code} {e.read().decode()}")
        except Exception as e:
            print(f"  Batch {i//batch_size + 1}: ERROR {e}")

    return total


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 seed_from_obsidian.py <api_url> <api_token>")
        print(f"Example: python3 seed_from_obsidian.py http://localhost:8765 change-me")
        sys.exit(1)

    api_url = sys.argv[1]
    api_token = sys.argv[2]

    print(f"🔍 Scanning Obsidian vault at {VAULT_PATH}")
    vault_path = os.path.expanduser(VAULT_PATH)

    if not os.path.isdir(vault_path):
        print(f"❌ Vault path {vault_path} not found")
        sys.exit(1)

    highlights = parse_readwise_directory(vault_path)

    if not highlights:
        print("❌ No highlights found")
        sys.exit(0)

    print(f"\n📤 Sending {len(highlights)} highlights to {api_url}")
    total = send_highlights(highlights, api_url, api_token)
    print(f"\n✅ Done! Imported {total} highlights into commonplace")


if __name__ == "__main__":
    main()
