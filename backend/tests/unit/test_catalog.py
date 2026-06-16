from __future__ import annotations

import pytest

from handoff.tools.catalog import (
    check_sanctions,
    lookup_company,
    name_similarity,
    normalize_name,
    search_news,
)


def test_normalize_strips_legal_suffixes_and_accents() -> None:
    assert normalize_name("Quantum Ledger OÜ") == "quantum ledger"
    assert normalize_name("Meridian Pharma S.A.") == "meridian pharma"


@pytest.mark.parametrize(
    ("left", "right", "minimum"),
    [("Corvane Trading FZE", "corvane trading", 1.0), ("Wei Ming Tan", "Tan Wei Ming", 1.0)],
)
def test_similarity_is_order_and_suffix_insensitive(left: str, right: str, minimum: float) -> None:
    assert name_similarity(left, right) >= minimum


def test_exact_sdn_name_is_a_match() -> None:
    result = check_sanctions("Marek Dravik", "person")
    assert result.result == "match"
    assert result.matches[0].entry_id == "SDN-48211"


def test_transliteration_variant_is_only_a_potential_match() -> None:
    result = check_sanctions("Dmitri Volkonsky", "person")
    assert result.result == "potential_match"
    assert 0.82 <= result.matches[0].score < 0.97


def test_entity_kind_is_respected() -> None:
    assert check_sanctions("Marek Dravik", "company").result == "clear"


def test_shared_trading_name_is_ambiguous_until_pinned_by_number() -> None:
    ambiguous = lookup_company("Bluefin Analytics", "GB")
    assert ambiguous.ambiguous
    assert len(ambiguous.matches) == 2
    pinned = lookup_company("Bluefin Analytics", registration_number="11290877")
    assert [m.legal_name for m in pinned.matches] == ["Bluefin Analytics Ltd"]


def test_country_filter_excludes_other_jurisdictions() -> None:
    assert lookup_company("Northwind Logistics", "US").matches == []


def test_adverse_search_filters_by_keywords_within_company() -> None:
    general = search_news("Helios Components Ltd")
    adverse = search_news("breach investigation", company="Helios Components Ltd")
    assert general.total == 3
    assert {item.id for item in adverse.items} == {"news-2001", "news-2002"}
    assert [i.published_on for i in general.items] == sorted(
        (i.published_on for i in general.items), reverse=True
    )
