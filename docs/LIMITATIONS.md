# Limitations

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
