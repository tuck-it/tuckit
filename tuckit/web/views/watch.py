from django.http import JsonResponse

from tuckit.core.services.watches import read_watch


def canvas_watch(request, token):
    """Has anyone picked yet? The only question this URL can answer.

    Unauthenticated on purpose. The agent waiting on it polls from a shell that
    holds no tuckit credentials, and the reason this endpoint exists is so that
    it never needs any -- which is also why the body is two keys and no slice
    content: not the title, not the spec, not a node body. The id it returns is
    a string the agent itself authored.

    A dead token and a token that never existed answer identically. Telling
    them apart would make this a way to probe for live channels.
    """
    answer = read_watch(token)
    if answer is None:
        return JsonResponse({"status": "expired"}, status=404)
    return JsonResponse(answer)
