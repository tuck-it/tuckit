import re

import pytest
from core.services.areas import create_area
from core.services.slices import create_slice
from core.services.bites import create_bite


@pytest.mark.django_db
def test_slice_full_page_renders_spec_and_bites(client_local, workspace):
    a = create_area(workspace, "Backend")
    s = create_slice(a, "결제 도입", spec="## 목표\nStripe 붙이기", status="building")
    create_bite(s, "SDK 연동", status="done")
    resp = client_local.get(f"/slices/{s.id}/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "결제 도입" in body
    assert "<h2" in body            # markdown rendered
    assert "SDK 연동" in body


@pytest.mark.django_db
def test_slice_panel_is_partial(client_local, workspace):
    a = create_area(workspace, "Backend")
    s = create_slice(a, "X")
    resp = client_local.get(f"/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true")
    body = resp.content.decode()
    assert "<!doctype html>" not in body.lower()   # partial, not full page
    assert "X" in body


@pytest.mark.django_db
def test_spec_html_is_sanitized(client_local, workspace):
    a = create_area(workspace, "Backend")
    s = create_slice(
        a,
        "위험한 스펙",
        spec="## 제목\n<script>alert(1)</script>\n<img src=x onerror=alert(1)>",
    )
    resp = client_local.get(f"/slices/{s.id}/")
    body = resp.content.decode()
    assert resp.status_code == 200
    # Scope assertions to the rendered spec_html output (the `spec` div).
    # base.html legitimately ships vendor <script> tags, and the edit form
    # intentionally shows the raw (auto-escaped) spec text in a <textarea>
    # for editing, so checking the whole page would collide with both.
    spec_section = re.search(r'<div class="spec".*?</div>', body, re.S).group(0)
    assert "<script>" not in spec_section
    assert "onerror" not in spec_section
    assert "<h2" in spec_section


@pytest.mark.django_db
def test_slice_other_workspace_404(client_local):
    from core.models import Org, Workspace
    from core.services.areas import create_area
    from core.services.slices import create_slice
    other_org = Org.objects.create(name="Other Org", slug="other-org")
    other = Workspace.objects.create(org=other_org, name="O", slug="o")
    s = create_slice(create_area(other, "A"), "secret")
    assert client_local.get(f"/slices/{s.id}/").status_code == 404
