from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path

from tuckit.web.views import pages, slices, mutations, board, capture, health, workspaces, accounts, settings_org
from tuckit.web.views import settings as settings_views

app_name = "web"
urlpatterns = [
    # NB: "/healthz" is intercepted by Cloud Run's Google Front End before it
    # reaches the container, so use "/healthcheck".
    path("healthcheck", health.healthz, name="healthcheck"),
    path("login/", login_not_required(auth_views.LoginView.as_view()), name="login"),
    path("register/", login_not_required(accounts.register_view), name="register"),
    path("invite/<str:token>/", login_not_required(accounts.invite_accept), name="invite_accept"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", pages.home, name="home"),
    path("capture", capture.capture, name="capture"),
    path("triage/", capture.triage_list, name="triage"),
    path("attention/", pages.attention, name="attention"),
    path("in-progress/", pages.in_progress, name="in_progress"),
    path("roadmap/", pages.roadmap, name="roadmap"),
    path("areas/new", capture.area_create, name="area_create"),
    path("areas/<slug:slug>/", slices.area_view, name="area"),
    path("areas/<int:area_id>/rename", capture.area_rename, name="area_rename"),
    path("areas/<int:area_id>/delete", capture.area_delete, name="area_delete"),
    path("areas/<int:area_id>/reorder", capture.area_reorder, name="area_reorder"),
    path("slices/<int:slice_id>/", slices.slice_detail, name="slice"),
    path("slices/<int:slice_id>/status", mutations.slice_status, name="slice_status"),
    path("slices/<int:slice_id>/edit", mutations.slice_edit, name="slice_edit"),
    path("slices/<int:slice_id>/tags", mutations.slice_tags, name="slice_tags"),
    path("slices/<int:slice_id>/bites", mutations.bite_create, name="bite_create"),
    path("slices/<int:slice_id>/move", board.slice_move, name="slice_move"),
    path("slices/<int:slice_id>/triage", capture.triage, name="slice_triage"),
    path("bites/<int:bite_id>/toggle", mutations.bite_toggle, name="bite_toggle"),
    path("bites/<int:bite_id>/body", mutations.bite_body, name="bite_body"),
    path("settings/", settings_views.settings, name="settings"),
    path("settings/workspace", settings_views.workspace_settings, name="settings_workspace"),
    path("settings/tokens", settings_views.token_create, name="token_create"),
    path("settings/tokens/<int:token_id>/revoke", settings_views.token_revoke, name="token_revoke"),
    path("settings/rename", settings_views.workspace_rename, name="workspace_rename"),
    path("settings/workspace/delete", settings_views.workspace_delete, name="workspace_delete"),
    path("settings/invites", settings_views.invite_create, name="invite_create"),
    path("settings/invites/<int:invitation_id>/cancel", settings_views.invite_cancel, name="invite_cancel"),
    path("settings/org", settings_org.org_settings, name="settings_org"),
    path("settings/org/rename", settings_org.org_rename, name="org_rename"),
    path("settings/org/members/<int:member_id>/role", settings_org.member_role, name="org_member_role"),
    path("settings/org/members/<int:member_id>/remove", settings_org.member_remove, name="org_member_remove"),
    path("settings/org/delete", settings_org.org_delete, name="org_delete"),
    path("switch-workspace", workspaces.switch_workspace, name="switch_workspace"),
    path("workspaces/new", workspaces.workspace_create, name="workspace_create"),
]
