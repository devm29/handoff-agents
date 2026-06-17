"""MCP server exposing the due-diligence tools over fixture data.

Run standalone with `python -m handoff.tools.server` (stdio) or
`handoff mcp-tools --transport http` for Streamable HTTP.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from handoff.tools.catalog import (
    NewsSearchResult,
    RegistryLookupResult,
    SanctionsCheckResult,
    check_sanctions,
    lookup_company,
    search_news,
)

SERVER_NAME = "handoff-due-diligence"


def build_server() -> MCPServer:
    server: MCPServer = MCPServer(
        name=SERVER_NAME,
        log_level="WARNING",
        instructions="Synthetic company registry, sanctions lists and news archive for vendor due diligence.",
    )

    @server.tool(
        name="company_registry_lookup",
        description=(
            "Look up a company in the corporate registry. Returns registration details, status and "
            "beneficial owners. Several matches means the name is ambiguous: call again with "
            "registration_number to pin the right entity."
        ),
    )
    def company_registry_lookup(
        name: Annotated[str, Field(description="Company name as given by the requester")],
        country: Annotated[str | None, Field(description="ISO 3166-1 alpha-2 jurisdiction filter")] = None,
        registration_number: Annotated[str | None, Field(description="Exact registry number")] = None,
    ) -> RegistryLookupResult:
        return lookup_company(name, country, registration_number)

    @server.tool(
        name="sanctions_check",
        description=(
            "Screen a person or company against OFAC SDN, EU, UK and UN consolidated lists. "
            "Uses fuzzy name matching and reports clear, potential_match or match."
        ),
    )
    def sanctions_check(
        name: Annotated[str, Field(description="Full name of the person or company")],
        kind: Annotated[Literal["person", "company"], Field(description="Entity type")],
    ) -> SanctionsCheckResult:
        return check_sanctions(name, kind)

    @server.tool(
        name="news_search",
        description=(
            "Search the news archive. Pass only `query` with the company name for general coverage, or "
            "`company` plus keyword `query` to look for adverse media about that company."
        ),
    )
    def news_search(
        query: Annotated[str, Field(description="Company name or keywords")],
        company: Annotated[str | None, Field(description="Restrict results to this company")] = None,
        limit: Annotated[int, Field(ge=1, le=25)] = 10,
    ) -> NewsSearchResult:
        return search_news(query, company, limit)

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
