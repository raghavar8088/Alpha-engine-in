"""Angel One (SmartAPI) price feed — the standby the desks fall back to when Dhan's
quote feed is unusable.

WHY A SECOND FEED AT ALL
------------------------
The desks' single documented failure mode is not bad strategy logic, it is a blind feed.
Dhan permits exactly one active token per account, so any component that mints a token
silently invalidates whoever else was holding one, and the desk spends the session
taking 401s. It also rate-limits per account (429). Both have produced whole zero-trade
sessions on the buying desk. A second, independent broker session removes the single
point of failure for PRICES specifically — not for orders, which this desk never places.

WHAT THIS IS NOT
----------------
It is not a general Angel One broker integration. It answers exactly one question —
"what is this instrument trading at right now?" — because that is the only thing the
paper desks need a broker for.

THE HARD PART IS INSTRUMENT IDENTITY, NOT THE HTTP
---------------------------------------------------
Dhan and Angel One name the same contract differently. The desks hold Dhan
`security_id`s, and Angel One only answers to its own `symboltoken`. Translating between
them cannot be guessed, so the mapping is built by matching on the contract's REAL
identity — underlying, expiry date, strike and option type — read from Angel's published
scrip master. Anything that fails to match is left unmapped and reported as unpriceable.

That last point is the important safety property. A price feed that returns the WRONG
contract's price is far more dangerous than one that returns nothing: on a short option
position a wrong mark does not fail loudly, it silently mis-marks the book and can fire
or suppress a stop. So every failure path here returns None, never a guess.

MEASURED COVERAGE (2026-07-21, against the live account)
--------------------------------------------------------
Login, scrip-master download and quoting all verified end to end. Of ~4000 NIFTY option
rows in this app's `instruments` collection, ~1475 map to an Angel token — and that gap
is expected rather than a defect: Angel's master lists only ~1600 NIFTY OPTIDX contracts
at all, because our collection accumulates expired contracts and far-out strikes the
exchange does not actively list.

What matters is coverage where the desk actually trades. Near-ATM strikes on the front
expiry — which is where 15-delta short legs live — mapped and priced 10 of 10, with
sensible values (23600CE at 653.85 against spot 24216: intrinsic 616 plus time value).
Deep strikes thousands of points from spot return None, correctly, because Angel does
not list them.

So: treat this as a standby that covers the tradeable book, not the whole instrument
universe. If a future strategy ever sells strikes far from spot, re-measure before
relying on the failover for them.

CREDENTIALS come from the encrypted `broker_credentials` collection (same Fernet pattern
as Dhan) or from env, never from a file checked into the repo.
"""

import os
import time
from datetime import datetime

import requests

BASE_URL = "https://apiconnect.angelone.in"
LOGIN_PATH = "/rest/auth/angelbroking/user/v1/loginByPassword"
QUOTE_PATH = "/rest/secure/angelbroking/market/v1/quote"
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# Angel's batch quote accepts many tokens per exchange in one call; keep well under any
# per-request ceiling and well under a per-second limit the desks could otherwise trip.
MAX_TOKENS_PER_REQUEST = 50
REQUEST_GAP_SECONDS = 0.35

# Dhan exchange segment -> Angel exchange code, for the segments the desks actually use.
SEGMENT_TO_EXCHANGE = {
    "IDX_I": "NSE",     # index spot
    "NSE_FNO": "NFO",   # index/stock options and futures
    "NSE_EQ": "NSE",
}


