"""Strict no-lookahead replay tests: all observations here are SYNTHETIC."""
import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

import historical_backtest as hist
import nordic_margin_reversion as model


def write_rows(path, cols, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        w=csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def example_inputs(directory):
    names=[c["name"] for c in model.COMPANIES]
    filings=[];annual=[];prices=[]
    for i,name in enumerate(names):
        filings.append(dict(company=name,period_end="2023-09-30",published_on="2023-10-26",
                            revenue_ttm_m=1000+i*9,ebit_ttm_m=110+i,net_debt_m=180,
                            shares_m=90,beta=1.1,tax_rate=.22,structural_flag="N",
                            source_url="https://issuer.example/TEST-NOT-REAL"))
        # Future report may not influence January 2024, even when file contains it.
        filings.append(dict(company=name,period_end="2024-03-31",published_on="2024-05-10",
                            revenue_ttm_m=2000+i*9,ebit_ttm_m=22+i,net_debt_m=180,
                            shares_m=90,beta=1.1,tax_rate=.22,structural_flag="Y",
                            source_url="https://issuer.example/TEST-FUTURE-NOT-REAL"))
        for y in range(2013,2023):
            annual.append(dict(company=name,fiscal_year=y,period_end=f"{y}-12-31",
                               published_on=f"{y+1}-04-21",operating_margin=8+(i%6)*1.5+(y%3)*.2,
                               source_url="https://issuer.example/TEST-NOT-REAL"))
        for day in ("2023-12-29","2024-01-02","2024-01-03","2024-02-01","2024-02-02"):
            prices.append(dict(company=name,date=day,close=100+i+(1 if day.endswith("02") else 0),
                               dividend=0,split_factor=1,fx_to_eur=.09 if i%4==0 else 1,
                               reporting_fx_to_eur=.85 if name=="A.P. Møller-Mærsk" else 1,
                               price_currency=next(c["trd"] for c in model.COMPANIES if c["name"]==name),
                               fx_source_url="https://exchange.example/TEST-FX",
                               source_url="https://exchange.example/TEST-NOT-REAL"))
    for table,rows in (("filings",filings),("annual_margins",annual),("prices",prices)):
        write_rows(directory/f"{table}.csv",hist.SCHEMAS[table],rows)


class PointInTimeTests(unittest.TestCase):
    def test_empty_templates_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for table,cols in hist.SCHEMAS.items():write_rows(root/f"{table}.csv",cols,[])
            with self.assertRaisesRegex(hist.CoverageError,"no evidence-backed"):
                hist.read_inputs(root)

    def test_late_report_not_visible_to_earlier_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);example_inputs(root)
            tables=hist.read_inputs(root)
            company=model.COMPANIES[0]["name"]
            rows=[r for r in tables["filings"] if r["company"]==company]
            earlier=hist._latest(rows,date(2024,1,2))
            self.assertEqual(earlier["published_on"],"2023-10-26")
            self.assertEqual(hist._latest(rows,date(2024,5,10))["published_on"],"2023-10-26")
            later=hist._latest(rows,date(2024,5,13))
            self.assertEqual(later["published_on"],"2024-05-10")

    def test_replay_reconciles_and_leads_signals_by_one_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);example_inputs(root)
            data=hist.replay(hist.read_inputs(root),through=date(2024,2,2))
            self.assertEqual(data["from"],"2024-01-02")
            self.assertEqual(len(data["history"]),4)
            self.assertEqual(len(data["decisions"]),2)
            self.assertEqual(data["decisions"][0]["signal_asof"],"2023-12-29")
            self.assertEqual(data["decisions"][1]["signal_asof"],"2024-01-03")
            self.assertTrue(all(h["nav"]>0 for h in data["history"]))
            self.assertFalse(data["is_investable_track_record"])

    def test_source_and_duplicate_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);example_inputs(root)
            p=root/"prices.csv"
            text=p.read_text(encoding="utf-8")
            p.write_text(text+text.splitlines()[1]+"\n",encoding="utf-8")
            with self.assertRaisesRegex(hist.CoverageError,"Duplicate"):
                hist.read_inputs(root)


if __name__=="__main__":unittest.main()
