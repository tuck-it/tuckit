import pathlib

import pytest
from tuckit.core.models import Slice
from tuckit.core.services.slices import create_slice, query_slices

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.django_db
def test_query_slices_finds_area_less_slices_by_org_column(org, area):
    """org 스코핑이 area__org 조인으로 되돌아가면 area 없는 슬라이스가 조용히 사라진다.

    이 테스트의 전부는 area가 NULL인 행이다. 예전 버전은 항상 area가 붙어 있는
    `slice_` 픽스처만 썼고, 그래서 slices.py의 `filter(org=org)`를
    `filter(area__org=org)`로 되돌려도 그대로 통과했다 — 이름이 말하는 결함을
    한 번도 세운 적이 없었다.

    include_inbox=True인 이유: 기본값은 filed_slices()로 Inbox를 감추므로,
    그대로 두면 조인이 살아 있든 아니든 area 없는 행이 안 보인다."""
    filed = create_slice(org, area=area, title="filed")
    unfiled = create_slice(org, title="captured, not filed yet")
    assert unfiled.area_id is None

    found = query_slices(org, include_inbox=True)
    assert unfiled in found, "area 없는 슬라이스가 org 스코핑에서 빠졌다 (area 조인이 살아 있다)"
    assert filed in found
    # inbox_only 경로도 같은 org 컬럼을 타야 한다.
    assert query_slices(org, inbox_only=True) == [unfiled]
    assert Slice.objects.filter(org=org).count() == 2


def test_no_area_org_joins_remain_in_services():
    """소스 수준 가드 — 조인이 되살아나면 잡는다.

    경로는 이 파일 기준으로 고정한다. 예전 버전은 CWD 상대 경로
    pathlib.Path("tuckit/core/services") 였고, 스캔한 파일이 하나라도 있는지
    확인하지 않았다 — 다른 디렉터리에서 pytest를 부르면 root.glob()이 빈
    이터레이터를 내고, 되살아난 조인을 초록불로 통과시켰다. glob이 아니라
    rglob인 이유는 services/social/ 같은 하위 패키지가 스캔에서 통째로 빠져
    있었기 때문이다."""
    root = REPO_ROOT / "tuckit" / "core" / "services"
    scanned = []
    offenders = []
    for p in sorted(root.rglob("*.py")):
        if p.name == "areas.py":       # Area 자신의 org라 정상
            continue
        scanned.append(p)
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if "area__org" in line or ".area.org" in line:
                offenders.append(f"{p.relative_to(root)}:{i}")
    # "무엇을 읽기는 했는가" — 이 단언이 없으면 위 루프가 0회 돌아도 통과한다.
    assert len(scanned) >= 10, f"서비스 모듈을 못 찾았다 (scanned={len(scanned)}, root={root})"
    assert {p.name for p in scanned} >= {"slices.py", "state.py", "bites.py"}
    # Task 6에서 create_slice/set_slice_area가 정리되어, slices.py도 더는
    # 예외가 필요 없다 — 이제 area.org에 의존하는 서비스 함수는 없다.
    assert offenders == [], f"area 조인이 남아 있다: {offenders}"
