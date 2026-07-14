"""
httpx-oriented pace wrapper (optional httpx).

    from plugins.adapters.httpx_client import EyeStormTransport

    api = ApiClientPlugin(base_rps=15)
    # After each response:
    api.record(ok=resp.is_success, status=resp.status_code)
    if window_done:
        ctrl = api.observe()
        time.sleep(api.pace_delay(ctrl))

Or use EyeStormSession helper for simple GET/POST with auto pace.
"""

from __future__ import annotations

import time
from typing import Any

from .api_client import ApiClientPlugin


class EyeStormSession:
    """
    Thin request loop helper. Uses stdlib urllib if httpx missing.
    """

    def __init__(self, api: ApiClientPlugin | None = None, *, base_rps: float = 8.0):
        self.api = api or ApiClientPlugin(base_rps=base_rps)
        self._since_observe = 0
        self.observe_every = 10

    def _observe_if_needed(self) -> None:
        self._since_observe += 1
        if self._since_observe >= self.observe_every:
            self.api.observe()
            self._since_observe = 0

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        ctrl = self.api.last
        if ctrl and not self.api.allow_request(ctrl):
            time.sleep(self.api.pace_delay(ctrl) * 2)
        delay = self.api.pace_delay(ctrl)
        if delay > 0:
            time.sleep(delay)

        try:
            import httpx  # type: ignore

            with httpx.Client(timeout=kwargs.pop("timeout", 30.0)) as client:
                resp = client.request(method, url, **kwargs)
            self.api.record(ok=resp.is_success, status=resp.status_code)
            self._observe_if_needed()
            return resp
        except ImportError:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(url, method=method.upper())
            try:
                with urllib.request.urlopen(req, timeout=kwargs.get("timeout", 30)) as resp:
                    body = resp.read()
                    status = getattr(resp, "status", 200)
                    self.api.record(ok=200 <= status < 400, status=status)
                    self._observe_if_needed()
                    return {"status": status, "body": body}
            except urllib.error.HTTPError as e:
                self.api.record(ok=False, status=e.code, error=True)
                self._observe_if_needed()
                raise
