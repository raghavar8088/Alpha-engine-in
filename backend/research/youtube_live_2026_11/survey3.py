"""Pass 3: newest stream's description (broker / referral links) for the big channels. Metadata only."""
import json, sys, re
import concurrent.futures as cf
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from survey import RAW, slug  # noqa: E402
from survey2 import video_meta  # noqa: E402

TARGETS = {
    "The Trade Room": "UC9zh516XCUhN1EVIdblTXXQ", "Trade Time With Pranjal": "UC5Pug1yQPkk3FG9ii04kVCg",
    "Vinbull Trading Academy": "UCvkKjDe2XGRYv3dn0_ahdug", "TRADE WITH MANSI": "UC2zdAZeihqvLsUsNx3et8gQ",
    "Market Trader": "UCXf5JQF72XZe_U10HF3SS6A", "Trading Techstreet": "UC6VsKH_O59Kdc_yYATRGc_A",
    "Traders Paradise Live": "UCUMAP6ENB2EIq04ZKMw4EqA", "Mehak Trades": "UCq5uGxe_EkZNqj9le3OXnKQ",
    "Trade Like Malika": "UCf6LtAmwVDvzq1myGwCRRmA", "Umar Punjabi Live": "UC7QFqtxMMFsPUO2rxZsBKEA",
    "Trade with Pat": "UC04-HvUvHG4hpMnQx07ObYQ", "TraderNick": "@TraderNick", "Crypto Face": "@CryptoFace",
    "Crypto Claudius": "UC7FkshE7oKhI1uoQBq9cuaA", "Riley Coleman": "@RileyColeman",
    "Crypto Banter": "@CryptoBanterGroup", "Lorenzo Corrado": "UCFEgynfV4t075rh5WowawDw",
    # added on 27 Nov 2026 for the YouTube Live Streaming page (brokers of every listed channel)
    "Booming Bulls": "@BoomingBulls", "Devansh Rai": "UCRem0cxZp0CNrJaFGRB2Tpw",
    "Bullish Master FX": "UCqAp2ZBo9pWZAUODe0OiJCw", "Trade For Profit": "UCQemzRWOMazoaSuULUuSCpg",
    "Shaakuni Trap": "UCBz5NCFRfIfNbXmwH1_qmww", "Balraj Trading Tech": "UCj7cny5FsrDD2AdLntePeiQ",
    "Young Trader Viraj": "UC8tnMSzCEcVn_9YGCF4V68w", "IITian Trader": "@IITianTrader",
    "Delta Exchange": "UCaw-1cUd74wvEatvZna0TzQ", "The Moon Show": "UCc4Rz_T9Sb1w5rqqo9pL1Og",
    "Crypto Capital Venture": "@CryptoCapitalVenture", "Krown": "UCnwxzpFzZNtLH8NgTeAROFA",
    "The Wolf Of All Streets": "UCxIU1RFIdDpvA8VOITswQ1A", "Crypto Jebb": "@CryptoJebb",
    "Trader Tom": "UC4C43bjs7bwwasNPecJm8bw", "Simply Forex": "@SimplyForex",
    "Markets With Mack": "UCtBjlVRuHjIQPws7tRe1IXg", "BIG BULL YT": "UCpoy0NO215QBKaQ28GMuS0g",
    "TraderXO": "@TraderXO", "TheChartGuys": "UCnqZ2hx679DqRi6khRUNw2g",
}
BROKERS = ["delta.exchange", "zuperior", "exness", "vigco", "vantage", "xm.com", "icmarkets", "pepperstone", "bybit",
           "binance", "bingx", "blofin", "bitunix", "toobit", "weex", "mexc", "coinswitch", "coindcx", "mudrex",
           "sharkexchange", "suncrypto", "pionex", "phemex", "okx", "bitget", "ftmo", "topstep", "apex", "fundednext",
           "the5ers", "fxify", "fundingpips", "tradovate", "ninjatrader", "elefin", "affs.click", "headway",
           "octa", "fbs", "puprime", "taurex", "startrader", "dhan", "angel", "zerodha", "upstox"]


def newest_id(target):
    p = RAW / f"streams_{slug(target)}.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for e in d.get("entries") or []:
        if e.get("live_status") in ("was_live", "is_live"):
            return e["id"]
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ids = {name: newest_id(t) for name, t in TARGETS.items()}
    with cf.ThreadPoolExecutor(4) as ex:
        metas = dict(ex.map(video_meta, [v for v in ids.values() if v]))
    out = {}
    for name, vid in ids.items():
        m = metas.get(vid) or {}
        raw = json.loads((RAW / f"video_{vid}.json").read_text(encoding="utf-8")) if vid and (RAW / f"video_{vid}.json").exists() else {}
        desc = raw.get("description") or ""
        hits = sorted({b for b in BROKERS if b in desc.lower()})
        tg = sorted(set(re.findall(r"t\.me/[^\s)]+", desc)))[:3]
        out[name] = {"vid": vid, "brokers": hits, "telegram": tg, "desc": re.sub(r"\s+", " ", desc)[:300]}
        print(f"{name} ({vid}): brokers={hits} tg={tg}")
        print(f"    {out[name]['desc'][:300]}")
    (HERE / "summary3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
