#!/usr/bin/env python3
"""Safe, reproducible daily 2024 strategy replay report builder.

No input records => no invented historic trades, returns, charts or metrics.
Build only from explicitly source-dated historical_data/*.csv. This status file
allows the public UI to explain exactly what is still missing.
"""
from __future__ import annotations
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0,str(ROOT))
from historical_backtest import CoverageError, SCHEMAS, read_inputs, replay

STATUS=ROOT/"historical-status.json"
OUT=ROOT/"historical-backtest.json"


def build():
    root=ROOT/"historical_data"
    counts={}
    for name,cols in SCHEMAS.items():
        path=root/(name+".csv")
        if not path.exists():
            counts[name]=0
        else:
            with path.open("r",encoding="utf-8-sig",newline="") as f:
                counts[name]=sum(1 for _ in csv.DictReader(f))
    status={
        "generated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "research_window_start":"2024-01-01",
        "universe_companies":30,
        "input_rows":counts,
        "data_delay":"Quotes refresh with the scheduled end-of-day GitHub Action, not tick-by-tick.",
        "source_authenticity":"URLs and dates are structurally validated; original issuer PDFs require human verification.",
        "retrospective":"Fixed 2026-selected universe; survivorship and selection biases cannot be ruled out."
    }
    try:
        results=replay(read_inputs(root))
        if not results["history"] or not results["decisions"]:
            raise CoverageError("Backtest produced no price history or trade decisions")
        status["status"]="research_backtest_available"
        status["validated_inputs"]=True
        status["days"]=len(results["history"])
        status["rebalance_days"]=len(results["decisions"])
        status["asof"]=results["through"]
        tmp=OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(results,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
        tmp.replace(OUT)
    except (CoverageError,ValueError,KeyError,TypeError,ZeroDivisionError) as e:
        status["status"]="source_data_incomplete"
        status["validated_inputs"]=False
        status["reason"]=str(e)
        # A stale previously published backtest cannot remain visible once
        # its input coverage or verification is invalid.
        if OUT.exists():OUT.unlink()
    STATUS.write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return status


if __name__=="__main__":
    s=build()
    print("Historical replay: "+s["status"]+"; rows "+str(s["input_rows"]))
    if s.get("reason"):print("  "+s["reason"])
