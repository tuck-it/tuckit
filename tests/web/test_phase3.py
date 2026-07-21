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
    assert "Assign area" in body
    assert ">Status" in body
    assert "— Choose an area —" not in body


@pytest.mark.django_db
def test_slice_panel_order_and_close_aria(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    from tuckit.core.services.bites import create_bite
    from tuckit.core.services.plans import create_plan
    a = create_area(org, "Backend")
    s = create_slice(a, "panel order", status="building", tags=["billing"])
    create_bite(create_plan(s, title="Plan"), "step one")
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'aria-label="Close panel"' in body
    assert "Open full" in body
    assert "Backend" in body                         # Area context near title
    # blueprint order: tags (a property row) appear before the plan's bites;
    # bites (inside the plan card) come before the destructive drop
    assert body.index("billing") < body.index("step one") < body.index("Drop")


@pytest.mark.django_db
def test_slice_panel_renders_status_dropdown(client_local, org):
    from tuckit.core.services.areas import create_area
    from tuckit.core.services.slices import create_slice
    p = f"/{org.slug}"
    s = create_slice(create_area(org, "Backend"), "seg", status="building")
    body = client_local.get(f"{p}/slices/{s.id}/?panel=1", HTTP_HX_REQUEST="true").content.decode()
    assert 'class="status-menu"' in body and 'status-opt--on' in body


@pytest.mark.django_db
def test_slide_over_container_is_labelled_dialog(client_local, org):
    p = f"/{org.slug}"
    body = client_local.get(f"{p}/").content.decode()
    assert 'id="panel"' in body
    assert 'role="dialog"' in body
    assert 'aria-modal="true"' in body
    assert 'aria-labelledby="panel-title"' in body
    # focus-management wiring present
    assert "closePanel" in body
    assert "trapPanel" in body
    assert "__overlayOpeners" in body   # shared by #panel/#ticket-modal/#member-modal
