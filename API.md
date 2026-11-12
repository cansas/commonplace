# Commonplace API Reference

> Commonplace is a self-hosted Readwise alternative — a FastAPI + SQLite app for
> collecting, reviewing, and sharing book highlights.

**App version:** 0.7.0  
**Base URL:** `http://localhost:8000` (configurable)

---

## Authentication & CSRF

### Auth Layers

| Layer | Mechanism | Scope |
|-------|-----------|-------|
| **Session auth** | `user_id` stored in signed session cookie | Web UI pages (any path not under `/api/`) |
| **API token auth** | `Authorization: Token cp_<abbrev>_<random>` header | All `/api/*` routes |
| **Session API auth** | Session cookie with `user_id` | All `/api/*` routes (no separate token needed) |

### Public Paths (no auth required)

```
/login        /health        /setup
/static/*     /share/*       /api/highlights/<int>/*
```

- `/share/*` — public share cards (PNG, SVG, HTML)
- `/static/*` — static files (CSS, JS, covers)
- `/api/highlights/<int>/*` — individual highlight item endpoints (card, etc.)
- `/health`, `/login`, `/setup` — healthcheck, login page, first-run wizard

### CSRF Protection

CSRF uses a double-submit cookie pattern with `itsdangerous`-signed tokens.

**CSRF-exempt paths** (no token required):

| Type | Paths |
|------|-------|
| Exact | `/login`, `/health` |
| Prefix | `/static`, `/share`, `/api/`, `/logout`, `/health` |

- All `GET`/`HEAD`/`OPTIONS` requests are CSRF-exempt by nature.
- All paths under `/api/` are CSRF-exempt (API tokens or session auth used instead).
- All paths under `/share/` are CSRF-exempt (public).
- All paths under `/settings/` **require** CSRF tokens for state-changing requests.
- All `/review` POST actions require CSRF tokens.
- `/import/*` POST actions require CSRF tokens.

**Sending CSRF tokens:**

```http
# As a form field:
csrf_token=<token>

# Or as a header (for JS fetch/XHR):
X-CSRF-Token: <token>
```

The CSRF cookie is named `csrf_token` and is set automatically on all GET requests.

---

## Endpoints

---

## 1. Health & Root

### `GET /health` — Healthcheck

**Auth:** Public  
**CSRF:** Exempt  
**Rate limited:** No

Returns application status and database connectivity.

**Response `200 OK`:**
```json
{
  "status": "ok",
  "version": "0.7.0",
  "database": "connected"
}
```

**Response `503 Service Unavailable`** (DB unreachable):
```json
{
  "status": "degraded",
  "version": "0.7.0",
  "database": "unreachable"
}
```

---

### `GET /` — Dashboard

**Auth:** Session required  
**CSRF:** Exempt (GET)

Renders the main dashboard HTML page with:
- Total highlight/book counts
- Today's review count
- Current streak data
- A random highlight
- Today's date

**Query parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `imported` | int | 0 | Flash message count after import |

---

## 2. Auth

### `GET /login` — Login page

**Auth:** Public  
**CSRF:** Exempt (GET)

Redirects to `/` if already authenticated, or to `/setup` if no user exists yet.

---

### `POST /login` — Login

**Auth:** Public  
**CSRF:** Exempt (path is in exempt set)

**Rate limiting:** 5 attempts per 5 minutes per IP

**Form body:**
| Field | Type | Required |
|-------|------|----------|
| `username` | string | yes |
| `password` | string | yes |

**Response:** Redirect to `/` on success, re-renders login page with error on failure.

---

### `GET /logout` — Logout

**Auth:** Public (clears session)  
**CSRF:** Exempt

Clears the session and redirects to `/login`.

---

### `GET /api/session-status` — Session status

**Auth:** Public (returns authenticated status)  
**CSRF:** Exempt (GET, under `/api/`)

**Response:**
```json
{
  "authenticated": true,
  "username": "admin"
}
```

---

### `GET /setup` — First-run setup page

**Auth:** Public (only accessible when no users exist)  
**CSRF:** Exempt (GET)

---

### `POST /setup` — Create admin user

**Auth:** Public (only works when no users exist)  
**CSRF:** Required

**Form body:**
| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `username` | string | yes | ≥ 2 characters |
| `password` | string | yes | ≥ 8 characters |
| `confirm` | string | yes | must match password |
| `csrf_token` | string | yes | |

