# Runs on the server host (python3, no dependencies). Output: /tmp/bn_bhav/<day>.json.gz -> copy to $BN_DATA/bhav/
"""Download NSE F&O bhavcopies day by day (old format to 2024-07-05, UDiFF after) and keep only
BANKNIFTY index options + futures: expiries <= 100 days out, option strikes within +-10% of the
nearest future. One gz JSON per day; resumable; a day NSE has no file for -> <day>.none."""
import csv, gzip, io, json, os, sys, time, urllib.request, zipfile
from datetime import date, datetime, timedelta

OUT = "/tmp/bn_bhav"
os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Referer": "https://www.nseindia.com/"}
START, END = date(2015, 1, 1), date(2026, 10, 9)
UDIFF_FROM = date(2024, 7, 8)


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def get(url):
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("failed " + url)


def rows_old(text, d):
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("SYMBOL", "").strip() != "BANKNIFTY" or r.get("INSTRUMENT", "").strip() not in ("OPTIDX", "FUTIDX"):
            continue
        exp = datetime.strptime(r["EXPIRY_DT"].strip(), "%d-%b-%Y").date()
        typ = "FUT" if r["INSTRUMENT"].strip() == "FUTIDX" else r["OPTION_TYP"].strip()
        out.append([typ, exp.isoformat(), fnum(r["STRIKE_PR"]), fnum(r["OPEN"]), fnum(r["HIGH"]), fnum(r["LOW"]),
                    fnum(r["CLOSE"]), fnum(r["SETTLE_PR"]), int(fnum(r["CONTRACTS"])), int(fnum(r["OPEN_INT"])), 0.0, 0])
    return out


def rows_udiff(text, d):
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("TckrSymb") != "BANKNIFTY" or r.get("FinInstrmTp") not in ("IDO", "IDF"):
            continue
        typ = "FUT" if r["FinInstrmTp"] == "IDF" else r["OptnTp"]
        out.append([typ, r["XpryDt"][:10], fnum(r["StrkPric"]), fnum(r["OpnPric"]), fnum(r["HghPric"]), fnum(r["LwPric"]),
                    fnum(r["ClsPric"]), fnum(r["SttlmPric"]), int(fnum(r["TtlTradgVol"])), int(fnum(r["OpnIntrst"])),
                    fnum(r["UndrlygPric"]), int(fnum(r["NewBrdLotQty"]))])
    return out


def keep(rows, d):
    futs = sorted((r for r in rows if r[0] == "FUT" and r[1] >= d.isoformat()), key=lambda r: r[1])
    ref = next((r[6] for r in futs if r[6] > 0), None)
    lim = (d + timedelta(days=100)).isoformat()
    out = []
    for r in rows:
        if r[1] < d.isoformat() or r[1] > lim:
            continue
        if r[0] != "FUT" and ref and abs(r[2] / ref - 1) > 0.10:
            continue
        out.append(r)
    return out


d, got, none, t0 = START, 0, 0, time.time()
while d <= END:
    f = f"{OUT}/{d.isoformat()}.json.gz"
    if d.weekday() < 5 and not os.path.exists(f) and not os.path.exists(f + ".none"):
        if d >= UDIFF_FROM:
            url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
        else:
            url = (f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{d.year}/"
                   f"{d.strftime('%b').upper()}/fo{d.strftime('%d%b%Y').upper()}bhav.csv.zip")
        raw = get(url)
        if raw is None:
            open(f + ".none", "w").close(); none += 1
        else:
            z = zipfile.ZipFile(io.BytesIO(raw))
            text = z.read(z.namelist()[0]).decode("utf-8", "replace")
            rows = keep(rows_udiff(text, d) if d >= UDIFF_FROM else rows_old(text, d), d)
            with gzip.open(f + ".tmp", "wt") as g:
                json.dump(rows, g, separators=(",", ":"))
            os.replace(f + ".tmp", f)
            got += 1
        if (got + none) % 100 == 0:
            print(f"{d} got={got} none={none} {time.time() - t0:.0f}s", flush=True)
        time.sleep(0.25)
    d += timedelta(days=1)
print(f"DONE got={got} none={none} {time.time() - t0:.0f}s", flush=True)
