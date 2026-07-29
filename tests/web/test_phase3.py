import pytest



@pytest.mark.django_db
def test_inbox_heading_has_count_and_capture(client_local, org):
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    create_slice(org, title="loose end")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="page-count"' in body
    assert "cap = true" in body                     # capture action in heading


@pytest.mark.django_db
def test_inbox_row_shows_the_area_picker_in_english(client_local, org):
    """Task 9: the Inbox lists Slices, not Tickets — one control (the Area
    picker), no separate Status field, no legacy em-dash placeholder."""
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    create_slice(org, title="loose end")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert 'class="inbox-area-select"' in body
    assert "Choose area" in body
    assert ">Status" not in body
    assert "— Choose an area —" not in body


@pytest.mark.django_db
def test_slice_detail_order_and_close_aria(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    a = create_area(org, "Backend")
    s = create_slice(a.org, area=a, title="panel order", status="open", tags=["billing"])
    create_bite(s, "step one")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'aria-label="Close panel"' in body
    assert "Open full" in body
    assert "Backend" in body                         # Area context near title
    # blueprint order: tags (a property row) appear before the Steps list;
    # steps come before the destructive drop
    assert body.index("billing") < body.index("step one") < body.index("Drop")


@pytest.mark.django_db
def test_slice_detail_renders_stage_pill(client_local, org):
    """Replaces the old status-picking dropdown: stage is read-only, derived,
    and rendered as a static pill (A0 — no status control anywhere)."""
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(org, area=create_area(org, "Backend"), title="seg", status="open")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="status-pill status-pill--static"' in body
    assert "status-opt" not in body


@pytest.mark.django_db
def test_detail_modal_container_is_wired_for_focus(client_local, org):
    """The container is now a bare scrim: role/aria-labelledby moved onto the
    card htmx swaps in, because an empty container cannot honestly claim to be
    a dialog labelled by a title that is not there."""
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'id="detail-modal"' in body
    assert "closeDetail" in body
    assert "trapOverlay" in body
    assert "__overlayOpeners" in body
