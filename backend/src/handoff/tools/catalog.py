"""Fixture-backed due-diligence data sources.

Pure functions over synthetic data, so the MCP server stays a thin transport layer and
the matching logic can be unit tested without spinning up a server.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter

from handoff.agents.schemas import BeneficialOwner

FIXTURES = Path(__file__).parent / "fixtures"

MATCH_THRESHOLD = 0.97
POTENTIAL_MATCH_THRESHOLD = 0.82
NAME_MATCH_THRESHOLD = 0.85

_LEGAL_SUFFIXES = frozenset(
    {"ltd", "llc", "inc", "gmbh", "sa", "ou", "pte", "fze", "plc", "jsc", "lp", "co", "corp", "limited"}
)


class CompanyRecord(BaseModel):
    registration_number: str
    legal_name: str
    aliases: list[str] = Field(default_factory=list)
    jurisdiction: str
    status: Literal["active", "dissolved", "suspended"]
    incorporated_on: date
    industry: str
    address: str
    website: str | None
    beneficial_owners: list[BeneficialOwner]


class SanctionsEntry(BaseModel):
    entry_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    kind: Literal["person", "company"]
    list_name: str
    program: str
    listed_on: date
    country: str


class NewsRecord(BaseModel):
    id: str
    company: str
    published_on: date
    headline: str
    summary: str
    source: str
    sentiment: float
    topics: list[str]


class RegistryLookupResult(BaseModel):
    query: str
    ambiguous: bool
    matches: list[CompanyRecord]


class SanctionsMatch(BaseModel):
    entry_id: str
    matched_name: str
    list_name: str
    program: str
    score: float


class SanctionsCheckResult(BaseModel):
    name: str
    kind: Literal["person", "company"]
    result: Literal["clear", "potential_match", "match"]
    lists_checked: list[str]
    matches: list[SanctionsMatch]


class NewsSearchResult(BaseModel):
    query: str
    total: int
    items: list[NewsRecord]


def normalize_name(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tokens = re.sub(r"[^a-z0-9 ]", " ", ascii_name.lower()).split()
    return " ".join(t for t in tokens if t not in _LEGAL_SUFFIXES and len(t) > 1)


def name_similarity(a: str, b: str) -> float:
    left, right = normalize_name(a), normalize_name(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    direct = SequenceMatcher(None, left, right).ratio()
    sorted_tokens = SequenceMatcher(
        None, " ".join(sorted(left.split())), " ".join(sorted(right.split()))
    ).ratio()
    return round(max(direct, sorted_tokens), 3)


@lru_cache(maxsize=1)
def companies() -> tuple[CompanyRecord, ...]:
    return tuple(TypeAdapter(list[CompanyRecord]).validate_json((FIXTURES / "companies.json").read_bytes()))


@lru_cache(maxsize=1)
def sanctions_list() -> tuple[SanctionsEntry, ...]:
    return tuple(TypeAdapter(list[SanctionsEntry]).validate_json((FIXTURES / "sanctions.json").read_bytes()))


@lru_cache(maxsize=1)
def news_archive() -> tuple[NewsRecord, ...]:
    return tuple(TypeAdapter(list[NewsRecord]).validate_json((FIXTURES / "news.json").read_bytes()))


def lookup_company(
    name: str, country: str | None = None, registration_number: str | None = None
) -> RegistryLookupResult:
    if registration_number:
        wanted = registration_number.replace(" ", "").upper()
        hits = [c for c in companies() if c.registration_number.replace(" ", "").upper() == wanted]
        return RegistryLookupResult(query=registration_number, ambiguous=False, matches=hits)

    scored: list[tuple[float, CompanyRecord]] = []
    for company in companies():
        if country and company.jurisdiction != country.upper():
            continue
        score = max(name_similarity(name, n) for n in (company.legal_name, *company.aliases))
        if score >= NAME_MATCH_THRESHOLD:
            scored.append((score, company))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    matches = [c for _, c in scored]
    return RegistryLookupResult(query=name, ambiguous=len(matches) > 1, matches=matches)


def check_sanctions(name: str, kind: Literal["person", "company"]) -> SanctionsCheckResult:
    matches: list[SanctionsMatch] = []
    for entry in sanctions_list():
        if entry.kind != kind:
            continue
        score = max(name_similarity(name, n) for n in (entry.name, *entry.aliases))
        if score >= POTENTIAL_MATCH_THRESHOLD:
            matches.append(
                SanctionsMatch(
                    entry_id=entry.entry_id,
                    matched_name=entry.name,
                    list_name=entry.list_name,
                    program=entry.program,
                    score=score,
                )
            )
    matches.sort(key=lambda m: m.score, reverse=True)
    if any(m.score >= MATCH_THRESHOLD for m in matches):
        result: Literal["clear", "potential_match", "match"] = "match"
    elif matches:
        result = "potential_match"
    else:
        result = "clear"
    lists = sorted({e.list_name for e in sanctions_list()})
    return SanctionsCheckResult(name=name, kind=kind, result=result, lists_checked=lists, matches=matches)


def search_news(query: str, company: str | None = None, limit: int = 10) -> NewsSearchResult:
    terms = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 2]
    items: list[NewsRecord] = []
    for record in news_archive():
        if company is not None:
            if name_similarity(company, record.company) < NAME_MATCH_THRESHOLD:
                continue
            haystack = " ".join([record.headline, record.summary, *record.topics]).lower()
            if terms and not any(term in haystack for term in terms):
                continue
        elif name_similarity(query, record.company) < NAME_MATCH_THRESHOLD:
            continue
        items.append(record)
    items.sort(key=lambda r: r.published_on, reverse=True)
    return NewsSearchResult(query=query, total=len(items), items=items[:limit])
