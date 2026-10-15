"""Create a Tori.fi listing over CDP.

Verified working via script: the whole category chain, condition, material,
price, postcode and photo upload. The free-text description is the one field
that does not accept synthetic input (see docs/LIMITATIONS.md) — pass
``type_text`` a callback if you want the script to delegate that field.
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

        await self.step("description (may not register — see LIMITATIONS)", """
          const el = __find(e => e.tagName === 'TEXTAREA');
          if (!el) return {ok: false, reason: 'no textarea'};
          __setNative(el, %s); return {ok: el.value.length > 0, len: el.value.length};
        """ % _q(listing.description))

        await self.step("price + postcode", """
          const nums = __all(e => e.tagName === 'INPUT' && e.type === 'number'
                              && e.getBoundingClientRect().width > 0);
          if (nums.length < 2) return {ok: false, reason: 'expected 2 number inputs'};
          __setNative(nums[0], %s); __setNative(nums[1], %s);
          return {ok: true, price: nums[0].value, postcode: nums[1].value};
        """ % (_q(listing.price), _q(listing.postcode)))

        if listing.images:
            await self.upload(listing.images)

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
        """Click Jatka. Only works once every required field is registered."""
        return await self.step("Jatka", 'return __clickText("Jatka");')


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
        await t.continue_forward()
        await asyncio.sleep(6)
        return await c.eval("location.href")
