from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # .../tuckit
STATIC = REPO_ROOT / "tuckit" / "web" / "static" / "web"


def test_product_brand_tokens_use_teal_accent_not_purple():
    css = (STATIC / "tokens.brand.css").read_text(encoding="utf-8")
    assert "#245a78" in css          # teal brand accent present
    assert "#5a6698" not in css      # legacy periwinkle purple gone
    assert "--radius: 14px" in css
    assert "--radius-small: 9px" in css


def test_product_extension_defines_aliases_and_dots():
    css = (STATIC / "tokens.product.css").read_text(encoding="utf-8")
    # alias bridge maps legacy names onto brand tokens
    assert "--bg: var(--paper)" in css
    assert "--text: var(--ink)" in css
    assert "--muted: var(--ink-faint)" in css
    assert "--surface: var(--paper-raised)" in css
    assert "--border: var(--line)" in css
    assert "--accent: var(--blue)" in css
    # product-only status dots still present (both themes)
    assert "--dot-building" in css
    assert "--overlay" in css


def test_font_and_texture_assets_present():
    fonts = STATIC / "fonts"
    assert (fonts / "onest-latin-wght-normal.woff2").exists()
    assert (fonts / "ibm-plex-mono-latin-400-normal.woff2").exists()
    assert (fonts / "ibm-plex-mono-latin-500-normal.woff2").exists()
    tex = STATIC / "textures" / "notebook-paper.webp"
    assert tex.exists() and tex.stat().st_size > 0


def test_base_css_declares_fonts_texture_and_primitives():
    css = (STATIC / "base.css").read_text(encoding="utf-8")
    assert "@font-face" in css
    assert "Onest Variable" in css
    assert "IBM Plex Mono" in css
    assert "font-display: swap" in css
    assert "url(\"fonts/onest-latin-wght-normal.woff2\")" in css
    assert "body::before" in css                         # texture overlay
    assert "url(\"textures/notebook-paper.webp\")" in css
    assert ":focus-visible" in css
    assert ".button-primary" in css


@pytest.mark.django_db
def test_base_html_links_stylesheets_in_order_and_lang_en(client_local):
    body = client_local.get("/").content.decode()
    assert '<html lang="en"' in body
    i_brand = body.find("tokens.brand.css")
    i_product = body.find("tokens.product.css")
    i_base = body.find("web/base.css")
    i_app = body.find("web/app.css")
    assert -1 not in (i_brand, i_product, i_base, i_app)
    assert i_brand < i_product < i_base < i_app          # cascade order
    assert '/static/web/tokens.css"' not in body         # old single file gone


def test_brand_tokens_match_landing_when_sibling_present():
    landing = REPO_ROOT.parent / "tuckit-landing" / "app" / "tokens.brand.css"
    if not landing.exists():
        import pytest as _pytest
        _pytest.skip("tuckit-landing sibling not present; drift check is dev-only")
    product = STATIC / "tokens.brand.css"
    assert product.read_bytes() == landing.read_bytes(), (
        "tokens.brand.css drifted between repos. "
        "Run: node tuckit-landing/scripts/sync-tokens.mjs"
    )
