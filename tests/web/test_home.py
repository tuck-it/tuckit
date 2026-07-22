import pytest
from datetime import timedelta

from django.utils import timezone

from tuckit.core.models import Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.plans import create_plan
from tuckit.core.services.slices import create_slice
from tuckit.core.services.tickets import create_ticket


def _body(client, org):
    resp = client.get(f"/{org.slug}/")
    assert resp.status_code == 200
    return resp.content.decode()


def _band(body, name):
    """The HTML of one band. Assertions about what a band does NOT contain must
    be scoped this way: the `since you were away` band echoes every event's
    target_label, so a slice title legitimately appears elsewhere on the page.
    """
    marker = f"<span>{name}</span>"
    start = body.rindex('<section class="band">', 0, body.index(marker))
    end = body.index("</section>", start)
    return body[start:end]


@pytest.mark.django_db
def test_home_renders_four_bands_in_order(client_local, org):
    body = _body(client_local, org)
    order = [body.index(f"<span>{name}</span>") for name in
             ("your turn", "since you were away", "in progress", "shipped")]
    assert order == sorted(order), "bands must read act → read → watch → proof"
    assert body.count('class="band"') == 4


@pytest.mark.django_db
def test_home_bands_carry_their_one_line_explanations(client_local, org):
    body = _body(client_local, org)
    assert "Nothing moves on these until you decide" in body
    assert "What changed since you last looked" in body
    assert "Slices you're building right now" in body
    assert "What you've finished lately" in body


@pytest.mark.django_db
def test_home_has_no_stat_cards(client_local, org):
    """Every card repeated the length of a list further down the page."""
    body = _body(client_local, org)
    assert "stat-card" not in body
    assert "Shipped this week" not in body
    assert "since yesterday" not in body


@pytest.mark.django_db
def test_home_has_no_column_grid(client_local, org):
    body = _body(client_local, org)
    assert "home-cols" not in body
    assert "<span>focus</span>" not in body
    assert "<span>doing</span>" not in body


@pytest.mark.django_db
def test_specless_building_slice_is_your_turn(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "Undesigned work", status="building")
    body = _body(client_local, org)
    assert "Undesigned work" in body
    assert "write the spec" in body


@pytest.mark.django_db
def test_open_tickets_collapse_to_one_row_linking_to_inbox(client_local, org):
    for i in range(3):
        create_ticket(org, f"capture {i}")
    body = _body(client_local, org)
    turn = _band(body, "your turn")
    assert "3 waiting for triage" in turn
    assert f'href="/{org.slug}/inbox/"' in turn
    assert "capture 0" not in turn, "the Inbox lists tickets; Home only counts them"


@pytest.mark.django_db
def test_your_turn_empty_state_reads_as_good_news(client_local, org):
    body = _body(client_local, org)
    assert "Nothing is waiting on you — agents can keep going." in body
    assert "all-clear" in body


@pytest.mark.django_db
def test_building_slice_appears_in_progress_even_when_it_is_your_turn(client_local, org):
    """Intentional duplication. Removing it from `in progress` is exactly the
    hidden filter this redesign exists to kill."""
    a = create_area(org, "Backend")
    create_slice(a, "Undesigned work", status="building")
    body = _body(client_local, org)
    assert "Undesigned work" in _band(body, "your turn")
    assert "Undesigned work" in _band(body, "in progress")


@pytest.mark.django_db
def test_someday_tagged_building_slice_is_not_hidden(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "Parked but building", status="building",
                 spec="designed", tags=["someday"])
    body = _body(client_local, org)
    assert "Parked but building" in body


@pytest.mark.django_db
def test_stalled_building_slice_stays_listed(client_local, org):
    a = create_area(org, "Backend")
    s = create_slice(a, "Stalled work", status="building", spec="designed")
    create_bite(create_plan(s, title="Plan"), "todo", status="todo")
    Slice.objects.filter(pk=s.pk).update(updated_at=timezone.now() - timedelta(days=30))
    body = _body(client_local, org)
    assert "Stalled work" in body


@pytest.mark.django_db
def test_backlog_is_a_link_not_a_column(client_local, org):
    a = create_area(org, "Backend")
    create_slice(a, "Queued work", status="planned")
    body = _body(client_local, org)
    flight = _band(body, "in progress")
    assert "Queued work" not in flight, "the backlog belongs to Board"
    assert "1 planned" in flight
    assert "status=planned" in flight


@pytest.mark.django_db
def test_agent_activity_badges_new_on_a_second_visit(client_local, org):
    from tuckit.core.services.activity import record_activity

    a = create_area(org, "Backend")
    s = create_slice(a, "Work", status="building", spec="designed")

    _body(client_local, org)                       # first visit sets the watermark
    record_activity(org, actor="agent", verb="shipped", target=s)
    body = _body(client_local, org)

    assert "1 new" in body
    assert "is-new" in body
    assert "is-agent" in body


@pytest.mark.django_db
def test_first_visit_badges_nothing(client_local, org):
    from tuckit.core.services.activity import record_activity

    a = create_area(org, "Backend")
    s = create_slice(a, "Distinctive title", status="building", spec="designed")
    record_activity(org, actor="agent", verb="shipped", target=s)

    body = _body(client_local, org)
    assert "band-count--new" not in body, "a first-ever visit has nothing to catch up on"
    assert "is-new" not in body
    assert 'class="activity-row' in body, "the log still renders — only the badge is empty"


@pytest.mark.django_db
def test_home_ok_with_stale_open_ticket(client_local, org):
    """A stale open Ticket collapses into the aggregate triage row. The panel
    must render it without reversing web:slice on a null id — otherwise Home
    500s (NoReverseMatch)."""
    from tuckit.core.models import Ticket

    t = create_ticket(org, "Stale ticket")
    Ticket.objects.filter(pk=t.pk).update(
        created_at=timezone.now() - timedelta(days=30)
    )
    body = _body(client_local, org)
    assert "1 waiting for triage" in body


@pytest.mark.django_db
def test_home_page_head_and_capture_button(client_local, org):
    body = _body(client_local, org)
    assert 'class="page-head"' in body
    assert "What needs you, and what moved while you were away" in body
    assert 'class="button button-small"' in body
