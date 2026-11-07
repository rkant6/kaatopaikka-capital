"""Checks a change before it goes live.   Run:  python check_site.py

1. The Python files compile.
2. The JavaScript inside index.html has no syntax errors (needs Node.js; skipped without it).
3. update_site.py runs end to end on a throwaway copy with mock prices: a first buy,
   then a month-end rebalance, and the files it writes are valid.

The repository's own data files (data.json, portfolio.json, simulation.json, model.xlsx)
are never touched: everything runs in a temporary folder.
GitHub runs this on every pull request (.github/workflows/check.yml).
"""
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY_FILES = ["update_site.py", "nordic_margin_reversion.py", "check_site.py"]
OUTPUTS = ["data.json", "portfolio.json", "simulation.json", "model.xlsx"]


def fail(msg):
    print(f"\nFAILED: {msg}")
    sys.exit(1)


def check_python():
    for f in PY_FILES:
        try:
            py_compile.compile(os.path.join(HERE, f), doraise=True)
        except py_compile.PyCompileError as e:
            fail(f"{f} does not compile:\n{e.msg or e}")
    print(f"  {len(PY_FILES)} Python files compile")


def check_javascript():
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        html = f.read()
    blocks = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I)
    code = [body for attrs, body in blocks if "src=" not in attrs and "json" not in attrs.lower() and body.strip()]
    if not code:
        fail("index.html has no inline JavaScript")
    node = shutil.which("node")
    if not node:
        print("  Node.js not found: JavaScript check skipped")
        return
    with tempfile.TemporaryDirectory() as d:
        for i, body in enumerate(code, 1):
            path = os.path.join(d, f"block{i}.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            r = subprocess.run([node, "--check", path], capture_output=True, text=True)
            if r.returncode:
                fail(f"JavaScript syntax error in index.html, inline <script> block {i}:\n{r.stderr.strip()}")
    print(f"  {len(code)} inline script block(s) in index.html parse")


def check_pipeline():
    with tempfile.TemporaryDirectory() as d:
        work = os.path.join(d, "site")
        shutil.copytree(HERE, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        for f in OUTPUTS:                                   # start like a fresh repository
            if f != "data.json" and os.path.exists(os.path.join(work, f)):
                os.remove(os.path.join(work, f))
        for date in ("2026-01-30", "2026-02-02"):           # first buy, then a new month = rebalance
            t = time.time()
            r = subprocess.run([sys.executable, "update_site.py", "--mock", "--date", date],
                               cwd=work, capture_output=True, text=True)
            if r.returncode:
                fail(f"update_site.py --mock --date {date} crashed:\n{(r.stdout + r.stderr)[-3000:]}")
            print(f"  mock run {date} OK ({time.time() - t:.0f} s)")
        for f in OUTPUTS:
            if not os.path.exists(os.path.join(work, f)):
                fail(f"update_site.py did not write {f}")
        for f in OUTPUTS[:3]:
            try:
                with open(os.path.join(work, f), encoding="utf-8") as fh:
                    json.load(fh)
            except ValueError as e:
                fail(f"{f} is not valid JSON: {e}")
        with open(os.path.join(work, "data.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        with open(os.path.join(work, "portfolio.json"), encoding="utf-8") as fh:
            port = json.load(fh)
        sys.path.insert(0, work)
        import nordic_margin_reversion as model
        import update_site as site
        expected = len(model.COMPANIES)
        if len(data.get("companies", [])) != expected:
            fail(f"data.json has {len(data.get('companies', []))} companies, nordic_margin_reversion.py has {expected}")
        missing = [c["name"] for c in model.COMPANIES if c["name"] not in site.HQ]
        if missing:
            fail(f"no headquarters location in update_site.py HQ for: {', '.join(missing)}")
        if port.get("status") != "live" or not port.get("holdings"):
            fail("the paper portfolio did not buy anything")
        held = port["cash"] + sum(h["value"] for h in port["holdings"])
        if abs(held - port["value"]) > 0.01 or port["cash"] < -0.01:
            fail(f"portfolio does not add up: cash + holdings {held:,.2f} vs value {port['value']:,.2f}")
        if len(port.get("decisions", [])) < 2:
            fail("the month-end rebalance did not run")
        print(f"  {expected} companies, {len(port['holdings'])} holdings, {len(port['decisions'])} decisions, "
              f"value EUR {port['value']:,.0f}")


def main():
    for name, fn in (("Python", check_python), ("JavaScript", check_javascript),
                     ("Test run on mock prices", check_pipeline)):
        print(f"== {name}", flush=True)
        fn()
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
