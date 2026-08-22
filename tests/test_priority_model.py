import pytest

from tuckit.core.models import Org, Slice
from tuckit.core.services.areas import create_area
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_a_new_slice_has_no_priority_and_a_new_org_has_no_policy():
    """Unset is the honest default. A slice nobody has ranked must not claim a
    middle priority it never earned, and an empty policy is a normal state --
    it is what every org looks like before anyone writes one."""
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = create_slice(org, area=area, title="Thing")

    assert s.priority is None
    assert org.priority_policy == ""


@pytest.mark.django_db
def test_priority_accepts_1_through_5():
    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = create_slice(org, area=area, title="Thing")

    for value in (1, 2, 3, 4, 5):
        s.priority = value
        s.full_clean()  # runs the choices validator


@pytest.mark.django_db
def test_priority_rejects_a_value_outside_the_scale():
    from django.core.exceptions import ValidationError

    org = Org.objects.create(name="Acme", slug="acme")
    area = create_area(org, "Backend")
    s = create_slice(org, area=area, title="Thing")
    s.priority = 6

    with pytest.raises(ValidationError):
        s.full_clean()
