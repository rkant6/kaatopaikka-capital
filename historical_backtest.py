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
    """Research-only 2024 replay: look-ahead-safe trades and auditable events.

    Use all actual Nordic exchange sessions for NAV marks, but execute monthly
    rebalances only when all 30 local markets have a contemporaneous close.
    A recent holiday close may be carried forward for NAV (never fabricated).
    """
    through=through or datetime.now(timezone.utc).date()
    if through<START:
        raise CoverageError("End date precedes January 2024")
    names={c["name"] for c in model.COMPANIES}
    by_day=defaultdict(dict)
    for row in tables["prices"]:
        d=_day(row["date"],"quote date")
        if d<=through:
            by_day[d][row["company"]]=row
    sessions=sorted(by_day)
    before=[d for d in sessions if d<START]
    valid=[d for d in sessions if START<=d<=through]
    if not before:
        raise CoverageError("The final 2023 trading sessions are required for the first January 2024 signal")
    if len(valid)<2:
        raise CoverageError("Fewer than two dated trading sessions since January 2024")
    if len(names)!=len(model.COMPANIES):
        raise CoverageError("Company identifiers must be unique")
    seen=set()
    for d,quotes in by_day.items():
        for n in quotes:
            if n not in names:
                raise CoverageError(f"Unrecognized security on {d}: {n}")
            seen.add(n)
    if seen!=names:
        raise CoverageError("Historical price set does not cover the fixed 30-company universe")
    # Weekends and national holidays differ across Nordic markets. Carry only
    # explicitly observed recent closes; fail instead of manufacturing price
    # paths through a suspension, delisting or missing data outage.
    last_quotes={}
    for d in before:
        last_quotes.update(by_day[d])
    if set(last_quotes)!=names:
        raise CoverageError("Missing pre-2024 last closes for parts of the universe")
    max_carry_days=8
    def check_quotes(day,rows):
        stale=[]
        for name in sorted(names):
            row=rows.get(name)
            if row is None:
                raise CoverageError(f"Missing quote for {name} at {day}")
            age=(day-_day(row["date"],"quote date")).days
            if age<0 or age>max_carry_days:
                raise CoverageError(f"Unverified/stale {name} price from {row['date']} at {day}")
            if age:
                stale.append((name,age))
        return stale
    check_quotes(valid[0],last_quotes | by_day[valid[0]])
    filings_by_name=defaultdict(list)
    for row in tables["filings"]:
        filings_by_name[row["company"]].append(row)
    cash=float(STRATEGY["start_capital"])
    benchmark_cash=float(STRATEGY["start_capital"])
    holdings={n:0.0 for n in names}
    benchmark_units={n:0.0 for n in names}
    curve=[];decisions=[];events=[];snapshots=[]
    last_month=None
    previous=before[-1]
    # Published earnings provide real-world chronological context for replay.
    # Sources must be attached to each event in the raw input files.
    for row in tables["filings"]:
        d=_day(row["published_on"],"published_on")
        if START<=d<=through:
            margin=_number(row,"ebit_ttm_m")/_number(row,"revenue_ttm_m")
            events.append({"date":d.isoformat(),"type":"earnings",
                           "company":row["company"],"source_url":row["source_url"],
                           "period_end":row["period_end"],
                           "margin_ttm":round(margin,6),
                           "description":f"{row['company']} released results for {row['period_end']}; "
                                         f"reported trailing operating margin {margin:.1%}."})
    for day in valid:
        prior=last_quotes.copy()
        check_quotes(previous,prior)
        actual_today=by_day[day]
        last_quotes.update(actual_today)
        held_stale=check_quotes(day,last_quotes)
        px={n:_number(last_quotes[n],"close")*_number(last_quotes[n],"fx_to_eur")
            for n in names}
        for n,row in actual_today.items():
            factor=_number(row,"split_factor")
            dividend=_number(row,"dividend")
            if holdings[n]>0:
                if factor!=1:
                    holdings[n]*=factor
                    events.append({"date":day.isoformat(),"type":"split","company":n,
                                   "factor":factor,
                                   "description":f"{n} stock split factor {factor:.3g} applied to held shares.",
                                   "source_url":row["source_url"]})
                if dividend>0:
                    amount=holdings[n]*dividend*_number(row,"fx_to_eur")
                    cash+=amount
                    events.append({"date":day.isoformat(),"type":"dividend","company":n,
                                   "amount_eur":round(amount,4),
                                   "description":f"{n}: {amount:.2f} EUR cash dividend received.",
                                   "source_url":row["source_url"]})
            if benchmark_units[n]>0:
                if factor!=1:
                    benchmark_units[n]*=factor
                if dividend>0:
                    benchmark_cash+=benchmark_units[n]*dividend*_number(row,"fx_to_eur")
        value=cash+sum(holdings[n]*px[n] for n in names)
        # The benchmark is an equal-weight buy-and-hold of the 30 constituents,
        # explicitly subject to the same initial 0.15% execution cost.
        open_together=len(actual_today)==len(names)
        if last_month is None and open_together:
            allocation=(benchmark_cash*(1-STRATEGY["cost"]))/len(names)
            for n in names:
                benchmark_units[n]=allocation/px[n]
            benchmark_cash=0.0
        if (day.year,day.month)!=last_month and open_together:
            results=point_in_time_model(tables,previous,prior)
            weights,rationale=target_weights(results)
            if any(not math.isfinite(v) or v<0 for v in weights.values()):
                raise CoverageError(f"Invalid portfolio weights at {day}")
            total_weights=sum(weights.values())
            if total_weights>1.000001:
                raise CoverageError(f"Target portfolio exceeds 100% at {day}")
            evidence={}
            for c in model.COMPANIES:
                doc=_latest(filings_by_name[c["name"]],previous)
                evidence[c["name"]]={
                    "published_on":doc["published_on"],
                    "period_end":doc["period_end"],
                    "source_url":doc["source_url"]
                }
            snapshots.append({
                "date":day.isoformat(),"signal_asof":previous.isoformat(),
                "companies":[{"id":HQ[r["name"]][3],"name":r["name"],
                              "signal":r["signal"],"rank":r["rank"],
                              "cur":r["cur"],"norm":r["norm"],
                              "gap":r["gap"],"revUp":r["rev_upside"],
                              "score":r["score"]} for r in results],
                "evidence":{k:evidence[k] for k in weights}
            })
            # Fixed-point solve for turnover fees before target sizing.
            investable=value
            for _ in range(14):
                costs=STRATEGY["cost"]*sum(
                    abs(investable*weights.get(n,0)-holdings[n]*px[n])
                    for n in names)
                investable=value-costs
                if investable<0:
                    raise CoverageError(f"Trade costs exceeded NAV at {day}")
            orders=[]
            for name in sorted(names):
                old=holdings[name]
                desired=investable*weights.get(name,0)/px[name]
                trade=(desired-old)*px[name]
                if abs(trade)>=0.0001:
                    order={
                        "company":name,"id":HQ[name][3],
                        "side":"BUY" if trade>0 else "SELL",
                        "eur":round(abs(trade),2),
                        "shares_delta":round(desired-old,8),
                        "price_eur":round(px[name],6),
                        "price_local":_number(actual_today[name],"close"),
                        "fx_to_eur":_number(actual_today[name],"fx_to_eur"),
                        "fee_eur":round(abs(trade)*STRATEGY["cost"],4),
                        "reason":rationale.get(name,"No longer in eligible top five"),
                        "source_url":evidence[name]["source_url"],
                        "report_published_on":evidence[name]["published_on"]
                    }
                    orders.append(order)
                    events.append({
                        "date":day.isoformat(),"type":"trade","company":name,
                        "side":order["side"],"eur":order["eur"],
                        "description":f"{order['side']} {name} for EUR {order['eur']:,.2f}. "
                                      f"{order['reason']}.",
                        "source_url":order["source_url"],
                        "report_published_on":order["report_published_on"]
                    })
                holdings[name]=desired
            cash=value-investable*total_weights-costs
            if cash < -0.01:
                raise CoverageError(f"Negative cash from allocations on {day}")
            decisions.append({
                "date":day.isoformat(),"signal_asof":previous.isoformat(),
                "orders":orders,"fees_eur":round(costs,4),
                "portfolio_weights":weights,
                "source":"Strict previous-session prices and prior published filings"
            })
            events.append({
                "date":day.isoformat(),"type":"rebalance",
                "description":f"Monthly model rebalance: {len(orders)} trades, "
                              f"EUR {costs:.2f} estimated costs.",
                "trade_count":len(orders),
                "source_url":None
            })
            last_month=(day.year,day.month)
            value=cash+sum(holdings[n]*px[n] for n in names)
        benchmark_nav=benchmark_cash+sum(benchmark_units[n]*px[n] for n in names)
        if curve:
            daily=value/curve[-1]["nav"]-1
            if daily<=-.05:
                events.append({"date":day.isoformat(),
                               "type":"observed_drawdown",
                               "severity":round(abs(daily),6),
                               "description":f"Simulated strategy declined {abs(daily):.1%} since "
                                             "the prior market session."})
        positions=[
            {"id":HQ[n][3],"name":n,
             "value":round(holdings[n]*px[n],4),
             "weight":round(holdings[n]*px[n]/value,8) if value else 0}
            for n in sorted(names) if holdings[n]>.00000001
        ]
        curve.append({
            "date":day.isoformat(),"nav":round(value,4),
            "bench_nav":round(benchmark_nav,4),
            "return":round(value/STRATEGY["start_capital"]-1,8),
            "bench_return":round(benchmark_nav/STRATEGY["start_capital"]-1,8),
            "cash_eur":round(cash,4),
            "positions":positions,
            "carried_quotes":len(held_stale)
        })
        previous=day
    if not decisions:
        raise CoverageError("Never observed a day when all required Nordic markets were open")
    events.sort(key=lambda e:(e["date"],{"earnings":0,"rebalance":1,"trade":2,
                                      "split":3,"dividend":4,
                                      "observed_drawdown":5}.get(e["type"],6)))
    return {
        "status":"research_backtest",
        "from":valid[0].isoformat(),"through":valid[-1].isoformat(),
        "validated_inputs":True,
        "universe":"Fixed 2026-selected 30-company universe, survivorship and strategy-selection bias",
        "execution":"Prior-session published filings and closes; next common session close; "
                    "0.15% turnover cost; actual dated dividends/splits; holiday quotes carried up to 8 days",
        "benchmark":"Equal-weight 30-company buy-and-hold, 0.15% initial entry cost, dividends and splits",
        "is_investable_track_record":False,
        "is_hypothetical_retrospective":True,
        "last_rebuilt_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "history":curve,"decisions":decisions,"snapshots":snapshots,"events":events
    }

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
