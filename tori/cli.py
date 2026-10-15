"""Command line entry points.

    python -m tori.cli search "kenkäteline" --near "Kallio, Helsinki, Finland"
    python -m tori.cli create --title "..." --price 25 --desc-file d.txt \
        --images a.jpg b.jpg --postcode 00100 [--dry-run]
    python -m tori.cli browser            # launch the dedicated Chrome
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _cmd_search(args):
    from . import search

    origin = search.geocode(args.near) if args.near else (float(args.lat), float(args.lon))
    rows = search.shortlist(args.query, origin, radius_km=args.radius,
                            max_price=args.max_price, pages=args.pages)
    shown = [r for r in rows if not r["excluded"] or args.all]
    print(f"{len(rows)} results, {len(shown)} shown "
          f"(origin {origin[0]:.5f},{origin[1]:.5f}, radius {args.radius} km)\n")
    for i, r in enumerate(shown, 1):
        flag = "EXCLUDED" if r["excluded"] else "        "
        dist = f"{r['distance_km']:>6.2f} km" if r["distance_km"] is not None else "     ? km"
        price = f"{r['price_num']:.0f} €" if r["price_num"] is not None else "  ? €"
        area = r.get("postal_name") or r.get("postal_code") or "?"
        print(f"{i:>3}. {flag} {dist} {price:>8}  {area}")
        print(f"     {r['name'][:78]}")
        print(f"     {r['url']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(shown, f, ensure_ascii=False, indent=1)
        print(f"\nwrote {args.json}")


def _cmd_create(args):
    from . import browser, listing

    for p in args.images:
        pass
    desc = open(args.desc_file, encoding="utf-8").read() if args.desc_file else args.desc
    item = listing.Listing(
        title=args.title,
        price=args.price,
        description=desc or "",
        images=args.images,
        postcode=args.postcode,
        condition=args.condition,
        material=args.material,
    )
    if not browser.cdp.is_running():
        browser.launch()
        print("launched the dedicated Chrome — log in to Tori if you have not already")
        return
    url = asyncio.run(listing.create(item, dry_run=args.dry_run))
    print("\nended at:", url)
    if args.dry_run:
        print("DRY RUN — form filled, not submitted.")


def _cmd_browser(args):
    from . import browser

    if browser.cdp.is_running():
        print("already listening on port", browser.cdp.DEFAULT_PORT)
        return
    print("profile:", browser.launch())
    print("log in to Tori once in that window; the session then persists.")


def _cmd_targets(args):
    from . import cdp

    for t in cdp.targets():
        print(t.get("title", "")[:60], "|", (t.get("url") or "")[:80])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tori", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search and rank by distance")
    s.add_argument("query", help="search terms (in Finnish)")
    s.add_argument("--near", help="address to geocode as the origin")
    s.add_argument("--lat", default="60.1583")
    s.add_argument("--lon", default="24.7380")
    s.add_argument("--radius", type=float, default=5.0, help="km")
    s.add_argument("--max-price", type=float, default=None)
    s.add_argument("--pages", type=int, default=None)
    s.add_argument("--all", action="store_true", help="also show excluded rows")
    s.add_argument("--json", help="write the result set here")
    s.set_defaults(func=_cmd_search)

    c = sub.add_parser("create", help="fill and submit a listing")
    c.add_argument("--title", required=True)
    c.add_argument("--price", required=True)
    c.add_argument("--desc")
    c.add_argument("--desc-file")
    c.add_argument("--images", nargs="*", default=[])
    c.add_argument("--postcode", default="00100")
    c.add_argument("--condition", default=None, help='e.g. "Hyvä"')
    c.add_argument("--material", default=None, help='e.g. "Nahka"')
    c.add_argument("--dry-run", action="store_true", help="fill but do not submit")
    c.set_defaults(func=_cmd_create)

    b = sub.add_parser("browser", help="launch the dedicated Chrome")
    b.set_defaults(func=_cmd_browser)

    t = sub.add_parser("targets", help="list CDP page targets")
    t.set_defaults(func=_cmd_targets)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
