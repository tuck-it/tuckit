import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.bites import create_bite
from tuckit.core.services.slices import annotate_stage_counts, create_slice
from tuckit.core.services.state import render_slice_markdown


@pytest.fixture
def slice_with_steps(db):
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = create_slice(org, area=area, title="A slice", spec="designed")
    create_bite(s, "first step", body="details")
    create_bite(s, "second step")
    return s


@pytest.mark.django_db
def test_injected_bites_and_activity_issue_no_queries(slice_with_steps):
    from tuckit.core.services.activity import slice_activity
    from tuckit.core.services.bites import list_bites

    s = slice_with_steps
    bites = list(list_bites(s))
    activity = slice_activity(s)
    # Mirror how the export's collect() (TP-146 bite 141) actually hands
    # slices to this renderer: tags prefetched and stage counts annotated on
    # the queryset that fetched the instance. That is the only way Django
    # avoids re-querying `.tags.all()` / stage_of()'s bite counts on a plain
    # instance — calling the renderer once does not warm those, since a
    # related manager's `.all()` is a fresh queryset each time unless the
    # instance carries `_prefetched_objects_cache` or a stage annotation.
    # Re-fetching this way isolates the assertion to what this bite actually
    # changes: that passing bites= / activity= stops the renderer from
    # calling list_bites() / slice_activity() itself.
    s = (
        annotate_stage_counts(Slice.objects.filter(pk=s.pk))
        .prefetch_related("tags")
        .get()
    )

    with CaptureQueriesContext(connection) as q:
        render_slice_markdown(s, with_activity=True, bites=bites,
                              activity=activity)
    assert len(q) == 0, f"renderer still queried: {[e['sql'] for e in q]}"


@pytest.mark.django_db
def test_output_is_identical_whether_injected_or_queried(slice_with_steps):
    """MCP get_slice must keep returning byte-identical text."""
    from tuckit.core.services.activity import slice_activity
    from tuckit.core.services.bites import list_bites

    s = slice_with_steps
    queried = render_slice_markdown(s, with_activity=True)
    injected = render_slice_markdown(
        s, with_activity=True, bites=list(list_bites(s)),
        activity=slice_activity(s),
    )
    assert queried == injected


@pytest.mark.django_db
def test_default_call_still_queries_and_renders_steps(slice_with_steps):
    out = render_slice_markdown(slice_with_steps)
    assert "## Steps" in out
    assert "- [ ] first step" in out


@pytest.mark.django_db
def test_injecting_an_empty_bite_list_omits_the_steps_section(slice_with_steps):
    out = render_slice_markdown(slice_with_steps, bites=[])
    assert "## Steps" not in out