**Response:** Redirect to `/` on success (auto-logged in), re-renders setup page with errors on failure.

---

## 3. Highlights

### `GET /highlights` — Highlights browser (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

**Query parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | `""` | FTS full-text search |
| `source` | string | `""` | Filter by source type (`all` to clear) |
| `book` | string | `""` | Filter by book title (ILIKE) |
| `favorites` | string | `""` | Set to `"1"` to show only favorites |
| `page` | int | 1 | Page number (20 per page) |

---

### `POST /api/highlights` — Create highlight

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

**Request body** (`application/json`):
```json
{
  "text": "The unexamined life is not worth living.",
  "note": "Socrates' defense",
  "page": 42,
  "chapter": "Apology",
  "source_type": "manual",
  "source_id": null,
  "book_title": "Plato: Collected Works",
  "book_author": "Plato",
  "book_url": null,
  "category": "books",
  "color": "yellow",
  "highlighted_at": "2025-01-15T10:30:00",
  "tags": ["philosophy", "ancient-greece"]
}
```

**Field aliases** (Readwise v2 compatible):
| JSON field | Maps to |
|------------|---------|
| `title` | `book_title` |
| `author` | `book_author` |
| `location` | `page` |

**Response `201 Created`:**
```json
{
  "id": 1,
  "text": "The unexamined life is not worth living.",
  "note": "Socrates' defense",
  "page": 42,
  "chapter": "Apology",
  "source_type": "manual",
  "book_title": "Plato: Collected Works",
  "book_author": "Plato",
  "category": "books",
  "color": "yellow",
  "highlighted_at": "2025-01-15T10:30:00",
  "created_at": "2025-01-15T10:30:00",
  "tags": ["philosophy", "ancient-greece"],
  "favorite": 0
}
```

---

### `GET /api/highlights` — List highlights

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

**Query parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Number of records to skip |
| `limit` | int | 50 | Max records to return |
| `since` | string (ISO 8601) | `""` | Only highlights created after this datetime |
| `search` | string | `""` | FTS full-text search |

**Response `200 OK`:**
```json
[
  {
    "id": 1,
    "text": "The unexamined life is not worth living.",
    "note": null,
    "page": null,
    "chapter": null,
    "source_type": "manual",
    "book_title": "Plato: Collected Works",
    "book_author": "Plato",
    "category": "books",
    "color": null,
    "highlighted_at": "2025-01-15T10:30:00",
    "created_at": "2025-01-15T10:30:00",
    "tags": ["philosophy"],
    "favorite": 0
  }
]
```

---

### `GET /api/export` — Export highlights (Obsidian sync)

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Returns highlights grouped by book. Paginated.

**Query parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `since` | string (ISO 8601) | `""` | Only highlights created after this datetime |
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 500 | Max records to return |

**Response `200 OK`:**
```json
{
  "books": [
    {
      "title": "Plato: Collected Works",
      "author": "Plato",
      "highlights": [
        {
          "id": 1,
          "text": "The unexamined life is not worth living.",
          "note": null,
          "page": null,
          "chapter": null,
          "color": null,
          "favorite": false,
          "highlighted_at": "2025-01-15T10:30:00",
          "created_at": "2025-01-15T10:30:00",
          "tags": ["philosophy"]
        }
      ]
    }
  ],
  "total": 1,
  "total_books": 1,
  "offset": 0,
  "limit": 500
}
```

---

### `GET /api/highlights/{hl_id}/card` — Highlight card SVG

**Auth:** Public (under `/api/highlights/<int>/*` pattern)  
**CSRF:** Exempt (GET, under `/api/`)

Returns an SVG image of the highlight card (suitable for embedding in social cards).

**Response `200 OK`:**
```
Content-Type: image/svg+xml
Cache-Control: public, max-age=86400

<svg>...</svg>
```

**Response `404`:**
```json
{
  "detail": "Highlight not found"
}
```

---

### `PUT /api/highlights/{hl_id}` — Update highlight

**Auth:** Public (under `/api/highlights/<int>/*` pattern) or API token or session  
**CSRF:** Exempt (under `/api/`)

