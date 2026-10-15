"""Launch and find the dedicated Chrome instance used for automation.

Two Chrome behaviours shape this module:

* Since Chrome 136 the ``--remote-debugging-port`` flag is **silently ignored
  on the default profile**. The port only opens when an explicit non-default
  ``--user-data-dir`` is supplied.
* Copying an existing profile to a new directory does **not** carry cookies
  over: Chrome's app-bound encryption invalidates them on a profile copy. So
  the dedicated profile needs its own one-time login.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from . import cdp

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def chrome_path() -> str:
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env
    for p in CHROME_CANDIDATES:
        found = p if os.path.exists(p) else shutil.which(p)
        if found:
            return found
    raise RuntimeError("Chrome not found — set CHROME_PATH")


def profile_dir() -> str:
    return os.environ.get("TORI_PROFILE",
                          os.path.join(os.path.expanduser("~"), ".tori-automation", "chrome"))


def launch(url: str = "https://www.tori.fi/", port: int = cdp.DEFAULT_PORT,
           wait: float = 10.0, extra_args=None) -> str:
    """Start the dedicated Chrome with the debug port and open *url*."""
    os.makedirs(profile_dir(), exist_ok=True)
    args = [chrome_path(),
            f"--user-data-dir={profile_dir()}",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run", "--no-default-browser-check"]
    args += list(extra_args or [])
    args.append(url)
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)
    deadline = time.time() + wait
    while time.time() < deadline:
        if cdp.is_running(port):
            return profile_dir()
        time.sleep(0.5)
    raise RuntimeError(
        f"Chrome started but nothing is listening on 127.0.0.1:{port}. "
        "Check that the profile dir is not the default Chrome profile."
    )


def ensure_running(url: str = "https://www.tori.fi/", port: int = cdp.DEFAULT_PORT) -> None:
    if not cdp.is_running(port):
        launch(url, port)
