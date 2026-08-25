"""Shared dataclasses for zameen-mcp.

Exact field contract from CONTRACTS.md §DATA CONTRACT. models.py imports
nothing from this package, so it is safe for every other module to depend on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Listing:
    """One property listing card (or full listing, after detail enrichment)."""

    listing_id: str
    title: str
    url: str
    price_text: str = ""
    price_pkr: Optional[int] = None
    location: str = ""
    beds: Optional[int] = None
    baths: Optional[int] = None
    area_text: Optional[str] = None
    area_value: Optional[float] = None
    area_unit: Optional[str] = None
    property_type: str = ""
    purpose: str = ""
    verified: bool = False
    agent_tier: str = ""
    promoted: bool = False
    added_text: str = ""
    image_url: str = ""

    def to_dict(self) -> dict:
        """JSON-safe dict of every field (dataclasses.asdict)."""
        return asdict(self)


@dataclass
class SearchResult:
    """One page of parsed search results."""

    total_results: Optional[int] = None
    listings: List[Listing] = field(default_factory=list)
    page: int = 1
    next_page_url: Optional[str] = None

    def to_dict(self) -> dict:
        """JSON-safe dict with listings serialized."""
        return {
            "total_results": self.total_results,
            "listings": [l.to_dict() for l in self.listings],
            "page": self.page,
            "next_page_url": self.next_page_url,
        }
