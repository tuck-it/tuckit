"""Ticket과 Plan을 Slice 하나로 접는다. 되돌릴 수 없다.

서비스 코드를 import하지 않는다 (apps.get_model()만 쓴다). 마이그레이션이
서비스를 부르면 그 서비스가 바뀌는 날 이미 실행된 과거의 의미까지 조용히
바뀐다 — 파생 로직이 필요하면 여기 인라인으로 박는다.
"""

from django.db import migrations

SEP = "\n\n---\n\n"

# fractional-indexing의 정수 키 형식. head 글자가 뒤따르는 base-62 자릿수를
# 인코딩한다: 'a'=1자리, 'b'=2자리, … ('a0','a1',…,'az','b00',…)
_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_HEADS = "abcdefghijklmnopqrstuvwxyz"


def _order_key(i):
    """증가 순서의 i번째 유효한 fractional-indexing rank 키.

    '000001' 같은 0-패딩 숫자를 쓰면 안 된다. head가 '0'이라 유효한 order key가
    아니고, 그 rank를 가진 바이트 뒤에 새 바이트를 붙이려는 순간
    generate_key_between()이 FIError로 죽는다 — 마이그레이션은 통과하고
    한참 뒤 사용자가 바이트를 추가할 때 터진다.

    tuckit.core.ranking을 import하는 대신 형식을 여기서 재현한다."""
    for width, head in enumerate(_HEADS, start=1):
        span = 62**width
        if i < span:
            digits = ""
            for _ in range(width):
                i, remainder = divmod(i, 62)
                digits = _DIGITS[remainder] + digits
            return head + digits
        i -= span
    raise ValueError("한 슬라이스에 rank를 매길 수 없을 만큼 많은 바이트가 있다")


def _append(existing, addition):
    return (existing + SEP if existing else "") + addition


def forward(apps, schema_editor):
    Ticket = apps.get_model("core", "Ticket")
    Plan = apps.get_model("core", "Plan")
    Bite = apps.get_model("core", "Bite")
    Slice = apps.get_model("core", "Slice")
    Activity = apps.get_model("core", "ActivityEvent")

    ticket_to_slice = {}          # ticket.id -> slice.id (활동 이벤트 재타겟팅용)
    collisions = 0

    # 1) 이미 슬라이스에 묶인 티켓(승격 원본 + absorb된 것들): 슬라이스를 새로
    #    만들지 않는다. number가 겹쳐 uniq_slice_number_per_org를 위반하기 때문이다.
    #    v0.28.0부터 승격은 복사가 아니라 링크라, 캡처 원문은 오직 티켓에만 있다 —
    #    버리면 사라진다. 그래서 대상 spec에 이어붙인다.
    #
    #    슬라이스를 매번 다시 읽는 이유: 한 슬라이스에 티켓이 여럿 붙을 수 있고
    #    (absorb_ticket), select_related로 받아온 사본들은 서로의 저장을 못 본다.
    #    그러면 마지막 티켓의 본문만 남고 앞의 것들이 조용히 덮인다.
    for t in Ticket.objects.filter(slice__isnull=False).order_by("id"):
        if t.body:
            s = Slice.objects.get(pk=t.slice_id)
            s.spec = _append(s.spec, f"### 원본 캡처 ({t.title})\n\n{t.body}")
            s.save(update_fields=["spec"])
        ticket_to_slice[t.id] = t.slice_id

    # 2) 나머지 티켓 → 새 슬라이스. number/rank/source/external_key/생성시각을 승계한다.
    status_map = {"open": "open", "dismissed": "dropped", "duplicate": "dropped"}
    for t in Ticket.objects.filter(slice__isnull=True).order_by("id"):
        ext = t.external_key or ""
        note = ""
        if ext and Slice.objects.filter(org_id=t.org_id, external_key=ext).exists():
            note = f"\n\n<!-- migrated-external-key: {ext} -->"
            ext = ""
            collisions += 1
        s = Slice.objects.create(
            org_id=t.org_id,
            area_id=t.area_id,                       # area는 살린다 (설계 결정)
            title=t.title,
            spec=(t.body or "") + note,
            constraints="",
            status=status_map.get(t.status, "open"),
            number=t.number,
            rank=t.rank,
            source=t.source,
            external_key=ext,
        )
        # created_at은 auto_now_add라 create()가 준 값을 무시하고 '지금'을 쓴다.
        # 그대로 두면 인박스에 몇 달 묵어 있던 캡처가 전부 오늘 만들어진 것으로
        # 보인다 — Home/활동 정렬이 통째로 거짓말을 한다.
        Slice.objects.filter(pk=s.pk).update(created_at=t.created_at)
        ticket_to_slice[t.id] = s.pk

    # 3) Plan → Slice 필드. 한 슬라이스에 Plan이 여럿이면 id 순서대로 이어붙인다.
    #    여기서도 슬라이스를 매번 다시 읽는다 (2번 항목과 같은 이유).
    plan_count = 0
    for p in Plan.objects.all().order_by("id"):
        plan_count += 1
        s = Slice.objects.get(pk=p.slice_id)
        if p.body:
            head = f"### {p.title}" if p.title else "### 계획"
            s.spec = _append(s.spec, f"{head}\n\n{p.body}")
        if p.constraints:
            s.constraints = _append(s.constraints, p.constraints)
        s.save(update_fields=["spec", "constraints"])

    # 4) Bite 재부모화. rank는 plan 안에서만 유일했으므로 slice 기준으로 다시 매긴다.
    by_slice = {}
    for b in Bite.objects.select_related("plan").order_by("plan_id", "rank", "id"):
        by_slice.setdefault(b.plan.slice_id, []).append(b)
    for slice_id, bites in by_slice.items():
        for n, b in enumerate(bites):
            b.slice_id = slice_id
            b.rank = _order_key(n)
            b.save(update_fields=["slice", "rank"])

    # 5) 활동 이벤트 재타겟팅. target_type/target_id는 FK가 아니라 (문자열, 정수)
    #    쌍이라, 빠뜨려도 DB는 아무 불평을 하지 않고 이력만 조용히 죽는다.
    retargeted = 0
    for e in Activity.objects.filter(target_type="ticket"):
        new_id = ticket_to_slice.get(e.target_id)
        if new_id is None:
            # 이미 삭제된 티켓을 가리키던 이벤트. 가리킬 곳이 없으니 그대로 둔다.
            continue
        e.target_type = "slice"
        e.target_id = new_id
        e.save(update_fields=["target_type", "target_id"])
        retargeted += 1

    if ticket_to_slice or plan_count or by_slice:
        print(
            f"[0045] tickets={len(ticket_to_slice)} plans={plan_count} "
            f"bite_slices={len(by_slice)} activity_retargeted={retargeted} "
            f"external_key_collisions={collisions}"
        )


def backward(apps, schema_editor):
    raise RuntimeError(
        "0045는 되돌릴 수 없다. spec에 합쳐진 plan.body와 ticket.body를 다시 쪼갤 수 "
        "없기 때문이다. 롤백은 Neon 스냅샷/브랜치 복원으로 한다."
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0044_two_layer_schema")]
    operations = [migrations.RunPython(forward, backward)]
