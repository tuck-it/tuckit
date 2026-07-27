import pytest

from tuckit.core.models import Bite, Slice


@pytest.mark.django_db
def test_slice_can_exist_without_an_area(org):
    s = Slice.objects.create(org=org, area=None, title="unfiled", rank="m", number=1)
    assert s.area_id is None


@pytest.mark.django_db
def test_slice_carries_constraints_and_duplicate_of(org, area):
    target = Slice.objects.create(org=org, area=area, title="canonical", rank="m", number=1)
    dupe = Slice.objects.create(
        org=org, area=area, title="dupe", rank="n", number=2,
        constraints="hx-swap을 명시할 것", duplicate_of=target,
    )
    assert dupe.constraints == "hx-swap을 명시할 것"
    assert dupe.duplicate_of == target
    assert list(target.duplicates.all()) == [dupe]


@pytest.mark.django_db
def test_slice_external_key_is_unique_per_org(org, area):
    Slice.objects.create(org=org, area=area, title="a", rank="m", number=1, external_key="k")
    with pytest.raises(Exception):
        Slice.objects.create(org=org, area=area, title="b", rank="n", number=2, external_key="k")


@pytest.mark.django_db
def test_blank_external_keys_do_not_collide(org, area):
    Slice.objects.create(org=org, area=area, title="a", rank="m", number=1, external_key="")
    Slice.objects.create(org=org, area=area, title="b", rank="n", number=2, external_key="")
    assert Slice.objects.filter(external_key="").count() == 2


@pytest.mark.django_db
def test_bite_can_exist_without_a_plan(org, area):
    """Task 5의 전제. plan이 NOT NULL이면 Slice 직결 자체가 불가능하다."""
    from tuckit.core.models import Bite, Slice

    s = Slice.objects.create(org=org, area=area, title="s", rank="m", number=1)
    b = Bite.objects.create(slice=s, plan=None, title="단계", rank="a0")
    assert b.plan_id is None and b.slice_id == s.id
