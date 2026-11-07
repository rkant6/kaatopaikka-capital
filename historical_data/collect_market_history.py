#!/usr/bin/env python3
"""Fetch historical market observations for 2024-onward margin-reversion research.

This module collects *real* daily OHLC close prices, corporate actions and
contemporaneous exchange rates. It does NOT fabricate financial statements,
earnings release dates, tax rates, share counts or historical betas.

The resulting prices.csv is intended as an INPUT to historical_backtest.py,
never as proof that the full strategy has been backtested. Its use may be
restricted by the market data supplier's license: do not commit/re-distribute
raw Yahoo historical records to a public GitHub repository without permission.

Run locally:
    python historical_data/collect_market_history.py --output historical_data/prices.csv

The default date window includes December 2023, which supplies the signals
for trades in January 2024.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import nordic_margin_reversion as model  # noqa: E402

START = date(2023, 12, 20)
CURRENCIES = dict(SEK="EURSEK=X", NOK="EURNOK=X", DKK="EURDKK=X", USD="EURUSD=X")
FIELDS = [
    "company", "date", "close", "dividend", "split_factor", "fx_to_eur",
    "reporting_fx_to_eur", "price_currency", "source_url", "fx_source_url",
]


class DataError(RuntimeError):
    """Unable to verify market data; do not quietly fill with 2026 quotes."""


def positive(x, field):
    try:
        value = float(x)
    except (TypeError, ValueError) as exc:
        raise DataError(f"Missing {field}: {x!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise DataError(f"Invalid {field}: {x!r}")
    return value


def reconstruct_as_traded(days):
    """Undo *future* splits embedded in Yahoo's split-adjusted historical Close.

    E.g. 4-for-1 in 2025: Close reported by Yahoo for 2024 may be 25 though
    its actual 2024 exchange quote was 100. Multiply by subsequent (not same
    day) split factors, then let the backtest perform the split on ex-date.
    Dividends in the historical feed may also be adjusted for later splits.
    """
    future_factor = 1.0
    rows = []
    for row in reversed(days):
        factor = row.get("split_factor", 1.0) or 1.0
        close = positive(row["close"], "Yahoo Close")
        dividend = float(row.get("dividend") or 0.0)
        if dividend < 0 or not math.isfinite(dividend):
            raise DataError("Invalid dividend")
        rows.append({
            "date": row["date"],
            "close": close * future_factor,
            "dividend": dividend * future_factor,
            "split_factor": positive(factor, "split ratio"),
        })
        future_factor *= positive(factor, "split ratio")
    rows.reverse()
    return rows


def download(ticker, start, end):
    import yfinance as yf
    last_error = None
    for attempt in range(4):
        try:
            hist = yf.Ticker(ticker).history(
                start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                interval="1d", auto_adjust=False, actions=True, keepna=False,
                timeout=25,
            )
            if hist.empty or "Close" not in hist:
                raise DataError(f"Yahoo returned no history for {ticker}")
            data = []
            for day, record in hist.iterrows():
                if math.isnan(float(record["Close"])):
                    continue
                iso = day.date().isoformat()
                if iso > end.isoformat():
                    continue
                data.append({
                    "date": iso,
                    "close": float(record["Close"]),
                    "dividend": float(record.get("Dividends", 0) or 0),
                    "split_factor": float(record.get("Stock Splits", 0) or 0) or 1.0,
                })
            if len(data) < 100:
                raise DataError(f"{ticker}: only {len(data)} observations")
            data.sort(key=lambda d: d["date"])
            if len({r["date"] for r in data}) != len(data):
                raise DataError(f"{ticker}: duplicate market sessions")
            return data
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
    raise DataError(f"Failed to download {ticker}: {last_error}") from last_error


def asof_rate(times, values, when, ticker, max_age=7):
    index = bisect_right(times, when) - 1
    if index < 0:
        raise DataError(f"No past FX quote for {ticker} at {when}")
    last = date.fromisoformat(times[index])
    current = date.fromisoformat(when)
    if (current - last).days > max_age:
        raise DataError(f"Stale FX {ticker}: {last} at {when}")
    return 1 / positive(values[index], f"EUR/{ticker} quote")


def collect(start=START, through=None, download_fn=download):
    through = through or date.today()
    if through < date(2024, 1, 2):
        raise DataError("Historical start needs at least one session in 2024")
    required_ccy = {
        c["trd"] for c in model.COMPANIES
    } | {c["rep"] for c in model.COMPANIES}
    fx = {}
    for ccy in sorted(required_ccy - {"EUR"}):
        ticker = CURRENCIES.get(ccy)
        if not ticker:
            raise DataError(f"No trusted FX ticker configured for currency {ccy}")
        rows = download_fn(ticker, start, through)
        fx[ccy] = (list(r["date"] for r in rows),
                   list(positive(r["close"], f"{ticker} close") for r in rows))
    output = []
    for company in model.COMPANIES:
        ticker = company["yf"]
        print(f"  {ticker} {company['name']}", flush=True)
        prices = reconstruct_as_traded(download_fn(ticker, start, through))
        if prices[0]["date"] > "2023-12-29":
            raise DataError(f"{ticker} has no price observation preceding 2024")
        for r in prices:
            def rate(ccy):
                return 1.0 if ccy == "EUR" else asof_rate(*fx[ccy], r["date"], CURRENCIES[ccy])
            rate_trade, rate_report = rate(company["trd"]), rate(company["rep"])
            output.append({
                "company": company["name"],
                "date": r["date"],
                "close": f"{r['close']:.8f}",
                "dividend": f"{r['dividend']:.8f}",
                "split_factor": f"{r['split_factor']:.8f}",
                "fx_to_eur": f"{rate_trade:.10f}",
                "reporting_fx_to_eur": f"{rate_report:.10f}",
                "price_currency": company["trd"],
                "source_url": "https://finance.yahoo.com/quote/" + ticker + "/history/",
                "fx_source_url": "https://finance.yahoo.com/quote/" + (
                    CURRENCIES.get(company["trd"]) or "EURUSD=X") + "/history/",
            })
    if len({r["company"] for r in output}) != len(model.COMPANIES):
        raise DataError("Price importer did not cover all 30 model companies")
    return sorted(output, key=lambda r: (r["date"], r["company"]))


def write_csv(output, rows):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".partial")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        tmp.replace(output)
    finally:
        if tmp.exists():
            tmp.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "historical_data" / "prices.csv")
    parser.add_argument("--through", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    values = collect(through=args.through)
    write_csv(args.output, values)
    print(f"Collected {len(values):,} actual price/FX records through "
          f"{values[-1]['date']}; stored at {args.output}")


if __name__ == "__main__":
    main()
