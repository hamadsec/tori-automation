# tori-automation

Scripted automation for **[Tori.fi](https://www.tori.fi)** — Finland's main
second-hand marketplace. Two things:

- **Search & shortlist** buyers' listings and rank them by *real* distance from
  your address (Tori's own radius filter is city-granular, and the search HTML
  carries no coordinates at all).
- **Create a listing** by driving the create form in a real logged-in Chrome
  over the Chrome DevTools Protocol — no Selenium, no Playwright, no clicking
  pixels, and no native file dialogs.

Both are plain Python. The only third-party dependency is `websockets`.

## Status — read this first

| Area | State |
|---|---|
| Search harvest (JSON-LD) | ✅ works, paginated |
| Item coordinates, district, condition, reserved flag, shipping flag | ✅ works |
| Distance ranking with audit trail | ✅ works |
| Open the create form, pick category chain / condition / material | ✅ works |
| Title, **description**, postcode | ✅ works — postcode by its label, and it is what sets the ad's location |
| **Korkeus / Leveys / Syvyys** (only on categories that ask) | ✅ works — `--height/--width/--depth`, addressed by label |
| **Price** | ✅ works and is verified after publishing — written into both the form field and Tori's own save request (`tori/price.py`), then read back from Tori's API. Price alone fails *silently* (an ad with no price goes live at 0 €), so never trust the form |
| **Photo upload** (bypasses the file dialog) | ✅ works |
| Steps after *Jatka* (delivery, package, **publish**) | ✅ scripted — one command publishes |
| Deleting an ad | ❌ not scripted — needs a manual tap |

**One command takes a listing from an empty form to a live ad.** The price is
written twice — into the field and into the save request Tori sends (see
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) §0) — and then read back from Tori's
API, because a price that did not register publishes as 0 € with no error at all.
The price of an ad that already exists can be corrected with:

```bash
python -m tori.cli fix-price --ad <adId> --price 50
```

The **postcode and the dimension fields can fail the same silent way**, and on
categories that ask for `Korkeus`/`Leveys`/`Syvyys` they used to be written into
the wrong boxes entirely (price → Korkeus, postcode → Leveys), which left the ad
in the seller's *profile* location with nonsense measurements. Numeric fields are
now addressed by their visible label, and an ad that is already wrong can be
repaired:

```bash
python -m tori.cli fix-fields --ad <adId> --postcode 02230 \
    --postalname "Espoo, Matinkylä, Uusimaa" --lat 60.155226521 --lon 24.746018667 \
    --height 45 --width 92 --depth 55
```

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) §0b. Always read the stored ad
back — the form is not evidence.


## Install

```bash
git clone https://github.com/hamadsec/tori-automation
cd tori-automation
pip install -r requirements.txt        # just: websockets
```

Python 3.10+. No API keys, no accounts beyond your own Tori login.

## One-time browser setup

Chrome changed two things that break the obvious approach, so read this before
filing a bug:

1. **`--remote-debugging-port` is silently ignored on the default Chrome
   profile** (Chrome 136+, a security default). The port only opens when you
   pass an explicit non-default `--user-data-dir`.
2. **Copying your existing Chrome profile does not carry the login.** Chrome's
   app-bound cookie encryption invalidates cookies on a profile copy — you land
   on the login page.

So the tool uses its own Chrome profile and you log into Tori in it **once**:

```bash
python -m tori.cli browser
```

That launches Chrome with the debug port on `127.0.0.1:9222` and its own profile
(`~/.tori-automation/chrome`, override with `$TORI_PROFILE`). Log into Tori in
that window — the login is an email one-time code, so it needs a human. The
session then persists across runs.

Verify the connection at any time:

```bash
python -m tori.cli targets
```

## Usage — searching

Search in **Finnish**. Tori's inventory is indexed in Finnish even when your
browser auto-translates the page.

```bash
python -m tori.cli search "kenkäteline" --near "Kallio, Helsinki, Finland" --radius 5
```