**Request body** (`application/json`):
```json
{
  "text": "Updated text",
  "note": "Updated note",
  "page": 43,
  "chapter": "New Chapter",
  "book_title": "Updated Book Title",
  "book_author": "Updated Author",
  "tags": ["new-tag", "another-tag"]
}
```

All fields are optional — only provided fields are updated.

**Response:**
```json
{
  "ok": true,
  "id": 1
}
```

---

### `DELETE /api/highlights/{hl_id}` — Delete highlight

**Auth:** Public (under `/api/highlights/<int>/*` pattern) or API token or session  
**CSRF:** Exempt (under `/api/`)

**Response:**
```json
{
  "ok": true
}
```

---

### `POST /api/highlights/{hl_id}/favorite` — Toggle favorite

**Auth:** Public (under `/api/highlights/<int>/*` pattern) or API token or session  
**CSRF:** Exempt (under `/api/`)

Toggles the `favorite` flag on a highlight (0↔1).

**Response:**
```json
{
  "id": 1,
  "favorite": 1
}
```

---

## 4. Books

### `GET /books` — Books browser (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

**Query parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | `""` | Search by title or author (ILIKE) |
| `sort` | string | `"highlights"` | Sort: `highlights`, `title`, `author`, `recent` |
| `page` | int | 1 | Page number (30 per page) |

---

### `POST /api/books/cover/fetch` — Fetch book cover

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Looks up a cover image from Open Library, Hardcover, or Goodreads.

**Form body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | — | Book title (required) |
| `author` | string | `""` | Book author |
| `source` | string | `"auto"` | Cover source preference |

**Response:**
```json
{
  "ok": true,
  "cover_url": "https://covers.openlibrary.org/b/id/123456-L.jpg",
  "source": "openlibrary"
}
```

**Error response:**
```json
{
  "ok": false,
  "error": "No cover found on Open Library, Hardcover, or Goodreads"
}
```

---

### `POST /api/books/cover/fetch/{hl_id}` — Fetch cover by highlight ID

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Same as above but derives the book title/author from a highlight record.

**Response:** Same as `/api/books/cover/fetch`.

---

### `POST /api/books/cover/upload` — Upload cover image

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Upload a cover image file (JPG, PNG, or WebP, max 10 MB).

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Book title |
| `author` | string | Book author |
| `file` | file | Image file |

**Response:**
```json
{
  "ok": true,
  "cover_url": "/static/covers/abc123.jpg"
}
```

---

### `POST /api/books/cover/upload/{hl_id}` — Upload cover by highlight ID

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Same as above but derives the book from a highlight record.

---

### `POST /api/books/cover/backfill` — Backfill covers

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Checks all distinct books in the database for missing covers and fetches them in bulk.

**Response:**
```json
{
  "ok": true,
  "fetched": 12
}
```

---

### `POST /api/books/metadata` — Set book metadata

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Manually set or update HardCover ID and ISBN for a book. If a HardCover ID is provided, triggers an immediate cover lookup.

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Book title (required) |
| `author` | string | Book author |
| `hardcover_id` | string | Hardcover numeric ID |
| `isbn` | string | ISBN |

**Response:**
```json
{
  "ok": true,
  "hardcover_id": 12345,
  "isbn": "978-0-14-044927-9",
  "cover_url": "https://covers.openlibrary.org/b/id/123456-L.jpg",
  "cover_source": "hardcover"
}
```

---

### `POST /api/books/rename` — Rename book

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Rename a book across all highlights. Merges with the target book if it already exists (two-step confirmation).

**Form body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `old_title` | string | — | Current book title |
| `old_author` | string | `""` | Current book author |
| `new_title` | string | — | New book title |
| `new_author` | string | `""` | New book author |
| `merge` | string | `""` | Set to `"true"` to confirm merge |

**Response (success — renamed):**
```json
{
  "ok": true,
  "merged": false,
  "affected": 5,
  "old_title": "Old Title",
  "new_title": "New Title",
  "message": "Renamed 5 highlights"
}
```

**Response (merge conflict — requires confirmation):**
```json
{
  "ok": false,
  "conflict": true,
  "existing_count": 3,
  "new_title": "Existing Book",
  "new_author": "Author Name",
  "message": "\"Existing Book\" already exists with 3 highlights. Merge 5 highlights into it?"
}
```

