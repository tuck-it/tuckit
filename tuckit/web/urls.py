from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path
from django.views.generic import RedirectView

from tuckit.web.views import (
    pages, slices, mutations, board, capture, health,
    accounts, settings_org, settings_account, settings_shell, routing,
    onboarding, oauth, social, live, search, export, watch,
)
from tuckit.web.views import settings as settings_views

app_name = "web"

# --- root / auth (no tenant) ---
auth_patterns = [
    path("healthcheck", health.healthz, name="healthcheck"),
    path("login/", login_not_required(accounts.auth_entry), name="login"),
    path("login/<slug:provider>/", login_not_required(social.social_begin), name="social_begin"),
    path("login/<slug:provider>/callback/", login_not_required(social.social_callback), name="social_callback"),
    # query_string=True: RedirectView discards the query string by default, so
    # ?next= (and anything else an inbound link carries) died on this hop.
    path("register/", login_not_required(RedirectView.as_view(pattern_name="web:login", permanent=False, query_string=True)), name="register"),
    path("invite/<str:token>/", login_not_required(accounts.invite_accept), name="invite_accept"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("orgs/", onboarding.orgs, name="orgs"),
]

# --- internal JSON API (no HTML pages) ---
api_patterns = [
    path("api/check-slug", login_not_required(routing.check_slug), name="api_check_slug"),
    # The one CAPABILITY-TOKEN route in the product -- not the only login-exempt
    # one (login/, register/, invite/, healthcheck, api/check-slug above, and
    # the OAuth metadata routes are all login_not_required too), but the only
    # one whose token IS the authorisation. It lives fifteen minutes and
    # answers exactly one question. Deliberately outside the tenant prefix --
    # the shell polling it knows a URL and nothing else, not an org slug.
    path("watch/<str:token>", login_not_required(watch.canvas_watch), name="canvas_watch"),
]

# --- OAuth 2.1 (MCP authorization server; no tenant slug) ---
oauth_patterns = [
    path(".well-known/oauth-protected-resource/mcp",
         login_not_required(oauth.protected_resource_metadata), name="oauth_prm"),
    path(".well-known/oauth-authorization-server",
         login_not_required(oauth.authorization_server_metadata), name="oauth_asm"),
    path("oauth/register", login_not_required(oauth.register), name="oauth_register"),
    path("oauth/authorize", oauth.authorize, name="oauth_authorize"),
    path("oauth/token", login_not_required(oauth.token), name="oauth_token"),
]

# --- settings shell (org-based URLs; the new IA). Task 2 lays the shell +
#     org General; Tasks 3–5 append their own pages/mutations below in turn. ---
settings_patterns = [
    path("<slug:org_slug>/settings/", settings_shell.settings_root, name="settings_root"),
    path("<slug:org_slug>/settings/general", settings_org.org_general, name="settings_org_general"),
    path("<slug:org_slug>/settings/rename", settings_org.org_rename, name="org_rename"),
    path("<slug:org_slug>/settings/key", settings_org.org_key, name="org_key"),
    path("<slug:org_slug>/settings/members", settings_org.org_members, name="settings_org_members"),
    path("<slug:org_slug>/settings/members/<int:member_id>/role", settings_org.member_role, name="org_member_role"),
    path("<slug:org_slug>/settings/members/<int:member_id>/remove", settings_org.member_remove, name="org_member_remove"),
    path("<slug:org_slug>/settings/members/<int:member_id>/manage", settings_org.member_manage, name="org_member_manage"),
    path("<slug:org_slug>/settings/invites", settings_views.invite_create, name="invite_create"),
    path("<slug:org_slug>/settings/invites/<int:invitation_id>/cancel", settings_views.invite_cancel, name="invite_cancel"),
    path("<slug:org_slug>/settings/invites/<int:invitation_id>/manage", settings_views.invite_manage, name="invite_manage"),
    path("<slug:org_slug>/settings/agent", settings_views.org_agent, name="settings_org_agent"),
    path("<slug:org_slug>/settings/tokens", settings_views.token_create, name="token_create"),
    path("<slug:org_slug>/settings/tokens/<int:token_id>/revoke", settings_views.token_revoke, name="token_revoke"),
    path("<slug:org_slug>/settings/agent/apps/<str:client_id>/disconnect", settings_views.oauth_disconnect, name="oauth_disconnect"),
    # The page lives at .../shipped-board and the mutation at .../shipped-board/prefs
    # so the fixed page URL and the mutation never collide.
    path("<slug:org_slug>/settings/shipped-board", settings_views.org_shipped, name="settings_org_shipped"),
    path("<slug:org_slug>/settings/shipped-board/prefs", settings_views.shipped_board_prefs, name="shipped_board_prefs"),
    # The page sits at .../export and the download hangs off .../export/download,
    # the same split shipped-board uses so a fixed page path and its action can
    # never collide.
    path("<slug:org_slug>/settings/export", export.export_page,
         name="settings_org_export"),
    path("<slug:org_slug>/settings/export/download", export.export_download,
         name="settings_org_export_download"),
    path("<slug:org_slug>/settings/danger", settings_org.org_danger, name="settings_org_danger"),
    path("<slug:org_slug>/settings/delete", settings_org.org_delete, name="org_delete"),
    # --- account settings pages + mutations (Task 5) ---
    path("<slug:org_slug>/settings/account/profile", settings_account.account_profile, name="settings_account_profile"),
    path("<slug:org_slug>/settings/account/organizations", settings_account.account_orgs, name="settings_account_orgs"),
    path("<slug:org_slug>/settings/account/orgs", settings_account.org_create, name="account_org_create"),
    path("<slug:org_slug>/settings/account/orgs/<int:org_id>/leave", settings_account.org_leave, name="account_org_leave"),
    path("<slug:org_slug>/settings/account", settings_shell.settings_account_root, name="settings_account_root"),
]

# --- bare root ---
root_patterns = [
    path("", routing.root_redirect, name="root"),
]

# --- app content (tenant; slug stripped by TenantMiddleware) ---
P = "<slug:org_slug>/"
app_patterns = [
    path(f"{P}onboarding/dismiss", pages.dismiss_onboarding, name="onboarding_dismiss"),
    path(f"{P}onboarding/connect-key", onboarding.connect_key, name="onboarding_connect_key"),
    path(f"{P}onboarding/agent-activity", onboarding.agent_check, name="onboarding_agent_check"),
    path(f"{P}capture", capture.capture, name="capture"),
    path(f"{P}live", live.live, name="live"),
    path(f"{P}search", search.search, name="search"),
    path(f"{P}inbox/", capture.inbox, name="inbox"),
    path(f"{P}roadmap/", pages.roadmap, name="roadmap"),
    path(f"{P}areas/", pages.areas, name="areas"),
    path(f"{P}areas/new", capture.area_create, name="area_create"),
    path(f"{P}areas/<slug:slug>/", slices.area_view, name="area"),
    path(f"{P}areas/<slug:slug>/slices", capture.area_slice_create, name="area_slice_create"),
    path(f"{P}areas/<int:area_id>/rename", capture.area_rename, name="area_rename"),
    path(f"{P}areas/<int:area_id>/edit", capture.area_edit, name="area_edit"),
    path(f"{P}areas/<int:area_id>/delete", capture.area_delete, name="area_delete"),
    path(f"{P}areas/<int:area_id>/reorder", capture.area_reorder, name="area_reorder"),
    path(f"{P}areas/<int:area_id>/move", capture.area_move, name="area_move"),
    path(f"{P}slices/<int:slice_id>/", slices.slice_detail, name="slice"),
    path(f"{P}slices/<int:slice_id>/status", mutations.slice_status, name="slice_status"),
    path(f"{P}slices/<int:slice_id>/edit", mutations.slice_edit, name="slice_edit"),
    path(f"{P}slices/<int:slice_id>/tags", mutations.slice_tags, name="slice_tags"),
    # A click on the canvas. POST-only and login-scoped like every other
    # mutation here -- the unauthenticated half of this loop is the watch URL
    # in api_patterns, which only ever reads.
    path(f"{P}slices/<int:slice_id>/choice", mutations.slice_choice, name="slice_choice"),
    path(f"{P}slices/<int:slice_id>/move", board.slice_move, name="slice_move"),
    # Triage = picking an Area (reversible: an empty area_id sends the slice
    # back to the Inbox). It replaced the old Ticket promote/dismiss flow, and
    # with the Ticket modal deleted (Task 10) every one of those endpoints is
    # gone: promote was the last one-way action in the product.
    path(f"{P}slices/<int:slice_id>/area", mutations.slice_area, name="slice_area"),
    # Steps hang off the Slice, not a Plan (Task 5). The old
    # POST /plans/<id>/bites is gone with the plan card.
    path(f"{P}slices/<int:slice_id>/steps", mutations.bite_create, name="bite_create"),
    # No /tickets/<id>/ route. It forwarded a legacy deep link to the Slice
    # that capture became, and it could only do that by reading the Ticket
    # table — which 0050 drops. The ~27 already-published URLs now 404, which
    # is the honest answer: the id they carry no longer names anything.
    path(f"{P}bites/<int:bite_id>/toggle", mutations.bite_toggle, name="bite_toggle"),
    path(f"{P}bites/<int:bite_id>/body", mutations.bite_body, name="bite_body"),
    path(f"{P}bites/<int:bite_id>/edit", mutations.bite_edit, name="bite_edit"),
    path(f"{P}bites/<int:bite_id>/delete", mutations.bite_delete, name="bite_delete"),
]

# --- org root = Home (single segment; MUST be last so literal single-segment
#     routes like login/ orgs/ always win) ---
home_patterns = [
    path(P, pages.home, name="home"),
]

urlpatterns = (
    auth_patterns + api_patterns + oauth_patterns + settings_patterns
    + root_patterns + app_patterns + home_patterns
)
