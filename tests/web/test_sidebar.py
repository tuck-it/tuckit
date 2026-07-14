from tuckit.web.templatetags.web_extras import icon


def test_search_and_dots_icons_have_paths():
    assert "<path" in icon("search")
    assert "<path" in icon("dots") or "<circle" in icon("dots")