**Response (success — merged):**
```json
{
  "ok": true,
  "merged": true,
  "affected": 8,
  "old_title": "Old Title",
  "new_title": "Existing Book",
  "message": "Merged 8 highlights"
}
```

---

### `POST /api/books/delete` — Delete book

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Delete an entire book and all its highlights. Two-step confirmation not needed (the API always deletes immediately).

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Book title |
| `author` | string | Book author |

**Response:**
```json
{
  "ok": true,
  "deleted": 5,
  "title": "Book Title"
}
```

---

## 5. Review (SM-2 Spaced Repetition)

### `GET /review` — Daily review page (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

Displays one unreviewed highlight at a time. Shows "done" page when daily limit is reached or no more highlights remain.

---

### `GET /review/today` — Today's review log (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

Displays all reviews from today with their ratings.

---

### `GET /api/review/stats` — Review statistics

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

**Response:**
```json
{
  "streak": 7,
  "best_streak": 15,
  "reviewed_today": 5,
  "daily_limit": 10,
  "remaining": 5
}
```

---

### `POST /review/rate` — Rate a highlight

**Auth:** Session required  
**CSRF:** Required

Records an SM-2 rating for a highlight during review.

**Rate limiting:** 30 requests per minute per IP

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `hl_id` | int | Highlight ID |
| `rating` | int | 0=Forgot, 1=Hard, 2=Good, 3=Easy |
| `csrf_token` | string | CSRF token |

**Response:** Redirect to `/review` (303). May include `new_achievements` in session.

---

### `POST /review/next` — Skip to next (legacy)

**Auth:** Session required  
**CSRF:** Required

Logs the highlight as "seen" without an SM-2 rating and moves to the next.

**Rate limiting:** 30 requests per minute per IP

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `hl_id` | int | Highlight ID |
| `csrf_token` | string | CSRF token |

**Response:** Redirect to `/review` (303).

---

### `POST /review/favorite` — Toggle favorite during review

**Auth:** Session required  
**CSRF:** Required

Toggles the favorite flag and logs as "seen".

**Rate limiting:** 30 requests per minute per IP

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `hl_id` | int | Highlight ID |
| `csrf_token` | string | CSRF token |

**Response:** Redirect to `/review` (303).

---

### `POST /review/delete` — Delete during review

**Auth:** Session required  
**CSRF:** Required

Deletes the highlight and logs the review.

**Rate limiting:** 30 requests per minute per IP

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `hl_id` | int | Highlight ID |
| `csrf_token` | string | CSRF token |

**Response:** Redirect to `/review` (303).

---

## 6. Import

### `GET /import` — Import page (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

Shows upload forms for Readwise Markdown and KOReader JSON, plus recent import history.

---

### `POST /import/readwise` — Import Readwise Markdown

**Auth:** Session required  
**CSRF:** Required

Import highlights from Readwise Obsidian export (Markdown format). Supports both file upload and pasted content.

**Form body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `csrf_token` | string | `""` | CSRF token |
| `file` | file | — | Readwise .md file |
| `content` | string | `""` | Pasted Readwise content (alternative to file) |
| `dry_run` | string | `""` | Set to `"true"` to preview without saving |

**Response:** Re-renders import page with import result summary.

**Result object:**
```json
{
  "success": true,
  "imported": 15,
  "skipped": 2,
  "errors": [],
  "dry_run": false,
  "source_name": "Readwise Export.md",
  "source_type": "readwise",
  "action": "/import/readwise"
}
```

---

### `POST /import/koreader-json` — Import KOReader JSON

**Auth:** Session required  
**CSRF:** Required

Import highlights from KOReader JSON export format.

**Form body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `csrf_token` | string | `""` | CSRF token |
| `file` | file | — | KOReader .json file |
| `dry_run` | string | `""` | Set to `"true"` to preview without saving |

**Response:** Re-renders import page with import result summary (same format as Readwise import).

---

### `POST /api/v2/highlights` — Readwise API v2 import

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Readwise-compatible API endpoint — what the KOReader Readwise plugin sends directly.

**Request body** (`application/json`):
```json
{
  "highlights": [
    {
      "text": "Highlight text",
      "note": "Optional note",
      "page": 42,
      "chapter": "Chapter 3",
      "source_type": "koreader",
      "source_id": "book-uuid",
      "book_title": "Book Title",
      "book_author": "Author Name",
      "book_url": null,
      "category": "books",
      "color": "yellow",
      "highlighted_at": "2025-01-15T10:30:00"
    }
  ]
}
```

