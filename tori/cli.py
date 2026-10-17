"""Command line entry points.

    python -m tori.cli search "kenkäteline" --near "Kallio, Helsinki, Finland"
    python -m tori.cli create --title "..." --price 25 --desc-file d.txt \
        --images a.jpg b.jpg --postcode 00100 [--dry-run]
    python -m tori.cli browser            # launch the dedicated Chrome
    python -m tori.cli doctor             # is the environment + login OK?
    python -m tori.cli categories "Koti ja sisustus" "Valaisimet"
    python -m tori.cli screenshot --out form.png
    python -m tori.cli fix-price  --ad <adId> --price 50
    python -m tori.cli fix-fields --ad <adId> --postcode 02230 --height 45

`create` publishes unless `--dry-run` is passed. `fix-price` and `fix-fields`
patch Tori's own save request, then read the stored ad back.
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
        category=tuple(c.strip() for c in args.category.split(",")) if args.category
                 else listing.DEFAULT_CATEGORY,
        condition=args.condition,
        material=args.material,
        dimensions={k: v for k, v in (("Korkeus", args.height),
                                      ("Leveys", args.width),
                                      ("Syvyys", args.depth)) if v is not None},
    )
    if not browser.cdp.is_running():
        print("Nothing is listening on the CDP port yet.\n")
        _cmd_browser(args)
        return 0
    try:
        url = asyncio.run(listing.create(item, dry_run=args.dry_run))
    except RuntimeError as e:
        msg = str(e)
        print(f"\nCould not complete the listing: {msg}")
        if "not logged in" in msg or "/auth" in msg or "login" in msg:
            print("\nYou are not logged in to Tori in the automation window.\n"
                  "Open it, log in (email one-time code), then re-run. "
                  "`python -m tori.cli doctor` tells you which.")
        return 1
    print("\nended at:", url)
    if args.dry_run:
        print("DRY RUN — form filled, not submitted.")
    elif "/ad-receipt" in url or "/my-items" in url:
        ad_id = url.split("adId=")[1].split("&")[0] if "adId=" in url else ""
        print(f"PUBLISHED — ad {ad_id}." if ad_id else "PUBLISHED.")
        print("Tori shows it as Under review until they approve it. Confirm it "
              "is really there at https://www.tori.fi/my-items")
    else:
        print("Stopped before publishing — still on:", url)
        print("See docs/LIMITATIONS.md.")


def _login_state() -> str:
    """Probe the open tori.fi tab for a logged-in marker. 'in' | 'out' | 'unknown'."""
    import asyncio

    from . import cdp

    try:
        ws, target = cdp.page_target(port=cdp.default_port())
    except Exception:
        return "unknown"

    url = (target.get("url") or "").lower()
    # An auth-gated page can only be reached with a live session, and the
    # login host can only mean the opposite. Both beat guessing from markup.
    if "login.vend.fi" in url or "/auth/login" in url or "/authn/" in url:
        return "out"
    if any(p in url for p in ("/my-page", "/my-items", "/messages", "/recommerce/create")):
        return "in"

    probe = r"""
    (() => {
      const seen = new Set(); const hrefs = [];
      (function walk(root, depth) {
        if (depth > 6) return;
        let n; try { n = root.querySelectorAll('*'); } catch (e) { return; }
        for (const el of n) {
          if (el.shadowRoot && !seen.has(el)) { seen.add(el); walk(el.shadowRoot, depth + 1); }
          if (el.tagName === 'A') hrefs.push(el.getAttribute('href') || '');
        }
      })(document, 0);
      if (hrefs.some(h => h.includes('/my-page'))) return 'in';
      if (hrefs.some(h => h.includes('/auth/login'))) return 'out';
      const t = (document.body.innerText || '');
      if (/Kirjaudu/i.test(t)) return 'out';
      if (/Oma Tori/i.test(t)) return 'in';
      return 'unknown';
    })()
    """

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


async def _read_price(c) -> str:
    from . import page

    return await c.eval(page.wrap("""
      const nums = __all(e => e.tagName === 'INPUT' && e.type === 'number'
                          && e.getBoundingClientRect().width > 0);
      return nums.length ? nums[0].value : null;
    """))


def _cmd_fix_price(args):
    """Set the price on an existing ad by patching Tori's own save request."""
    import asyncio

    from . import cdp, listing, price

    ad = str(args.ad)
    if not cdp.is_running():
        print("Nothing is listening on the CDP port — run: python -m tori.cli browser")
        return 1

    async def run():
        ws, _ = cdp.page_target(port=cdp.default_port())
        async with cdp.CDP(ws) as c:
            await c.send("Runtime.enable")
            await c.send("DOM.enable")
            t = listing.ToriListing(c)
            await c.navigate(f"https://www.tori.fi/recommerce/create/{ad}?editMode=true", wait=10)
            print("before:", await _read_price(c))
            state = await price.patch_with(
                c, ad, args.price,
                click_step=lambda mode: t._click_once("Tallenna", mode))
            print("patched requests:", state["patched"])
            if not state["patched"]:
                print("no save request was intercepted — the ad was not changed")
                return 1
            await asyncio.sleep(2)
            # the edit funnel finishes with another Tallenna on the delivery step
            await t.click_until("Tallenna", "location.href.indexOf('/delivery/') < 0",
                                label="save delivery")
            await asyncio.sleep(3)
            await c.navigate(f"https://www.tori.fi/recommerce/create/{ad}?editMode=true", wait=10)
            print("after:", await _read_price(c))
        return 0

    return asyncio.run(run())



