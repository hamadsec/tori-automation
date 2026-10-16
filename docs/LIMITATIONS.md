# Limitations

## 0. Price — BROKEN, no working fix yet

Script-posted ads go live at **0 €**. Two live ads confirm it: the microphone ad
(48602826, meant to be 50 €) and the plant ad (48590647, meant to be 5 €). Price
is not a validated field, so nothing complains — the ad just publishes at 0 €.

**Cause.** Price was filled with the native value setter, which writes the DOM but
never reaches Tori's app state. Same class of bug as the description.

**The obvious fix does not work.** `set_number()` was changed to use
`Input.insertText`, mirroring the description fix. Verified against the live form
and it is **not** sufficient for the price input: immediately after
`insertText`, the price field reads `''` — while the *postcode* input in the same
routine does keep its value, and the description does too. So `insertText` is
right for those fields and wrong for this one.

**Why this is hard to verify.** Unlike the description — where success is visible
because `aria-invalid` clears and *Jatka* unlocks — price has **no observable in
the form**. It is not required, not validated, and nothing unlocks when it is
set. The only trustworthy oracle is to publish and read the price back off the
live ad (this is how the bug was found), which is why it went unnoticed.

**What to try next.** The price field is a spinner-style `w-` component; suspects
are that clearing it re-renders and detaches the node before the write lands
(re-find the element between clear and write, and lengthen the settle), or that
it only accepts real key events. Note that *every* other field now works, so
scope the experiment to this one input.

**Until then: do not trust the price.** Every listing this tool creates needs its
price checked and, if 0 €, corrected in the Tori UI by hand. Ads can be edited at
`/recommerce/create/<adId>?editMode=true` (the save button there is *Tallenna*,
and editing reuses the same delivery → package funnel).

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