**Response:**
```json
{
  "imported": 10,
  "skipped": 0
}
```

---

## 7. Tags

### `GET /api/tags` — List all tags

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

**Response:**
```json
[
  {
    "id": 1,
    "name": "philosophy",
    "color": "#3b82f6",
    "count": 5
  }
]
```

---

### `PUT /api/tags/{tag_id}` — Rename / recolor tag

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | New tag name (leave empty to keep) |
| `color` | string | Hex color like `#3b82f6` (leave empty to keep) |

**Response:**
```json
{
  "ok": true,
  "id": 1,
  "name": "philosophy",
  "color": "#3b82f6"
}
```

---

### `POST /api/tags/merge` — Merge tags

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Merges source tag into target tag. All highlight-tag associations are transferred, then the source tag is deleted.

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `source_id` | int | Tag ID to merge FROM |
| `target_id` | int | Tag ID to merge INTO |

**Response:**
```json
{
  "ok": true,
  "merged_into": "target-tag-name",
  "target_id": 2
}
```

---

### `DELETE /api/tags/{tag_id}` — Delete tag

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Deletes a tag and removes all its highlight associations.

**Response:**
```json
{
  "ok": true
}
```

---

### `POST /api/highlights/{hl_id}/tags` — Set tags on highlight

**Auth:** Public (under `/api/highlights/<int>/*` pattern) or API token or session  
**CSRF:** Exempt (under `/api/`)

Replace all tags on a highlight with a comma-separated list of tag IDs.

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `tag_ids` | string | Comma-separated list of tag IDs, e.g. `"1,3,5"` |

**Response:**
```json
{
  "ok": true
}
```

---

### `GET /tags` — Tag browser page (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

---

### `GET /tags/{tag_id}` — Tag detail page (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

Shows all highlights with a given tag.

---

## 8. Settings

### `GET /settings` — Settings page (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

**Query parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `saved` | string | Flash: `"1"` after successful save |

Shows review mode, review count, theme, cover source config, API tokens, password change form, and reset option.

---

### `POST /settings/review-mode` — Set review mode

**Auth:** Session required  
**CSRF:** Required

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `csrf_token` | string | CSRF token |
| `spaced_mode` | string | Set to `"1"` for spaced repetition, anything else for random |

**Response:** Redirect to `/settings?saved=1`.

---

### `POST /settings/review-count` — Set daily review count

**Auth:** Session required  
**CSRF:** Required

**Form body:**
| Field | Type | Default |
|-------|------|---------|
| `csrf_token` | string | `""` |
| `count` | int | 10 (clamped 5–30) |

**Response:** Redirect to `/settings?saved=1`.

---

### `POST /settings/theme` — Set theme

**Auth:** Session required  
**CSRF:** Required

**Form body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `csrf_token` | string | `""` | CSRF token |
| `theme` | string | `"modern"` | One of: `modern`, `reader`, `dark` |

**Response:**
```json
{
  "ok": true,
  "theme": "modern"
}
```

---

### `POST /settings/cover-source` — Set cover source (Hardcover API key)

**Auth:** Session required  
**CSRF:** Required

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `csrf_token` | string | CSRF token |
| `hardcover_key` | string | Hardcover API bearer token |
| `action` | string | `"set"` (default) or `"clear"` |

**Response:**
```json
{
  "ok": true,
  "connected": true,
  "message": "Key saved and verified"
}
```

---

### `POST /settings/change-password` — Change password

**Auth:** Session required  
**CSRF:** Required

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `csrf_token` | string | CSRF token |
| `current_password` | string | Current password |
| `new_password` | string | New password (≥ 8 chars) |
| `confirm_password` | string | Must match new_password |

**Response:** Redirect to `/settings?saved=1` on success, or `/settings?error=<reason>` on failure.

---

### `GET /api/tokens` — List API tokens

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Returns all device tokens for the authenticated user (prefix only, no secrets).

**Response:**
```json
[
  {
    "id": 1,
    "name": "koreader",
    "prefix": "cp_kr_a1b2c3d4...",
    "created_at": "2025-01-15T10:30:00",
    "last_used_at": null
  }
]
```

---

