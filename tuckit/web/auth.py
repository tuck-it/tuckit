from tuckit.core.models import Workspace
from tuckit.core.services.orgs import accessible_workspaces, user_can_access_workspace


def get_current_workspace(request) -> Workspace | None:
    if not request.user.is_authenticated:
        return None
    ws_id = request.session.get("active_workspace_id")
    if ws_id:
        ws = Workspace.objects.filter(pk=ws_id).select_related("org").first()
        if ws and user_can_access_workspace(request.user, ws):
            return ws
    ws = accessible_workspaces(request.user).first()
    if ws:
        request.session["active_workspace_id"] = ws.id
    return ws
