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
PY_FILES = ["update_site.py", "nordic_margin_reversion.py", "historical_backtest.py", "check_site.py",
            "historical_data/collect_market_history.py", "historical_data/refresh_status.py",
            "tests/test_historical_backtest.py"]
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
    # The professional terminal keeps JavaScript in a separate, testable asset.
    assets = [p.split("?")[0] for p in re.findall(
        r'<script[^>]+src="([^"]+\.js(?:\?[^"]*)?)"', html, re.I)]
    assets.append("assets/home-earth.js")  # intentionally cache-versioned in HTML
    assets.append("assets/solar-globe.js")  # loaded by classic.html, not index.html
    for rel in assets:
        if rel.startswith(('https://', 'http://')):
            continue
        source = os.path.join(HERE, rel)
        if not os.path.isfile(source):
            fail(f"missing JavaScript asset: {rel}")
        with open(source, encoding="utf-8") as f:
            code.append(f.read())
    if not code:
        fail("index.html has no testable JavaScript")
    for rel in [p.split("?")[0] for p in re.findall(
            r'<link[^>]+href="([^"]+\.css(?:\?[^"]*)?)"', html, re.I)]:
        if not rel.startswith(('https://', 'http://')) and not os.path.isfile(os.path.join(HERE, rel)):
            fail(f"missing CSS asset: {rel}")
    for id_ in ("overview-stats", "home-earth-canvas", "time-date-range", "time-play", "replay-mini-chart", "backtest-chart", "backtest-events", "backtest-orders", "research-rows", "portfolio-holdings", "journal-feed",
                "journal-rejected", "lab-company", "lab-chart", "lab-sensitivity",
                "lab-validation", "company-drawer", "classic-frame"):
        if f'id="{id_}"' not in html:
            fail(f"new terminal is missing required element: {id_}")
    if not os.path.exists(os.path.join(HERE, "classic.html")):
        fail("original 3D globe was not preserved as classic.html")
    if not os.path.isfile(os.path.join(HERE,"assets/solar-globe.css")):
        fail("missing astronomical globe styles")
    if "classic.html?embed=1" not in html:
        fail("3D globe embed must use dedicated no-overlap mode")
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
    print(f"  {len(code)} local script(s) referenced by index.html parse")
    astronomy=("const s=require('./assets/solar-globe.js').solarDirection;"
               "const v=s(new Date('2024-03-20T12:00:00Z'));"
               "const j=s(new Date('2024-06-21T12:00:00Z'));"
               "const d=s(new Date('2024-12-21T12:00:00Z'));"
               "if(Math.abs(Math.asin(v[1])*180/Math.PI)>1||"
               "Math.abs(Math.asin(j[1])*180/Math.PI-23.44)>1||"
               "Math.abs(Math.asin(d[1])*180/Math.PI+23.44)>1)throw Error('Solar declination error');"
               "for(const a of [v,j,d])if(Math.abs(Math.hypot(...a)-1)>1e-6)throw Error('Sun vector not normalized');"
               "console.log('  March equinox and both solstices: solar geometry OK')")
    check=subprocess.run([node,"-e",astronomy],cwd=HERE,capture_output=True,text=True)
    if check.returncode:fail(f"Solar position calculation failed:\n{check.stderr}")
    print(check.stdout.strip())
    smoke=subprocess.run([node,"tests/home_earth_smoke.js"],cwd=HERE,capture_output=True,text=True)
    if smoke.returncode:fail(f"Home globe runtime smoke test failed:\\n{smoke.stderr[-1800:]}")
    print(smoke.stdout.strip())
    if "assets/replay-desk.js" not in assets:
        fail("2024 replay JS was not included in the script verification")
    if "assets/replay-desk.css" not in html:
        fail("2024 replay stylesheet is missing")



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
        quality = data.get("meta", {}).get("quality", {})
        if quality.get("lastFiscalYear") != model.YEARS[-1] or "portfolioExecution" not in quality:
            fail("data freshness / execution disclosures missing")
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
        if not all("reason" in t for t in port.get("trades", [])):
            fail("trade rationale missing from decision journal")
        # Validate every published baseline against the same ten-year DCF
        # implemented in the client; these are genuinely recalculated values.
        valuations = data["companies"]
        if not all("valuation" in c and "netClaims" in c["valuation"] for c in valuations):
            fail("the published valuation snapshot is incomplete")
        node = shutil.which("node")
        if node:
            program = (
                "const fs=require('fs');"
                "const engine=require('./assets/valuation-engine.js');"
                "const data=JSON.parse(fs.readFileSync('data.json','utf8'));"
                "for(const c of data.companies){"
                " const v=engine.calculate(c.valuation);"
                " if(!v.valid || Math.abs(v.upside-c.fairUp)>1e-7)"
                " {throw Error(c.name+': DCF mismatch '+v.upside+' vs '+c.fairUp+' '+v.error)}}"
                "console.log('  DCF baselines reconcile for '+data.companies.length+' companies');"
            )
            result = subprocess.run([node,"-e",program],cwd=work,capture_output=True,text=True)
            if result.returncode:
                fail(f"browser DCF differs from Python's published values:\n{result.stderr[-2400:]}")
            print(result.stdout.strip())
        historical = subprocess.run(
            [sys.executable, "historical_data/refresh_status.py"],
            cwd=work, capture_output=True, text=True
        )
        if historical.returncode:
            fail("Status refresh failed: " + historical.stderr[-1500:])
        with open(os.path.join(work, "historical-status.json"),encoding="utf-8") as f:
            report=json.load(f)
        if report.get("validated_inputs") or report.get("status")!="source_data_incomplete":
            fail("Empty source files must NEVER produce 2024 strategy returns")
        if os.path.exists(os.path.join(work, "historical-backtest.json")):
            fail("Invented or stale historical return file was published")
        print("  Missing 2024 original filings correctly withhold historical returns")

        print(f"  {expected} companies, {len(port['holdings'])} holdings, {len(port['decisions'])} decisions, "
              f"value EUR {port['value']:,.0f}")


def main():
    for name, fn in (("Python", check_python), ("JavaScript", check_javascript),
                     ("Test run on mock prices", check_pipeline)):
        print(f"== {name}", flush=True)
        fn()
    print("== Point-in-time backtest tests",flush=True)
    r=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-p","test_*.py"],
                     cwd=HERE,capture_output=True,text=True)
    if r.returncode:fail(f"Historical replay checks failed:\n{r.stdout}\n{r.stderr}")
    print(r.stderr.strip().splitlines()[-1])
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
