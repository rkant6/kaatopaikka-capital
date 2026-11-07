"""Offline importer tests. Market observations here are SYNTHETIC test fixtures only."""
from __future__ import annotations
import unittest
from datetime import date
from historical_data.collect_market_history import (
    DataError, asof_rate, reconstruct_as_traded, collect, FIELDS
)
import nordic_margin_reversion as model


class MarketInputTests(unittest.TestCase):
    def test_reconstruct_actual_pre_split_quoted_prices(self):
        sample=[
            {"date":"2024-01-02","close":25.0,"dividend":1.0,"split_factor":1.0},
            {"date":"2025-01-02","close":26.0,"dividend":0.0,"split_factor":4.0},
            {"date":"2025-01-03","close":27.0,"dividend":0.0,"split_factor":1.0},
        ]
        got=reconstruct_as_traded(sample)
        self.assertEqual(got[0]["close"],100.0)
        self.assertEqual(got[0]["dividend"],4.0)
        self.assertEqual(got[1]["close"],26.0)
        self.assertEqual(got[1]["split_factor"],4.0)

    def test_fx_never_looks_ahead(self):
        days=["2023-12-29","2024-01-03"]
        rates=[10.0,11.0]
        self.assertAlmostEqual(asof_rate(days,rates,"2024-01-02","SEK"),.10)
        self.assertAlmostEqual(asof_rate(days,rates,"2024-01-03","SEK"),1/11)
        with self.assertRaises(DataError):
            asof_rate(days,rates,"2023-12-20","SEK")
        with self.assertRaises(DataError):
            asof_rate(days,rates,"2024-02-01","SEK")

    def test_collector_labels_currency_and_source_and_dates(self):
        invoked=[]
        def download(ticker,start,through):
            invoked.append(ticker)
            if ticker.startswith("EUR"):
                return [
                    {"date":"2023-12-29","close":10.0,"dividend":0,"split_factor":1},
                    {"date":"2024-01-02","close":10.2,"dividend":0,"split_factor":1},
                ]
            return [
                {"date":"2023-12-29","close":100.0,"dividend":0,"split_factor":1},
                {"date":"2024-01-02","close":101.0,"dividend":0.5,"split_factor":1},
            ]
        collected=collect(start=date(2023,12,20),through=date(2024,1,2),download_fn=download)
        self.assertEqual(len(collected),2*len(model.COMPANIES))
        self.assertEqual(set(FIELDS)-set(collected[0]),set())
        names={c["name"]:c for c in model.COMPANIES}
        for item in collected:
            self.assertTrue(item["source_url"].startswith("https://"))
            self.assertEqual(item["price_currency"],names[item["company"]]["trd"])
            self.assertLessEqual(item["date"],"2024-01-02")
        cross=[x for x in collected if names[x["company"]]["rep"]!=names[x["company"]]["trd"]]
        self.assertTrue(cross)
        self.assertTrue(all(float(x["reporting_fx_to_eur"])>0 for x in cross))


if __name__=="__main__":
    unittest.main()
