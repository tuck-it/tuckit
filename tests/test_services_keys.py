"""org key 파생/검증 — DB를 타지 않는 순수 함수라 django_db 마크가 없다."""

import pytest

from tuckit.core.services.exceptions import InvalidValue
from tuckit.core.services.keys import derive_key, unique_key, validate_key


@pytest.mark.parametrize(
    "slug,expected",
    [
        ("tuckit-projects", "TP"),      # 2단어 → 각 단어 첫 글자
        ("tuckit", "TUC"),              # 1단어 → 앞 3글자
        ("a-b-c-d-e", "ABCD"),          # 최대 4단어까지만
        ("go", "GO"),                   # 최소 길이 slug
        ("1abc", "ABC"),                # 숫자로 시작 → 선행 비알파벳 제거
        ("1-2-3", "ORG"),               # 남는 게 없으면 폴백
    ],
)
def test_derive_key(slug, expected):
    assert derive_key(slug) == expected


def test_unique_key_returns_base_when_free():
    assert unique_key("TP", []) == "TP"


def test_unique_key_appends_suffix_on_collision():
    assert unique_key("TP", ["TP"]) == "TP2"
    assert unique_key("TP", ["TP", "TP2"]) == "TP3"


def test_unique_key_truncates_stem_instead_of_overflowing_max():
    """6글자가 상한이므로 접미를 붙일 자리를 밑동에서 잘라낸다."""
    assert unique_key("ABCDEF", ["ABCDEF"]) == "ABCDE2"


def test_unique_key_is_case_insensitive_about_taken():
    assert unique_key("TP", ["tp"]) == "TP2"


def test_validate_key_normalises_to_upper():
    assert validate_key(" tuc ") == "TUC"


@pytest.mark.parametrize("raw", ["", "T", "ABCDEFG", "1AB", "A B", "A-B", "A_B"])
def test_validate_key_rejects(raw):
    with pytest.raises(InvalidValue):
        validate_key(raw)