```
53 results, 1 shown (origin 60.18413,24.95021, radius 5.0 km)

  1.            3.34 km     20 €  Helsinki, Kallio, Uusimaa
     Kenkäteline
     https://www.tori.fi/recommerce/forsale/item/42312162
```

Options: `--radius` (km), `--max-price`, `--pages`, `--all` (include excluded
rows), `--json out.json`, or pass `--lat/--lon` instead of `--near`.

As a library:

```python
from tori import search

origin = search.geocode("Kallio, Helsinki, Finland")   # geocode once, reuse
rows = search.shortlist("kenkäteline", origin, radius_km=5, max_price=50)

for r in rows:
    if not r["excluded"]:
        print(r["distance_km"], "km", r["price_num"], "€", r["postal_name"])
        print("  ", r["url"])
```

Out-of-radius and reserved items are kept and flagged `excluded` rather than
dropped, so a shortlist can always be audited. Marketplace map pins are
neighbourhood-level: treat distances as accurate to a few hundred metres.

## Usage — creating a listing

```bash
python -m tori.cli create \
    --title "Nahkainen reppu, ruskea nahka, nyöri- ja solkikiinnitys" \
    --price 25 \
    --desc-file description.txt \
    --images photo1.jpg photo2.jpg \
    --category "Vaatteet, kosmetiikka ja asusteet,Laukut ja lompakot,Reput" \
    --postcode 00100 --condition "Hyvä" --material "Nahka" \
    --dry-run
```

`--dry-run` fills the form and stops before submitting — **use it the first time
so you can look at the result**.

**Drop `--dry-run` and this command publishes.** It continues through the
delivery step (pickup only), picks the free **Basic** package, and publishes —
no manual clicks. On success it prints `PUBLISHED — ad <id>` (the ad shows as
*Under review* until Tori approves it) followed by a price read-back straight
from Tori's API:

```
  ok  price verified: ad 48604695 stores 15 €
```

If that line says `FAIL` instead, the printed `fix-price` command repairs it. A
changed URL is not proof of anything on its own — confirm the ad independently at
<https://www.tori.fi/my-items>.

Always pass `--category`. Without it every ad is filed under the default bag
category. The path is the three visible Finnish labels, comma-separated
(Osasto, Alaluokka, Tuoteryhmä) — e.g. for a houseplant:

```
--category "Piha ja remontointi,Piha ja puutarha,Kasvit ja istutus"
```

Do not guess a path: print the live tree, one level at a time, with

```bash
python -m tori.cli categories                                  # Osasto
python -m tori.cli categories "Koti ja sisustus"               # Alaluokka
python -m tori.cli categories "Koti ja sisustus" "Valaisimet"  # Tuoteryhmä + Kunto
```

It also lists the labelled number fields, which is how you find out whether the
category asks for `Korkeus/Leveys/Syvyys`. Each run opens a new draft ad —
harmless, but do not reuse those ids.

To look at a `--dry-run` fill before publishing, screenshot the form:

```bash
python -m tori.cli screenshot --out /tmp/tori-form.png
```

Write the title and description in Finnish; the audience is Finnish-language.

Add `--height/--width/--depth` (cm) on the categories that show
`Korkeus`/`Leveys`/`Syvyys` (e.g. `Koti ja sisustus,Pöydät ja tuolit,…`,
`Koti ja sisustus,Hyllyt ja lipastot,…`). On categories without them the fields
are skipped with a note, not an error. `--postcode` sets the ad's location — it
is the field that decides Matinkylä vs. the profile default, so read the stored
ad back and check `address.postalcode`.

As a library:

