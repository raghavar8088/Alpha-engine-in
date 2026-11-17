"""Verify app.core.fast_json: every route answers with the SAME BYTES as FastAPI's own path.

Run:  python backend/tests/main_control/verify_fast_json.py

Two identical apps are built from one route list; only one gets `fast_json.install`. Every
route is called on both and the bodies, status codes and content types must match exactly -
including the routes whose payloads the C encoder cannot write directly (datetime keys, NaN,
ObjectId-like objects), which must fall back and fail or succeed exactly as before.
"""

import asyncio
import dataclasses
import datetime as dt
import enum
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, PlainTextResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.core import fast_json  # noqa: E402

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class Side(str, enum.Enum):
    BUY = "BUY"


class Plain(enum.Enum):
    A = 3


class Item(BaseModel):
    name: str
    at: dt.datetime
    qty: int = 1


@dataclasses.dataclass
class DC:
    x: float
    when: dt.date


class Opaque:
    """Neither the C encoder nor jsonable_encoder knows this; both must refuse it."""
    __slots__ = ("v",)

    def __init__(self):
        self.v = 1


def row(i):
    return {
        "id": uuid.UUID(int=i), "sym": f"S{i}", "px": 100.25 + i, "tiny": 1e-05 * i, "neg0": -0.0,
        "naive": dt.datetime(2026, 11, 16, 9, 15, 3, 123000), "utc": dt.datetime(2026, 11, 16, 3, 45, tzinfo=dt.timezone.utc),
        "ist": dt.datetime(2026, 11, 16, 9, 15, tzinfo=IST), "day": dt.date(2026, 11, 16), "t": dt.time(9, 15),
        "td": dt.timedelta(seconds=90), "dec": Decimal("1.50"), "deci": Decimal("3"), "side": Side.BUY,
        "plain": Plain.A, "set": {1}, "tuple": (1, 2), "none": None, "nested": {"k": [1, {"z": True}], 3: "intkey"},
        "big": 10 ** 18, "uni": "₹ Δ é", "bytes": b"ok", "model": Item(name="a", at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)),
        "dc": DC(1.5, dt.date(2026, 1, 2)),
    }


ROUTES = {
    "/rows": lambda: [row(i) for i in range(50)],
    "/empty": lambda: {},
    "/list": lambda: [1, 2, 3],
    "/str": lambda: "hello",
    "/none": lambda: None,
    "/model": lambda: Item(name="m", at=dt.datetime(2026, 2, 3, 4, 5, 6, tzinfo=IST)),
    "/datekey": lambda: {dt.date(2026, 1, 1): 1},            # C encoder refuses: falls back, works
    "/enumkey": lambda: {Side.BUY: 1},
    "/plainenumkey": lambda: {Plain.A: 1},                   # falls back
    "/nan": lambda: {"v": float("nan")},                     # both must 500
    "/opaque": lambda: {"v": Opaque()},                      # both must 500
    "/gen": lambda: {"g": (i for i in range(3))},
}


def build(fast: bool) -> FastAPI:
    app = FastAPI()
    for path, fn in ROUTES.items():
        def endpoint(fn=fn):
            return fn()
        app.add_api_route(path, endpoint, methods=["GET"])

    @app.get("/model-response", response_model=Item)
    async def with_model():
        return {"name": "x", "at": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), "extra": 1}

    @app.get("/html", response_class=HTMLResponse)
    async def html():
        return "<b>x</b>"

    @app.get("/text", response_class=PlainTextResponse)
    async def text():
        return "plain"

    @app.get("/async-rows")
    async def async_rows():
        return [row(i) for i in range(5)]

    if fast:
        n = fast_json.install(app)
        assert n >= len(ROUTES) + 2, n          # the two default-JSON extras; never html/text
    return app


async def main() -> int:
    slow_app, fast_app = build(False), build(True)
    paths = list(ROUTES) + ["/model-response", "/html", "/text", "/async-rows"]
    failures = 0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=slow_app, raise_app_exceptions=False),
                                 base_url="http://t") as slow, \
            httpx.AsyncClient(transport=httpx.ASGITransport(app=fast_app, raise_app_exceptions=False),
                              base_url="http://t") as fast:
        for p in paths:
            a, b = await slow.get(p), await fast.get(p)
            same = (a.status_code, a.content, a.headers.get("content-type")) == \
                   (b.status_code, b.content, b.headers.get("content-type"))
            print(f"{'OK  ' if same else 'FAIL'} {p:18s} {a.status_code} {len(a.content)}B")
            if not same:
                failures += 1
                print("   old:", a.status_code, a.content[:300])
                print("   new:", b.status_code, b.content[:300])
    print("stats:", fast_json.stats())
    assert fast_json.stats()["fallback"] >= 3, "datekey / plainenumkey / nan / opaque should fall back"

    big = [row(i) for i in range(3000)]
    from fastapi.encoders import jsonable_encoder
    from starlette.responses import JSONResponse
    t = time.perf_counter(); old = JSONResponse(jsonable_encoder(big)).body; t_old = time.perf_counter() - t
    t = time.perf_counter(); new = fast_json.dumps(big); t_new = time.perf_counter() - t
    assert old == new
    print(f"3,000 rows ({len(new) / 1e6:.2f} MB): FastAPI path {t_old:.3f}s, fast path {t_new:.3f}s "
          f"({t_old / t_new:.1f}x)")
    print("ALL IDENTICAL" if not failures else f"{failures} DIFFERENCES")
    return failures


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
