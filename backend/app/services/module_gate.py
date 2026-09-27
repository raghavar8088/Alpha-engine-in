"""The API half of the module switch: refuse work for a module that is switched off.

`desk_switches.gated()` stops a desk's background loop. This stops its endpoints. Both read
the same switch, so one toggle in Main Control closes both doors at once.

WHY A MIDDLEWARE AND NOT A DEPENDENCY ON EACH ROUTE
---------------------------------------------------
There are 42 routers and several hundred endpoints. A per-route dependency would have to be
added to every one of them, and the ones that got forgotten would be exactly the holes the
switch was built to close - silently, with no way to notice. A middleware sees every request
whether or not anyone remembered it, and a router added next month is covered the moment its
prefix is claimed in the registry. The cost is that it decides from the PATH rather than from
what the handler will do, which is why the work-detection rule lives in the registry and is
tested against the real route list.

WHY PURE ASGI AND NOT BaseHTTPMiddleware
----------------------------------------
BaseHTTPMiddleware pumps the response through an internal queue. This app has already had a
server-sent-events endpoint (`/api/chart/stream`) hang dead because a middleware in this
chain tried to buffer an endless generator, and that is not a mistake worth repeating one
layer up. A pure ASGI middleware either short-circuits with its own response or hands `scope,
receive, send` straight through untouched - an unaffected stream stays byte-for-byte
unaffected. The one thing it does add on a pass-through is a header, written by wrapping
`send` on the response-start message only, which buffers nothing.

WHERE IT SITS IN THE STACK
--------------------------
Registered so it runs INSIDE the shared-secret gate and OUTSIDE the response cache:

    require_shared_secret  ->  THIS GATE  ->  APICacheMiddleware  ->  routes

Inside the auth gate, because an unauthenticated caller should be told it is unauthenticated,
not which of our modules are switched off. Outside the cache for two reasons that both bite:
a 423 must never be stored and replayed for 20s after the module is switched back on, and a
blocked request must not be handed a cached body it was not allowed to generate.

FAIL OPEN
---------
Every failure path lets the request through. If the switch store is unreachable, if the path
resolves to no module, if this code raises - the request proceeds, and the decision is made
BEFORE the request is passed downstream so a failure can never mean sending it twice. A
control plane that breaks the app when it malfunctions is worse than one that occasionally
fails to block.
"""

import logging

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from app.services import desk_switches as sw
from app.services.module_registry import REGISTRY, is_ungated, is_work, resolve

logger = logging.getLogger("module_gate")

# Per-module count of requests refused since the process started, so the UI can show that a
# switch is doing something. In memory, and reset by a restart - this is feedback, not an
# audit trail, and not worth a write per blocked request to a cluster under quota.
_blocked: dict[str, int] = {}
_blocked_examples: dict[str, str] = {}


def blocked_counts() -> dict[str, dict]:
    return {k: {"blocked": v, "last": _blocked_examples.get(k, "")}
            for k, v in _blocked.items()}


def reset_counts() -> int:
    n = sum(_blocked.values())
    _blocked.clear()
    _blocked_examples.clear()
    return n


class ModuleGateMiddleware:
    """Blocks work for OFF modules; passes everything else through untouched."""

    def __init__(self, app):
        self.app = app

    async def _decide(self, method: str, path: str) -> tuple[str | None, bool]:
        """(module key, block) - key is None when this path is not gated at all."""
        if is_ungated(path):
            return None, False
        key = resolve(path)
        if key is None or await sw.is_on(key):
            return None, False
        # Module is OFF. Reads of rows already stored still answer; anything that would spend
        # a broker call or write a document does not. See module_registry on why.
        return key, is_work(method, path)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        key = None
        block = False
        try:
            key, block = await self._decide(scope.get("method", "GET"),
                                            scope.get("path", ""))
        except Exception:  # noqa: BLE001
            # Never let the gate be the reason a request fails.
            logger.warning("[module_gate] gate failed, letting request through",
                           exc_info=True)
            key, block = None, False

        if block and key:
            m = REGISTRY.get(key)
            label = m.label if m else key
            method, path = scope.get("method", "GET"), scope.get("path", "")
            _blocked[key] = _blocked.get(key, 0) + 1
            _blocked_examples[key] = f"{method} {path}"
            logger.info("[module_gate] blocked %s %s (%s is OFF)", method, path, key)
            response = JSONResponse(
                status_code=423,
                headers={"X-Module": key, "X-Module-Enabled": "0"},
                content={
                    "detail": f"{label} is switched OFF in Main Control, so this request "
                              f"was not run. Nothing was fetched and nothing was saved.",
                    "module": key,
                    "label": label,
                    "enabled": False,
                    "blocked_method": method,
                    "blocked_path": path,
                    "hint": "Turn it back on at /main-control.",
                })
            return await response(scope, receive, send)

        if key:
            # Served, but from frozen rows - mark it so a caller can tell live from stale.
            async def send_with_marker(message):
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers.append("X-Module", key)
                    headers.append("X-Module-Enabled", "0")
                await send(message)

            return await self.app(scope, receive, send_with_marker)

        return await self.app(scope, receive, send)
