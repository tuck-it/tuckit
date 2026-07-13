from django.http import Http404

from tuckit.core.models import Org, OrgMember, Workspace


class TenantMiddleware:
    """Resolves the <org>/<workspace> URL kwargs into request.org/request.workspace,
    enforces membership (404 on non-member — never reveal existence), and strips the
    slug kwargs so content views keep their original signatures."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        org_slug = view_kwargs.pop("org_slug", None)
        ws_slug = view_kwargs.pop("ws_slug", None)
        request.org = None
        request.workspace = None
        if org_slug is None:
            return None
        # LoginRequiredMiddleware runs earlier, so anonymous users never reach here
        # for tenant views; guard defensively anyway.
        if not request.user.is_authenticated:
            raise Http404
        org = Org.objects.filter(slug=org_slug).first()
        if org is None or not OrgMember.objects.filter(user=request.user, org=org).exists():
            raise Http404
        request.org = org
        if ws_slug is not None:
            ws = Workspace.objects.filter(org=org, slug=ws_slug).select_related("org").first()
            if ws is None:
                raise Http404
            request.workspace = ws
            request.session["active_workspace_id"] = ws.id
        return None
