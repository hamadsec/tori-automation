"""Minimal Chrome DevTools Protocol client.

Talks to a Chrome started with ``--remote-debugging-port``. Only needs
``websockets`` (no Playwright/Selenium).
"""
from __future__ import annotations

import asyncio
import json
import urllib.request

DEFAULT_PORT = 9222


def endpoint(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def _http(path: str, port: int = DEFAULT_PORT):
    with urllib.request.urlopen(endpoint(port) + path, timeout=10) as r:
        return json.loads(r.read().decode())


def is_running(port: int = DEFAULT_PORT) -> bool:
    try:
        _http("/json/version", port)
        return True
    except Exception:
        return False


def targets(port: int = DEFAULT_PORT):
    return [t for t in _http("/json/list", port) if t.get("type") == "page"]


def page_target(match: str = "tori.fi", port: int = DEFAULT_PORT):
    """Return ``(webSocketDebuggerUrl, target)`` for a page, preferring `match`."""
    pages = targets(port)
    if not pages:
        raise RuntimeError(
            "no page targets — is the dedicated Chrome running with "
            f"--remote-debugging-port={port}?"
        )
    for t in pages:
        if match in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"], t
    return pages[0]["webSocketDebuggerUrl"], pages[0]


class CDP:
    """Async CDP session against a single page target."""

    def __init__(self, ws_url: str, timeout: float = 45.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self._ws = None
        self._id = 0
        self.events: list = []

    async def __aenter__(self) -> "CDP":
        import websockets

        self._ws = await websockets.connect(self.ws_url, max_size=64 * 1024 * 1024)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ws:
            await self._ws.close()

    async def send(self, method: str, **params):
        """Send a CDP command and return its result (events are collected)."""
        self._id += 1
        mid = self._id
        await self._ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=self.timeout)
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    async def eval(self, expression: str, await_promise: bool = False):
        """Evaluate JS in the page and return the value (by value)."""
        r = await self.send("Runtime.evaluate", expression=expression,
                            returnByValue=True, awaitPromise=await_promise)
        if r.get("exceptionDetails"):
            raise RuntimeError(
                "JS error: " + str(r["exceptionDetails"].get("text")) + " :: "
                + str(r["exceptionDetails"].get("exception", {}).get("description"))[:300]
            )
        return r.get("result", {}).get("value")

    async def handle(self, expression: str):
        """Evaluate JS returning a DOM node; yields its CDP objectId."""
        r = await self.send("Runtime.evaluate", expression=expression)
        return r.get("result", {}).get("objectId")

    async def call(self, object_id: str, function_declaration: str, *args):
        """Call a function on a previously obtained objectId."""
        return await self.send("Runtime.callFunctionOn", objectId=object_id,
                               functionDeclaration=function_declaration,
                               arguments=[{"value": a} for a in args],
                               returnByValue=True)

    async def navigate(self, url: str, wait: float = 4.0):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(wait)

    async def screenshot(self, path: str, full_page: bool = True):
        import base64

        await self.send("Page.enable")
        r = await self.send("Page.captureScreenshot", format="png",
                            captureBeyondViewport=full_page)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return path
