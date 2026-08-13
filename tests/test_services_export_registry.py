import json
import zipfile
import io

import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.export import UnknownExport, export_org
from tuckit.core.services.export.registry import available_exports
from tuckit.core.services.slices import create_slice


@pytest.fixture
def org(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="owner@acme.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    create_slice(org, area=create_area(org, "Backend"), title="A slice")
    return org


@pytest.mark.django_db
@pytest.mark.parametrize("view,fmt,media", [
    ("full", "json", "application/json"),
    ("full", "md", "application/zip"),
    ("report", "csv", "text/csv"),
])
def test_the_three_shipping_combinations_produce_a_file(org, view, fmt, media):
    out = export_org(org, view, fmt)
    assert out.media_type.startswith(media)
    assert out.content
    assert out.filename.startswith("tuckit-acme-")


@pytest.mark.django_db
def test_filenames_carry_the_right_extension(org):
    assert export_org(org, "full", "json").filename.endswith(".json")
    assert export_org(org, "full", "md").filename.endswith(".zip")
    assert export_org(org, "report", "csv").filename.endswith(".csv")


@pytest.mark.django_db
def test_full_csv_is_blocked_not_silently_substituted(org):
    with pytest.raises(UnknownExport):
        export_org(org, "full", "csv")


@pytest.mark.django_db
@pytest.mark.parametrize("view,fmt", [
    ("report", "json"), ("report", "md"), ("nonsense", "json"),
    ("full", "xlsx"), ("", ""),
])
def test_unshipped_and_unknown_combinations_raise(org, view, fmt):
    with pytest.raises(UnknownExport):
        export_org(org, view, fmt)


@pytest.mark.django_db
def test_the_json_combination_really_produces_json(org):
    payload = json.loads(export_org(org, "full", "json").content)
    assert payload["tuckit_export"]["schema_version"] == 1


@pytest.mark.django_db
def test_the_md_combination_really_produces_a_zip(org):
    raw = export_org(org, "full", "md").content
    assert "README.md" in zipfile.ZipFile(io.BytesIO(raw)).namelist()


def test_available_exports_lists_exactly_the_shipping_three():
    combos = available_exports()
    assert {(c.view, c.format) for c in combos} == {
        ("full", "json"), ("full", "md"), ("report", "csv"),
    }
    for c in combos:
        assert c.label and c.blurb, f"{c.view}/{c.format} has no page copy"


def test_non_lossless_blurbs_point_at_the_json_export():
    """full/md and report/csv are both partial copies, so each blurb must
    name the JSON export as the field-for-field original — otherwise a future
    edit can quietly drop the pointer that keeps these files honest about
    what they are (see: the full/md blurb once claimed equivalence with the
    lossless copy while the zip's own README said the opposite)."""
    combos = {(c.view, c.format): c for c in available_exports()}
    for key in [("full", "md"), ("report", "csv")]:
        assert "JSON" in combos[key].blurb, f"{key} blurb does not mention JSON"


@pytest.mark.django_db
def test_exporting_writes_nothing(org):
    from tuckit.core.models import ActivityEvent, Slice
    before_events = ActivityEvent.objects.filter(org=org).count()
    before_updated = list(Slice.objects.filter(org=org)
                          .values_list("updated_at", flat=True))
    for view, fmt in [("full", "json"), ("full", "md"), ("report", "csv")]:
        export_org(org, view, fmt)
    assert ActivityEvent.objects.filter(org=org).count() == before_events
    assert list(Slice.objects.filter(org=org)
                .values_list("updated_at", flat=True)) == before_updated
