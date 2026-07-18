from tuckit.web.templatetags.web_extras import spec_summary


def test_empty_spec_returns_blank():
    assert spec_summary("") == ""
    assert spec_summary(None) == ""


def test_plain_first_line():
    assert spec_summary("Payment integration flow\n\nBody...") == "Payment integration flow"


def test_strips_markdown_heading():
    assert spec_summary("# Payment integration\nBody") == "Payment integration"


def test_skips_yaml_frontmatter():
    spec = "---\nname: billing\n---\n# Payment integration\nBody"
    assert spec_summary(spec) == "Payment integration"


def test_skips_blank_and_hr_lines():
    assert spec_summary("\n\n---\n\nActual first line") == "Actual first line"


def test_strips_list_and_quote_markers():
    assert spec_summary("> Quoted first line") == "Quoted first line"
    assert spec_summary("* List first line") == "List first line"


def test_strips_wrapping_emphasis():
    assert spec_summary("*Emphasized first line*") == "Emphasized first line"


def test_truncates_to_limit():
    out = spec_summary("a" * 200, limit=10)
    assert out == "a" * 10 + "…"
