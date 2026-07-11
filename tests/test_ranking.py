from tuckit.core.ranking import rank_between


def test_first_key_when_empty():
    key = rank_between(None, None)
    assert isinstance(key, str) and key


def test_append_produces_increasing_keys():
    a = rank_between(None, None)
    b = rank_between(a, None)
    c = rank_between(b, None)
    assert a < b < c


def test_prepend_produces_decreasing_keys():
    a = rank_between(None, None)
    before = rank_between(None, a)
    assert before < a


def test_between_two_keys_sorts_in_the_middle():
    a = rank_between(None, None)
    c = rank_between(a, None)
    b = rank_between(a, c)
    assert a < b < c
