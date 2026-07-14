from django.http import Http404, HttpResponse
from django.shortcuts import render

from tuckit.core.services.exceptions import NotFound, InvalidValue
from tuckit.core.services.resolve import get_slice, get_bite
from tuckit.core.services.slices import set_slice_status, update_slice
from tuckit.core.services.bites import create_bite, set_bite_status, update_bite
from tuckit.web.auth import get_current_workspace
from tuckit.web.panel import slice_panel_context


def _slice_or_404(request, slice_id):
    try:
        return get_slice(get_current_workspace(request), slice_id)
    except NotFound:
        raise Http404


def _panel(request, slice_):
    is_panel = request.GET.get("panel") == "1"
    return render(
        request, "web/partials/_slice_panel.html",
        slice_panel_context(slice_, is_panel=is_panel),
    )


def slice_status(request, slice_id):
    slice_ = _slice_or_404(request, slice_id)
    try:
        set_slice_status(slice_, request.POST["status"])
    except InvalidValue as e:
        return HttpResponse(str(e), status=400)
    return _panel(request, slice_)


def slice_edit(request, slice_id):
    slice_ = _slice_or_404(request, slice_id)
    kwargs = {}
    if "title" in request.POST: kwargs["title"] = request.POST["title"]
    if "spec" in request.POST: kwargs["spec"] = request.POST["spec"]
    update_slice(slice_, **kwargs)
    return _panel(request, slice_)


def slice_tags(request, slice_id):
    slice_ = _slice_or_404(request, slice_id)
    names = [t.name for t in slice_.tags.all()]
    add = request.POST.get("add", "").strip()
    remove = request.POST.get("remove", "").strip()
    if add and add not in names:
        names.append(add)
    if remove and remove in names:
        names.remove(remove)
    update_slice(slice_, tags=names)
    return render(request, "web/partials/_slice_tags.html", {"slice": slice_})


def bite_create(request, slice_id):
    slice_ = _slice_or_404(request, slice_id)
    create_bite(slice_, request.POST["title"], source="human")
    return _panel(request, slice_)


def bite_toggle(request, bite_id):
    try:
        bite = get_bite(get_current_workspace(request), bite_id)
    except NotFound:
        raise Http404
    set_bite_status(bite, "todo" if bite.status == "done" else "done")
    return render(request, "web/partials/_bite_row.html", {"bite": bite})


def bite_body(request, bite_id):
    try:
        bite = get_bite(get_current_workspace(request), bite_id)
    except NotFound:
        raise Http404
    update_bite(bite, body=request.POST.get("body", ""))
    return render(request, "web/partials/_bite_row.html", {"bite": bite})
