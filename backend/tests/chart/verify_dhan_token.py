"""Verifies the single-flight Dhan token manager (app/services/dhan_token.py).

The bug this guards against is subtle and only shows up under concurrency: Dhan
allows one active session per account, so two simultaneous logins revoke each
other, and bursts trip its rate limit. These checks drive the real module against
an in-memory Redis stub and a fake Dhan, asserting that N concurrent refreshers
produce exactly ONE login.

Run:  cd backend && python tests/chart/verify_dhan_token.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("BROKER_ENCRYPTION_KEY", "")
if not os.environ["BROKER_ENCRYPTION_KEY"]:
    from cryptography.fernet import Fernet
    os.environ["BROKER_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got={got!r} want={want!r}")


def check_true(name, cond, detail=""):
    global failures
    if not cond:
        failures += 1
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' — ' + str(detail)) if detail else ''}")


# --- minimal async Redis stub: only what the lock actually uses -------------
class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.expiries: dict[str, float] = {}

    async def get(self, k):
        return self.store.get(k)

    async def exists(self, k):
        return 1 if k in self.store else 0

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        if ex:
            self.expiries[k] = ex
        return True

    async def eval(self, script, numkeys, key, arg):
        # Mirrors the compare-and-delete release script.
        if self.store.get(key) == arg:
            del self.store[key]
            return 1
        return 0


# --- fake Mongo collection --------------------------------------------------
class FakeCreds:
    def __init__(self):
        self.doc: dict | None = None

    async def find_one_and_update(self, query, update, upsert=False):
        self.doc = {**(self.doc or {}), **update["$set"]}
        return self.doc

    async def find_one(self, query, *a, **k):
        return self.doc


import app.core.db as db_mod  # noqa: E402

fake_creds = FakeCreds()
db_mod.broker_credentials_collection = fake_creds

from app.core.config import settings  # noqa: E402

settings.dhan_client_id = "1103401872"
settings.dhan_pin = "123456"
settings.dhan_totp_secret = "JBSWY3DPEHPK3PXP"

import app.services.dhan_token as dt  # noqa: E402

dt.broker_credentials_collection = fake_creds


def make_jwt(exp_dt: datetime) -> str:
    """A token shaped like Dhan's: JWT whose payload carries an `exp` claim."""
    import base64
    import json

    def seg(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{seg({'alg':'HS512'})}.{seg({'exp': int(exp_dt.timestamp()), 'dhanClientId':'1103401872'})}.sig"


LOGIN_CALLS = []


def install_fake_dhan(delay=0.05, raise_429=False):
    LOGIN_CALLS.clear()

    async def fake_totp_login(client_id, pin, secret):
        LOGIN_CALLS.append(datetime.now(timezone.utc))
        await asyncio.sleep(delay)  # simulate the network round-trip
        if raise_429:
            from app.services.dhan_client import DhanRateLimitError
            raise DhanRateLimitError("throttled")
        return {
            "dhanClientId": "1103401872",
            "dhanClientName": "TEST",
            "accessToken": make_jwt(datetime.now(timezone.utc) + timedelta(hours=24)),
            "expiryTime": "2026-07-22T20:46:30.272",
        }

    dt.totp_login = fake_totp_login


async def main():
    # ---- should_refresh is driven by real expiry, not wall-clock age --------
    await dt.store_token("u1", "1103401872", make_jwt(datetime.now(timezone.utc) + timedelta(hours=20)))
    fresh = await fake_creds.find_one({})
    check("a healthy token does NOT trigger a refresh", dt.should_refresh(fresh), False)
    check_true("stored token records its expiry", fresh.get("token_expiry") is not None, fresh.get("token_expiry"))

    await dt.store_token("u1", "1103401872", make_jwt(datetime.now(timezone.utc) + timedelta(minutes=5)))
    near = await fake_creds.find_one({})
    check("a near-expiry token DOES trigger a refresh", dt.should_refresh(near), True)

    await dt.store_token("u1", "1103401872", make_jwt(datetime.now(timezone.utc) - timedelta(hours=1)))
    expired = await fake_creds.find_one({})
    check("an already-expired token triggers a refresh", dt.should_refresh(expired), True)

    # ---- the core: concurrent refreshers must produce exactly ONE login -----
    dt._redis = FakeRedis()
    install_fake_dhan(delay=0.05)
    results = await asyncio.gather(*[dt.refresh_locked("u1") for _ in range(8)])
    check("8 concurrent refreshes performed exactly 1 Dhan login", len(LOGIN_CALLS), 1)
    check("exactly one caller reports having minted", sum(1 for r in results if r), 1)
    check_true("the rest deferred rather than erroring", all(r is False for r in results if not r))

    stored = await fake_creds.find_one({})
    check_true("the winner left a usable token behind", dt.seconds_remaining(stored) > 3600,
               dt.seconds_remaining(stored))

    # ---- the lock is released, so a later refresh can still happen ---------
    install_fake_dhan(delay=0.0)
    check("lock released — a subsequent refresh still mints", await dt.refresh_locked("u1"), True)
    check("that refresh was a single login", len(LOGIN_CALLS), 1)

    # ---- 429 sets a cooldown that suppresses further attempts --------------
    dt._redis = FakeRedis()
    install_fake_dhan(delay=0.0, raise_429=True)
    first = await dt.refresh_locked("u1")
    check("a 429 reports no mint", first, False)
    check("the 429 attempt still made exactly one call", len(LOGIN_CALLS), 1)
    calls_after_429 = len(LOGIN_CALLS)
    for _ in range(5):
        await dt.refresh_locked("u1")
    check("cooldown suppresses every follow-up login", len(LOGIN_CALLS), calls_after_429)
    check_true("cooldown key was set", await dt._redis.get(dt._COOLDOWN_KEY) is not None)

    # ---- Redis down must not disable refresh entirely -----------------------
    class BrokenRedis(FakeRedis):
        async def get(self, k):
            raise RuntimeError("redis down")

        async def set(self, k, v, nx=False, ex=None):
            raise RuntimeError("redis down")

        async def eval(self, *a, **k):
            raise RuntimeError("redis down")

    dt._redis = BrokenRedis()
    install_fake_dhan(delay=0.0)
    check("a broken Redis degrades to unlocked refresh, not to no refresh",
          await dt.refresh_locked("u1"), True)

    # ---- health surfaces something a human can read -------------------------
    dt._redis = FakeRedis()
    await dt.store_token("u1", "1103401872", make_jwt(datetime.now(timezone.utc) + timedelta(hours=10)))
    h = dt.health(await fake_creds.find_one({}))
    check("health reports a healthy token", h["token_healthy"], True)
    check_true("health reports remaining seconds ~10h", 35000 < h["seconds_remaining"] < 36500,
               h["seconds_remaining"])
    check("health of a missing connection is not healthy", dt.health(None)["token_healthy"], False)

    await dt.store_token("u1", "1103401872", make_jwt(datetime.now(timezone.utc) - timedelta(minutes=1)))
    h_exp = dt.health(await fake_creds.find_one({}))
    check("health reports an expired token as unhealthy", h_exp["token_healthy"], False)

    print()
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return 0 if failures == 0 else 1


raise SystemExit(asyncio.run(main()))
