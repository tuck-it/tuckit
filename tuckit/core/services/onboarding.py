from dataclasses import dataclass

from tuckit.core.models import ApiToken, Slice, Workspace


@dataclass(frozen=True)
class OnboardingState:
    connected: bool
    captured: bool
    triaged: bool

    @property
    def completed(self) -> int:
        return sum((self.connected, self.captured, self.triaged))

    @property
    def done(self) -> bool:
        return self.completed == 3


def onboarding_state(workspace: Workspace) -> OnboardingState:
    connected = ApiToken.objects.filter(workspace=workspace).exists()
    captured = Slice.objects.filter(area__workspace=workspace).exists()
    triaged = Slice.objects.filter(
        area__workspace=workspace, area__is_triage=False
    ).exists()
    return OnboardingState(connected=connected, captured=captured, triaged=triaged)