def _cmd_fix_fields(args):
    """Repair stored fields on an existing ad (location and/or dimensions).

    Why this exists: price is not the only field that can be silently wrong.
    Tori's own save payload (``PUT /recommerce/create/api/item/<ad>``) carries
    the postcode and the Korkeus/Leveys/Syvyys trio, so both are patched at the
    request level the same way the price is — the form's own state is not
    trusted, and a field written by ``Input.insertText`` can be dropped without
    any error. Note the *location* comes from the postcode field: an ad whose
    postcode never registered keeps the profile's default location, which looks
    right to the seller and wrong to every buyer.
    """
    import asyncio

    from . import cdp, listing, price

    ad = str(args.ad)
    if not cdp.is_running():
        print("Nothing is listening on the CDP port — run: python -m tori.cli browser")
        return 1

    extra = {}
    for label, value in (("height", args.height), ("width", args.width),
                         ("depth", args.depth)):
        if value is not None:
            extra[label] = value
    if args.postcode:
        address = {"postalcode": str(args.postcode), "country": "FI"}
        if args.postalname:
            address["postalname"] = args.postalname
        if args.lat:
            address["latitude"] = str(args.lat)
        if args.lon:
            address["longitude"] = str(args.lon)
        extra["address"] = address
    if not extra:
        print("nothing to fix — pass --postcode and/or --height/--width/--depth")
        return 2

    async def run():
        ws, _ = cdp.page_target(port=cdp.default_port())
        async with cdp.CDP(ws) as c:
            await c.send("Runtime.enable")
            await c.send("DOM.enable")
            t = listing.ToriListing(c)
            await c.navigate(
                f"https://www.tori.fi/recommerce/create/{ad}?editMode=true", wait=10)
            print("before:", await t.read_price(ad), "€;", extra)
            state = await price.patch_with(
                c, ad, None, click_step=lambda mode: t._click_once("Tallenna", mode),
                extra=extra)
            print("patched requests:", state["patched"])
            if not state["patched"]:
                print("no save request was intercepted — the ad was not changed")
                return 1
            await asyncio.sleep(2)
            # the edit funnel finishes with another Tallenna on the delivery step
            await t.click_until("Tallenna", "location.href.indexOf('/delivery/') < 0",
                                label="save delivery")
            await asyncio.sleep(3)
            r = await c.eval(
                "(async () => {"
                f" const r = await fetch('https://www.tori.fi/recommerce/create/api/item/{ad}',"
                " {credentials:'include', headers:{'Accept':'application/json'}});"
                " const j = await r.json(); const d = j.data || j;"
                " return {price: d.price, height: d.height, width: d.width,"
                "         depth: d.depth, address: d.address};"
                "})()", await_promise=True)
            print("after:", r)
        return 0

    return asyncio.run(run())


