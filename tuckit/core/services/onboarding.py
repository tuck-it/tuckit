from dataclasses import dataclass

from tuckit.core.models import ActivityEvent, ApiToken, Area, Bite, Slice, Workspace


@dataclass(frozen=True)
class OnboardingState:
    has_area: bool
    has_slice: bool
    has_bite: bool
    connected: bool
    has_key: bool = False
    newest_slice_id: int | None = None

    @property
    def completed(self) -> int:
        return sum((self.has_area, self.has_slice, self.has_bite, self.connected))

    @property
    def done(self) -> bool:
        return self.completed == 4

    @property
    def current(self) -> int:
        """1=Area, 2=Slice, 3=Bite, 4=Connect, 0=all done — the first open step."""
        if not self.has_area:
            return 1
        if not self.has_slice:
            return 2
        if not self.has_bite:
            return 3
        if not self.connected:
            return 4
        return 0


def onboarding_state(workspace: Workspace) -> OnboardingState:
    newest = (
        Slice.objects.filter(area__workspace=workspace)
        .order_by("-id").values_list("id", flat=True).first()
    )
    return OnboardingState(
        has_area=Area.objects.filter(workspace=workspace, is_triage=False).exists(),
        has_slice=Slice.objects.filter(area__workspace=workspace).exists(),
        has_bite=Bite.objects.filter(plan__slice__area__workspace=workspace).exists(),
        connected=ActivityEvent.objects.filter(workspace=workspace, actor="agent").exists(),
        has_key=ApiToken.objects.filter(workspace=workspace).exists(),
        newest_slice_id=newest,
    )
