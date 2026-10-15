"""Tori.fi automation toolkit — search, shortlist and create listings.

Selling (scripted, over CDP):
    from tori import browser, listing
    browser.ensure_running()                     # dedicated Chrome + debug port
    asyncio.run(listing.create(listing.Listing(...)))

Buying (no browser needed):
    from tori import search
    search.shortlist("kenkäteline", origin=(60.16, 24.74), radius_km=5)
"""

__version__ = "0.1.0"

from . import browser, cdp, listing, page, search  # noqa: F401

__all__ = ["browser", "cdp", "listing", "page", "search", "__version__"]