### `POST /api/tokens` — Create API token

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Creates a new named device token. Returns the plaintext token exactly once.

**Request body** (`application/json`):
```json
{
  "name": "koreader"
}
```

**Response:**
```json
{
  "name": "koreader",
  "prefix": "cp_kr_a1b2c3d4...",
  "token": "cp_kr_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
}
```

---

### `DELETE /api/tokens/{token_id}` — Revoke API token

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

**Response:**
```json
{
  "ok": true
}
```

---

### `POST /settings/create-token` — Create token (form)

**Auth:** Session required  
**CSRF:** Required

Creates an API token from the settings page form.

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `csrf_token` | string | CSRF token |
| `token_name` | string | Name for the token |

**Response:** Redirect to `/settings?saved=1` with token stored in session for display.

---

### `POST /settings/revoke-token/{token_id}` — Revoke token (form)

**Auth:** Session required  
**CSRF:** Required

Revokes a token from the settings page form.

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `csrf_token` | string | CSRF token |

**Response:** Redirect to `/settings?saved=1`.

---

### `POST /settings/reset` — Reset database

**Auth:** Session required  
**CSRF:** Required

**WARNING:** Deletes all highlights, review logs, tags, and sources. Requires typing "reset" as confirmation.

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `csrf_token` | string | CSRF token |
| `confirm` | string | Must equal `"reset"` |

**Response:** Redirect to `/` (303).

---

### `POST /api/settings/bookorbit-sync` — Save BookOrbit sync settings

**Auth:** API token or session  
**CSRF:** Not required (JSON body)

**JSON body** (all fields optional — only the ones present are written):

| Field | Type | Description |
|-------|------|-------------|
| `bookorbit_url` | string | BookOrbit base URL, e.g. `http://192.168.1.130:3000` |
| `bookorbit_api_key` | string | API key from BookOrbit → Settings → You → API keys (preferred) |
| `bookorbit_username` | string | Fallback login username |
| `bookorbit_password` | string | Fallback login password |
| `bookorbit_sync_enabled` | bool | Run the sync every 15 minutes |

Sending `bookorbit_api_key`, `bookorbit_password`, or `bookorbit_sync_enabled` clears
the stored failure reason. An empty `bookorbit_api_key` leaves the username/password
path in charge, so a setup created before API keys existed keeps working unchanged.

**Response:**
```json
{ "ok": true }
```

---

### `POST /api/settings/bookorbit-test` — Test BookOrbit credentials

**Auth:** API token or session  
**CSRF:** Not required (JSON body)

Takes the same fields as above. Any field omitted falls back to the stored value.
When an API key is present it is checked against `GET /api/v1/auth/me`, otherwise the
credentials are checked with `POST /api/v1/auth/login`.

**Response — success:**
```json
{ "ok": true, "method": "api_key", "username": "brandon", "access": "" }
```
`method` is `api_key` or `password`.

**Response — failure:**
```json
{ "ok": false, "method": "api_key", "error": "Invalid API key" }
```

---

### `POST /api/settings/bookorbit-sync-now` — Run a BookOrbit sync now

**Auth:** API token or session  
**CSRF:** Not required

**Response:**
```json
{ "ok": true, "result": { "posted": 12, "skipped": 124, "errors": 0, "last_id": 149 } }
```

Returns `{"ok": false, "error": "..."}` when sync is disabled or has no usable
credentials (server URL plus an API key, or a username and password) instead of a
misleading `0/0/0` result.

---

## 9. Share (Public Cards)

All share endpoints are **public** (no auth required) and **CSRF-exempt** (under `/share/` prefix).

### `GET /share/{share_token}` — Share page (HTML)

**Auth:** Public  
**CSRF:** Exempt

HTML page with OpenGraph and Twitter Card meta tags for social sharing.

**Response:** Rendered `share.html` template with `Cache-Control: public, max-age=86400`.

---

### `GET /share/{share_token}.png` — Share as PNG

**Auth:** Public  
**CSRF:** Exempt

Returns the highlight as a PNG image (converted from SVG via CairoSVG/Pillow).

**Response:**
```
Content-Type: image/png
Cache-Control: public, max-age=86400
```

---

### `GET /share/{share_token}.svg` — Share as SVG

**Auth:** Public  
**CSRF:** Exempt

Returns the highlight as raw SVG.

