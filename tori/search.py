"""Search Tori.fi and rank results by real distance from a pickup point.

Tori's search pages are server-rendered, so plain HTTP works and no browser is
needed. Cards carry JSON-LD ``ListItem`` entries; coordinates are **not** in the
search HTML, so each detail page has to be fetched for its own location.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
SEARCH = "https://www.tori.fi/recommerce/forsale/search?q={q}&page={page}"
# Coordinates are only exposed inside the static map URL on the item page.
GEO_RE = re.compile(r"staticmap\?lat=(-?\d+\.\d+)\\?u0026lng=(-?\d+\.\d+)")
# The location object is embedded as a *double-escaped* JS string, so the item
# page's JSON has \\"postalCode\\" rather than plain quotes — flatten first.
ESCAPED_QUOTE_RE = re.compile(r'\\+"')
POSTAL_RE = re.compile(r'"postalCode"\s*:\s*"(\d{5})"')
POSTALNAME_RE = re.compile(r'"postalName"\s*:\s*"([^"]{2,80})"')
CONDITION_RE = re.compile(r'"id"\s*:\s*"condition".{0,200}?"value"\s*:\s*"([^"]{1,40})"')
JSONLD_RE = re.compile(r'"ListItem"')
RESERVED_MARK = "VARATTU"


def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def haversine(a, b) -> float:
    """Great-circle distance in km between two (lat, lon) pairs."""
    R = 6371.0088
    la1, lo1 = map(math.radians, a)
    la2, lo2 = map(math.radians, b)
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def geocode(address: str):
    """Address → (lat, lon) via Nominatim. Respect their usage policy (1 req/s)."""
    url = ("https://nominatim.openstreetmap.org/search?"
           + urllib.parse.urlencode({"q": address, "format": "json", "limit": 1}))
    req = urllib.request.Request(url, headers={"User-Agent": "tori-automation/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        hits = json.loads(r.read().decode())
    if not hits:
        raise RuntimeError(f"could not geocode: {address!r}")
    return float(hits[0]["lat"]), float(hits[0]["lon"])


def _items_from_page(html: str):
    """Extract listing cards from the embedded JSON-LD blocks.

    Tori nests the real results under ``mainEntity.itemListElement`` (an
    ``ItemList``); the top-level ``itemListElement`` only carries breadcrumbs.
    """
    out = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                         html, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        blobs = data if isinstance(data, list) else [data]
        for blob in blobs:
            lists = []
            top = blob.get("itemListElement")
            if isinstance(top, list):
                lists.append(top)
            main = blob.get("mainEntity")
            for mn in (main if isinstance(main, list) else [main]):
                if isinstance(mn, dict) and isinstance(mn.get("itemListElement"), list):
                    lists.append(mn["itemListElement"])
            for entries in lists:
                for entry in entries:
                    it = entry.get("item") if isinstance(entry, dict) else None
                    if not isinstance(it, dict) or it.get("@type") not in ("Product", "Offer", None):
                        continue
                    off = it.get("offers") or {}
                    if isinstance(off, list):
                        off = off[0] if off else {}
                    img = it.get("image")
                    out.append({
                        "url": it.get("url") or entry.get("url"),
                        "name": (it.get("name") or entry.get("name") or "").strip(),
                        "description": (it.get("description") or "").strip(),
                        "price": off.get("price"),
                        "image": img if isinstance(img, str) else None,
                    })
    seen, uniq = set(), []
    for it in out:
        if it["url"] and it["url"] not in seen:
            seen.add(it["url"])
            uniq.append(it)
    return uniq


def page_count(html: str) -> int:
    pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
    return max(pages) if pages else 1


def search(query: str, pages: int | None = None, workers: int = 8):
    """Harvest search results. Search in Finnish — inventory is Finnish-indexed."""
    q = urllib.parse.quote(query)
    first = _get(SEARCH.format(q=q, page=1))
    total = pages or page_count(first)
    items = _items_from_page(first)
    if total > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for html in ex.map(lambda p: _get(SEARCH.format(q=q, page=p)),
                               range(2, total + 1)):
                items.extend(_items_from_page(html))
    seen, uniq = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            uniq.append(it)
    return uniq


def enrich(item: dict) -> dict:
    """Fetch one item page for its own coordinates, postal area and reserved flag."""
    try:
        html = _get(item["url"])
    except Exception as e:
        item["error"] = str(e)
        return item
    g = GEO_RE.search(html)
    if g:
        item["lat"], item["lon"] = float(g.group(1)), float(g.group(2))
    flat = ESCAPED_QUOTE_RE.sub('"', html)
    p = POSTAL_RE.search(flat)
    n = POSTALNAME_RE.search(flat)
    c = CONDITION_RE.search(flat)
    item["postal_code"] = p.group(1) if p else None
    item["postal_name"] = n.group(1) if n else None
    item["condition"] = c.group(1) if c else None
    item["reserved"] = RESERVED_MARK in html
    item["shipping"] = ("Osta heti" in html and "Toimitus alkaen" in html)
    return item


def shortlist(query: str, origin, radius_km: float = 5.0,
              max_price: float | None = None, pages: int | None = None,
              workers: int = 10):
    """Search, enrich with real coordinates, then rank by distance.

    ``origin`` is ``(lat, lon)`` — geocode your address once and pass it in.
    Items outside ``radius_km`` are kept but marked ``excluded`` rather than
    dropped, so a shortlist can always be audited.
    """
    items = search(query, pages=pages)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        items = list(ex.map(enrich, items))
    rows = []
    for it in items:
        price = None
        try:
            price = float(it.get("price")) if it.get("price") is not None else None
        except (TypeError, ValueError):
            pass
        it["price_num"] = price
        if it.get("lat") is not None:
            it["distance_km"] = round(haversine(origin, (it["lat"], it["lon"])), 2)
        else:
            it["distance_km"] = None
        it["excluded"] = bool(
            (it["distance_km"] is not None and it["distance_km"] > radius_km)
            or (max_price is not None and price is not None and price > max_price)
            or it.get("reserved")
        )
        rows.append(it)
    rows.sort(key=lambda r: (r["excluded"], r["distance_km"] if r["distance_km"] is not None else 9e9,
                             r["price_num"] if r["price_num"] is not None else 9e9))
    return rows
