"""Stand-ins for the Mongo driver and pydantic-settings, so pure logic can be tested.

`aliases`, `scoring` and `nlq` contain no I/O at all, but importing any of them goes
through the package `__init__`, which reaches `enrich` -> `app.core.db` -> `motor`. Rather
than install a database driver to test a string-ranking function, both are stubbed.

Shared by the tests in this directory instead of pasted into each: the stub is identical
for all of them, and three copies would drift.
"""

import sys
import types
from pathlib import Path


def stub_infra() -> None:
    """Put the backend on sys.path and neutralise the two import-time dependencies."""
    backend = str(Path(__file__).resolve().parents[2])
    if backend not in sys.path:
        sys.path.insert(0, backend)

    if "pydantic_settings" not in sys.modules:
        try:
            import pydantic_settings  # noqa: F401
        except ImportError:
            from pydantic import BaseModel

            ps = types.ModuleType("pydantic_settings")
            ps.BaseSettings = type("BaseSettings", (BaseModel,),
                                   {"model_config": {"extra": "ignore"}})
            ps.SettingsConfigDict = dict
            sys.modules["pydantic_settings"] = ps

    if "motor" not in sys.modules:
        class _Coll:
            def __getattr__(self, _item):
                raise AssertionError("these tests never touch Mongo")

        class _DB:
            def __getitem__(self, _name):
                return _Coll()

        class _Client:
            def __init__(self, *a, **k):
                pass

            def __getitem__(self, _name):
                return _DB()

        motor = types.ModuleType("motor")
        ma = types.ModuleType("motor.motor_asyncio")
        ma.AsyncIOMotorClient = _Client
        ma.AsyncIOMotorCollection = _Coll
        motor.motor_asyncio = ma
        sys.modules["motor"] = motor
        sys.modules["motor.motor_asyncio"] = ma
