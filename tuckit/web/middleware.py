from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

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


class LegacyTicketLinkMiddleware:
    """`?ticket=<id>` on any tenant page 302s to the Slice that capture became.

    Tickets stopped being a surface in this release. The param used to arm the
    old Ticket modal from base.html, and THAT modal's Promote was one-way
    (reopen_ticket refuses a promoted ticket), so leaving the param wired would
    have kept the product's last irreversible action alive for anyone arriving
    from a bookmark or one of the ~27 URLs already handed out.

    Resolved here rather than in each view because the param rode on whatever
    LIST page the reader was on (/inbox/, an area board, Home) — it was never
    a route of its own. Registered after TenantMiddleware, whose process_view
    has already resolved request.org by the time this one runs.

    A ticket with no slice at all (or a junk/foreign id) is treated as no
    ticket: the param is dropped and the page renders, rather than 404ing
    someone out of a page that exists.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from tuckit.core.services.tickets import slice_for_ticket

        raw = request.GET.get("ticket", "")
        org = getattr(request, "org", None)
        # isascii(): '٤'.isdigit() is True but int() of it never matches a pk,
        # and neither would the <int:...> route — same guard as ascii_int.
        if request.method != "GET" or org is None or not (raw.isascii() and raw.isdigit()):
            return None
        slice_ = slice_for_ticket(org, int(raw))
        if slice_ is not None:
            return redirect(reverse("web:slice", args=[org.slug, slice_.id]))
        parts = urlsplit(request.get_full_path())
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "ticket"]
        return redirect(urlunsplit(("", "", parts.path, urlencode(query), "")))
