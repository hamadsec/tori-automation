# Findings

Notes from building this against the live site. Mostly a list of things that
wasted time, so the next person does not repeat them.

## Chrome

- **`--remote-debugging-port` is ignored on the default Chrome profile** from
  Chrome 136 onward. Chrome starts fine and the flag is simply dropped —
  `netstat` shows nothing listening and `/json/version` never answers. A
  non-default `--user-data-dir` is required. This is a security default, not a
  bug in your launch code.
- **Copying a Chrome profile does not carry cookies.** Copy `Local State`,
  `Default/Preferences` and `Default/Network/Cookies` into a new user-data-dir
  and Chrome still lands you on the login page: app-bound cookie encryption
  invalidates them on a profile copy. Budget a one-time manual login instead.
- **You cannot read the cookie database while Chrome is running.** The file is
  opened without share flags, so `Copy-Item`, `robocopy /B` and even a
  `CreateFileW` with `FILE_SHARE_READ|WRITE|DELETE` all fail with error 32.
  Close Chrome (or use a shadow copy) or do not bother.
- Passing flags to `chrome.exe` while any Chrome process is alive starts a
  window in the *existing* process and drops the flags. Kill everything first,
  wait a few seconds, then launch.
- `launch` uses raw CDP over `websockets` (already a Python dependency of most
  environments, and one `pip install` here). Playwright and Selenium are
  deliberately not used.

## The create form

- **Every control lives inside a shadow root.** `document.querySelector`
  returns `null` for all of it and the page looks empty. Walk `el.shadowRoot`
  recursively. Half the time spent on this project was discovering that.
- The category tiles are **not links**. The Tori (recommerce) tile is a `<form>`
  containing `input[name=adType][value=recommerce]`; submitting that form is more
  reliable than clicking the tile div, which has no anchor.
- The dropdowns are **real `<select>` elements** — good news, they are settable —
  but every one of them has `id="select_id"`, so ids are useless. Match on option
  text. They also appear *progressively*: choosing Osasto creates Alaluokka, which
  creates Tuoteryhmä, and so on. Set one, wait ~3 s, set the next.
- Bypassing the AJAX/React-only layer is not possible: a native `form.submit()`
  fires but the app's own validation still blocks, because validation reads the
  app's state rather than the DOM.
- **`Jatka` is `<w-button type="submit">`**, not a button. `.click()` on the host
  does nothing, and a trusted CDP mouse click at its coordinates does nothing
  either while validation is failing.
- The photo input is a plain `input[type=file][multiple]`.
  `DOM.setFileInputFiles` accepts an **objectId** from `Runtime.evaluate`, which
  sidesteps the shadow-DOM problem entirely — `DOM.querySelector` cannot pierce
  shadow roots, and `DOM.requestNode` did not resolve for us. Worth using even in
  a Playwright project: it removes the native file dialog, which was the slowest
  part of the GUI route.
- **Events need `composed: true`** to leave a shadow root and reach a listener
  registered at the document level.
- Dispatching an event can trigger a re-render that **replaces the node**. Hold a
  reference across a re-render and your second write goes to a detached element.
  Re-find between writes.
- Uploading images and then reloading the create page is safe: Tori keeps the
  draft server-side and the images come back with it. Useful escape hatch when the
  SPA renders a blank form after a file dialog.

## Verified category path (clothing accessories)

```
Osasto      Vaatteet, kosmetiikka ja asusteet   (value 71)
Alaluokka   Laukut ja lompakot                  (value 3946)
Tuoteryhmä  Reput                               (value 9472)
Kunto       Hyvä                                (value 3)
Materiaali  Nahka                               (value 2)
```

Values change; the texts have been stable. Address them by text.

## The search pages

- Server-rendered, so `curl` beats a browser. A desktop User-Agent is enough.
- Results are in JSON-LD, but **nested under `mainEntity.itemListElement`**
  (an `ItemList`). The top-level `itemListElement` on the same page is a
  `BreadcrumbList` — parse only that and you get zero results from a page that
  clearly has 50-plus listings.
- ~53 listings per page; the page count is in the `?page=` links.
- The item page exposes coordinates in two places: the static-map URL
  (`staticmap?lat=..&lng=..`) and `itemData.location.position`. The location
  object is embedded as a **double-escaped** JS string, so `"postalCode"` appears
  as `\\"postalCode\\"`. Flatten `\\+"` → `"` before regexing, or your postal
  fields silently come back `null` while the coordinates work — which looks like
  a working parser.
- `VARATTU` means reserved. `Osta heti` **and** `Toimitus alkaen` together mean
  shippable; the bare string `ToriDiili` also appears in promo blocks, so it is
  not a reliable flag.
- **Do not regex the page text for a district name.** Item pages embed
  "recommended listings", so text scraping labels an item with a *neighbouring*
  item's district. Use only the item-scoped `postalName`/`postalCode` fields and
  check they agree with the coordinates.
