"""Static assets must be cache-busted once per release.

The service worker used to be cache-first for everything under /static/ with a
hardcoded cache name that only changed when someone remembered to bump it. A
browser could therefore keep running the previous release's commonplace.js
indefinitely. In 2.2.0 that showed up as the BookOrbit API key field looking
broken: the server rendered the new field, but the stale JS still demanded a
username and password ("Fill in URL, username, and password first") and never
sent the key.

These tests pin the fix at the source level (no auth or browser needed): the
asset URLs carry the app version, the worker is registered under a versioned
URL, and JS/CSS are network-first.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_base_template_versions_assets_from_app_version():
    html = _read("app/templates/base.html")

    assert 'name="app-version" content="{{ app_version }}"' in html
    for asset in ("commonplace.js", "style.css", "themes.css"):
        assert f"{asset}?v={{{{ app_version }}}}" in html, asset
    # The hand-maintained counters these replaced must not come back.
    assert "?v=9" not in html
    assert "?v=10" not in html


def test_render_injects_app_version():
    template_py = _read("app/template.py")

    assert 'ctx.setdefault("app_version"' in template_py


def test_service_worker_is_network_first_for_code():
    sw = _read("app/static/sw.js")

    assert "commonplace-v5" not in sw, "cache name must change when the strategy does"
    assert r"\.(js|css)$" in sw, "JS/CSS must be detected for the network-first path"


def test_service_worker_registration_is_versioned():
    js = _read("app/static/commonplace.js")

    assert "updateViaCache" in js
    assert 'meta[name="app-version"]' in js
