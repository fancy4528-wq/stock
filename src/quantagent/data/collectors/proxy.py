"""Shared helpers for collectors."""

from __future__ import annotations

import os
from urllib import request as urllib_request

from quantagent.shared.config import get_settings


def apply_proxy_bypass() -> None:
    """Bypass broken local system proxies for vendor HTTP calls when configured.

    On Windows, ``urllib.request.getproxies()`` often reads a local Clash port
    from Internet Settings even when env proxy vars are empty. Force ``NO_PROXY=*``
    and clear proxy env vars so requests/akshare do not prefer a dead proxy.
    """
    if not get_settings().collector_bypass_proxy:
        return
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    # Prefer empty proxy map for code paths that call getproxies() directly.
    urllib_request.getproxies = lambda: {}  # type: ignore[assignment]
