import pytest


@pytest.mark.django_db
def test_home_returns_200_and_shell(client_local):
    resp = client_local.get("/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "tuck-it" in body            # brand in sidebar
    assert "/static/web/tokens.css" in body or "tokens.css" in body


@pytest.mark.django_db
def test_current_workspace_resolves(client_local, workspace):
    from tuckit.web.auth import get_current_workspace

    resp = client_local.get("/")
    assert get_current_workspace(resp.wsgi_request).id == workspace.id


@pytest.mark.django_db
def test_sidebar_shows_icons_and_triage_count(client_local, workspace):
    from tuckit.core.services.areas import get_or_create_triage
    from tuckit.core.services.slices import create_slice
    create_slice(get_or_create_triage(workspace), "미분류 1")
    body = client_local.get("/").content.decode()
    assert "<svg" in body                 # line icons present
    assert 'class="nav-count"' in body    # triage count element rendered


@pytest.mark.django_db
def test_sidebar_grouped_with_english_labels_and_capture(client_local, workspace):
    body = client_local.get("/").content.decode()
    assert 'class="nav-group"' in body        # grouped, not a flat list
    assert 'class="capture-btn"' in body       # Capture promoted to its own button
    assert ">Home<" in body and ">Triage<" in body and ">Settings<" in body
    assert 'href="/triage/"' in body
    # Phase-1 boundary: state-lens items belong to Phase 2, must not appear yet.
    assert ">Attention<" not in body
    assert ">In Progress<" not in body
    assert ">Roadmap<" not in body
    assert 'class="nav-sep"' in body        # visual group separator present


@pytest.mark.django_db
def test_lens_count_context_processors(client_local, workspace):
    from datetime import timedelta
    from django.utils import timezone
    from tuckit.core.models import Slice
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.areas import get_or_create_triage
    a = create_area(workspace, "Backend")
    s = create_slice(a, "정체", status="building")           # building -> in_progress
    create_bite(s, "doing bite", status="doing")             # doing bite -> in_progress
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=9))  # -> attention
    # A doing bite in a Triage-area slice must NOT be counted (badge must match
    # the /in-progress/ page, which excludes triage). Guards the badge/page drift.
    triage_slice = create_slice(get_or_create_triage(workspace), "captured", status="building")
    create_bite(triage_slice, "triage doing bite", status="doing")
    resp = client_local.get("/")
    assert resp.context["attention_count"] == 1              # the stalled building slice
    assert resp.context["in_progress_count"] == 2             # building slice + doing bite (triage excluded)
