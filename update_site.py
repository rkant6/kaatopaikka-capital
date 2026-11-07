#!/usr/bin/env python3
"""
Kaatopaikka Capital - daily site updater
========================================

Runs once a day (GitHub Actions, see .github/workflows/daily-update.yml):

  1. Fetches the latest closing price of the 30 companies and EUR FX rates
     (yfinance).
  2. Re-runs the margin reversion model (nordic_margin_reversion.py) with the
     new prices -> data.json (what the globe and the ranking show).
  3. Updates the EUR 10,000 paper portfolio: buys on the first run, marks to
     market every day, rebalances on the first run of each month
     -> portfolio.json.
  4. Re-runs the Monte Carlo projection -> simulation.json.
  5. Rebuilds the Excel model with today's prices -> model.xlsx.

Margins (financial statements) only change when companies report; update the
history in nordic_margin_reversion.py once a quarter.

Usage:
    python update_site.py                 # normal daily run (needs internet)
    python update_site.py --mock --date 2026-11-09   # offline test with random prices
    python update_site.py --reset         # put the portfolio back to "pending"
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import statistics
from collections import Counter
from datetime import datetime, timezone

import numpy as np

import nordic_margin_reversion as m

HERE = os.path.dirname(os.path.abspath(__file__))
def P(name): return os.path.join(HERE, name)

# --------------------------------------------------------------------------- HQ
# (city, lat, lon, url id) - city/district level
HQ = {
    "Atlas Copco": ("Nacka, Stockholm", 59.3045, 18.1290, "atlas-copco"),
    "Sandvik": ("Stockholm", 59.3326, 18.0560, "sandvik"),
    "SKF": ("Gothenburg", 57.7215, 11.9420, "skf"),
    "Volvo": ("Gothenburg", 57.7150, 11.9100, "volvo"),
    "Alfa Laval": ("Lund", 55.7160, 13.2120, "alfa-laval"),
    "Epiroc": ("Nacka, Stockholm", 59.3049, 18.1318, "epiroc"),
    "Assa Abloy": ("Stockholm", 59.3330, 18.0540, "assa-abloy"),
    "Husqvarna": ("Stockholm", 59.3490, 18.0340, "husqvarna"),
    "Trelleborg": ("Trelleborg", 55.3755, 13.1570, "trelleborg"),
    "Indutrade": ("Kista, Stockholm", 59.4035, 17.9445, "indutrade"),
    "NIBE": ("Markaryd", 56.4600, 13.5960, "nibe"),
    "Saab": ("Stockholm", 59.3380, 18.0580, "saab"),
    "Skanska": ("Stockholm", 59.3385, 18.0170, "skanska"),
    "Lifco": ("Enköping", 59.6360, 17.0770, "lifco"),
    "KONE": ("Espoo", 60.1770, 24.8290, "kone"),
    "Wärtsilä": ("Helsinki", 60.1625, 24.9080, "wartsila"),
    "Metso": ("Espoo", 60.1595, 24.7380, "metso"),
    "Valmet": ("Espoo", 60.1760, 24.8255, "valmet"),
    "Konecranes": ("Hyvinkää", 60.6315, 24.8580, "konecranes"),
    "Ponsse": ("Vieremä", 63.7445, 27.0040, "ponsse"),
    "Kongsberg Gruppen": ("Kongsberg", 59.6670, 9.6490, "kongsberg"),
    "Tomra": ("Asker", 59.8335, 10.4340, "tomra"),
    "Veidekke": ("Oslo", 59.9225, 10.6800, "veidekke"),
    "Vestas": ("Aarhus", 56.1930, 10.1450, "vestas"),
    "DSV": ("Hedehusene", 55.6485, 12.2050, "dsv"),
    "FLSmidth": ("Valby, Copenhagen", 55.6600, 12.5035, "flsmidth"),
    "Rockwool": ("Hedehusene", 55.6468, 12.1875, "rockwool"),
    "NKT": ("Brøndby", 55.6555, 12.4010, "nkt"),
    "ISS": ("Søborg, Copenhagen", 55.7320, 12.4960, "iss"),
    "A.P. Møller-Mærsk": ("Copenhagen", 55.6885, 12.5945, "maersk"),
}
FX_TICKERS = {"SEK": "EURSEK=X", "NOK": "EURNOK=X", "DKK": "EURDKK=X"}
FX_FALLBACK = {"SEK": 10.98, "NOK": 10.80, "DKK": 7.4749, "EUR": 1.0}   # ECB 30 Oct 2026 (NOK ~early Oct)

# --------------------------------------------------------------------------- strategy spec
STRATEGY = dict(
    start_capital=10_000.0,
    n_holdings=5,          # concentrated: five positions
    max_weight=0.30,       # max 30 % in one stock
    watch_haircut=0.5,     # WATCH (possible value trap) names get half weight
    cost=0.0015,           # 0.15 % of traded value per trade (commission + spread)
)
RULES = [
    "Start with EUR 10,000, fully invested, long only, no leverage.",
    "Buy the 5 highest composite scores whose reversion upside is positive and whose signal is not SHORT.",
    "Weight = reversion upside x adjusted beta: bigger upside and higher market risk get more money (risk-seeking tilt).",
    "WATCH names (margin below normal but still falling) get half weight. Max 30 % per stock.",
    "Rebalance on the first trading day of each month to the latest model; sell anything that drops out.",
    "Trading cost 0.15 % of traded value. Prices are closing prices converted to EUR; dividends are not included.",
]

# Monte Carlo assumptions (documented on the site)
SIM = dict(paths=4000, months=36, seed=2026,
           edge_haircut=0.5,   # only half of the model's mispricing is assumed real
           noise_share=0.35,   # share of idiosyncratic price moves that is noise and later reverts
           mkt_mu=0.07, mkt_sigma=0.17)


def beta_adj(b):
    return max(0.70, 0.67 * b + 0.33)


def cap_normalize(raw: dict, cap: float) -> dict:
    tot = sum(v for v in raw.values() if v > 0)
    if tot <= 0:
        return {}
    w = {k: v / tot for k, v in raw.items() if v > 0}
    for _ in range(20):
        over = {k for k, v in w.items() if v > cap + 1e-12}
        if not over:
            break
        excess = sum(w[k] - cap for k in over)
        for k in over:
            w[k] = cap
        free = {k: v for k, v in w.items() if v < cap - 1e-12}
        ft = sum(free.values())
        if ft <= 0:
            break                       # everything capped -> remainder stays in cash
        for k, v in free.items():
            w[k] = v + excess * v / ft
    return w


def target_weights(results, spec=STRATEGY):
    cands = [r for r in results if r["eligible"] and r["rev_upside"] > 0
             and not r["signal"].startswith(("SHORT", "EXCLUDED"))]
    cands.sort(key=lambda r: -(r["score"] if r["score"] is not None else -99))
    raw, why = {}, {}
    for r in cands[:spec["n_holdings"]]:
        w = r["rev_upside"] * beta_adj(r["beta"])
        if r["signal"].startswith("WATCH"):
            w *= spec["watch_haircut"]
        raw[r["name"]] = w
        why[r["name"]] = (f"rank {r['rank']}, {r['signal']}, reversion upside {r['rev_upside']:+.0%}, "
                          f"adj. beta {beta_adj(r['beta']):.2f}")
    return cap_normalize(raw, spec["max_weight"]), why


# --------------------------------------------------------------------------- prices
def fetch_live(companies):
    import yfinance as yf
    prices, fx = {}, dict(FX_FALLBACK)
    import time
    for c in companies:
        for attempt in range(3):                       # Yahoo occasionally throttles cloud runners
            try:
                h = yf.Ticker(c["yf"]).history(period="10d", interval="1d", auto_adjust=False)
                h = h[h["Close"].notna()]
                if len(h):
                    prices[c["name"]] = (float(h["Close"].iloc[-1]), h.index[-1].strftime("%Y-%m-%d"))
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  price attempt {attempt + 1} failed {c['yf']}: {e}")
            time.sleep(2 + 3 * attempt)
    for ccy, t in FX_TICKERS.items():
        try:
            h = yf.Ticker(t).history(period="10d", interval="1d")
            h = h[h["Close"].notna()]
            if len(h):
                fx[ccy] = float(h["Close"].iloc[-1])
        except Exception as e:  # noqa: BLE001
            print(f"  fx failed {t}: {e}")
    return prices, fx


def fetch_mock(companies, prev, day):
    """Offline test: random daily moves from the previous price (deterministic per day)."""
    rnd = random.Random(day)
    prices = {}
    for c in companies:
        p0 = prev.get(c["name"], (c["mkt"][0], None))[0]
        prices[c["name"]] = (round(p0 * math.exp(rnd.gauss(0.0004, 0.018)), 4), day)
    fx = {k: v * math.exp(rnd.gauss(0, 0.003)) if k != "EUR" else 1.0 for k, v in FX_FALLBACK.items()}
    return prices, fx


def apply_prices(companies, prices, prev):
    """New price -> new market cap and EV (net debt and other EV items kept from the snapshot)."""
    out = copy.deepcopy(companies)
    used = {}
    for c in out:
        p_snap, d_snap, sh, mcap, nd, ev, rev, ebit, beta = c["mkt"]
        ref = prev.get(c["name"], (p_snap, d_snap))
        new = prices.get(c["name"])
        if new and new[0] > 0 and abs(new[0] / ref[0] - 1) < 0.6:
            p, d = new
        else:
            if new:
                print(f"  rejected suspicious price for {c['name']}: {new[0]} (previous {ref[0]})")
            p, d = ref
        new_mcap = mcap * p / p_snap
        c["mkt"] = (p, d, sh, new_mcap, nd, new_mcap + nd + (ev - mcap - nd), rev, ebit, beta)
        used[c["name"]] = (p, d)
    return out, used


# --------------------------------------------------------------------------- site data
def evidence_stats(companies):
    xs, ys = [], []
    for c in companies:
        for i, y in enumerate(m.YEARS[:-1]):
            if y < c["first"]:
                continue
            m0, m1 = c["mar"][i], c["mar"][i + 1]
            hist = [c["mar"][j] for j in range(i + 1) if m.YEARS[j] >= c["first"] and c["mar"][j] is not None]
            if m0 is None or m1 is None or len(hist) < 3:
                continue
            xs.append(m0 / 100 - statistics.mean(hist) / 100)
            ys.append((m1 - m0) / 100)
    xs, ys = np.array(xs), np.array(ys)
    qs = np.percentile(xs, [0, 20, 40, 60, 80, 100])
    quint = []
    for q in range(5):
        sel = (xs >= qs[q]) & ((xs <= qs[q + 1]) if q == 4 else (xs < qs[q + 1]))
        quint.append(dict(dev=float(xs[sel].mean()), chg=float(ys[sel].mean()), n=int(sel.sum())))
    n, b = m.evidence_regression(companies)
    return dict(n=n, b=b, phi=1 + b, hl=float(math.log(0.5) / math.log(1 + b)), quint=quint)


def build_site_data(results, companies, fx, updated):
    by = {c["name"]: c for c in companies}
    out = []
    for r in results:
        c = by[r["name"]]
        city, lat, lon, slug = HQ[r["name"]]
        ccy = c["trd"]
        out.append(dict(
            id=slug, name=r["name"], ticker=c["ticker"], country=r["country"], city=city, lat=lat, lon=lon,
            group=r["group"], ccy=ccy, price=r["price"], priceDate=c["mkt"][1],
            mcapEur=round(r["mcap"] / fx.get(ccy, 1.0) / 1000, 2),
            cur=r["cur"], norm=r["norm"], own=r["own"], gap=r["gap"], z=r["z"], pct=r["pct"],
            phi=r["phi"], hl=r["half_life"], trend=r["trend"], implied=r["implied"],
            revUp=r["rev_upside"], fairUp=r["upside"], evEbit=r["ev"] / (r["rev_ttm"] * r["ttm"]),
            evNorm=r["ev"] / (r["rev_ttm"] * r["norm"]), score=r["score"], rank=r["rank"],
            signal=r["signal"], flag=r["flag"], note=c["note"], trap=r["trap"], start=r["start"],
            nObs=r["n"], margins=[None if v is None else v / 100 for v in c["mar"]], disc=r["wacc"]))
    dates = sorted(c["mkt"][1] for c in companies)
    meta = dict(snapshot=m.SNAPSHOT_DATE, updated=updated, priceFrom=dates[0], priceTo=dates[-1],
                years=m.YEARS, fx={k: round(v, 4) for k, v in fx.items() if k != "EUR"},
                medCur=statistics.median([r["cur"] for r in results]),
                medNorm=statistics.median([r["norm"] for r in results]),
                nLong=sum(r["signal"].startswith("LONG") for r in results),
                nShort=sum(r["signal"].startswith("SHORT") for r in results),
                evidence=evidence_stats(companies))
    # Make market/fundamental freshness visible separately. The price fetch does
    # not refresh revenue, debt, EBIT, shares outstanding or corporate actions.
    asof = datetime.strptime(updated[:10], "%Y-%m-%d")
    ages = [(asof - datetime.strptime(d, "%Y-%m-%d")).days for d in dates]
    meta["quality"] = dict(
        quoteSource="yfinance / Yahoo Finance (closing prices, potentially delayed)",
        fundamentalSource="Manual standardized-statement snapshot; verify with issuer filings",
        lastFiscalYear=m.YEARS[-1],
        priceAgesDays=dict(oldest=max(ages), newest=min(ages)),
        quotesOlderThanFiveDays=sum(age > 5 for age in ages),
        flaggedCompanies=sum(r["flag"] == "Y" for r in results),
        priceDatesVary=len(set(dates)) > 1,
        returnBasis="Close-to-close prices, EUR-converted; dividends excluded",
        portfolioExecution="Hypothetical same-close fills, not attainable using signals only known after that close",
    )
    return dict(companies=out, meta=meta)


# --------------------------------------------------------------------------- paper portfolio
def new_portfolio(results, companies, fx, decided):
    w, why = target_weights(results)
    by = {c["name"]: c for c in companies}
    cap = STRATEGY["start_capital"]
    orders = []
    for name, wt in sorted(w.items(), key=lambda kv: -kv[1]):
        c = by[name]
        px_eur = c["mkt"][0] / fx.get(c["trd"], 1.0)
        orders.append(dict(id=HQ[name][3], name=name, weight=wt, eur=round(cap * wt, 2),
                           est_shares=round(cap * wt / px_eur, 4), ref_price=c["mkt"][0], ccy=c["trd"],
                           reason=why[name]))
    return dict(name="Kaatopaikka Capital paper portfolio", currency="EUR", start_capital=cap,
                status="pending", decided=decided, inception=None, rules=RULES, strategy=STRATEGY,
                decisions=[dict(n=1, date=decided, type="initial buy", orders=orders)],
                targets=orders, holdings=[], cash=cap, value=cap, bench_value=cap,
                history=[], trades=[], last_rebalance=None, bench_base={}, updated=decided)


def _price_eur(companies, fx):
    return {c["name"]: c["mkt"][0] / fx.get(c["trd"], 1.0) for c in companies}


def _rebalance(port, weights, px, date, label, why=None):
    hold = {h["name"]: h for h in port["holdings"]}
    value = port["cash"] + sum(h["shares"] * px[h["name"]] for h in hold.values())
    cur = {n: h["shares"] * px[n] for n, h in hold.items()}
    names = set(cur) | set(weights)
    turnover = sum(abs(weights.get(n, 0) * value - cur.get(n, 0)) for n in names)
    cost = STRATEGY["cost"] * turnover
    invest = value - cost
    new_hold, trades = [], []
    for n in sorted(names, key=lambda k: -weights.get(k, 0)):
        tgt = weights.get(n, 0) * invest
        delta = tgt - cur.get(n, 0)
        old = hold.get(n)
        basis = old["cost"] if old else 0.0
        if old and cur.get(n, 0) > 0 and delta < 0:            # partial / full sale reduces cost basis
            basis *= max(0.0, tgt) / cur[n]
        elif delta > 0:
            basis += delta
        if abs(delta) > 0.01:
            trades.append(dict(date=date, name=n, id=HQ[n][3], side="BUY" if delta > 0 else "SELL",
                               eur=round(abs(delta), 2), price_eur=round(px[n], 4), note=label,
                               reason=(why or {}).get(n, "No longer selected at this rebalance")))
        if tgt > 0.01:
            new_hold.append(dict(name=n, id=HQ[n][3], shares=tgt / px[n], cost=basis))
    port["holdings"] = new_hold
    port["cash"] = value - cost - sum(h["shares"] * px[h["name"]] for h in new_hold)
    port["trades"] = (port["trades"] + trades)[-200:]
    port["costs_paid"] = round(port.get("costs_paid", 0) + cost, 2)
    return trades


def update_portfolio(port, results, companies, fx, date, updated):
    px = _price_eur(companies, fx)
    w, why = target_weights(results)
    by = {c["name"]: c for c in companies}
    port["targets"] = [dict(id=HQ[n][3], name=n, weight=wt, eur=None, reason=why[n], ccy=by[n]["trd"],
                            ref_price=by[n]["mkt"][0]) for n, wt in sorted(w.items(), key=lambda kv: -kv[1])]
    if port["status"] == "pending":
        _rebalance(port, w, px, date, "Decision 1: initial buy", why)
        port["status"], port["inception"], port["last_rebalance"] = "live", date, date[:7]
        port["bench_base"] = px
    elif date[:7] != port["last_rebalance"]:
        n = len(port["decisions"]) + 1
        trades = _rebalance(port, w, px, date, f"Decision {n}: monthly rebalance", why)
        port["decisions"].append(dict(n=n, date=date, type="monthly rebalance",
                                      orders=[dict(name=t["name"], id=t["id"], side=t["side"],
                                                   eur=t["eur"], reason=t["reason"]) for t in trades]))
        port["last_rebalance"] = date[:7]
    value = port["cash"] + sum(h["shares"] * px[h["name"]] for h in port["holdings"])
    base = port["bench_base"]
    bench = port["start_capital"] * statistics.mean(px[n] / base[n] for n in base if n in px)
    for h in port["holdings"]:
        h["price_eur"] = px[h["name"]]
        h["value"] = h["shares"] * px[h["name"]]
        h["weight"] = h["value"] / value
        h["ret"] = h["value"] / h["cost"] - 1 if h["cost"] > 0 else 0.0
        h["signal"] = next(r["signal"] for r in results if r["name"] == h["name"])
    port["value"], port["bench_value"], port["updated"] = value, bench, updated
    hist = [x for x in port["history"] if x["date"] != date]
    hist.append(dict(date=date, value=round(value, 2), bench=round(bench, 2)))
    port["history"] = sorted(hist, key=lambda x: x["date"])
    return port


# --------------------------------------------------------------------------- Monte Carlo
def _cap_rows(raw, cap):
    W = np.zeros_like(raw)
    tot = raw.sum(1, keepdims=True)
    np.divide(raw, tot, out=W, where=tot > 0)
    for _ in range(20):
        over = W > cap + 1e-12
        if not over.any():
            break
        excess = np.where(over, W - cap, 0).sum(1, keepdims=True)
        W = np.where(over, cap, W)
        free = (W > 0) & (W < cap - 1e-12)
        ft = np.where(free, W, 0).sum(1, keepdims=True)
        add = np.zeros_like(W)
        np.divide(np.where(free, W, 0) * excess, ft, out=add, where=ft > 0)
        W = W + add
    return W


def simulate(results, companies, fx, init_weights, s=SIM, spec=STRATEGY):
    """Monthly Monte Carlo of the strategy.  Each stock has a 'mispricing gap' G (log units):
    G0 = haircut x ln(1 + reversion upside).  Each month a share (1 - phi^(1/12)) of the gap
    closes and is earned as alpha; a share of idiosyncratic price noise widens/narrows the gap
    (new opportunities).  Market factor + beta + idiosyncratic volatility by size.
    'No edge' uses the same random draws and the same trades but earns no alpha."""
    rng = np.random.default_rng(s["seed"])
    Pn, T, n = s["paths"], s["months"], len(results)
    by = {c["name"]: c for c in companies}
    beta = np.array([beta_adj(r["beta"]) for r in results])
    mcap_e = np.array([r["mcap"] / fx.get(by[r["name"]]["trd"], 1.0) / 1000 for r in results])
    sig = np.select([mcap_e > 20, mcap_e > 5, mcap_e > 1], [0.20, 0.25, 0.30], 0.38)
    kappa = 1 - np.array([r["phi"] for r in results]) ** (1 / 12)
    G = np.tile(s["edge_haircut"] * np.log1p(np.array([r["rev_upside"] for r in results])), (Pn, 1))
    elig = np.array([r["eligible"] for r in results], bool)
    idx_of = {r["name"]: i for i, r in enumerate(results)}
    W0 = np.zeros(n)
    for name, w in init_weights.items():
        W0[idx_of[name]] = w
    ew = elig / elig.sum()
    V = {k: np.full(Pn, spec["start_capital"]) for k in ("edge", "noedge", "bench")}
    drift = {k: None for k in ("edge", "noedge")}
    peak, mdd = V["edge"].copy(), np.zeros(Pn)
    track = {k: [V[k].copy()] for k in V}
    rows = np.arange(Pn)[:, None]
    N, cap = spec["n_holdings"], spec["max_weight"]
    for t in range(T):
        if t == 0:
            W = np.tile(W0, (Pn, 1))
        else:
            Gm = np.where(elig, G, -np.inf)
            top = np.argsort(-Gm, axis=1)[:, :N]
            raw = np.zeros((Pn, n))
            raw[rows, top] = np.maximum(G[rows, top], 0) * beta[top]
            W = _cap_rows(raw, cap)
        rM = rng.normal(s["mkt_mu"] / 12 - s["mkt_sigma"] ** 2 / 24, s["mkt_sigma"] / math.sqrt(12), Pn)
        eps = rng.standard_normal((Pn, n)) * (sig / math.sqrt(12))
        alpha = kappa * G
        base = beta * rM[:, None] + eps - 0.5 * sig ** 2 / 12
        for key, R in (("edge", np.exp(base + alpha)), ("noedge", np.exp(base))):
            to = W.sum(1) if drift[key] is None else np.abs(W - drift[key]).sum(1)
            cash = 1 - W.sum(1)
            gross = (W * R).sum(1) + cash
            V[key] = V[key] * (1 - spec["cost"] * to) * gross
            drift[key] = (W * R) / gross[:, None]
        V["bench"] = V["bench"] * (ew * np.exp(base + alpha)).sum(1)
        G = G - alpha - s["noise_share"] * eps
        peak = np.maximum(peak, V["edge"])
        mdd = np.maximum(mdd, 1 - V["edge"] / peak)
        for k in V:
            track[k].append(V[k].copy())
    pct = lambda arr, qs: {f"p{q}": [round(float(np.percentile(a, q)), 1) for a in arr] for q in qs}
    end = {k: track[k][-1] for k in track}
    yrs = T / 12
    return dict(
        params=dict(s, n_holdings=N, max_weight=cap, cost=spec["cost"]),
        months=list(range(T + 1)),
        edge=pct(track["edge"], [5, 10, 25, 50, 75, 90, 95]),
        noedge=pct(track["noedge"], [10, 50, 90]),
        bench=pct(track["bench"], [10, 50, 90]),
        stats=dict(
            median_end=float(np.median(end["edge"])), mean_end=float(end["edge"].mean()),
            p10_end=float(np.percentile(end["edge"], 10)), p90_end=float(np.percentile(end["edge"], 90)),
            median_cagr=float((np.median(end["edge"]) / spec["start_capital"]) ** (1 / yrs) - 1),
            p_loss=float((end["edge"] < spec["start_capital"]).mean()),
            p_halve=float((end["edge"] < spec["start_capital"] / 2).mean()),
            p_beat_bench=float((end["edge"] > end["bench"]).mean()),
            median_mdd=float(np.median(mdd)), p90_mdd=float(np.percentile(mdd, 90)),
            noedge_median_end=float(np.median(end["noedge"])),
            noedge_p_loss=float((end["noedge"] < spec["start_capital"]).mean()),
            bench_median_end=float(np.median(end["bench"]))))


# --------------------------------------------------------------------------- main
def load_json(name, default=None):
    try:
        with open(P(name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(name, obj):
    with open(P(name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="offline test with random prices")
    ap.add_argument("--date", help="price date for --mock (YYYY-MM-DD)")
    ap.add_argument("--snapshot", action="store_true", help="no price fetch: use the model's snapshot prices")
    ap.add_argument("--reset", action="store_true", help="reset the paper portfolio to 'pending' (decision 1)")
    ap.add_argument("--no-excel", action="store_true")
    ap.add_argument("--no-sim", action="store_true")
    a = ap.parse_args()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prev_data = load_json("data.json", {"companies": []})
    prev = {c["name"]: (c["price"], c["priceDate"]) for c in prev_data.get("companies", [])}

    if a.snapshot or a.reset:
        prices, fx = {}, dict(FX_FALLBACK)
        prev = {}
    elif a.mock:
        prices, fx = fetch_mock(m.COMPANIES, prev, a.date or now[:10])
    else:
        print("Fetching prices ...")
        prices, fx = fetch_live(m.COMPANIES)
        print(f"  got {len(prices)}/{len(m.COMPANIES)} prices")
    companies, used = apply_prices(m.COMPANIES, prices, prev)
    results = m.compute_model(companies)
    price_date = Counter(d for _, d in used.values()).most_common(1)[0][0]
    if prices:
        m.SNAPSHOT_DATE = price_date
    save_json("data.json", build_site_data(results, companies, fx, now))

    port = load_json("portfolio.json")
    if a.reset or port is None:
        port = new_portfolio(results, companies, fx, now[:10] if not a.reset else m.SNAPSHOT_DATE)
    if prices:                                     # only trade / mark on real (or mock) prices
        port = update_portfolio(port, results, companies, fx, price_date, now)
    save_json("portfolio.json", port)

    if not a.no_sim:
        init_w = {h["name"]: h["weight"] for h in port["holdings"]} or {o["name"]: o["weight"] for o in port["targets"]}
        save_json("simulation.json", simulate(results, companies, fx, init_w))
    if not a.no_excel:
        m.build_workbook(P("model.xlsx"), companies)

    print(f"Updated {now}: prices as of {price_date}; portfolio {port['status']} "
          f"value EUR {port['value']:,.0f} (benchmark {port['bench_value']:,.0f})")
    for h in port["holdings"]:
        print(f"  {h['name']:<20} {h['weight']:6.1%}  EUR {h['value']:>9,.0f}  {h['ret']:+.1%}")


if __name__ == "__main__":
    main()
