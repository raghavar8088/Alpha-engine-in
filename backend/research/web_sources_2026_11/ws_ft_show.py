"""Print a freqtrade strategy's rule-bearing code with line numbers (evidence reading; parsing only, nothing runs).

    python -I ws_ft_show.py <clone root> <Class> [<Class> ...]

For each class: settings lines, then populate_indicators / entry / exit (and custom_* callbacks) without blank lines,
comments or docstrings, each line prefixed by its number in the file.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
INV = json.loads((HERE / "registry" / "freqtrade_inventory.json").read_text(encoding="utf-8"))
SHOW = ["populate_indicators", "populate_entry_trend", "populate_buy_trend", "populate_exit_trend", "populate_sell_trend",
        "custom_stoploss", "custom_exit", "custom_sell", "informative_pairs", "adjust_trade_position", "leverage"]


def docstring_lines(fn: ast.AST) -> set[int]:
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(getattr(n.body[0], "value", None), ast.Constant) and isinstance(n.body[0].value.value, str):
            out.update(range(n.body[0].lineno, n.body[0].end_lineno + 1))
    return out


def main(root: Path, names: list[str]) -> None:
    by = {r["class"]: r for r in INV["strategies"] if "class" in r}
    for name in names:
        r = by[name]
        lines = (root / r["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
        tree = ast.parse("\n".join(lines))
        doc = docstring_lines(tree)
        print(f"######## {name}  ({r['file']}, lines {r['lines'][0]}-{r['lines'][1]})")
        for k, v in r["settings"].items():
            print(f"  L{v['line']:<4} {k} = {json.dumps(v['value']) if not isinstance(v['value'], str) else v['value']}")
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
        extra = []
        for st in cls.body:
            # hyperopt parameters and other class constants the rules read (their defaults are the rules as shipped)
            if isinstance(st, (ast.Assign, ast.AnnAssign)):
                tgt = st.targets[0] if isinstance(st, ast.Assign) else st.target
                if isinstance(tgt, ast.Name) and tgt.id not in r["settings"] and tgt.id not in ("plot_config", "order_time_in_force"):
                    print(f"  L{st.lineno:<4} {ast.unparse(st)[:170]}")
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)) and st.name not in SHOW and not st.name.startswith("populate"):
                extra.append((st.name, st.lineno, st.end_lineno))
        for m in SHOW + [e[0] for e in extra]:
            if m in r["methods"]:
                a, b = r["methods"][m]["lines"]
            elif any(e[0] == m for e in extra):
                a, b = next((e[1], e[2]) for e in extra if e[0] == m)
            else:
                continue
            print(f"  --- {m} L{a}-{b}")
            for i in range(a, b + 1):
                s = lines[i - 1]
                t = s.strip()
                if not t or t.startswith("#") or i in doc or t.startswith("def ") or t in ("return dataframe", ")", "]", "),", "):"):
                    continue
                print(f"  L{i:<4} {t[:150]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
