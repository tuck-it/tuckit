from django.http import Http404

from tuckit.core.models import Org, OrgMember


class TenantMiddleware:
    """Resolves the <org> URL kwarg into request.org, enforces membership (404 on
    non-member — never reveal existence), and strips the slug kwarg so content views
    keep their original signatures."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        org_slug = view_kwargs.pop("org_slug", None)
        request.org = None
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
        request.session["active_org_id"] = org.id
        return None


class LiveCursorMiddleware:
    """Stamp every mutating tenant response with the org's newest activity id.

    live.js polls an org-scoped activity feed and toasts what it finds. That
    feed cannot exclude the caller — ActivityEvent.source is only human-vs-agent,
    with no member behind it — so a tab's own writes came back on the next poll
    and were announced as "Someone …", replacing (and destroying the Undo
    button inside) the toast the action had just rendered.

    Rather than widen the model, hand the client a watermark: adopt this and the
    poller resumes from after your own writes. Other members' events keep their
    higher ids, so cross-user liveness is untouched.

    Read AFTER the view has run, so the id includes the events this request just
    wrote. GETs are skipped — they write nothing, and stamping them would let a
    plain page fetch swallow a concurrent write by someone else.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        org = getattr(request, "org", None)
        if request.method == "GET" or org is None:
            return response
        # The view may have DELETED the org it ran under (settings → danger →
        # delete). request.org is then an in-memory husk with pk=None, and
        # filtering a relation by an unsaved instance raises ValueError — which
        # from here, after the response exists, turns a successful deletion into
        # a 500. There is also nothing left to publish a cursor for.
        if org.pk is None:
            return response
        # Imported here: this module is imported from settings' MIDDLEWARE path,
        # and the services package pulls in models at import time.
        from tuckit.core.services.activity import latest_activity_id

        response["X-Live-Cursor"] = str(latest_activity_id(org))
        return response


# No LegacyTicketLinkMiddleware. `?ticket=<id>` on a tenant page used to 302
# to the Slice that capture became, which it could only do by reading the
# Ticket table — dropped in 0050. With nothing to resolve the id against, the
# param is now just an unrecognised query string: pages render and ignore it,
# which is what they did before it ever existed.


class WritesBlockedMiddleware:
    """Turn WritesBlocked into a response that says why, on every write view.

    A middleware rather than a try/except in each handler: mutations.py alone
    has a dozen POST endpoints and capture.py more, and the one that gets
    forgotten is the one a customer meets. process_exception fires for whichever
    view raised, including views added later.

    The body is the reason itself, verbatim. That is the whole contract of this
    exception — a status code with no sentence behind it is the failure this
    replaces, and it is what the seat wall used to do (a bare 402 reading "seat
    limit reached (3)" with no price, no explanation and no way to act on it).

    402 Payment Required is the honest code: the org may read everything it has,
    and the block lifts on payment. It is NOT 403 — nothing here is about
    permission, and a 403 would tell an agent to stop trying rather than to tell
    its human something.

    How this looks in a browser is deliberately not decided here. htmx swaps the
    body into whatever the requesting element targets, which is fine as a
    truthful fallback but is not a designed surface, and this codebase has been
    bitten repeatedly by swap/OOB behaviour that endpoint tests cannot see. The
    banner and the upgrade path are a separate, browser-verified piece of work.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from django.http import HttpResponse

        from tuckit.core.services.exceptions import WritesBlocked

        if isinstance(exception, WritesBlocked):
            return HttpResponse(str(exception), status=402, content_type="text/plain; charset=utf-8")
        return None
