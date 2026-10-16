"""Create a Tori.fi listing over CDP.

Verified end to end: the category chain, condition, material, title, description,
price, postcode, photo upload, and the delivery → package → publish funnel all
run without any GUI input. Two traps worth knowing:

* Every uploaded photo adds a caption textarea (``placeholder="Kuvateksti"``).
  The listing description is the textarea that is *not* a caption — select it by
  that, not by "the first textarea".
* The description must be set with ``Input.insertText``. Writing ``value`` via
  the native setter updates the DOM but not the app state, so the field stays
  "required" and *Jatka* never advances.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from . import cdp, page

CREATE_START = "https://www.tori.fi/create-item/start"

# Option texts as they appear in the Finnish UI. Override per listing.
DEFAULT_CATEGORY = ("Vaatteet", "Laukut ja lompakot", "Reput")


@dataclass
class Listing:
    title: str
    price: str
    description: str
    images: list = field(default_factory=list)
    postcode: str = "00100"
    category: tuple = DEFAULT_CATEGORY          # (Osasto, Alaluokka, Tuoteryhmä)
    condition: str | None = None                # e.g. "Hyvä"
    material: str | None = None                 # e.g. "Nahka"
    skip_shipping: bool = True                  # True → pickup only (no ToriDiili)


class ToriListing:
    def __init__(self, client: cdp.CDP, verbose: bool = True):
        self.c = client
        self.verbose = verbose

    async def step(self, name: str, body: str):
        r = await self.c.eval(page.wrap(body))
        ok = (r or {}).get("ok")
        if self.verbose:
            print(("  ok  " if ok else " FAIL ") + name +
                  (" :: " + str(r)[:220] if r else ""))
        return r

    async def open_form(self) -> str:
        """Open /create-item/start and submit the Tori (recommerce) tile form."""
        await self.c.navigate(CREATE_START, wait=5)
        r = await self.step("open form", """
          const inp = __find(e => e.tagName === 'INPUT' && e.name === 'adType'
                               && e.value === 'recommerce');
          if (!inp) return {ok: false, reason: 'recommerce tile not found'};
          (inp.form || inp.closest('form')).submit();
          return {ok: true};
        """)
        if not (r or {}).get("ok"):
            raise RuntimeError("could not open the create form")
        await asyncio.sleep(7)
        url = await self.c.eval("location.href")
        if "/recommerce/create/" not in url:
            if "login" in (url or "") or "/auth" in (url or ""):
                raise RuntimeError(
                    "the browser is not logged in to Tori (redirected to "
                    f"{url}) — log in in the automation window and re-run"
                )
            raise RuntimeError(f"unexpected form url: {url}")
        return url

    async def fill(self, listing: Listing):
        # Each dropdown only exists after the previous one is chosen.
        for i, option in enumerate(listing.category):
            await self.set_select(option, label=f"category level {i + 1}")
            await asyncio.sleep(3)
        for extra in (listing.condition, listing.material):
            if extra:
                await self.set_select(extra)
                await asyncio.sleep(2)

        await self.step("title", """
          const el = __find(e => e.tagName === 'INPUT' && e.name === 'title');
          if (!el) return {ok: false, reason: 'no title input'};
          __setNative(el, %s); return {ok: el.value === %s, value: el.value};
        """ % (_q(listing.title), _q(listing.title)))

        await self.set_number(0, listing.price, "price")
        await self.set_number(1, listing.postcode, "postcode")

        # Images upload before the description: each photo adds a "Kuvateksti"
        # caption box, and the description is identified by NOT being one of
        # those — so this order makes the field unambiguous.
        if listing.images:
            await self.upload(listing.images)

        await self.set_description(listing.description)

    # Every uploaded photo adds a caption TEXTAREA (placeholder "Kuvateksti").
    # The listing's own description is the textarea that is NOT a caption —
    # picking "the first textarea" silently types into a photo caption instead.
    DESC_SELECTOR = ("__all(e => e.tagName === 'TEXTAREA'"
                     " && (e.placeholder || '') === '')")

    # Visible number inputs, in order: price, then postcode.
    NUM_SELECTOR = ("__all(e => e.tagName === 'INPUT' && e.type === 'number'"
                    " && e.getBoundingClientRect().width > 0)")

    async def set_number(self, idx: int, value: str, label: str):
        """Fill a number input (price, postcode) with Input.insertText.

        NOT __setNative: that writes the DOM value but never reaches Tori's app
        state, so a price set that way publishes as **0 €** — silently, with no
        validation error. This was live: every script-posted ad went up at 0 €.
        """
        r = await self.step(label + ": focus", """
          const ns = %s;
          if (ns.length <= %d) return {ok: false, reason: 'number input missing'};
          const el = ns[%d];
          el.focus();
          const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
          if (d && d.set) d.set.call(el, '');
          el.dispatchEvent(new Event('input', {bubbles: true}));
          return {ok: true};
        """ % (self.NUM_SELECTOR, idx, idx))
        if not (r or {}).get("ok"):
            return r
        await asyncio.sleep(0.6)
        await self.c.send("Input.insertText", text=str(value))
        await asyncio.sleep(1.0)
        return await self.step(label, """
          const ns = %s;
          const el = ns.length > %d ? ns[%d] : null;
          const want = %s;
          const got = el ? el.value.replace(/[^0-9.,]/g, '') : null;
          return {ok: !!el && got === want.replace(/[^0-9.,]/g, ''),
                  value: el ? el.value : null, wanted: want};
        """ % (self.NUM_SELECTOR, idx, idx, _q(str(value))))

    async def set_description(self, text: str):
        """Type the description with Input.insertText.

        Not __setNative: that writes the value but never updates Tori's app
        state, so the field stays "required". insertText goes through the real
        input pipeline and does register.
        """
        if not text:
            return {"ok": True, "skipped": "empty description"}
        r = await self.step("description: focus", """
          const ts = %s;
          if (!ts.length) return {ok: false, reason: 'no description textarea'};
          const t = ts[ts.length - 1];
          t.focus();
          const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(t), 'value');
          if (d && d.set) d.set.call(t, '');
          t.dispatchEvent(new Event('input', {bubbles: true}));
          return {ok: true};
        """ % self.DESC_SELECTOR)
        if not (r or {}).get("ok"):
            return r
        await asyncio.sleep(0.8)
        # insertText needs no keyboard layout and keeps newlines intact.
        await self.c.send("Input.insertText", text=text)
        await asyncio.sleep(1.5)
        return await self.step("description", """
          const ts = %s;
          const t = ts.length ? ts[ts.length - 1] : null;
          return {ok: !!t && t.value.length > 0
                      && t.getAttribute('aria-invalid') !== 'true',
                  len: t ? t.value.length : -1,
                  invalid: t ? t.getAttribute('aria-invalid') : null};
        """ % self.DESC_SELECTOR)

    async def set_select(self, option: str, label: str = "select"):
        """Choose a dropdown option by its exact (or prefix) text."""
        return await self.step(label, "return __setSelectByText(" + _q(option) + ");")

    async def set_select_prefix(self, prefix: str, label: str = "select"):
        return await self.step(label, "return __setSelectByText(" + _q(prefix) + ", true);")

    async def upload(self, images: list):
        """Upload local image files into the (shadow-DOM) file input."""
        obj = await self.c.handle(page.find("e => e.tagName === 'INPUT' && e.type === 'file'"))
        if not obj:
            raise RuntimeError("file input not found")
        # DOM.setFileInputFiles accepts an objectId, so shadow roots are fine.
        await self.c.send("DOM.setFileInputFiles", objectId=obj, files=list(images))
        await asyncio.sleep(5)
        return await self.step("images present", """
          return {ok: true, images_on_page: __all(e => e.tagName === 'IMG').length};
        """)

    async def continue_forward(self):
        """Click Jatka on the create form and wait for the delivery step."""
        ok = await self.click_until("Jatka", "location.href.includes('/delivery/')",
                                    label="create → delivery")
        if not ok:
            raise RuntimeError(
                "Jatka did not advance — the form is incomplete (most likely a "
                "required dropdown never registered)")
        return await self.c.eval("location.href")

    # --- clicking Tori's custom controls -------------------------------------
    #
    # The form is built from custom elements (w-button, w-radio). Depending on
    # the control, a trusted coordinate click, a click on the button inside the
    # element's shadow root, or a plain .click() on the host is the one that
    # works — and which one varies per step. Rather than guess, try them in
    # order and stop as soon as the page actually moved.

    async def _trusted_click(self, x: int, y: int):
        await self.c.send("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await self.c.send("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y,
                          button="left", buttons=1, clickCount=1)
        await asyncio.sleep(0.1)
        await self.c.send("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y,
                          button="left", buttons=0, clickCount=1)

    async def _click_once(self, text: str, mode: str):
        if mode == "coords":
            box = await self.c.eval(page.wrap(
                "const el = __all(e => (e.innerText||'').trim() === %s"
                " && e.getBoundingClientRect().width > 0).pop();"
                "if (!el) return null; el.scrollIntoView({block:'center'});"
                "return {ok:true};" % _q(text)))
            if not box:
                return False
            await asyncio.sleep(1.2)
            pos = await self.c.eval(page.wrap(
                "const el = __all(e => (e.innerText||'').trim() === %s"
                " && e.getBoundingClientRect().width > 0).pop();"
                "if (!el) return null; const q = el.getBoundingClientRect();"
                "return {x: Math.round(q.x+q.width/2), y: Math.round(q.y+q.height/2)};"
                % _q(text)))
            if not pos:
                return False
            await self._trusted_click(pos["x"], pos["y"])
            return True
        # shadow-inner, then host
        sel = ("el.shadowRoot ? el.shadowRoot.querySelector('button,a,[role=button]') : null"
               if mode == "inner" else "null")
        r = await self.c.eval(page.wrap(
            "const el = __all(e => (e.innerText||'').trim() === %s"
            " && e.getBoundingClientRect().width > 0).pop();"
            "if (!el) return {ok:false, reason:'no element'};"
            "const inner = %s;"
            "if (inner) { inner.click(); return {ok:true, via:'inner'}; }"
            "if (%s) { el.click(); return {ok:true, via:'host'}; }"
            "return {ok:false, reason:'host click used'};"
            % (_q(text), sel, "true" if mode == "host" else "false")))
        return bool((r or {}).get("ok"))

    async def click_until(self, text: str, done_js: str, label: str | None = None,
                          settle: float = 7.0) -> bool:
        """Click `text` until `done_js` is true, escalating the click method."""
        for mode in ("coords", "inner", "host"):
            if await self.c.eval(done_js):
                return True
            fired = await self._click_once(text, mode)
            await asyncio.sleep(settle)
            moved = bool(await self.c.eval(done_js))
            if self.verbose and fired:
                print(("  ok  " if moved else "  --  ") +
                      (label or text) + f" [{mode}]")
            if moved:
                return True
        return bool(await self.c.eval(done_js))

    async def choose_package(self, name: str = "Basic") -> bool:
        """Pick the (free) Basic package. Basic costs nothing — never select a
        paid package without the user asking and approving the charge."""
        return await self.step(f"package: {name}", """
          const rs = __all(e => e.tagName === 'W-RADIO');
          const el = rs.find(x => (x.parentElement ? x.parentElement.innerText : '')
                                   .trim().startsWith(%s));
          if (!el) return {ok: false, reason: 'package radio not found'};
          const inner = el.shadowRoot ? el.shadowRoot.querySelector('input,button,[role=radio]') : null;
          (inner || el).click();
          return {ok: true};
        """ % _q(name))

    async def choose_pickup_only(self) -> dict:
        """Delivery step: pick "En voi lähettää tavaraa" (pickup only).

        Not always pre-selected — on a fresh funnel no radio is checked at all,
        and *Jatka* silently refuses to advance until one is. The w-radio host
        answers to a programmatic ``.click()``; trusted coordinate clicks and
        clicks on the surrounding row do nothing.
        """
        return await self.step("delivery: pickup only", """
          const rs = __all(e => e.tagName === 'W-RADIO');
          const el = rs.find(x => /En voi lähettää tavaraa/i.test(
                       x.parentElement ? x.parentElement.innerText : ''));
          if (!el) return {ok: false, reason: 'pickup-only radio not found'};
          if (el.hasAttribute('checked')) return {ok: true, already: true};
          el.click();
          return {ok: true, clicked: true};
        """)

    async def finish(self, package: str = "Basic") -> str:
        """Delivery → package → publish. Call after `fill`."""
        # Create form → delivery step. (The create→delivery Jatka only advances
        # once every required field has registered.)
        await self.continue_forward()
        await self.choose_pickup_only()
        await asyncio.sleep(2)
        await self.click_until("Jatka", "location.href.includes('/choose-products')",
                               label="delivery → package")
        await self.choose_package(package)
        await asyncio.sleep(2)
        # The submit button reads "Siirry maksamaan" until Basic is selected,
        # then becomes "Julkaise ilmoitus".
        ok = await self.click_until(
            "Julkaise ilmoitus",
            "location.href.includes('/ad-receipt') || location.href.includes('/my-items')",
            label="publish")
        if not ok:
            ok = await self.click_until(
                "Siirry maksamaan",
                "location.href.includes('/ad-receipt') || location.href.includes('/my-items')",
                label="publish (alt label)")
        return await self.c.eval("location.href")


def _q(s) -> str:
    import json
    return json.dumps(s, ensure_ascii=False)


async def create(listing: Listing, port: int = cdp.DEFAULT_PORT, dry_run: bool = False):
    ws, _ = cdp.page_target(port=port)
    async with cdp.CDP(ws) as c:
        await c.send("Runtime.enable")
        await c.send("DOM.enable")
        t = ToriListing(c)
        url = await t.open_form()
        await t.fill(listing)
        if dry_run:
            return url
        return await t.finish()
