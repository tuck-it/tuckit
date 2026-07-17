"""The slice detail page (panel + full page share _slice_panel.html) labels the
spec field "Spec" and uses English UI copy — no leftover Korean."""
import pytest

from tuckit.core.models import Workspace
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_slice_detail_labels_field_spec_not_description(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "labelled slice", spec="some detail")
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()
    assert '<div class="section-label">Spec</div>' in body
    assert '<div class="section-label">Description</div>' not in body


@pytest.mark.django_db
def test_slice_detail_uses_english_copy(client_local, org):
    ws = Workspace.objects.get(org=org)
    a = create_area(ws.org, "Backend")
    s = create_slice(a, "empty slice")  # no spec, no bites → empty states show
    p = f"/{org.slug}/{ws.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/").content.decode()
    # leftover Korean UI copy is gone
    assert "설명을 추가하려면" not in body
    assert "아직 bite가 없습니다" not in body
    assert "이 slice를 구현하기" not in body
    assert "전</span>" not in body            # timesince "… 전"
    # English replacements present
    assert "No bites yet" in body
