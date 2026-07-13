from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path

from tuckit.web.views import (
    pages, slices, mutations, board, capture, health, workspaces,
    accounts, settings_org, settings_account, routing, welcome as welcome_views,
)
from tuckit.web.views import settings as settings_views

app_name = "web"

# --- root / auth (no tenant) ---
auth_patterns = [
    path("healthcheck", health.healthz, name="healthcheck"),
    path("login/", login_not_required(auth_views.LoginView.as_view()), name="login"),
    path("register/", login_not_required(accounts.register_view), name="register"),
    path("invite/<str:token>/", login_not_required(accounts.invite_accept), name="invite_accept"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("welcome/", welcome_views.welcome, name="welcome"),
    path("welcome/key", welcome_views.welcome_generate_key, name="welcome_generate_key"),
    path("welcome/agent-activity", welcome_views.welcome_agent_check, name="welcome_agent_check"),
]

# --- settings hub (cross-cutting; explicit slugs) ---
settings_patterns = [
    path("settings/check-slug", login_not_required(routing.check_slug), name="check_slug"),
    path("settings/account", settings_account.account_settings, name="settings_account"),
    path("settings/account/orgs", settings_account.org_create, name="account_org_create"),
    path("settings/account/orgs/<int:org_id>/leave", settings_account.org_leave, name="account_org_leave"),
    # org level
    path("settings/<slug:org_slug>/", settings_org.org_settings, name="settings_org"),
    path("settings/<slug:org_slug>/rename", settings_org.org_rename, name="org_rename"),
    path("settings/<slug:org_slug>/members/<int:member_id>/role", settings_org.member_role, name="org_member_role"),
    path("settings/<slug:org_slug>/members/<int:member_id>/remove", settings_org.member_remove, name="org_member_remove"),
    path("settings/<slug:org_slug>/delete", settings_org.org_delete, name="org_delete"),
    path("settings/<slug:org_slug>/workspaces/new", workspaces.workspace_create, name="workspace_create"),
    path("settings/<slug:org_slug>/invites", settings_views.invite_create, name="invite_create"),
    path("settings/<slug:org_slug>/invites/<int:invitation_id>/cancel", settings_views.invite_cancel, name="invite_cancel"),
    # workspace level
    path("settings/<slug:org_slug>/<slug:ws_slug>/", settings_views.settings, name="settings"),
    path("settings/<slug:org_slug>/<slug:ws_slug>/workspace", settings_views.workspace_settings, name="settings_workspace"),
    path("settings/<slug:org_slug>/<slug:ws_slug>/rename", settings_views.workspace_rename, name="workspace_rename"),
    path("settings/<slug:org_slug>/<slug:ws_slug>/delete", settings_views.workspace_delete, name="workspace_delete"),
    path("settings/<slug:org_slug>/<slug:ws_slug>/tokens", settings_views.token_create, name="token_create"),
    path("settings/<slug:org_slug>/<slug:ws_slug>/tokens/<int:token_id>/revoke", settings_views.token_revoke, name="token_revoke"),
]

# --- bare root ---
root_patterns = [
    path("", routing.root_redirect, name="root"),
]

# --- workspace app content (tenant; slugs stripped by TenantMiddleware) ---
P = "<slug:org_slug>/<slug:ws_slug>/"
app_patterns = [
    path(f"{P}", pages.home, name="home"),
    path(f"{P}onboarding/dismiss", pages.dismiss_onboarding, name="onboarding_dismiss"),
    path(f"{P}capture", capture.capture, name="capture"),
    path(f"{P}triage/", capture.triage_list, name="triage"),
    path(f"{P}attention/", pages.attention, name="attention"),
    path(f"{P}in-progress/", pages.in_progress, name="in_progress"),
    path(f"{P}roadmap/", pages.roadmap, name="roadmap"),
    path(f"{P}activity/", pages.activity, name="activity"),
    path(f"{P}areas/new", capture.area_create, name="area_create"),
    path(f"{P}areas/<slug:slug>/", slices.area_view, name="area"),
    path(f"{P}areas/<slug:slug>/slices", capture.area_slice_create, name="area_slice_create"),
    path(f"{P}areas/<int:area_id>/rename", capture.area_rename, name="area_rename"),
    path(f"{P}areas/<int:area_id>/delete", capture.area_delete, name="area_delete"),
    path(f"{P}areas/<int:area_id>/reorder", capture.area_reorder, name="area_reorder"),
    path(f"{P}slices/<int:slice_id>/", slices.slice_detail, name="slice"),
    path(f"{P}slices/<int:slice_id>/status", mutations.slice_status, name="slice_status"),
    path(f"{P}slices/<int:slice_id>/edit", mutations.slice_edit, name="slice_edit"),
    path(f"{P}slices/<int:slice_id>/tags", mutations.slice_tags, name="slice_tags"),
    path(f"{P}slices/<int:slice_id>/bites", mutations.bite_create, name="bite_create"),
    path(f"{P}slices/<int:slice_id>/move", board.slice_move, name="slice_move"),
    path(f"{P}slices/<int:slice_id>/triage", capture.triage, name="slice_triage"),
    path(f"{P}bites/<int:bite_id>/toggle", mutations.bite_toggle, name="bite_toggle"),
    path(f"{P}bites/<int:bite_id>/body", mutations.bite_body, name="bite_body"),
]

urlpatterns = auth_patterns + settings_patterns + root_patterns + app_patterns
