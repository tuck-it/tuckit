import pytest



@pytest.mark.django_db
def test_inbox_heading_has_count_and_capture(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    p = f"/{org.slug}"
    create_ticket(org, "loose end")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert 'class="page-head"' in body
    assert 'class="page-count"' in body
    assert "cap = true" in body                     # capture action in heading


@pytest.mark.django_db
def test_ticket_row_shows_provenance_and_english_controls(client_local, org):
    from tuckit.core.services.tickets import create_ticket
    p = f"/{org.slug}"
    create_ticket(org, "loose end")
    body = client_local.get(f"{p}/inbox/").content.decode()
    assert 'class="ticket-controls"' in body        # controls grouped for reveal
    assert "Choose area" in body
    assert ">Status" in body
    assert "— Choose an area —" not in body


@pytest.mark.django_db
def test_slice_detail_order_and_close_aria(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.plans import create_plan
    a = create_area(org, "Backend")
    s = create_slice(a, "panel order", status="building", tags=["billing"])
    create_bite(create_plan(s, title="Plan"), "step one")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'aria-label="Close panel"' in body
    assert "Open full" in body
    assert "Backend" in body                         # Area context near title
    # blueprint order: tags (a property row) appear before the plan's bites;
    # bites (inside the plan card) come before the destructive drop
    assert body.index("billing") < body.index("step one") < body.index("Drop")


@pytest.mark.django_db
def test_slice_detail_renders_status_dropdown(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(create_area(org, "Backend"), "seg", status="building")
    body = client_local.get(f"{p}/slices/{s.id}/?modal=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="status-menu"' in body and 'status-opt--on' in body


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