def _cmd_categories(args):
    """Print the create-form dropdowns (and label-addressable number fields).

    Tori's controls live inside shadow roots, so `document.querySelector` sees
    nothing; this opens the real form and prints what is actually there, which
    is how a category path gets discovered instead of guessed. Options are
    matched by visible text (exact first, then prefix), so a partial label like
    "Valaisimet" is enough.

    Note: opening the form creates a new **draft** ad at
    `/recommerce/create/<adId>`. Throwaway drafts are harmless — do not reuse
    their ids.
    """
    import asyncio

    from . import cdp, listing, page

    if not cdp.is_running():
        print("Nothing is listening on the CDP port — run: python -m tori.cli browser")
        return 1

    async def run():
        ws, _ = cdp.page_target(port=cdp.default_port())
        async with cdp.CDP(ws) as c:
            await c.send("Runtime.enable")
            await c.send("DOM.enable")
            t = listing.ToriListing(c)
            print("URL:", await t.open_form())
            for ch in args.choices:
                r = await t.set_select(ch, label=f"choose {ch}")
                await asyncio.sleep(3)   # the next combo exists only after this one
                if not (r or {}).get("ok"):
                    print("FAILED at", ch, r)
                    return 1
            sels = await c.eval(page.wrap("return __selects();")) or []
            for i, s in enumerate(sels):
                print(f"--- select {i} (value={s['value']}) ---")
                for o in s["options"]:
                    print("   ", o["t"])
            nums = await c.eval(page.wrap("return __numberFieldLabels();")) or []
            print("--- number fields (address by label) ---")
            for n in nums:
                print("   ", n or "(unlabelled)")
        return 0

    return asyncio.run(run())


def _cmd_screenshot(args):
    """Full-page PNG of the current Tori tab — for checking a --dry-run fill."""
    import asyncio
    import os

    from . import cdp

    if not cdp.is_running():
        print("Nothing is listening on the CDP port — run: python -m tori.cli browser")
        return 1
    out = os.path.abspath(os.path.expanduser(args.out))

    async def run():
        ws, _ = cdp.page_target(port=cdp.default_port())
        async with cdp.CDP(ws) as c:
            await c.send("Page.enable")
            path = await c.screenshot(out, full_page=True)
            print(path)
            print("tab:", await c.eval("location.href"))
        return 0

    return asyncio.run(run())


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
    c.add_argument("--category", default=None,
                   help='comma-separated path, e.g. "Piha ja remontointi,Piha ja puutarha,Kasvit ja istutus"')
    c.add_argument("--condition", default=None, help='e.g. "Hyvä"')
    c.add_argument("--material", default=None, help='e.g. "Nahka"')
    c.add_argument("--height", default=None, type=int,
                   help="Korkeus in cm — only categories that ask for dimensions")
    c.add_argument("--width", default=None, type=int, help="Leveys in cm")
    c.add_argument("--depth", default=None, type=int, help="Syvyys in cm")
    c.add_argument("--dry-run", action="store_true", help="fill but do not submit")
    c.set_defaults(func=_cmd_create)

    b = sub.add_parser("browser", help="launch the dedicated Chrome")
    b.set_defaults(func=_cmd_browser)

    d = sub.add_parser("doctor", help="check your environment and connection")
    d.set_defaults(func=_cmd_doctor)

    t = sub.add_parser("targets", help="list CDP page targets")
    t.set_defaults(func=_cmd_targets)

    cat = sub.add_parser("categories",
                         help="print the create-form dropdowns (and number-field labels)")
    cat.add_argument("choices", nargs="*",
                     help='category choices already made, e.g. "Koti ja sisustus" "Valaisimet"')
    cat.set_defaults(func=_cmd_categories)

    sh = sub.add_parser("screenshot", help="full-page PNG of the current Tori tab")
    sh.add_argument("--out", default="tori-form.png")
    sh.set_defaults(func=_cmd_screenshot)

    f = sub.add_parser("fix-price", help="set the price on an existing ad")
    f.add_argument("--ad", required=True, help="ad id")
    f.add_argument("--price", required=True, type=int, help="price in €")
    f.set_defaults(func=_cmd_fix_price)

    g = sub.add_parser("fix-fields",
                       help="repair stored fields (location, dimensions) on an existing ad")
    g.add_argument("--ad", required=True, help="ad id")
    g.add_argument("--postcode", default=None, help="new postcode (e.g. 02230)")
    g.add_argument("--postalname", default=None,
                   help='postal name as Tori prints it, e.g. "Espoo, Matinkylä, Uusimaa"')
    g.add_argument("--lat", default=None)
    g.add_argument("--lon", default=None)
    g.add_argument("--height", default=None, type=int, help="Korkeus in cm")
    g.add_argument("--width", default=None, type=int, help="Leveys in cm")
    g.add_argument("--depth", default=None, type=int, help="Syvyys in cm")
    g.set_defaults(func=_cmd_fix_fields)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
