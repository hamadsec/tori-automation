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
    import os

    from . import browser, listing

    if args.desc_file:
        if not os.path.exists(args.desc_file):
            print(f"description file not found: {args.desc_file}")
            return 2
        desc = open(args.desc_file, encoding="utf-8").read()
    else:
        desc = args.desc or ""
    images = [os.path.abspath(os.path.expanduser(p)) for p in args.images]
    missing = [p for p in images if not os.path.exists(p)]
    if missing:
        print("image not found: " + ", ".join(missing))
        return 2

    item = listing.Listing(
        title=args.title,
        price=args.price,
        description=desc,
        images=images,
        postcode=args.postcode,
        condition=args.condition,
        material=args.material,
    )
    if not browser.cdp.is_running():
        print("Nothing is listening on the CDP port yet.\n")
        _cmd_browser(args)
        return 0
    try:
        url = asyncio.run(listing.create(item, dry_run=args.dry_run))
    except RuntimeError as e:
        print(f"\nCould not fill the form: {e}")
        if "login" in str(e).lower() or "create" in str(e).lower():
            print("\nMost likely you are not logged in to Tori in the automation "
                  "window.\nOpen it, log in (email one-time code), then re-run. "
                  "`python -m tori.cli doctor` tells you which.")
        return 1
    print("\nended at:", url)
    if args.dry_run:
        print("DRY RUN — form filled, not submitted.")
    else:
        print("Next steps (delivery / package / publish) are manual for now — "
              "they are still open in the browser, and the description usually "
              "needs typing by hand first. See docs/LIMITATIONS.md.")


def _login_state() -> str:
    """Probe the open tori.fi tab for a logged-in marker. 'in' | 'out' | 'unknown'."""
    import asyncio

    from . import cdp

    probe = r"""
    (() => {
      const tb = document.querySelector('finn-topbar');
      const root = tb && tb.shadowRoot ? tb.shadowRoot : document;
      const hrefs = [...root.querySelectorAll('a')].map(a => a.getAttribute('href') || '');
      if (hrefs.some(h => h.includes('/my-page'))) return 'in';
      if (hrefs.some(h => h.includes('/auth/login'))) return 'out';
      return 'unknown';
    })()
    """
    try:
        ws, _ = cdp.page_target(port=cdp.default_port())
    except Exception:
        return "unknown"

    async def run():
        async with cdp.CDP(ws) as c:
            return await c.eval(probe)

    try:
        return asyncio.run(run()) or "unknown"
    except Exception:
        return "unknown"


def _cmd_doctor(args):
    """One-shot environment check for a new user."""
    import os
    import sys

    from . import browser, cdp

    ok = True

    def line(label, good, detail="", fatal=True):
        nonlocal ok
        print(("  ok   " if good else " FAIL  ") + label + ((" — " + detail) if detail else ""))
        if not good and fatal:
            ok = False

    print("Environment")
    line("python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0])
    try:
        import websockets
        line("websockets importable", True, getattr(websockets, "__version__", ""))
    except Exception as e:
        line("websockets importable", False, f"{e} — pip install -r requirements.txt")

    print("\nChrome")
    try:
        line("chrome executable found", True, browser.chrome_path())
    except Exception as e:
        line("chrome executable found", False, str(e))

    prof = browser.profile_dir()
    print("\nConnection")
    listening = cdp.is_running()
    line(f"CDP listening on 127.0.0.1:{cdp.default_port()}", listening,
         "" if listening else "run: python -m tori.cli browser")
    line("profile directory", os.path.isdir(prof), prof, fatal=False)

    if listening:
        pages = cdp.targets()
        line("page targets", bool(pages), f"{len(pages)} open")
        tori = [t for t in pages if "tori.fi" in (t.get("url") or "")]
        line("a tori.fi tab is open", bool(tori))
        if tori:
            state = _login_state()
            if state == "in":
                line("logged in to Tori", True)
            elif state == "out":
                line("logged in to Tori", False,
                     "log in in that window (email one-time code)")
            else:
                line("logged in to Tori", True,
                     "could not tell — open a tori.fi page in that window and re-run",
                     fatal=False)

    print()
    print("All good — try:" if ok else "Fix the FAIL lines above, then re-run.")
    if ok:
        print('  python -m tori.cli search "kenkäteline" --near "Kallio, Helsinki, Finland"')
        print("  python -m tori.cli create --title ... --price ... --dry-run")
    return 0 if ok else 1


def _cmd_browser(args):
    from . import browser

    if browser.cdp.is_running():
        print(f"already listening on port {browser.cdp.default_port()} — profile {browser.profile_dir()}")
        return 0
    print("profile:", browser.launch())
    print("\nLog in to Tori once in that window (it emails you a one-time code).")
    print("The session persists, so this only needs doing once.")
    print("Then check everything with: python -m tori.cli doctor")
    return 0


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

    d = sub.add_parser("doctor", help="check your environment and connection")
    d.set_defaults(func=_cmd_doctor)

    t = sub.add_parser("targets", help="list CDP page targets")
    t.set_defaults(func=_cmd_targets)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
