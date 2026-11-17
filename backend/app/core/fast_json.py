"""Byte-identical JSON responses without FastAPI's pure-Python encoder pass.

WHY
---
For every route that returns a dict, FastAPI 0.115 runs `jsonable_encoder` over the whole
result - a recursive pure-Python walk with a dozen isinstance checks per value - and then
`json.dumps` over the copy it built. Both run ON THE EVENT LOOP, and this app's event loop is
the one every desk's scheduler and every other request shares, on a CPU-throttled box. A
page's 0.6-2 MB answers (option qualifiers, strategy lists, commodity positions, the ATH
universe) held the loop for that walk, and every request behind them waited: endpoints that
take ~1 s alone averaged 13 s four at a time (2026-11-16).

WHAT THIS DOES
--------------
One `json.dumps` in C, calling back into Python only for values the C encoder cannot write
(datetimes, mostly). Those go through the SAME conversions `jsonable_encoder` uses - dates
and times by `isoformat()`, everything else by `jsonable_encoder` itself - with the same
`json.dumps` options Starlette's JSONResponse uses. The bytes are the bytes the old path
produced; measured ~5x faster on a datetime-heavy 1.7 MB payload, more on plain numbers.

WHERE IT DOES NOT APPLY, AND THE FALLBACK
-----------------------------------------
* Routes with a `response_model` keep FastAPI's own validate-and-serialise path untouched.
* Routes that return a Response object, or declare a non-default `response_class`, are left
  alone (they never reach the encoder).
* ANY exception in the fast path - a datetime used as a dict key, NaN, a type the C encoder
  meets that `jsonable_encoder` would rename - falls back to the original call, so the result
  (including its error, where there was one) is exactly what it was before.

`tests/core/test_fast_json.py` pins the byte-identity on the awkward cases.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from contextvars import ContextVar

import fastapi.routing as _fr
from fastapi.datastructures import DefaultPlaceholder
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
from starlette.routing import request_response

logger = logging.getLogger("fast_json")

_ACTIVE: ContextVar[bool] = ContextVar("fast_json_active", default=False)
_original_serialize = _fr.serialize_response
_stats = {"fast": 0, "fallback": 0, "routes": 0}


class _Rendered:
    """Already-encoded JSON, handed from the serializer to FastJSONResponse.render."""

    __slots__ = ("body",)

    def __init__(self, body: bytes):
        self.body = body


class FastJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        if isinstance(content, _Rendered):
            return content.body
        return super().render(content)


def _default(o):
    # The hot case first: Motor hands back tz-aware datetimes on nearly every row.
    if isinstance(o, (_dt.date, _dt.time)):
        return o.isoformat()
    return jsonable_encoder(o)


def dumps(content) -> bytes:
    """Exactly Starlette's JSONResponse.render(jsonable_encoder(content)), or an exception."""
    return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=None,
                      separators=(",", ":"), default=_default).encode("utf-8")


async def _serialize_response(*, field=None, response_content, **kwargs):
    if field is None and _ACTIVE.get():
        try:
            body = dumps(response_content)
            _stats["fast"] += 1
            return _Rendered(body)
        except Exception:  # noqa: BLE001 - the original path decides, as it always did
            _stats["fallback"] += 1
    return await _original_serialize(field=field, response_content=response_content, **kwargs)


def _wrap(handler):
    async def fast_handler(request):
        token = _ACTIVE.set(True)
        try:
            return await handler(request)
        finally:
            _ACTIVE.reset(token)
    return fast_handler


def install(app) -> int:
    """Switch every default-JSON route registered so far onto the fast path. Never raises."""
    try:
        _fr.serialize_response = _serialize_response
        n = 0
        for route in app.router.routes:
            if not isinstance(route, APIRoute):
                continue
            rc = route.response_class
            if not (isinstance(rc, DefaultPlaceholder) and rc.value is JSONResponse):
                continue
            route.response_class = FastJSONResponse
            route.app = request_response(_wrap(route.get_route_handler()))
            n += 1
        _stats["routes"] = n
        logger.info("[fast_json] %d routes on the fast JSON path", n)
        return n
    except Exception:  # noqa: BLE001 - a speed-up must never be why the app fails to start
        _fr.serialize_response = _original_serialize
        logger.exception("[fast_json] install failed - responses use FastAPI's encoder")
        return 0


def stats() -> dict:
    return dict(_stats)
