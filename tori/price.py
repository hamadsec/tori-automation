"""Set an ad's price by patching the request Tori itself sends.

Why this exists: price is the one field in the create form that Tori never
validates, so a price that does not register fails **silently** — the ad is
saved with `"price": {}` and publishes at **0 €**. That is not hypothetical: the
microphone ad 48602826 (meant to be 50 €) and the plant ad 48590647 (meant to be
5 €) both went live at 0 € that way.

The price *field* is filled with `Input.insertText` and that has gone both ways
— it failed to register when those two ads went up, and it did register on later
runs (two drafts filled but never submitted stored 17 € and 23 € with no patch
installed at all). So the field is *unreliable* rather than broken, and this
module is the belt to its braces: the price is written twice.

What this does is intercept the save request. Clicking *Tallenna* (edit form) or
*Jatka* (create form) makes the app `PUT /recommerce/create/api/item/<ad>` with
a JSON body. With the CDP Fetch domain that request is paused, `data.price` is
rewritten to `{"price_amount": <n>}` and it is continued — so the request keeps
the browser's own `E-Tag`, cookies and headers, and the E-Tag stays valid.
Verified live: ad 48602826 went from 0 € to 50 € this way, visible both on the
seller's /my-items card and in public search.

Note what is *not* here: the publish click. It is `POST
/recommerce/choose-products/api/ordernow?adId=<id>` with an empty body — it
publishes whatever the stored ad already says, so there is no request body to
patch at that point and the price must be right beforehand.

Note also the background-window trap: in the automation Chrome (which never gets
OS focus) real key events are not delivered to the page at all, which is why the
price is fixed at the request level rather than with a better typing trick.
"""

from __future__ import annotations

import base64
import json


def _patch_body(raw: str, price: int | str) -> str | None:
    """Return the request body with the price set, or None if it is not ours."""
    try:
        body = json.loads(raw)
    except Exception:
        return None
    target = body.get("data") if isinstance(body.get("data"), dict) else body
    if not isinstance(target, dict):
        return None
    target["price"] = {"price_amount": int(price)}
    return json.dumps(body, ensure_ascii=False)


class PricePatcher:
    """Intercepts Tori's own save request and injects the price into it."""

    def __init__(self, client, ad_id: str, price):
        self.c = client
        self.ad_id = str(ad_id)
        self.price = price
        self.state = {"patched": [], "continued": 0}

    async def enable(self):
        await self.c.send("Fetch.enable", patterns=[{
            "urlPattern": f"*recommerce/create/api/item/{self.ad_id}*",
            "requestStage": "Request"}])

    async def disable(self):
        await self.c.send("Fetch.disable")

    async def pump(self) -> int:
        """Handle every paused request queued since the last call.

        Returns the number of requests whose body was rewritten. Call this in a
        loop while the save click is in flight (each call is a harmless eval that
        also drains the websocket).
        """
        await self.c.eval("1")
        patched = 0
        for ev in list(self.c.events):
            if ev.get("method") != "Fetch.requestPaused":
                continue
            p = ev["params"]
            rid = p["requestId"]
            raw = p["request"].get("postData") or ""
            new = _patch_body(raw, self.price) if f"/api/item/{self.ad_id}" in (
                p["request"].get("url") or "") else None
            if new is None:
                self.state["continued"] += 1
                await self.c.send("Fetch.continueRequest", requestId=rid)
            else:
                await self.c.send(
                    "Fetch.continueRequest", requestId=rid,
                    postData=base64.b64encode(new.encode("utf-8")).decode())
                self.state["patched"].append(p["request"].get("method"))
                patched += 1
        self.c.events = [e for e in self.c.events
                         if e.get("method") != "Fetch.requestPaused"]
        return patched


async def patch_with(client, ad_id: str, price, click_step, modes=("coords", "inner", "host"),
                     pumps: int = 8, settle: float = 0.7):
    """Install the patch, run *click_step* until Tori's save request is patched.

    *click_step* is an async callable taking one click method name (the CDP
    client here is single-threaded — one ``recv`` at a time — so the click and
    the pump cannot run concurrently; they alternate instead, which is also what
    the working manual sequence did).
    """
    import asyncio

    patcher = PricePatcher(client, ad_id, price)
    await patcher.enable()
    try:
        for mode in modes:
            await click_step(mode)
            for _ in range(pumps):
                await asyncio.sleep(settle)
                if await patcher.pump():
                    break
            if patcher.state["patched"]:
                break
        for _ in range(pumps):
            await asyncio.sleep(settle)
            await patcher.pump()
    finally:
        try:
            await patcher.disable()
        except Exception:
            pass
    return patcher.state