**Response:**
```
Content-Type: image/svg+xml
Cache-Control: public, max-age=86400

<svg>...</svg>
```

---

## 10. Backup & Restore

### `GET /api/backup` — Download backup

**Auth:** Session required (user_id check)  
**CSRF:** Exempt (under `/api/`)

Downloads a ZIP file containing the SQLite database and all cover images.

**Response:** `StreamingResponse` with `Content-Type: application/zip`.
```
Content-Disposition: attachment; filename="commonplace-2025-01-15.zip"
```

---

### `POST /api/backup/restore` — Restore from backup

**Auth:** Session required (user_id check)  
**CSRF:** Exempt (under `/api/`)

Restores the database from a ZIP backup file. Creates a `.bak` copy of the current database before replacing.

**Form body:**
| Field | Type | Description |
|-------|------|-------------|
| `csrf_token` | string | CSRF token (required despite API prefix — `csrf_guard` called explicitly) |
| `file` | file | ZIP file containing `.db` and optional `covers/` |

**Response:**
```json
{
  "ok": true,
  "restored_db": "commonplace.db",
  "restored_covers": 3,
  "message": "Database restored. A restart is recommended for FTS index consistency."
}
```

---

## 11. Achievements

### `GET /api/achievements` — List achievements

**Auth:** API token or session  
**CSRF:** Exempt (under `/api/`)

Returns all achievements with their unlock status.

**Response:**
```json
[
  {
    "id": "first_review",
    "name": "First Review",
    "description": "Complete your first review",
    "icon": "⭐",
    "unlocked": true,
    "unlocked_at": "2025-01-15T10:30:00"
  },
  {
    "id": "streak_7",
    "name": "Week Warrior",
    "description": "7-day review streak",
    "icon": "🔥",
    "unlocked": false,
    "unlocked_at": null
  }
]
```

---

### `GET /achievements` — Achievements page (web UI)

**Auth:** Session required  
**CSRF:** Exempt (GET)

Renders the achievements browser page.

---

## Appendix: Auth Summary Table

| Route Group | Prefix | Auth Required | CSRF Required |
|-------------|--------|---------------|---------------|
| Health & Root | `/health`, `/` | Public / Session | No |
| Auth | `/login`, `/logout`, `/setup` | Public | No (login/logout) / Yes (setup) |
| Highlights (API) | `/api/highlights` | Public\* / Token / Session | No |
| Highlights (UI) | `/highlights` | Session | No (GET only) |
| Books (API) | `/api/books` | Token / Session | No |
| Books (UI) | `/books` | Session | No (GET only) |
| Review (API) | `/api/review` | Token / Session | No |
| Review (UI) | `/review` | Session | **Yes** for POST |
| Import (UI) | `/import` | Session | **Yes** for POST |
| Import (API) | `/api/v2` | Token / Session | No |
| Tags (API) | `/api/tags` | Token / Session | No |
| Tags (UI) | `/tags` | Session | No (GET only) |
| Settings (UI) | `/settings` | Session | **Yes** for all POST |
| Settings (API) | `/api/tokens` | Token / Session | No |
| Share | `/share` | **Public** | No |
| Backup | `/api/backup` | Session (user_id) | No |
| Achievements (API) | `/api/achievements` | Token / Session | No |
| Achievements (UI) | `/achievements` | Session | No (GET only) |

> \* `/api/highlights/<int>/*` routes are publicly accessible (typically for card/SVG
> generation). All other `/api/` routes require a valid API token or session.

---

## Appendix: Token Auth Usage

```bash
# API token auth
curl -H "Authorization: Token cp_kr_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0" \
  http://localhost:8000/api/highlights

# Session auth (cookie)
curl -b "session=..." http://localhost:8000/api/highlights
```

### Token Format

```
cp_<abbreviation>_<32-hex-chars>

# Examples:
cp_kr_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5
cp_rd_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5
```

Tokens are hashed with SHA-256 before storage. The plaintext is shown exactly once at creation.

---

## Appendix: CSRF Token Usage

```html
<form method="POST" action="/settings/review-mode">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
  ...
</form>
```

```javascript
// JavaScript fetch with CSRF header
fetch('/settings/theme', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-CSRF-Token': getCookie('csrf_token'),
  },
  body: 'theme=dark',
});
```
