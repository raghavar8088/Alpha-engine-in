"""Static inventory of the freqtrade-strategies repository (STEP 1-2 evidence, no execution).

Reads every strategy file with ast.parse (parsing never runs the code) and records, per IStrategy class: the settings
freqtrade reads from class attributes (timeframe, minimal_roi, stoploss, trailing, can_short, startup candles, exit
flags), the line ranges of each populate_* / custom_* method, the indicator calls each method makes, and review flags
(negative shifts and other look-ahead patterns, network / file / process access, synthetic Heikin-Ashi prices,
position adjustment = averaging, informative pairs = other timeframes).

    python -I ws_freqtrade_inventory.py <path to the freqtrade-strategies clone>

Writes registry/freqtrade_inventory.json. The clone is untrusted data: this script never imports or executes it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "registry" / "freqtrade_inventory.json"
SETTINGS = ["timeframe", "minimal_roi", "stoploss", "trailing_stop", "trailing_stop_positive",
            "trailing_stop_positive_offset", "trailing_only_offset_is_reached", "can_short", "startup_candle_count",
            "process_only_new_candles", "use_exit_signal", "use_sell_signal", "exit_profit_only", "sell_profit_only",
            "ignore_roi_if_entry_signal", "ignore_roi_if_buy_signal", "position_adjustment_enable",
            "max_entry_position_adjustment", "use_custom_stoploss", "order_types", "INTERFACE_VERSION"]
METHODS = ["populate_indicators", "populate_entry_trend", "populate_buy_trend", "populate_exit_trend",
           "populate_sell_trend", "custom_stoploss", "custom_exit", "custom_sell", "informative_pairs",
           "adjust_trade_position", "leverage", "confirm_trade_entry", "custom_entry_price", "custom_exit_price"]
FLAGS = [
    (r"\.shift\(\s*-\s*\d", "lookahead", "negative shift reads a FUTURE row"),
    (r"\bcenter\s*=\s*True", "lookahead", "centered rolling window uses future rows"),
    (r"\.iloc\[\s*-\s*1\s*\]", "review", "reads the LAST row of the whole frame (whole-frame value used as a signal input?)"),
    (r"\b(max|min|mean|std)\(\)\s*(?![\w.(])", "review", "whole-column aggregate (may use the full history, future included)"),
    (r"\bheikinashi\b|heikin", "synthetic", "Heikin-Ashi candles: synthetic prices, not executable fills"),
    (r"\bresample\(", "timeframe", "resampling inside the strategy: check bar alignment and that only closed bars are used"),
    (r"\bmerge\(", "timeframe", "merging frames: check the informative bar is closed before it is used"),
    (r"\b(requests|urllib|httpx|socket|aiohttp)\b", "unsafe", "network access"),
    (r"\b(subprocess|os\.system|eval|exec)\b", "unsafe", "process or code execution"),
    (r"\bopen\(|\.to_csv\(|\.to_pickle\(|Path\(", "unsafe", "filesystem access"),
]


def lit(node):
    try:
        return ast.literal_eval(node)
    except Exception:  # noqa: BLE001
        return ast.unparse(node)[:200]


def calls_in(src: str) -> list[str]:
    names = re.findall(r"\b((?:ta|talib|qtpylib|pta|ftt|technical|indicators|tv|qtpylib\.indicators)\.[A-Za-z_][\w.]*)\s*\(", src)
    return sorted(set(names))


def main(root: Path) -> None:
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    rows = []
    for f in sorted(root.rglob("*.py")):
        if ".git" in f.parts:
            continue
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            rows.append({"file": rel, "error": f"syntax error line {e.lineno}"})
            continue
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            bases = [ast.unparse(b) for b in cls.bases]
            if not any(re.search(r"IStrategy|Strategy", b) for b in bases):
                continue
            rec = {"file": rel, "class": cls.name, "bases": bases, "lines": [cls.lineno, cls.end_lineno],
                   "sha256_file": hashlib.sha256(text.encode()).hexdigest(), "settings": {}, "methods": {}, "flags": []}
            for st in cls.body:
                if isinstance(st, ast.Assign):
                    for t in st.targets:
                        if isinstance(t, ast.Name) and t.id in SETTINGS:
                            rec["settings"][t.id] = {"value": lit(st.value), "line": st.lineno}
                elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.target.id in SETTINGS and st.value:
                    rec["settings"][st.target.id] = {"value": lit(st.value), "line": st.lineno}
                elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)) and st.name in METHODS:
                    body = "\n".join(lines[st.lineno - 1:st.end_lineno])
                    rec["methods"][st.name] = {"lines": [st.lineno, st.end_lineno], "calls": calls_in(body)}
            block = lines[cls.lineno - 1:cls.end_lineno]
            for i, ln in enumerate(block, start=cls.lineno):
                code = ln.split("#", 1)[0]
                for pat, kind, why in FLAGS:
                    if re.search(pat, code):
                        rec["flags"].append({"kind": kind, "line": i, "why": why, "code": ln.strip()[:160]})
            # module-level imports matter too (network / process libraries)
            for n in tree.body:
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    mod = (n.module or "") if isinstance(n, ast.ImportFrom) else ",".join(a.name for a in n.names)
                    if re.search(r"requests|urllib|httpx|socket|aiohttp|subprocess", mod):
                        rec["flags"].append({"kind": "unsafe", "line": n.lineno, "why": "imports " + mod, "code": ast.unparse(n)[:160]})
            rec["shorts"] = bool(rec["settings"].get("can_short", {}).get("value") is True)
            rec["averaging"] = bool(rec["settings"].get("position_adjustment_enable", {}).get("value") is True) or "adjust_trade_position" in rec["methods"]
            rec["informative"] = "informative_pairs" in rec["methods"] or bool(re.search(r"@informative|merge_informative_pair", "\n".join(block)))
            rows.append(rec)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"repo": "https://github.com/freqtrade/freqtrade-strategies", "commit": head,
                               "licence": "GPL-3.0 (repository LICENSE)", "strategies": rows}, indent=1), encoding="utf-8")
    print(f"commit {head}: {sum('class' in r for r in rows)} strategy classes in {len({r['file'] for r in rows})} files -> {OUT.name}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
