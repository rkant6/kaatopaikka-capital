"""Point-in-time Nordic portfolio replay, 2024 onward.

This engine deliberately does NOT infer historical filings from today's Excel
snapshot. Every fact must have a separately recorded public release date.

Required CSVs in historical_data/:
  filings.csv: company,period_end,published_on,revenue_ttm_m,ebit_ttm_m,
      net_debt_m,shares_m,beta,tax_rate,structural_flag,source_url
  annual_margins.csv: company,fiscal_year,period_end,published_on,operating_margin,source_url
  prices.csv: company,date,close,dividend,split_factor,fx_to_eur,source_url

Monetary accounting amounts and shares are in millions; prices and dividends
are in the local share currency. fx_to_eur converts one local currency unit to
EUR. One session's close is used for execution; signals use the PREVIOUS
session's close and reports strictly older than that prior session's date.

No data -> no fictitious equity curve. Outputs are written only after passing
all point-in-time and data-continuity checks.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import nordic_margin_reversion as model
from update_site import HQ, STRATEGY, target_weights

HERE = Path(__file__).resolve().parent
START = date(2024, 1, 1)

SCHEMAS = {
    "filings": ("company", "period_end", "published_on", "revenue_ttm_m", "ebit_ttm_m",
                "net_debt_m", "shares_m", "beta", "tax_rate", "structural_flag", "source_url"),
    "annual_margins": ("company", "fiscal_year", "period_end", "published_on", "operating_margin", "source_url"),
    "prices": ("company", "date", "close", "dividend", "split_factor", "fx_to_eur", "source_url"),
}


class CoverageError(ValueError):
    """Missing or unverifiable historical observations; no backtest allowed."""


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CoverageError(f"Invalid {field} date {value!r}; use YYYY-MM-DD") from exc


def _number(row: dict, key: str) -> float:
    try:
        x = float(row[key])
    except (ValueError, TypeError, KeyError) as exc:
        raise CoverageError(f"Invalid or missing numeric {key} in {row.get('company')}") from exc
    if not math.isfinite(x):
        raise CoverageError(f"Non-finite {key} for {row.get('company')}")
    return x


def read_inputs(directory: Path) -> dict:
    """Reject missing source links, duplicate observations and untagged rows."""
    directory = Path(directory)
    valid_names = {c["name"] for c in model.COMPANIES}
    tables = {}
    for table, fields in SCHEMAS.items():
        path = directory / f"{table}.csv"
        if not path.is_file():
            raise CoverageError(f"Missing {path}; historical source data are not yet provided")
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not set(fields).issubset(reader.fieldnames or []):
                raise CoverageError(f"{path} must contain columns: {', '.join(fields)}")
            rows = list(reader)
        if not rows:
            raise CoverageError(f"{path} has no evidence-backed historical observations")
        for row in rows:
            if row["company"] not in valid_names:
                raise CoverageError(f"Unknown company {row['company']!r} in {path}")
            if not row["source_url"].startswith("https://"):
                raise CoverageError(f"Source URL missing/invalid for {row['company']} in {path}")
        tables[table] = rows

    for table in ("filings", "annual_margins"):
        for r in tables[table]:
            _day(r["published_on"], "published_on")
    for r in tables["filings"]:
        if _day(r["published_on"], "published_on") <= _day(r["period_end"], "period_end"):
            raise CoverageError(f"Report release precedes/equal to period end for {r['company']}")
        for col in ("revenue_ttm_m", "ebit_ttm_m", "net_debt_m", "shares_m", "beta", "tax_rate"):
            _number(r, col)
        if _number(r,"revenue_ttm_m") <= 0 or _number(r,"shares_m") <= 0 or not 0 <= _number(r,"tax_rate") < 1:
            raise CoverageError(f"Invalid financial scale for {r['company']}")
        if r["structural_flag"] not in ("Y", "N"):
            raise CoverageError(f"Expected contemporaneously documented Y/N structural_flag for {r['company']}")
    for r in tables["annual_margins"]:
        int(r["fiscal_year"])
        _number(r, "operating_margin")
        if _day(r["published_on"], "published_on") <= _day(r["period_end"], "period_end"):
            raise CoverageError(f"Annual margin published before period end for {r['company']}")
    for r in tables["prices"]:
        _day(r["date"], "price date")
        for col in ("close", "dividend", "split_factor", "fx_to_eur"):
            _number(r, col)
        if min(_number(r,"close"),_number(r,"split_factor"),_number(r,"fx_to_eur")) <= 0 or _number(r,"dividend") < 0:
            raise CoverageError(f"Invalid price/FX/split for {r['company']}")
    for table, key in (("filings","period_end"),("annual_margins","fiscal_year"),("prices","date")):
        seen=set()
        for r in tables[table]:
            k=(r["company"],r[key])
            if k in seen:raise CoverageError(f"Duplicate {table} observation for {k}")
            seen.add(k)
    return tables


def _latest(rows: list, as_of: date) -> dict | None:
    """Release date strictly BEFORE the price observation used for a decision."""
    available=[r for r in rows if _day(r["published_on"], "published_on") < as_of]
    return max(available,key=lambda r:r["published_on"]) if available else None


def point_in_time_model(tables: dict, signal_session: date, prices_on_signal: dict) -> list:
    """Rebuild the *current strategy rules* from data public at the signal date.

    The trading and reporting currencies may differ (five firms in the model).
    Quotes are in actual local trading currency, while the reports are in the
    original reporting currency. Convert before creating valuation inputs.
    """
    filings=defaultdict(list)
    annual=defaultdict(list)
    stock_actions=defaultdict(list)
    for row in tables["filings"]:
        filings[row["company"]].append(row)
    for row in tables["annual_margins"]:
        annual[row["company"]].append(row)
    for row in tables["prices"]:
        if _number(row, "split_factor") != 1:
            stock_actions[row["company"]].append(row)
    companies=[]
    all_latest_years=[]
    for base in model.COMPANIES:
        name=base["name"]
        doc=_latest(filings[name],signal_session)
        quote=prices_on_signal.get(name)
        if doc is None or quote is None:
            raise CoverageError(f"No point-in-time filing or quote for {name} on {signal_session}")
        if _day(quote["date"], "quote date") > signal_session:
            raise CoverageError(f"Future quote used by signal for {name}")
        c=copy.deepcopy(base)
        history={int(r["fiscal_year"]):_number(r,"operating_margin") for r in annual[name]
                 if _day(r["published_on"],"published_on") < signal_session
                 and _day(r["period_end"],"period_end") < signal_session}
        if len(history)<3:
            raise CoverageError(f"Fewer than three previously published annual margins for {name}")
        c["mar"]=[history.get(y) for y in model.YEARS]
        c["first"]=min(history)
        all_latest_years.append(max(history))
        c["flag"]=doc["structural_flag"]
        filing_date=_day(doc["published_on"],"published_on")
        shares=_number(doc,"shares_m")
        # After a split the shares outstanding from the previous report are
        # no longer valid; adjust using only splits between report and signal.
        for action in stock_actions[name]:
            dt=_day(action["date"],"split date")
            if filing_date < dt <= signal_session:
                shares*=_number(action,"split_factor")
        fx_trade=_number(quote,"fx_to_eur")
        if base["rep"]==base["trd"]:
            fx_report=fx_trade
        else:
            if not quote.get("reporting_fx_to_eur"):
                raise CoverageError(
                    f"Missing source-dated {base['rep']} reporting FX for {name} at {signal_session}")
            fx_report=_number(quote,"reporting_fx_to_eur")
        if fx_trade<=0 or fx_report<=0:
            raise CoverageError(f"Nonpositive FX for {name}")
        report_to_trade=fx_report/fx_trade
        price=_number(quote,"close")
        rev=_number(doc,"revenue_ttm_m")*report_to_trade
        ebit=_number(doc,"ebit_ttm_m")*report_to_trade
        net_debt=_number(doc,"net_debt_m")*report_to_trade
        mcap=price*shares
        c["tax_override"]=_number(doc,"tax_rate")
        c["mkt"]=(price,quote["date"],shares,mcap,net_debt,mcap+net_debt,rev,ebit,
                  _number(doc,"beta"))
        companies.append(c)
    assumptions=model.default_assumptions()
    # Conservative common last FY: FY2023 cannot enter a January 2024 model
    # merely because one firm later published its FY2023 annual report.
    assumptions["LastFY"]=min(min(all_latest_years),signal_session.year-1,model.YEARS[-1])
    if assumptions["LastFY"] not in model.YEARS:
        raise CoverageError(f"Insufficient dated annual-report history as at {signal_session}")
    try:
        return model.compute_model(companies,assumptions)
    except (TypeError,ValueError,ZeroDivisionError,IndexError) as exc:
        raise CoverageError(f"Historical model failed at {signal_session}: {exc}") from exc

def replay(tables: dict, through: date | None = None) -> dict:
    """Daily EUR NAV, signal at yesterday's close, trade at today's close.

    Monthly first-session rebalance; long-only, EUR 10k start; fractional
    shares, per-trade costs; historical splits/dividends applied on ex-date.
    Missing quotes/days are a hard failure instead of a forged flat price.
    """
    through=through or datetime.now(timezone.utc).date()
    names={c["name"] for c in model.COMPANIES}
    by_day=defaultdict(dict)
    for r in tables["prices"]:
        d=_day(r["date"],"date")
        if d<=through:by_day[d][r["company"]]=r
    sessions=sorted(by_day)
    if not sessions or sessions[0] >= START:
        raise CoverageError("Include the last trading session of 2023 for a leakage-free January 2024 first trade")
    valid=[d for d in sessions if START<=d<=through]
    if len(valid)<2:raise CoverageError("At least two post-2023 trading sessions are required")
    # All included sessions must cover the same 30 names, including delisted
    # securities when they appear in a properly constructed historic universe.
    for d in sessions:
        if set(by_day[d])!=names:
            absent=names-set(by_day[d]);raise CoverageError(f"Incomplete daily universe {d}; missing {', '.join(sorted(absent)[:4])}")
    cash=float(STRATEGY["start_capital"])
    holdings={n:0.0 for n in names}
    curve=[];decisions=[];events=[];snapshots=[]
    previous=sessions[sessions.index(valid[0])-1]
    last_month=None
    for day in valid:
        quotes=by_day[day]
        prior=by_day[previous]
        for name,units in list(holdings.items()):
            q=quotes[name]
            if units:
                factor=_number(q,"split_factor")
                holdings[name]=units*factor
                cash+=holdings[name]*_number(q,"dividend")*_number(q,"fx_to_eur")
        px={n:_number(quotes[n],"close")*_number(quotes[n],"fx_to_eur") for n in names}
        value=cash+sum(holdings[n]*px[n] for n in names)
        if (day.year,day.month)!=last_month:
            results=point_in_time_model(tables,previous,prior)
            weights,rationale=target_weights(results)
            snapshots.append({"date":day.isoformat(),"signal_asof":previous.isoformat(),
                              "companies":[{"id":HQ[r["name"]][3],"name":r["name"],
                                            "signal":r["signal"],"rank":r["rank"],
                                            "cur":r["cur"],"norm":r["norm"],"gap":r["gap"],
                                            "revUp":r["rev_upside"],"score":r["score"]}
                                           for r in results]})
            # Solve gross target weights subject to proportional trading fees.
            # Fixed-point convergence is fast at 15bps and is deterministic.
            investable=value
            for _ in range(8):
                costs=STRATEGY["cost"]*sum(abs(investable*weights.get(n,0)-holdings[n]*px[n]) for n in names)
                investable=value-costs
            orders=[]
            for name in sorted(names):
                old=holdings[name]
                desired=investable*weights.get(name,0)/px[name]
                trade=(desired-old)*px[name]
                if abs(trade)>=.0001:
                    orders.append({"company":name,"side":"BUY" if trade>0 else "SELL",
                                   "eur":round(abs(trade),2),"reason":rationale.get(name,"Dropped from eligible top five")})
                holdings[name]=desired
            cash=value-investable*sum(weights.values())-costs
            if cash < -.01:raise CoverageError(f"Negative cash from target allocations on {day}")
            decisions.append({"date":day.isoformat(),"signal_asof":previous.isoformat(),"orders":orders,
                              "source":"point-in-time reported filings and previous close"})
            last_month=(day.year,day.month)
            value=cash+sum(holdings[n]*px[n] for n in names)
        if curve:
            delta=value/curve[-1]["nav"]-1
            if delta <= -.05:
                events.append({"date":day.isoformat(),"type":"observed_drawdown",
                               "severity":round(abs(delta),4),"description":"Simulated daily portfolio decline"})
        curve.append({"date":day.isoformat(),"nav":round(value,4),"return":round(value/STRATEGY["start_capital"]-1,6)})
        previous=day
    return {"status":"research_backtest","from":valid[0].isoformat(),"through":valid[-1].isoformat(),
            "validated_inputs":True,"universe":"fixed 2026-selected 30-company universe; survivorship bias is possible",
            "execution":"previous-session close signals; next-session close fills; 0.15% cost; cash dividends and splits",
            "is_investable_track_record":False,"history":curve,"decisions":decisions,
            "snapshots":snapshots,"events":events}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs",type=Path,default=HERE/"historical_data")
    parser.add_argument("--output",type=Path,default=HERE/"historical-backtest.json")
    parser.add_argument("--through",type=date.fromisoformat,default=datetime.now(timezone.utc).date())
    args=parser.parse_args()
    try:
        result=replay(read_inputs(args.inputs),through=args.through)
    except CoverageError as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Validated {len(result['history'])} daily NAV observations and {len(result['decisions'])} trades/rebalances")


if __name__=="__main__":
    main()
