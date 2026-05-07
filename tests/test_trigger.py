from claude_rag_hook.trigger import parse


def test_rag_colon_form():
    m = parse("rag: where do we handle auth?", ["rag:", "/rag"])
    assert m is not None and m.query == "where do we handle auth?" and m.tag is None


def test_slash_rag_form():
    m = parse("/rag where do we handle auth?", ["rag:", "/rag"])
    assert m is not None and m.query == "where do we handle auth?" and m.tag is None


def test_tagged_form():
    m = parse("rag@work: tokens", ["rag:", "/rag"])
    assert m is not None and m.query == "tokens" and m.tag == "work"


def test_all_tag():
    m = parse("rag@all: tokens", ["rag:", "/rag"])
    assert m is not None and m.tag == "all"


def test_lax_disabled_by_default():
    assert parse("rag tokens", ["rag:", "/rag"]) is None


def test_lax_enabled():
    m = parse("rag tokens", ["rag:", "/rag"], lax=True)
    assert m is not None and m.query == "tokens"


def test_non_trigger_returns_none():
    assert parse("how do I write a regex?", ["rag:", "/rag"]) is None


def test_leading_whitespace():
    m = parse("   rag: tokens", ["rag:", "/rag"])
    assert m is not None and m.query == "tokens"


def test_empty_query_returns_none():
    assert parse("rag: ", ["rag:", "/rag"]) is None


def test_case_insensitive():
    m = parse("RAG: tokens", ["rag:", "/rag"])
    assert m is not None and m.query == "tokens"