def _totp(secret: str) -> str:
    """Current TOTP for the SmartAPI login. pyotp if present, otherwise a local
    implementation so this module does not add a hard dependency for one 6-digit code."""
    try:
        import pyotp

        return pyotp.TOTP(secret).now()
    except ImportError:
        import base64
        import hashlib
        import hmac
        import struct

        key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
        counter = struct.pack(">Q", int(time.time()) // 30)
        digest = hmac.new(key, counter, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return f"{code % 1000000:06d}"


def load_angel_credentials() -> dict | None:
    """Angel One credentials from the encrypted credential store, falling back to env.

    Returns None when nothing is configured, which is a normal state: the failover is
    optional and its absence must degrade to "Dhan only", never to a crash.
    """
    try:
        from cryptography.fernet import Fernet

        from db_selling import _db

        doc = _db["broker_credentials"].find_one({"broker": "angelone"})
        if doc:
            key = os.getenv("BROKER_ENCRYPTION_KEY", "").encode()
            def _dec(v):
                if not v:
                    return ""
                try:
                    return Fernet(key).decrypt(v.encode()).decode()
                except Exception:
                    return v  # stored in the clear (older docs)
            return {
                "api_key": _dec(doc.get("api_key_encrypted")) or doc.get("api_key", ""),
                "client_id": doc.get("client_id", ""),
                "pin": _dec(doc.get("pin_encrypted")) or doc.get("pin", ""),
                "totp_secret": _dec(doc.get("totp_secret_encrypted")) or doc.get("totp_secret", ""),
            }
    except Exception as exc:
        print(f"[angel] credential store unavailable ({exc}) — trying env", flush=True)

    api_key = os.getenv("ANGEL_API_KEY")
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "client_id": os.getenv("ANGEL_CLIENT_ID", ""),
        "pin": os.getenv("ANGEL_PIN", ""),
        "totp_secret": os.getenv("ANGEL_TOTP_SECRET", ""),
    }


class AngelScripMap:
    """Dhan security_id -> Angel symboltoken, matched on real contract identity.

    Built once per process from Angel's published scrip master and the app's own
    `instruments` collection. Only NIFTY index + its options are mapped, because that is
    the entire universe both desks trade; widening it is a matter of relaxing the filter.
    """

    def __init__(self):
        self.by_security_id: dict[str, tuple[str, str]] = {}  # dhan sid -> (exchange, token)
        self.built_at: datetime | None = None
        self.unmapped: int = 0

    def build(self) -> bool:
        try:
            from db_selling import instruments_collection

            raw = requests.get(SCRIP_MASTER_URL, timeout=60).json()
        except Exception as exc:
            print(f"[angel] could not fetch scrip master: {exc}", flush=True)
            return False

        # Angel: strike is in PAISE, expiry like '31JUL2026'. Index options carry
        # instrumenttype OPTIDX and name NIFTY.
        angel_opts: dict[tuple, str] = {}
        angel_index: dict[str, str] = {}
        for row in raw:
            seg = row.get("exch_seg")
            name = (row.get("name") or "").upper()
            if seg == "NFO" and row.get("instrumenttype") == "OPTIDX" and name == "NIFTY":
                try:
                    expiry = datetime.strptime(row["expiry"], "%d%b%Y").date().isoformat()
                    strike = round(float(row["strike"]) / 100.0, 2)
                except Exception:
                    continue
                sym = (row.get("symbol") or "").upper()
                opt = "CE" if sym.endswith("CE") else "PE" if sym.endswith("PE") else None
                if opt:
                    angel_opts[(expiry, strike, opt)] = row["token"]
            elif seg == "NSE" and name in ("NIFTY", "NIFTY 50"):
                angel_index[name] = row["token"]

        mapped = unmapped = 0
        for inst in instruments_collection.find(
            {"$or": [
                {"asset_class": "INDEX_OPTION", "symbol": {"$regex": "^NIFTY-"}},
                {"asset_class": "INDEX", "symbol": "NIFTY"},
            ]},
            {"security_id": 1, "asset_class": 1, "expiry": 1, "strike": 1, "option_type": 1},
        ):
            sid = str(inst.get("security_id"))
            if inst.get("asset_class") == "INDEX":
                token = angel_index.get("NIFTY 50") or angel_index.get("NIFTY")
                if token:
                    self.by_security_id[sid] = ("NSE", token)
                    mapped += 1
                else:
                    unmapped += 1
                continue
            key = (inst.get("expiry"), round(float(inst.get("strike", 0)), 2),
                   inst.get("option_type"))
            token = angel_opts.get(key)
            if token:
                self.by_security_id[sid] = ("NFO", token)
                mapped += 1
            else:
                unmapped += 1

        self.built_at = datetime.now()
        self.unmapped = unmapped
        print(f"[angel] scrip map built: {mapped} contracts mapped, {unmapped} unmapped "
              f"(unmapped stay unpriceable — never guessed)", flush=True)
        return mapped > 0

    def lookup(self, security_id, exchange_segment) -> tuple[str, str] | None:
        hit = self.by_security_id.get(str(security_id))
        if hit:
            return hit
        # No positional guess: an unmapped contract is unpriceable, not approximated.
        return None


class AngelOneFeed:
    """Batched LTP over SmartAPI. Same call shape the desks already use for Dhan:
    prefetch(...) then ltp(security_id, segment)."""

    def __init__(self, scrip_map: AngelScripMap | None = None):
        self.creds = load_angel_credentials()
        self.jwt: str | None = None
        self.scrip_map = scrip_map or AngelScripMap()
        self._cache: dict[tuple[str, str], float] = {}
        self._requested: set = set()
        self._last_request = 0.0
        self._map_ready = False
        self.available = self.creds is not None

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json", "Accept": "application/json",
            "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self.creds["api_key"],
        }
        if self.jwt:
            h["Authorization"] = f"Bearer {self.jwt}"
        return h

    def login(self) -> bool:
        if not self.creds:
            return False
        try:
            body = {
                "clientcode": self.creds["client_id"],
                "password": self.creds["pin"],
                "totp": _totp(self.creds["totp_secret"]),
            }
            r = requests.post(BASE_URL + LOGIN_PATH, headers=self._headers(), json=body, timeout=15)
            data = r.json() if r.content else {}
            if r.status_code != 200 or not data.get("status"):
                print(f"[angel] login failed HTTP {r.status_code}: "
                      f"{str(data.get('message') or r.text)[:160]}", flush=True)
                return False
            self.jwt = data["data"]["jwtToken"].replace("Bearer ", "")
            print("[angel] logged in — standby feed ready", flush=True)
            return True
        except Exception as exc:
            print(f"[angel] login error: {exc}", flush=True)
            return False

    def ensure_ready(self) -> bool:
        """Log in and build the scrip map on first real use, not at construction — the
        standby should cost nothing while Dhan is healthy."""
        if not self.available:
            return False
        if self.jwt is None and not self.login():
            return False
        if not self._map_ready:
            self._map_ready = self.scrip_map.build()
        return self._map_ready

    def prefetch(self, segment_ids: dict[str, list]) -> None:
        self._cache = {}
        self._requested = {(str(s), seg) for seg, ids in segment_ids.items() for s in ids}
        if not self.ensure_ready():
            return

        by_exchange: dict[str, list[str]] = {}
        token_to_key: dict[tuple[str, str], tuple[str, str]] = {}
        for seg, ids in segment_ids.items():
            for sid in ids:
                hit = self.scrip_map.lookup(sid, seg)
                if hit is None:
                    continue
                exchange, token = hit
                by_exchange.setdefault(exchange, []).append(token)
                token_to_key[(exchange, token)] = (str(sid), seg)
        if not by_exchange:
            return

        for exchange, tokens in by_exchange.items():
            for i in range(0, len(tokens), MAX_TOKENS_PER_REQUEST):
                chunk = tokens[i:i + MAX_TOKENS_PER_REQUEST]
                gap = REQUEST_GAP_SECONDS - (time.monotonic() - self._last_request)
                if gap > 0:
                    time.sleep(gap)
                self._last_request = time.monotonic()
                try:
                    r = requests.post(
                        BASE_URL + QUOTE_PATH, headers=self._headers(),
                        json={"mode": "LTP", "exchangeTokens": {exchange: chunk}}, timeout=12,
                    )
                    if r.status_code == 401:
                        self.jwt = None  # session died; next ensure_ready re-logs in
                        print("[angel] 401 — session expired, will re-login", flush=True)
                        return
                    if r.status_code != 200:
                        print(f"[angel] quote HTTP {r.status_code}: {r.text[:160]}", flush=True)
                        continue
                    payload = r.json().get("data") or {}
                    for row in payload.get("fetched") or []:
                        key = token_to_key.get((row.get("exchange"), str(row.get("symbolToken"))))
                        ltp = row.get("ltp")
                        if key and ltp is not None:
                            self._cache[key] = float(ltp)
                except Exception as exc:
                    print(f"[angel] quote error: {exc}", flush=True)

    def spot(self) -> float | None:
        return self.ltp(13, "IDX_I")

    def ltp(self, security_id, exchange_segment) -> float | None:
        return self._cache.get((str(security_id), exchange_segment))


