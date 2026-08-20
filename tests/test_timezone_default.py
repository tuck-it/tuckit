"""Nobody chose America/Chicago; Django's global_settings did.

Every rendered date went through it, so a deadline could be shown one day off
from the one on the reader's own calendar. This test exists because the value
is invisible when it is right and only ever noticed when a date is wrong.
"""
from django.conf import settings


def test_the_products_timezone_is_not_an_accident_of_the_framework():
    assert settings.TIME_ZONE != "America/Chicago", (
        "Django's unchosen default is back — dates will render in a US zone"
    )
    assert settings.TIME_ZONE == "UTC"


def test_dates_are_still_stored_and_compared_with_a_timezone():
    assert settings.USE_TZ is True
