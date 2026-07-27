from dataclasses import dataclass

from tuckit.core.models import ActivityEvent, ApiToken, Area, Bite, Org, Plan, Slice


@dataclass(frozen=True)
class OnboardingState:
    has_area: bool
    has_slice: bool
    has_plan: bool
    has_bite: bool
    connected: bool
    has_key: bool = False
    newest_slice_id: int | None = None

    @property
    def completed(self) -> int:
        return sum(
            (self.has_area, self.has_slice, self.has_plan, self.has_bite, self.connected)
        )

    @property
    def done(self) -> bool:
        return self.completed == 5

    @property
    def current(self) -> int:
        """1=Area, 2=Slice, 3=Plan, 4=Bite, 5=Connect, 0=all done — first open step."""
        if not self.has_area:
            return 1
        if not self.has_slice:
            return 2
        if not self.has_plan:
            return 3
        if not self.has_bite:
            return 4
        if not self.connected:
            return 5
        return 0


def onboarding_state(org: Org) -> OnboardingState:
    newest = (
        Slice.objects.filter(org=org)
        .order_by("-id").values_list("id", flat=True).first()
    )
    return OnboardingState(
        has_area=Area.objects.filter(org=org).exists(),
        has_slice=Slice.objects.filter(org=org).exists(),
        has_plan=Plan.objects.filter(slice__org=org).exists(),
        has_bite=Bite.objects.filter(plan__slice__org=org).exists(),
        connected=ActivityEvent.objects.filter(org=org, actor="agent").exists(),
        has_key=ApiToken.objects.filter(org=org).exists(),
        newest_slice_id=newest,
    )
