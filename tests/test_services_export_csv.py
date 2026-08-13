import csv
import io

import pytest

from tuckit.core.models import Org, OrgMember, User
from tuckit.core.services.areas import create_area
from tuckit.core.services.export.collect import collect
from tuckit.core.services.export.renderers import render_csv
from tuckit.core.services.export.schema import EXPORT_SCHEMA
from tuckit.core.services.slices import create_slice

MULTILINE_SPEC = "line one\nline two, with a comma\n\n\"quoted\""


@pytest.fixture
def org(db):
    org = Org.objects.create(name="Acme", slug="acme")
    user = User.objects.create(email="owner@acme.com")
    OrgMember.objects.create(user=user, org=org, role="owner")
    area = create_area(org, "Backend")
    create_slice(org, area=area, title="보고용 한국어 제목", spec=MULTILINE_SPEC,
                 tags=["gtm", "blocker"])
    create_slice(org, title="Unfiled capture")
    return org


@pytest.mark.django_db
def test_starts_with_a_utf8_bom_so_excel_reads_korean(org):
    """Without the BOM Excel shows mojibake, and only a human would notice."""
    raw = render_csv(collect(org))
    assert raw.startswith(b"\xef\xbb\xbf")


@pytest.mark.django_db
def test_decodes_cleanly_as_utf_8_sig_with_korean_intact(org):
    text = render_csv(collect(org)).decode("utf-8-sig")
    assert "보고용 한국어 제목" in text


@pytest.mark.django_db
def test_header_is_derived_from_the_schema_not_hand_written(org):
    text = render_csv(collect(org)).decode("utf-8-sig")
    header = next(csv.reader(io.StringIO(text)))
    assert header == list(EXPORT_SCHEMA["slices"].fields.keys())


@pytest.mark.django_db
def test_one_row_per_slice_including_inbox(org):
    text = render_csv(collect(org)).decode("utf-8-sig")
    body = list(csv.DictReader(io.StringIO(text)))
    assert len(body) == 2
    assert "Unfiled capture" in [r["title"] for r in body]


@pytest.mark.django_db
def test_spec_with_newlines_and_quotes_round_trips(org):
    text = render_csv(collect(org)).decode("utf-8-sig")
    body = list(csv.DictReader(io.StringIO(text)))
    row = next(r for r in body if r["spec"])
    assert row["spec"] == MULTILINE_SPEC


@pytest.mark.django_db
def test_tags_render_as_a_readable_string_not_a_python_list(org):
    text = render_csv(collect(org)).decode("utf-8-sig")
    row = next(r for r in csv.DictReader(io.StringIO(text)) if r["tags"])
    assert row["tags"] == "blocker gtm"
    assert "[" not in row["tags"]


@pytest.mark.django_db
def test_none_renders_as_an_empty_cell_not_the_word_none(org):
    text = render_csv(collect(org)).decode("utf-8-sig")
    row = next(r for r in csv.DictReader(io.StringIO(text))
               if r["title"] == "Unfiled capture")
    assert row["area_id"] == ""
    assert row["assignee"] == ""
    assert "None" not in row.values()


@pytest.mark.django_db
def test_empty_org_still_gets_a_header_row(db):
    empty = Org.objects.create(name="Empty", slug="empty")
    text = render_csv(collect(empty)).decode("utf-8-sig")
    reader = list(csv.reader(io.StringIO(text)))
    assert len(reader) == 1
    assert reader[0] == list(EXPORT_SCHEMA["slices"].fields.keys())
