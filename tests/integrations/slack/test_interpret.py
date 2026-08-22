from types import SimpleNamespace

import pytest

from tuckit.integrations.slack.interpret import (
    Intent, MAX_INTENTS, TooManyIntents, build_tools, interpret,
)


def tool_use(name, **args):
    return SimpleNamespace(type="tool_use", name=name, input=args)


def fake_response(*blocks):
    return SimpleNamespace(content=list(blocks))


@pytest.fixture(autouse=True)
def _key(settings):
    settings.ANTHROPIC_API_KEY = "sk-ant-test"


def test_area_enum_offers_every_area_plus_the_inbox():
    tools = {t["name"]: t for t in build_tools(["oss", "cloud"])}
    enum = tools["create_slice"]["input_schema"]["properties"]["area"]["enum"]
    assert set(enum) == {"oss", "cloud", ""}


def test_every_tool_is_strict_and_closed():
    for tool in build_tools(["oss"]):
        assert tool["strict"] is True
        schema = tool["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_no_tool_property_is_numeric_a_model_must_never_return_a_pk():
    """The slice's landmine: NEVER GIVE THE MODEL A PK.

    Every ref the model can hand back (e.g. add_note's `ref`) must be a
    string like "TP-214", resolved later by parse_ref() inside the caller's
    own org. If any tool property were typed "integer" or "number", the
    model could return a bare primary key instead, and a hostile or
    confused completion could then be used to reach another org's row.
    This workspace has already overwritten two slices by confusing a ref
    with a pk — this test pins the schema so that mistake cannot recur
    silently through a one-line type change.
    """
    for tool in build_tools(["oss"]):
        for prop_name, prop_schema in tool["input_schema"]["properties"].items():
            assert prop_schema["type"] not in ("integer", "number"), (
                f"{tool['name']}.{prop_name} must not be numeric; "
                "the model must never be able to emit a primary key"
            )


def test_tool_use_blocks_become_intents(monkeypatch):
    monkeypatch.setattr(
        "tuckit.integrations.slack.interpret._call_model",
        lambda **kw: fake_response(
            SimpleNamespace(type="text", text="ignore me"),
            tool_use("create_slice", title="A", spec="why", area="oss"),
            tool_use("add_note", ref="TP-214", body="also seen here"),
        ),
    )
    intents = interpret(messages=["hi"], area_slugs=["oss"], open_slices=[("TP-214", "mail")])
    assert intents == [
        Intent(tool="create_slice", args={"title": "A", "spec": "why", "area": "oss"}),
        Intent(tool="add_note", args={"ref": "TP-214", "body": "also seen here"}),
    ]


def test_more_than_the_cap_writes_nothing(monkeypatch):
    too_many = [
        tool_use("create_slice", title=f"S{i}", spec="x", area="")
        for i in range(MAX_INTENTS + 1)
    ]
    monkeypatch.setattr(
        "tuckit.integrations.slack.interpret._call_model",
        lambda **kw: fake_response(*too_many),
    )
    with pytest.raises(TooManyIntents):
        interpret(messages=["hi"], area_slugs=["oss"], open_slices=[])


def test_no_api_key_raises_rather_than_returning_nothing(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = ""
    from tuckit.integrations.slack.interpret import InterpretationUnavailable

    with pytest.raises(InterpretationUnavailable):
        interpret(messages=["hi"], area_slugs=[], open_slices=[])
