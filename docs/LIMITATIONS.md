# Limitations

## 1. The description field rejects automated input

This is the one hard wall in the project.

**Symptom.** The description text ends up in the DOM and is visible on screen,
but Tori's form validation still reports `Pakollinen kenttä` ("required field"),
and the *Jatka* button refuses to advance.

**What has been ruled out** (all tried against the live form):

| Method | Result |
|---|---|
| `el.value = x` | value set, app state unchanged |
| Prototype value setter + `input`/`change` events (`bubbles` + `composed`) | same |
| `Input.insertText` (CDP, browser-level) | same |
| Per-character `Input.dispatchKeyEvent` (keyDown/char/keyUp) | same — and text spills into whatever else has focus |
| Trusted `Input.dispatchMouseEvent` click on *Jatka* | nothing |
| `form.requestSubmit()` / `form.submit()` | native submit fires, validation still blocks |

**What does work.** Real OS-level keyboard input (the Hermes `computer_use`
`type` action) — that is how the manual run succeeded. So the practical setup is
a hybrid: script the dropdowns, price, postcode and photos, and type the two
free-text fields by hand or with a desktop-automation tool.

**Hypothesis.** The textarea is wrapped by a component that keeps its own model
and only syncs on its own event; the events above are visible in the DOM but
never reach that model. Worth investigating: whether the real binding sits on an
inner element of a `w-textarea`-style custom element, or on a `keyup`/`blur`
handler, or whether the value is mirrored into a hidden input at submit time.

**Watch out if you type by keyboard.** Key events go to whatever has focus. A
photo's *caption* box will happily swallow a paragraph intended for the
description — check the captions afterwards.

## 2. The title field is fine, so the problem is specific

The title (`input[name=title]`) accepts the same synthetic input with no
complaint. That rules out a blanket "this app ignores synthetic events"
explanation and points at the description widget specifically.

## 3. Publishing after *Jatka* is not scripted

The delivery page (ToriDiili package size, or "I can't send the goods"), the
package choice (Basic free / Plus / Premium) and the payment step are manual for
now. They are simple radio/button screens; scripting them is a small job for
whoever picks it up. Note that a paid package spends real money — never select
one implicitly.

## 4. Selector durability

Nothing depends on Tori's element ids: `select_id` is reused by *every* dropdown,
so ids are actively misleading here. Options are matched by their visible Finnish
text and elements are found by tag, `type` and `name`. That is more durable than
ids, but a redesign of the create page will still require edits in
`tori/page.py`.

## 5. Search results carry no location

Location lives only on the item page, so a shortlist costs one HTTP request per
listing. On a broad query that is hundreds of requests — use `--pages` to bound
it, and keep the thread pool modest out of politeness.

## 6. Nominatim rate limit

`search.geocode()` uses OpenStreetMap's Nominatim, which asks for at most one
request per second and a real User-Agent. Geocode your address once and pass the
coordinates around rather than geocoding per query.
