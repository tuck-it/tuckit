from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.http import JsonResponse


@login_not_required
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})