class FailoverFeed:
    """Dhan first, Angel One when Dhan cannot answer.

    Failover is per-TICK and evidence-based, never a permanent switch: Dhan is retried
    on every tick, and the standby is used only for the securities Dhan actually failed
    to price. Dhan remains the desk's book of record because it is the account the
    strategies were qualified against; Angel exists so a token rotation or a 429 costs
    the desk visibility rather than the whole session.

    Presents exactly the DhanFeed surface (prefetch/spot/ltp/rate_limited/...) so both
    daemons can use it without knowing a second broker exists.
    """

    def __init__(self, dhan_feed, angel_feed: AngelOneFeed | None = None):
        self.dhan = dhan_feed
        self.angel = angel_feed or AngelOneFeed()
        self.failover_ticks = 0
        self.failover_prices = 0
        self._last_note = 0.0

    # --- pass-throughs the daemons read for feed-health reporting ---
    @property
    def rate_limited(self):
        return self.dhan.rate_limited

    @property
    def throttled_ticks(self):
        return self.dhan.throttled_ticks

    @property
    def auth_failed_ticks(self):
        return self.dhan.auth_failed_ticks

    def prefetch(self, segment_ids: dict[str, list]) -> None:
        self.dhan.prefetch(segment_ids)
        # Which securities did Dhan fail to price this tick?
        missing: dict[str, list] = {}
        for seg, ids in segment_ids.items():
            for sid in ids:
                if self.dhan.ltp(sid, seg) is None:
                    missing.setdefault(seg, []).append(sid)
        if not missing or not self.angel.available:
            return
        self.failover_ticks += 1
        if time.time() - self._last_note > 60:
            self._last_note = time.time()
            total = sum(len(v) for v in missing.values())
            print(f"[failover] Dhan could not price {total} security(s) — asking Angel One",
                  flush=True)
        self.angel.prefetch(missing)

    def spot(self) -> float | None:
        return self.ltp(13, "IDX_I")

    def ltp(self, security_id, exchange_segment) -> float | None:
        price = self.dhan.ltp(security_id, exchange_segment)
        if price is not None:
            return price
        price = self.angel.ltp(security_id, exchange_segment)
        if price is not None:
            self.failover_prices += 1
        return price
