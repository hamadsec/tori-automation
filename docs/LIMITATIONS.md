# Limitations

## 0. Price — written twice on purpose, and read back

**Status: the one-command create publishes the requested price.** Verified on a
real publish: ad 48604695 (*Nahkareppu / olkalaukku, ruskea nahka*, the test ad
for this change) went live at **15 €** and reads back as 15 € from four
independent places — Tori's own API
(`GET /recommerce/create/api/item/48604695` → `"price": {"price_amount": 15}`),
the edit form at `?editMode=true`, the seller card on `/my-items`
(`Tori myydään 15 €`), and **public search** (the JSON-LD `Offer` carries
`"price": "15"`, `priceCurrency: EUR`,
`availability: InStock`).

**Why it needed any work at all.** Price is the one field Tori never validates,
so it fails **silently**: an ad with no price publishes at **0 €** and nothing
complains. Two live ads did exactly that — the microphone ad 48602826, meant to
be 50 €, and the plant ad 48590647, meant to be 5 €.

**The field is unreliable, not write-proof.** The earlier conclusion here was
that the price *field* "refuses every DOM-level write". That is what the 0 € ads
showed, but it does not hold now: two drafts were filled with `Input.insertText`
and **never submitted and never patched** — 48604881 stored `price_amount: 17`,
48604964 stored `price_amount: 23`, both read back from the API. So `insertText`
*does* reach Tori's app state in the current flow. These two observations cannot
be reconciled, and the safe reading is: the price field sometimes registers the
automated write and sometimes does not, which is worse than failing outright
because the form shows the right number either way.

**So the price is written twice.**

1. The field, with `Input.insertText` (the postcode's method — plain `value`
   writes, direct or through the native prototype setter, update the DOM but not
   the app state).
2. The save request, via `tori/price.py`. Clicking *Jatka* (create form) or
   *Tallenna* (edit form) makes the app `PUT
   /recommerce/create/api/item/<ad>` with the whole ad as JSON; with the CDP
   Fetch domain that request is paused, `data.price = {"price_amount": <n>}` is
   rewritten into it and it is continued — so it keeps the browser's own
   `E-Tag`, cookies and headers, and the E-Tag stays valid. Confirmed firing on a
   real create (one `PUT` rewritten). Harmless when the field already worked,
   and the thing that saves the ad when it did not, so it stays.

**What is *not* patched: the publish click.** Publishing is `POST
/recommerce/choose-products/api/ordernow?adId=<id>&productSpecificationUrns=…`
with an **empty body** — it publishes whatever the stored ad already says.
There is no request body to rewrite at that point, and the price has to be
correct *before* it. (An earlier revision tried to patch a
`PUT .../api/item/<id>` at publish time; that request does not exist in the
funnel, so the pattern never matched and the code only burned ~45 s of pumping.
It has been removed.)

**The oracle, now built in.** The silent-0 € failure mode is the reason the code
no longer trusts the form: after a successful publish it fetches the stored ad
and prints either

```
  ok  price verified: ad 48604695 stores 15 €
```

or a `FAIL` line naming the exact repair command. Treat the form field and the
seller card as *readings* of the API value, not as proof. To repair an ad that is
already live:

```bash
python -m tori.cli fix-price --ad 48602826 --price 50
```

Verified working: ad 48602826 went 0 → 49 → 50 that way, read back each time.

**Watch out.** The price field is useless as a *signal*: neither required nor
validated, nothing in the form unlocks when it is set, and its DOM value can read
correctly while the stored ad has no price at all. Never verify from the form
alone.


## 1. The description field — solved, and why it looked impossible

**It works now.** Set it with `Input.insertText` on the correct textarea. Two
separate mistakes made this look like a hard wall:

1. **Wrong element.** Every uploaded photo adds its own caption textarea
   (`placeholder="Kuvateksti"`). `__find(e => e.tagName === 'TEXTAREA')` returns
   the *first caption box*, so the text went into a photo caption. The listing's
   own description is the textarea that is **not** a caption — select it that
   way. This mistake alone accounts for most of the "nothing works" evidence
   that used to be listed here.
2. **Wrong write method.** Writing `value` — directly or through the native
   prototype setter — updates the DOM but not Tori's app state, so the field
   still counts as empty. `Input.insertText` goes through the real input
   pipeline and does register.

Symptom when it goes wrong: the text is visible in the field, validation still
shows `Tarkista Kuvaus ennen kuin voit jatkaa.` ("check the description before
you can continue") and *Jatka* refuses to advance.

| Method (against the **correct** textarea) | Result |
|---|---|
| `Input.insertText` | ✅ registers — this is what the code uses |
| Native prototype value setter + `input`/`change` events | ❌ DOM only, app state unchanged |
| `el.value = x` | ❌ DOM only |
| Per-character `Input.dispatchKeyEvent` | ❌ does not register, and the text spills into whatever else has focus |

**Earlier conclusion, now known to be wrong:** that only real OS-level keyboard
input (the `computer_use` `type` action) would do, and the flow had to be a
script-plus-hand-typing hybrid. That was an artefact of typing into a caption
box. No GUI input is needed anywhere in this tool.

## 2. The title field was never the problem

The title (`input[name=title]`) accepted synthetic input all along. That ruled
out a blanket "this app ignores synthetic events" explanation and pointed at the
description widget specifically — which turned out to be half right: the widget
*writes* only accept `insertText`, and the rest of the mystery was that the code
was addressing a photo caption instead.

## 3. Deleting an ad is not scripted

Everything else in the funnel is. What remains manual is *deleting*:

The quick-action menu (*Valikko ilmoituksen pikavalintoihin*) → *Poista* opens a
confirmation dialog whose **Poista** button did not respond to any of the three
click methods that work elsewhere:

| Method | Result |
|---|---|
| Host `.click()` on the `w-button` | nothing |
| Shadow-inner `button.click()` | no shadow button found |
| Trusted `Input.dispatchMouseEvent` at its centre | nothing |

So ad deletion needs a human tap in the Tori UI. Do not promise automated
cleanup.

Note also that a paid package (Plus / Premium) spends real money — the code
always selects **Basic** (free) and never selects a paid one implicitly. Keep it
that way.

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
