from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render

from tuckit.core.services.export import UnknownExport, available_exports, export_org
from tuckit.core.services.orgs import can_export_org
from tuckit.web.views.settings_shell import settings_context


def export_download(request):
    """Hand the caller one export file.

    A non-member never arrives here — TenantMiddleware raises Http404 rather
    than confirm the org exists — so the 403 below is about role, not
    membership.
    """
    org = request.org
    if not can_export_org(request.user, org):
        return HttpResponseForbidden("You don't have permission to export this "
                                     "organization's data.")
    view = request.GET.get("view", "")
    fmt = request.GET.get("format", "")
    try:
        out = export_org(org, view, fmt)
    except UnknownExport:
        # Say which pair was refused. Silently serving a different file would
        # be worse than an error: the caller would trust the wrong artifact.
        return HttpResponse(
            f"There is no {view or '(none)'} export in {fmt or '(none)'} "
            f"format.",
            status=400, content_type="text/plain; charset=utf-8",
        )
    response = HttpResponse(out.content, content_type=out.media_type)
    response["Content-Disposition"] = f'attachment; filename="{out.filename}"'
    return response


def export_page(request):
    """The settings page offering the three download combinations.

    Driven by available_exports() so the page and the registry cannot
    disagree about what ships.
    """
    ctx = settings_context(request, active="org_export")
    ctx["org"] = request.org
    ctx["exports"] = available_exports()
    return render(request, "web/settings/org_export.html", ctx)
