import pytest
from django.test import RequestFactory
from tuckit.web.templatetags.web_extras import slice_push_url


def _ctx(path):
    return {"request": RequestFactory().get(path)}


def test_slice_push_url_appends_param_to_current_path():
    assert slice_push_url(_ctx("/acme/main/home"), 42) == "/acme/main/home?slice=42"


def test_slice_push_url_preserves_other_query_and_replaces_slice():
    out = slice_push_url(_ctx("/acme/main/board?view=board&slice=9"), 42)
    assert out == "/acme/main/board?view=board&slice=42"


def test_slice_push_url_drops_panel_param():
    assert slice_push_url(_ctx("/acme/main/home?panel=1"), 7) == "/acme/main/home?slice=7"


@pytest.mark.django_db
def test_page_with_slice_param_autoloads_panel(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(create_area(org, "Design"), "Restore")
    body = client_local.get(f"{p}/?slice={s.id}").content.decode()   # home is /{org}/
    assert 'hx-trigger="load"' in body
    assert f'/slices/{s.id}/?panel=1' in body    # panel endpoint wired into #panel


@pytest.mark.django_db
def test_page_without_slice_param_does_not_autoload(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'id="panel"' in body
    assert 'hx-trigger="load"' not in body


@pytest.mark.django_db
def test_page_with_nonnumeric_slice_param_does_not_crash_or_autoload(client_local, org):
    p = f"/{org.slug}"
    resp = client_local.get(f"{p}/?slice=abc")     # malformed id must not reverse() -> 500
    assert resp.status_code == 200
    assert 'hx-trigger="load"' not in resp.content.decode()


def test_ascii_int_filter_rejects_unicode_and_nonnumeric():
    from tuckit.web.templatetags.web_extras import ascii_int
    assert ascii_int("12") == "12"
    assert ascii_int("²") == ""       # unicode superscript: str.isdigit True but not ASCII
    assert ascii_int("abc") == ""
    assert ascii_int("") == ""


@pytest.mark.django_db
def test_page_with_unicode_digit_slice_param_does_not_crash_or_autoload(client_local, org):
    p = f"/{org.slug}"
    resp = client_local.get(f"{p}/", {"slice": "²"})   # passes str.isdigit but not the <int> route
    assert resp.status_code == 200
    assert 'hx-trigger="load"' not in resp.content.decode()
