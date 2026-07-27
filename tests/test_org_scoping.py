import pytest
from tuckit.core.models import Slice
from tuckit.core.services.slices import query_slices


@pytest.mark.django_db
def test_query_slices_finds_slices_by_org_column(org, slice_):
    """area__org 조인이 남아 있으면, area가 없는 슬라이스가 조용히 사라진다.

    area는 아직 non-null이라 여기서는 org 컬럼 경로가 살아 있는지만 확인한다.
    Task 2에서 area가 nullable이 된 뒤 이것이 진짜 가드가 된다."""
    assert list(query_slices(org)) == [slice_]
    assert Slice.objects.filter(org=org).count() == 1


@pytest.mark.django_db
def test_no_area_org_joins_remain_in_services():
    """소스 수준 가드 — 조인이 되살아나면 잡는다."""
    import pathlib
    root = pathlib.Path("tuckit/core/services")
    offenders = []
    for p in root.glob("*.py"):
        if p.name == "areas.py":       # Area 자신의 org라 정상
            continue
        text = p.read_text()
        for i, line in enumerate(text.splitlines(), 1):
            if "area__org" in line or ".area.org" in line:
                offenders.append(f"{p.name}:{i}")
    # Task 6에서 create_slice/set_slice_area가 정리되어, slices.py도 더는
    # 예외가 필요 없다 — 이제 area.org에 의존하는 서비스 함수는 없다.
    assert offenders == [], f"area 조인이 남아 있다: {offenders}"