```python
import asyncio
from tori import browser, listing

browser.ensure_running()                     # dedicated Chrome + debug port

item = listing.Listing(
    title="Ruskea nahkainen reppu",
    price="25",
    description=open("description.txt", encoding="utf-8").read(),
    images=["photo1.jpg", "photo2.jpg"],
    postcode="00100",
    category=("Vaatteet", "Laukut ja lompakot", "Reput"),   # Osasto / Alaluokka / Tuoteryhmä
    condition="Hyvä",
    material="Nahka",
    dimensions={"Korkeus": 45, "Leveys": 92, "Syvyys": 55},  # only where the category asks
)
print(asyncio.run(listing.create(item, dry_run=True)))
```

Options are matched by their **visible Finnish text**, so they survive Tori
renumbering its category ids. Exact match first, then prefix — `"Vaatteet"`
resolves to `"Vaatteet, kosmetiikka ja asusteet"`.

## How it works

**Search** — Tori's search pages are server-rendered, so plain HTTP works. The
results are in an embedded JSON-LD `ItemList`, nested under
`mainEntity.itemListElement` (the top-level `itemListElement` is only
breadcrumbs). Search HTML has no location data, so each detail page is fetched
in a thread pool for its own coordinates, postal area and flags. Coordinates
come out of the embedded static-map URL; the location object is a
double-escaped JS string, so it is flattened before parsing. Distances are
haversine from an origin you geocode once.

**Create** — the form is a client-side app and its controls live **inside shadow
roots**, so `document.querySelector` finds nothing and every helper walks shadow
roots recursively. Category pickers are real `<select>` elements that appear one
after another (Osasto → Alaluokka → Tuoteryhmä, then Kunto and — depending on the
category — Materiaali, Sukupuoli, or the Korkeus/Leveys/Syvyys trio) and they all
share the id `select_id`, so they are addressed by option text instead. The
numeric fields are `<w-textfield>` custom elements whose label is an **attribute
on the host**, so they are addressed by label too — `w-textfield[label="Hinta"]`
— never by position. The photo input is a real `input[type=file]`, uploaded with
`DOM.setFileInputFiles` and an `objectId` — which is why there is no file dialog
in this tool at all.

Three things about the funnel are easy to get wrong, and all of them fail
*silently*:

- The **description** is only accepted via `Input.insertText` on the right
  textarea. Every uploaded photo adds its own caption box, so "the first
  textarea" is a photo caption — put your text there and the description stays
  required forever.
- The **pickup-only delivery radio is not pre-selected**. With no radio checked,
  *Jatka* refuses to advance and shows nothing.
- The **price is neither required nor validated**, so an ad whose price did not
  register simply publishes at 0 €. The code writes it into the field *and*
  Tori's save request, then reads it back from the API after publishing —
  see [docs/LIMITATIONS.md](docs/LIMITATIONS.md) §0.

The **postcode and dimensions** fail the same silent way, and position-addressed
fields made it worse on the categories that ask for dimensions: the price landed
in Korkeus and the postcode in Leveys, leaving the ad at the seller's profile
location with nonsense measurements. Fixed by addressing fields by label, and
repairable with `fix-fields` — see
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) §0b.

More detail, including every dead end worth not repeating, is in
[docs/FINDINGS.md](docs/FINDINGS.md) and [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Limitations

- **Deleting an ad is not scripted.** The confirmation dialog's button ignores
  programmatic, shadow-inner and trusted coordinate clicks — delete from the
  Tori UI by hand.
- Selectors are text- and structure-based, not id-based, which is more durable —
  but a redesign of the create page will still break `tori/page.py`.
- Nominatim (address → coordinates) asks for ≤1 request/second. Don't hammer it.
- Scraping and automating a marketplace is a **you** decision: read Tori's terms
  and keep request volume polite. This tool is for personal use on your own
  account and your own listings.

## Contributing

The most useful contributions, roughly in order:

1. Scripting ad deletion (see docs/LIMITATIONS.md for what has been ruled out).
2. A responder/listener for seller messages.
3. Keeping up with Tori's form changes.

Please keep the "no Playwright/Selenium" property if you can — raw CDP keeps the
dependency list to one package.

## License

MIT — see [LICENSE](LICENSE).
