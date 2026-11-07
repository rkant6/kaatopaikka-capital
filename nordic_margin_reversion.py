#!/usr/bin/env python3
"""
Nordic Industrials - Margin Reversion Model
============================================

Margin reversion philosophy (Fama & French 2000; Koller et al., "Valuation"):
operating margins are mean-reverting. Competition erodes unusually high margins
and capacity exits / cost actions repair unusually low ones. A company's
*current* margin is therefore a noisy, cyclical estimate of its *normal*
earning power. This model:

  1. Builds a 13-year (FY2013-FY2025) operating-margin history for 30 Nordic
     industrial companies (SE, FI, NO, DK).
  2. Estimates each company's NORMALIZED margin as a blend of its own history
     (median or mean over a look-back window), its peer group and the universe.
  3. Estimates the SPEED of reversion with an AR(1) model on margin deviations,
     shrunk toward an empirical prior (Fama-French: ~38% of a deviation
     disappears per year -> persistence ~0.6).
  4. Values every company with a margin-FADE DCF (current margin fades to
     normal at the estimated speed), discounted by default at the company's
     own market-implied cost of capital -> the only disagreement with the
     market is margin persistence. "Reversion upside" = fade value vs a
     status-quo value in which today's margin persists.
  5. Market-implied steady-state margin (value-driver formula) at a
     fundamental CAPM WACC, by default shifted equally for all companies so
     the universe median is fairly priced (relative cheapness).
  6. Combines four signals (margin gap, z-score, implied-margin gap,
     reversion upside) into a composite rank -> LONG / NEUTRAL / SHORT, with a
     value-trap filter (depressed margin that is also trending down).
  7. Tests the philosophy in-sample: pooled regression of next-year margin
     change on the deviation from the expanding (no look-ahead) mean.

Everything in the Excel workbook is a live formula driven by the
Assumptions sheet; only raw data is hard-coded (blue font, sourced).

Usage
-----
    python nordic_margin_reversion.py                       # build workbook
    python nordic_margin_reversion.py --out my_model.xlsx
    python nordic_margin_reversion.py --refresh-market      # update prices via yfinance
    python nordic_margin_reversion.py --no-summary

Requires: openpyxl. Optional: yfinance (for --refresh-market; untested
offline - it only updates share prices / market caps).

Data: roic.ai standardized statements (FY2013-25) and stockanalysis.com
statistics (market snapshot), retrieved 2026-11-07. See the Sources sheet.
"""
from __future__ import annotations

import argparse
import copy
import math
import statistics

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference, ScatterChart, Series
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as CL
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

# =============================================================================
# 1. DATA
# =============================================================================
YEARS = list(range(2013, 2026))          # FY2013 ... FY2025 (13 fiscal years)
N_Y = len(YEARS)
SNAPSHOT_DATE = "2026-11-07"

ROIC = "https://www.roic.ai/quote/"
SA = "https://stockanalysis.com/quote/"


def _m(ebit, rev):
    """Operating margin (%) from EBIT and revenue lists (None-safe)."""
    return [None if (e is None or r in (None, 0)) else round(100.0 * e / r, 2)
            for e, r in zip(ebit, rev)]


_N8 = [None] * 8
_PON_REV = _N8 + [608.27, 755.12, 821.80, 750.43, 749.87]
_PON_EBIT = _N8 + [49.64, 46.13, 46.04, 36.76, 41.63]
_VEI_REV = _N8 + [37592, 38658, 43146, 41403, 43143]
_VEI_EBIT = _N8 + [1373, 1489, 1395, 1594, 1916]
_NKT_REV = _N8 + [1828, 2079, 2567, 3252, 3565]
_NKT_EBIT = _N8 + [23.9, 60.2, 426, 551, 578]

# mkt = (price, price_date, shares_m, mcap_m, net_debt_m, ev_m,
#        ttm_revenue_m, ttm_ebit_m, beta_5y)  -- all in TRADING currency, millions
COMPANIES = [
    # ------------------------------------------------------------------ SWEDEN
    dict(name="Atlas Copco", ticker="ATCO A", yf="ATCO-A.ST", country="Sweden",
         group="General Machinery", rep="SEK", trd="SEK", src="roic.ai (ATLKY)",
         first=2013, flag="N", note="Epiroc spun off 2018 (FY2017 restated ex-Epiroc)",
         hurl=ROIC + "ATLKY", murl=SA + "sto/ATCO.A/statistics/",
         rev=[83888, 93721, 98973, 101356, 85653, 95363, 103756, 99787, 110912, 141325, 172664, 176771, 168343],
         mar=[20.3, 17.76, 19.78, 19.38, 22.24, 21.91, 21.05, 19.47, 20.73, 21.65, 22.29, 21.47, 20.68],
         mkt=(178.90, "2026-10-26", 4880, 842230, 13230, 855680, 176220, 37020, 1.04)),
    dict(name="Sandvik", ticker="SAND", yf="SAND.ST", country="Sweden",
         group="Mining & Process Equipment", rep="SEK", trd="SEK", src="roic.ai (SDVKF)",
         first=2013, flag="N", note="Alleima (SMT) spun off 2022 (FY2021 restated)",
         hurl=ROIC + "SDVKF/classic", murl=SA + "sto/SAND/statistics/",
         rev=[87328, 82533, 85845, 81553, 90827, 100072, 103236, 86404, 85700, 112332, 126503, 122878, 120680],
         mar=[9.89, 12.34, 8.46, 13.37, 15.45, 18.6, 15.79, 14.34, 20.26, 16.94, 18.15, 15.59, 17.38],
         mkt=(349.90, "2026-10-26", 1250, 438910, 39680, 478710, 137630, 26180, 1.30)),
    dict(name="SKF", ticker="SKF B", yf="SKF-B.ST", country="Sweden",
         group="General Machinery", rep="SEK", trd="SEK", src="roic.ai (SKUFF)",
         first=2013, flag="N", note="Automotive separation under way; FY2025 margin depressed",
         hurl=ROIC + "SKUFF", murl=SA + "sto/SKF.B/statistics/",
         rev=[63597, 70975, 75997, 72589, 77938, 85713, 86013, 74852, 81732, 96933, 103881, 98722, 91583],
         mar=[5.84, 11.05, 9.11, 10.41, 11.09, 11.29, 11.02, 9.31, 12.62, 9.68, 10.83, 10.69, 7.51],
         mkt=(268.00, "2026-10-26", 455.35, 122010, 9080, 133530, 91310, 8890, 0.85)),
    dict(name="Volvo", ticker="VOLV B", yf="VOLV-B.ST", country="Sweden",
         group="Vehicles & Mobile Machinery", rep="SEK", trd="SEK", src="roic.ai (VLVLY)",
         first=2013, flag="N", note="Net debt / EV include Volvo Financial Services funding",
         hurl=ROIC + "VLVLY", murl=SA + "sto/VOLV.B/statistics/",
         rev=[272622, 282948, 312515, 301914, 332738, 390834, 431980, 338446, 372216, 473479, 552252, 526816, 479183],
         mar=[3.38, 4.13, 6.52, 7.62, 8.44, 8.5, 10.79, 8.61, 11.36, 10.49, 14.58, 13.25, 10.33],
         mkt=(315.80, "2026-10-20", 2030, 642120, 213290, 855530, 471530, 48960, 1.00)),
    dict(name="Alfa Laval", ticker="ALFA", yf="ALFA.ST", country="Sweden",
         group="General Machinery", rep="SEK", trd="SEK", src="roic.ai (ALFVY)",
         first=2013, flag="N", note="",
         hurl=ROIC + "ALFVY", murl=SA + "sto/ALFA/statistics/",
         rev=[29801, 35067, 39746, 35634, 35314, 40666, 46517, 41468, 40911, 52135, 63598, 66953, 69675],
         mar=[14.55, 13.29, 14.36, 8.35, 12.96, 14.3, 15.43, 13.4, 14.79, 12.41, 14.47, 15.54, 16.87],
         mkt=(544.40, "2026-10-26", 413.33, 225010, 16010, 241470, 70430, 11750, 0.77)),
    dict(name="Epiroc", ticker="EPI A", yf="EPI-A.ST", country="Sweden",
         group="Mining & Process Equipment", rep="SEK", trd="SEK", src="roic.ai (EPI-A.ST)",
         first=2015, flag="N", note="Listed 2018; carve-out history from FY2015",
         hurl=ROIC + "EPI-A.ST", murl=SA + "sto/EPI.A/statistics/",
         rev=[None, None, 28663, 27102, 31364, 38285, 40849, 36122, 39645, 49694, 60343, 63604, 61998],
         mar=[None, None, 17.98, 16.23, 19.39, 19.51, 19.88, 21.09, 22.08, 21.96, 21.75, 18.56, 20.15],
         mkt=(251.20, "2026-10-26", 1210, 289130, 11850, 300980, 62390, 12740, 1.21)),
    dict(name="Assa Abloy", ticker="ASSA B", yf="ASSA-B.ST", country="Sweden",
         group="Building Products & Elevators", rep="SEK", trd="SEK", src="roic.ai (ASAZY)",
         first=2013, flag="N", note="",
         hurl=ROIC + "ASAZY", murl=SA + "sto/ASSA.B/statistics/",
         rev=[48481, 56843, 68099, 71293, 76137, 84048, 94029, 87649, 95007, 120793, 140716, 150162, 152409],
         mar=[14.22, 16.06, 16.45, 14.51, 16.39, 14.2, 15.6, 12.23, 15.41, 15.76, 15.26, 16.29, 15.49],
         mkt=(351.20, "2026-10-20", 1110, 390100, 67520, 457800, 151460, 25200, 0.82)),
    dict(name="Husqvarna", ticker="HUSQ B", yf="HUSQ-B.ST", country="Sweden",
         group="Vehicles & Mobile Machinery", rep="SEK", trd="SEK", src="roic.ai (HSQVY)",
         first=2013, flag="N", note="",
         hurl=ROIC + "HSQVY", murl=SA + "sto/HUSQ.B/statistics/",
         rev=[30307, 32838, 36170, 35982, 39394, 41085, 42277, 41943, 47058, 54036, 53260, 48352, 46613],
         mar=[5.32, 7.1, 7.77, 8.95, 9.45, 4.9, 8.26, 8.69, 12.1, 5.26, 7.29, 5.08, 6.3],
         mkt=(33.92, "2026-10-08", 571.88, 19420, 10440, 29860, 44980, 2920, 1.47)),
    dict(name="Trelleborg", ticker="TREL B", yf="TREL-B.ST", country="Sweden",
         group="General Machinery", rep="SEK", trd="SEK", src="roic.ai (TBABF)",
         first=2013, flag="N", note="Tyre business divested 2022 (FY2021 restated)",
         hurl=ROIC + "TBABF", murl=SA + "sto/TREL.B/statistics/",
         rev=[21473, 22533, 24803, 27145, 31581, 34005, 36588, 30258, 23789, 30095, 34286, 34170, 34329],
         mar=[11.22, 12.46, 12.6, 12.54, 12.87, 13.18, 12.61, 13.25, 15.68, 16.34, 15.98, 16.01, 16.69],
         mkt=(465.80, "2026-10-19", 222.52, 103650, 9730, 113390, 34680, 6000, 0.85)),
    dict(name="Indutrade", ticker="INDT", yf="INDT.ST", country="Sweden",
         group="Industrial Distribution & Services", rep="SEK", trd="SEK", src="roic.ai (STO-INDT)",
         first=2013, flag="N", note="Serial acquirer",
         hurl=ROIC + "STO-INDT/classic", murl=SA + "sto/INDT/statistics/",
         rev=[8831, 9746, 11881, 12955, 14847, 16848, 18411, 19217, 21715, 27016, 31835, 32544, 32229],
         mar=[9.51, 9.59, 10.29, 9.55, 9.67, 10.7, 10.73, 11.34, 13.09, 12.99, 12.8, 11.95, 11.75],
         mkt=(255.80, "2026-10-01", 364.32, 93700, 9500, 103210, 33120, 4000, 1.20)),
    dict(name="NIBE", ticker="NIBE B", yf="NIBE-B.ST", country="Sweden",
         group="Building Products & Elevators", rep="SEK", trd="SEK", src="roic.ai (NDRBF)",
         first=2013, flag="N", note="FY2024 hit by heat-pump downturn and impairments",
         hurl=ROIC + "NDRBF", murl=SA + "sto/NIBE.B/statistics/",
         rev=[9834, 11033, 13243, 15348, 19009, 22516, 25342, 27146, 30832, 40071, 46649, 40521, 40841],
         mar=[11.18, 11.84, 12.22, 12.22, 11.77, 12.04, 11.48, 12.12, 13.53, 13.03, 13.78, 4.49, 9.94],
         mkt=(43.98, "2026-10-13", 2020, 88670, 17980, 106640, 41590, 4250, 0.88)),
    dict(name="Saab", ticker="SAAB B", yf="SAAB-B.ST", country="Sweden",
         group="Defence & Aerospace", rep="SEK", trd="SEK", src="roic.ai (SAABY)",
         first=2013, flag="N", note="Raw beta 0.03 -> floored in WACC; defence up-cycle",
         hurl=ROIC + "SAABY", murl=SA + "sto/SAAB.B/statistics/",
         rev=[23750, 23527, 27186, 28631, 31666, 33156, 35433, 35431, 39154, 42006, 51609, 63751, 79146],
         mar=[6.37, 5.67, 5.96, 6.18, 7.3, 7.38, 8.11, 1.95, 7.52, 7.81, 8.76, 8.78, 9.63],
         mkt=(651.90, "2026-10-26", 539.05, 351410, -3770, 348090, 92870, 9520, 0.03)),
    dict(name="Skanska", ticker="SKA B", yf="SKA-B.ST", country="Sweden",
         group="Construction & Engineering", rep="SEK", trd="SEK", src="roic.ai (SKBSY)",
         first=2013, flag="N", note="Property development value not separated in EV",
         hurl=ROIC + "SKBSY", murl=SA + "sto/SKA.B/statistics/",
         rev=[136589, 143325, 153049, 145365, 157877, 171730, 172846, 160344, 143865, 163174, 167168, 176481, 176658],
         mar=[3.57, 3.4, 3.38, 3.5, 1.85, 2.79, 3.96, 5.37, 5.45, 4.71, 2.34, 3.27, 3.52],
         mkt=(272.10, "2026-10-26", 414.05, 112660, -563, 112330, 174140, 6870, 0.81)),
    dict(name="Lifco", ticker="LIFCO B", yf="LIFCO-B.ST", country="Sweden",
         group="Industrial Distribution & Services", rep="SEK", trd="SEK", src="roic.ai (LIFCO-B.ST)",
         first=2013, flag="N", note="Serial acquirer; structural margin uptrend",
         hurl=ROIC + "LIFCO-B.ST", murl=SA + "sto/LIFCO.B/statistics/",
         rev=[6030, 6802, 7901, 8987, 10030, 11956, 13845, 13782, 17480, 21552, 24454, 26137, 28251],
         mar=[10.38, 13.47, 14.01, 13.93, 15.14, 15.91, 14.87, 16.46, 17.97, 18.34, 19.44, 18.74, 18.3],
         mkt=(280.40, "2026-10-23", 454.22, 127360, 9600, 138040, 29820, 5630, 1.13)),
    # ----------------------------------------------------------------- FINLAND
    dict(name="KONE", ticker="KNEBV", yf="KNEBV.HE", country="Finland",
         group="Building Products & Elevators", rep="EUR", trd="EUR", src="roic.ai (KNYJY)",
         first=2013, flag="N", note="",
         hurl=ROIC + "KNYJY", murl=SA + "hel/KNEBV/statistics/",
         rev=[6933, 7334, 8647, 8784, 8797, 9071, 9982, 9938, 10514, 10907, 10952, 11098, 11245],
         mar=[13.76, 14.12, 14.36, 14.72, 13.55, 11.49, 12.4, 12.58, 12.46, 9.87, 11.4, 11.25, 11.88],
         mkt=(56.32, "2026-10-23", 518.28, 29190, -446.2, 28780, 11370, 1360, 0.78)),
    dict(name="Wärtsilä", ticker="WRT1V", yf="WRT1V.HE", country="Finland",
         group="Energy & Electrical Equipment", rep="EUR", trd="EUR", src="roic.ai (WRT1V.HE)",
         first=2013, flag="N", note="FY2022 hit by Russia exit costs",
         hurl=ROIC + "WRT1V.HE", murl=SA + "hel/WRT1V/statistics/",
         rev=[4608, 4779, 5030, 4800, 4911, 5174, 5170, 4604, 4778, 5842, 6015, 6449, 6914],
         mar=[11.0, 10.23, 11.19, 10.81, 10.51, 9.63, 6.98, 5.21, 6.57, 2.31, 7.51, 10.54, 11.8],
         mkt=(28.31, "2026-10-26", 589.55, 16690, -1670, 15030, 6890, 798, 1.20)),
    dict(name="Metso", ticker="METSO", yf="METSO.HE", country="Finland",
         group="Mining & Process Equipment", rep="EUR", trd="EUR", src="roic.ai (OUKPF)",
         first=2020, flag="N", note="Pre-2020 = legal predecessor Outotec -> window starts FY2020",
         hurl=ROIC + "OUKPF", murl=SA + "hel/METSO/statistics/",
         rev=[1912, 1403, 1201, 1058, 1144, 1198, 2819, 3319, 4236, 4970, 5390, 5026, 5240],
         mar=[7.42, 4.04, 4.35, -2.04, 1.61, -2.82, 12.17, 7.5, 10.69, 10.78, 15.16, 15.6, 13.84],
         mkt=(16.23, "2026-10-20", 828.11, 13440, 1230, 14680, 5360, 732.6, 1.19)),
    dict(name="Valmet", ticker="VALMT", yf="VALMT.HE", country="Finland",
         group="Mining & Process Equipment", rep="EUR", trd="EUR", src="roic.ai (MUN-2VO)",
         first=2013, flag="N", note="Neles merged 2022",
         hurl=ROIC + "MUN-2VO/classic", murl=SA + "hel/VALMT/statistics/",
         rev=[2613, 2473, 2928, 2926, 3058, 3325, 3547, 3741, 3935, 5074, 5532, 5359, 5197],
         mar=[-1.07, 2.71, 4.37, 5.3, 5.72, 6.56, 7.56, 8.58, 10.22, 7.09, 8.44, 8.81, 8.68],
         mkt=(26.68, "2026-10-15", 184.23, 4920, 960, 5880, 5330, 537, 1.09)),
    dict(name="Konecranes", ticker="KCR", yf="KCR.HE", country="Finland",
         group="General Machinery", rep="EUR", trd="EUR", src="roic.ai (KNCRF)",
         first=2013, flag="N", note="MHPS acquired 2017",
         hurl=ROIC + "KNCRF", murl=SA + "hel/KCR/statistics/",
         rev=[2099, 2011, 2126, 2117, 3135, 3154, 3324, 3173, 3179, 3356, 3963, 4222, 4165],
         mar=[4.82, 5.75, 4.02, 6.32, 10.29, 5.63, 4.4, 5.29, 6.71, 6.66, 10.07, 12.0, 12.47],
         mkt=(29.34, "2026-10-20", 237.64, 6970, 23.5, 7000, 4080, 533.6, 1.23)),
    dict(name="Ponsse", ticker="PON1V", yf="PON1V.HE", country="Finland",
         group="Vehicles & Mobile Machinery", rep="EUR", trd="EUR", src="stockanalysis.com (5y)",
         first=2021, flag="N", note="Only FY2021-25 available (5 obs); margin = EBIT / revenue",
         hurl=SA + "hel/PON1V/financials/", murl=SA + "hel/PON1V/statistics/",
         rev=_PON_REV, mar=_m(_PON_EBIT, _PON_REV),
         mkt=(22.10, "2026-10-09", 27.98, 618.4, 26.36, 644.76, 746.04, 33.52, 0.56)),
    # ------------------------------------------------------------------ NORWAY
    dict(name="Kongsberg Gruppen", ticker="KOG", yf="KOG.OL", country="Norway",
         group="Defence & Aerospace", rep="NOK", trd="NOK", src="roic.ai (NSKFF)",
         first=2013, flag="Y", note="Kongsberg Maritime demerged: FY2024-25 restated ex-Maritime, earlier years incl. Maritime",
         hurl=ROIC + "NSKFF/classic", murl=SA + "osl/KOG/statistics/",
         rev=[16323, 16552, 17032, 15845, 14490, 14381, 23245, 25612, 27449, 31803, 40617, 24648, 31562],
         mar=[10.16, 8.79, 6.89, 3.05, 4.31, 5.35, 4.51, 7.89, 10.47, 10.47, 11.43, 13.03, 14.88],
         mkt=(301.00, "2026-10-23", 879.56, 264750, -1710, 263820, 35730, 5770, 0.22)),
    dict(name="Tomra", ticker="TOM", yf="TOM.OL", country="Norway",
         group="General Machinery", rep="EUR", trd="NOK", src="roic.ai (OSL-TOM)",
         first=2013, flag="N", note="Revenue before FY2023 unusable in source (unit error) -> blank; margins complete",
         hurl=ROIC + "OSL-TOM", murl=SA + "osl/TOM/statistics/",
         rev=[None] * 10 + [1288, 1348, 1318],
         mar=[13.51, 13.21, 14.5, 14.94, 12.32, 12.55, 12.6, 13.08, 14.23, 11.9, 7.83, 11.66, 11.23],
         mkt=(94.50, "2026-10-23", 295.70, 27940, 6410, 34790, 16190, 1860, 1.17)),
    dict(name="Veidekke", ticker="VEI", yf="VEI.OL", country="Norway",
         group="Construction & Engineering", rep="NOK", trd="NOK", src="stockanalysis.com (5y)",
         first=2021, flag="N", note="Only FY2021-25 available (5 obs); margin = EBIT / revenue",
         hurl=SA + "osl/VEI/financials/", murl=SA + "osl/VEI/statistics/",
         rev=_VEI_REV, mar=_m(_VEI_EBIT, _VEI_REV),
         mkt=(213.50, "2026-09-18", 135.48, 28920, -3440, 25560, 44770, 2090, 0.77)),
    # ----------------------------------------------------------------- DENMARK
    dict(name="Vestas", ticker="VWS", yf="VWS.CO", country="Denmark",
         group="Energy & Electrical Equipment", rep="EUR", trd="DKK", src="roic.ai (VWDRY)",
         first=2013, flag="N", note="",
         hurl=ROIC + "VWDRY", murl=SA + "cph/VWS/statistics/",
         rev=[6084, 6910, 8423, 10237, 9953, 10134, 12147, 14819, 15587, 14486, 15382, 17295, 18822],
         mar=[3.39, 8.13, 10.2, 13.88, 12.36, 9.46, 8.27, 5.06, 2.75, -7.95, 0.23, 4.27, 5.67],
         mkt=(184.85, "2026-10-20", 978.25, 180830, -687.82, 180200, 151750, 11720, 1.02)),
    dict(name="DSV", ticker="DSV", yf="DSV.CO", country="Denmark",
         group="Transport & Logistics", rep="DKK", trd="DKK", src="roic.ai (DSDVY)",
         first=2013, flag="N", note="DB Schenker acquired 2025",
         hurl=ROIC + "DSDVY", murl=SA + "cph/DSV/statistics/",
         rev=[45710, 48582, 50869, 67747, 74901, 79053, 94701, 115932, 182306, 235665, 150785, 167106, 247331],
         mar=[5.46, 5.4, 6.0, 5.13, 6.51, 6.89, 7.03, 8.21, 8.9, 10.69, 11.73, 9.61, 7.91],
         mkt=(1383.50, "2026-10-22", 238.78, 330350, 81230, 411950, 299490, 23220, 0.99)),
    dict(name="FLSmidth", ticker="FLS", yf="FLS.CO", country="Denmark",
         group="Mining & Process Equipment", rep="DKK", trd="DKK", src="roic.ai (FLIDY)",
         first=2013, flag="Y", note="Cement divested: FY2024-25 mining-only, earlier years incl. Cement",
         hurl=ROIC + "FLIDY", murl=SA + "cph/FLS/statistics/",
         rev=[25482, 20499, 19682, 18192, 18000, 18750, 20646, 16441, 17581, 21849, 24106, 15740, 14612],
         mar=[-1.11, 6.92, 5.82, 5.01, 5.91, 6.52, 6.23, 2.75, 4.12, 2.83, 4.98, 9.03, 12.67],
         mkt=(578.00, "2026-10-15", 53.24, 30770, 2180, 32950, 14750, 2050, 1.35)),
    dict(name="Rockwool", ticker="ROCK B", yf="ROCK-B.CO", country="Denmark",
         group="Building Products & Elevators", rep="EUR", trd="DKK", src="roic.ai (RKWBF)",
         first=2013, flag="N", note="",
         hurl=ROIC + "RKWBF", murl=SA + "cph/ROCK.B/statistics/",
         rev=[2003, 2180, 2208, 2202, 2374, 2671, 2757, 2602, 3088, 3907, 3620, 3855, 3877],
         mar=[8.76, 7.6, 7.08, 10.24, 10.91, 13.03, 13.57, 13.11, 12.99, 10.29, 14.67, 17.74, 15.32],
         mkt=(204.20, "2026-09-04", 206.81, 43190, -770.06, 42420, 29640, 4310, 1.51)),
    dict(name="NKT", ticker="NKT", yf="NKT.CO", country="Denmark",
         group="Energy & Electrical Equipment", rep="EUR", trd="DKK", src="stockanalysis.com (5y)",
         first=2021, flag="Y", note="Only FY2021-25; structural shift to HV power cables",
         hurl=SA + "cph/NKT/financials/", murl=SA + "cph/NKT/statistics/",
         rev=_NKT_REV, mar=_m(_NKT_EBIT, _NKT_REV),
         mkt=(806.00, "2026-10-23", 53.45, 43080, -4420, 38660, 26870, 4400, 0.65)),
    dict(name="ISS", ticker="ISS", yf="ISS.CO", country="Denmark",
         group="Industrial Distribution & Services", rep="DKK", trd="DKK", src="roic.ai (ISS.CO)",
         first=2013, flag="N", note="FY2020 COVID loss",
         hurl=ROIC + "ISS.CO", murl=SA + "cph/ISS/statistics/",
         rev=[78459, 74105, 79579, 78658, 73577, 73592, 77698, 70752, 71363, 73838, 78681, 83761, 84684],
         mar=[5.37, 5.6, 4.87, 4.96, 5.16, 4.4, 3.75, -4.65, 2.4, 3.86, 4.11, 4.84, 4.81],
         mkt=(301.20, "2026-10-16", 154.45, 46520, 15840, 62570, 87770, 4280, 0.83)),
    dict(name="A.P. Møller-Mærsk", ticker="MAERSK B", yf="MAERSK-B.CO", country="Denmark",
         group="Transport & Logistics", rep="USD", trd="DKK", src="roic.ai (AMKBY)",
         first=2013, flag="N", note="Reports in USD; energy divested 2016-18; freight-rate super-cycle 2021-22",
         hurl=ROIC + "AMKBY", murl=SA + "cph/MAERSK.B/statistics/",
         rev=[47386, 47569, 40308, 27266, 30945, 39280, 38890, 39740, 61787, 81529, 51065, 55482, 53988],
         mar=[14.46, 10.19, 2.68, 0.02, 1.74, 0.24, 3.73, 9.34, 30.95, 37.63, 5.94, 10.75, 5.4],
         mkt=(24030.0, "2026-10-20", 14.46, 339440, -6660, 340210, 368190, 17840, 0.51)),
]
NC = len(COMPANIES)
assert NC == 30

GROUPS = ["General Machinery", "Mining & Process Equipment", "Vehicles & Mobile Machinery",
          "Building Products & Elevators", "Energy & Electrical Equipment", "Defence & Aerospace",
          "Construction & Engineering", "Transport & Logistics", "Industrial Distribution & Services"]
COUNTRIES = [("Sweden", 0.206), ("Finland", 0.20), ("Norway", 0.22), ("Denmark", 0.22)]

# Default assumptions: (name, label, value, fmt, note, key?, list-options)
ASSUMPTIONS = [
    ("H", "Data window & signal basis"),
    ("LastFY", "Last fiscal year in history", 2025, "0", "Latest complete fiscal year used for the window", True, None),
    ("Lookback", "Look-back window (years)", 10, "0", "Normal margin = statistics over the last N fiscal years (max 13)", True, None),
    ("MinObs", "Minimum observations", 5, "0", "Companies with fewer valid years in window are EXCLUDED", False, None),
    ("Basis", "Current margin basis", "TTM", "@", "TTM = trailing 12m (market-data source); FY = last fiscal year (history source)", True, "TTM,FY"),
    ("Central", "Own-history central tendency", "Median", "@", "Median is robust to one-off years (impairments, COVID)", True, "Median,Mean"),
    ("ExclFlagged", "Exclude data-flagged companies from signals", "No", "@", "Yes = structural-break companies get EXCLUDED; No = ranked but marked '(data flag)'", False, "Yes,No"),
    ("H", "Normalized margin = blend of three anchors"),
    ("W_Own", "Weight: own history", 0.60, "0%", "Company-specific competitive position persists (moats)", True, None),
    ("W_Peer", "Weight: peer-group average", 0.25, "0%", "Industry economics pull margins toward peers", True, None),
    ("W_Univ", "Weight: universe median", 0.15, "0%", "Fama-French: profitability reverts toward economy-wide level", True, None),
    ("WSumCheck", "Check: weights sum to 100%", "=W_Own+W_Peer+W_Univ", "0%", "Must equal 100%", False, None),
    ("H", "Speed of reversion (AR(1) persistence phi)"),
    ("PhiPrior", "Prior persistence phi", 0.60, "0.00", "Fama & French (2000): ~38% of a profitability deviation disappears in one year -> phi ~0.6", True, None),
    ("ShrinkW", "Weight on company-estimated phi", 0.30, "0%", "Small-sample AR(1) estimates are noisy & downward-biased -> shrink toward prior", True, None),
    ("PhiMin", "phi floor", 0.00, "0.00", "", False, None),
    ("PhiMax", "phi cap", 0.95, "0.00", "", False, None),
    ("H", "Valuation (WACC, growth, reinvestment)"),
    ("WACCMode", "Fundamental WACC mode (implied-margin factor)", "Market-calibrated", "@",
     "Market-calibrated = CAPM WACC shifted equally so the universe-median company is fairly priced on normalized margins "
     "(cheapness is RELATIVE to the Nordic market). CAPM = absolute.", True, "Market-calibrated,CAPM"),
    ("DCFRate", "Discount rate in the fade DCF", "Market-implied", "@",
     "Market-implied = each company's own implied cost of capital at its CURRENT margin: the only disagreement with "
     "the market is margin persistence. Fundamental = WACC above.", True, "Market-implied,Fundamental"),
    ("Rf", "Risk-free rate", 0.0275, "0.00%", "Approx. 10y government yield; update to current level", True, None),
    ("ERP", "Equity risk premium", 0.055, "0.00%", "", True, None),
    ("CreditSpread", "Pre-tax credit spread", 0.015, "0.00%", "Kd = Rf + spread", False, None),
    ("BetaFloor", "Adjusted beta floor", 0.70, "0.00", "Guards against meaningless raw betas (e.g. Saab 0.03)", False, None),
    ("BlumeW", "Blume weight on raw beta", 0.67, "0.00", "Adjusted beta = w*raw + (1-w)*1.0", False, None),
    ("WACCMin", "WACC floor", 0.05, "0.0%", "", False, None),
    ("WACCMax", "WACC cap", 0.12, "0.0%", "", False, None),
    ("GrowthExplicit", "Revenue growth, years 1-10", 0.03, "0.0%", "Nominal; same for all companies", True, None),
    ("GrowthTerminal", "Terminal growth", 0.02, "0.0%", "", True, None),
    ("RONIC", "Return on new invested capital", 0.15, "0.0%", "Reinvestment rate = g / RONIC (value-driver formula)", True, None),
    ("H", "Composite score & signals"),
    ("Wt_Gap", "Weight: margin gap (normal - current)", 0.30, "0%", "", True, None),
    ("Wt_Z", "Weight: -z-score vs own history", 0.15, "0%", "", True, None),
    ("Wt_Implied", "Weight: normal - market-implied margin", 0.25, "0%", "", True, None),
    ("Wt_DCF", "Weight: reversion upside (fade DCF vs status quo)", 0.30, "0%",
     "Equity value change if margins fade to normal vs. if today's margin persists", True, None),
    ("WtSumCheck", "Check: score weights sum to 100%", "=Wt_Gap+Wt_Z+Wt_Implied+Wt_DCF", "0%", "Must equal 100%", False, None),
    ("ZCap", "Winsorize factor z-scores at +/-", 3.0, "0.0", "", False, None),
    ("LongPct", "LONG if composite percentile >=", 0.80, "0%", "Top quintile", True, None),
    ("ShortPct", "SHORT / AVOID if percentile <=", 0.20, "0%", "Bottom quintile", True, None),
    ("TrendMax", "Value-trap filter: max margin decline per year", 0.005, "0.00%", "If margin is below normal AND trend < -this -> WATCH instead of LONG", True, None),
]

# =============================================================================
# 2. PYTHON IMPLEMENTATION OF THE MODEL (mirrors the Excel formulas)
# =============================================================================


def default_assumptions() -> dict:
    a = {}
    for row in ASSUMPTIONS:
        if row[0] == "H" or (isinstance(row[2], str) and row[2].startswith("=")):
            continue
        a[row[0]] = row[2]
    return a


def _ols(x, y):
    n = len(x)
    if n < 3:
        return None
    sx, sy = sum(x), sum(y)
    sxy = sum(i * j for i, j in zip(x, y))
    sxx = sum(i * i for i in x)
    den = n * sxx - sx * sx
    return None if den == 0 else (n * sxy - sx * sy) / den


def compute_model(companies=COMPANIES, a=None) -> list[dict]:
    """Pure-Python version of the workbook logic. Returns one dict per company."""
    a = a or default_assumptions()
    out = []
    for c in companies:
        r = {"name": c["name"], "group": c["group"], "country": c["country"], "flag": c["flag"]}
        start = max(c["first"], a["LastFY"] - a["Lookback"] + 1)
        win = [(i, y, c["mar"][i] / 100) for i, y in enumerate(YEARS)
               if start <= y <= a["LastFY"] and c["mar"][i] is not None]
        vals = [v for _, _, v in win]
        n = len(vals)
        mean = statistics.mean(vals) if n else None
        med = statistics.median(vals) if n else None
        sd = statistics.stdev(vals) if n >= 2 else None
        ly = YEARS.index(a["LastFY"])
        fy_m = (c["mar"][ly] or 0) / 100
        p, d, sh, mcap, nd, ev, rev, ebit, beta = c["mkt"]
        ttm_m = ebit / rev
        cur = ttm_m if a["Basis"] == "TTM" else fy_m
        pct = ((sum(v < cur for v in vals) + 0.5 * sum(v == cur for v in vals)) / n) if n else None
        z = (cur - mean) / sd if (n >= 2 and sd and sd > 0) else None
        # AR(1) on deviations from window mean, consecutive valid pairs only
        dev = {i: v - mean for i, _, v in win}
        xs = [dev[i - 1] for i in dev if (i - 1) in dev]
        ys = [dev[i] for i in dev if (i - 1) in dev]
        phi = _ols(xs, ys) if len(xs) >= 3 else None
        if phi is None:
            phi = a["PhiPrior"]
        trend = _ols([i + 1 for i in dev], [dev[i] for i in dev]) if n >= 3 else 0
        trend = trend or 0
        r.update(n=n, start=start, mean=mean, median=med, sd=sd, cur=cur, fy=fy_m, ttm=ttm_m,
                 pct=pct, z=z, phi_est=phi, trend=trend,
                 own=med if a["Central"] == "Median" else mean,
                 price=p, shares=sh, mcap=mcap, nd=nd, ev=ev, rev_ttm=rev, beta=beta)
        out.append(r)
    # anchors
    univ = statistics.median([r["own"] for r in out])
    for r in out:
        peers = [q["own"] for q in out if q["group"] == r["group"]]
        r["peer"] = sum(peers) / len(peers)
        r["univ"] = univ
        r["norm"] = a["W_Own"] * r["own"] + a["W_Peer"] * r["peer"] + a["W_Univ"] * univ
        r["gap"] = r["norm"] - r["cur"]
        phi = a["ShrinkW"] * r["phi_est"] + (1 - a["ShrinkW"]) * a["PhiPrior"]
        r["phi"] = min(a["PhiMax"], max(a["PhiMin"], phi))
        r["half_life"] = 0 if r["phi"] <= 0.0001 else math.log(0.5) / math.log(r["phi"])
        r["trap"] = "YES" if (r["gap"] > 0 and r["trend"] < -a["TrendMax"]) else "no"
        r["eligible"] = int(r["n"] >= a["MinObs"] and (a["ExclFlagged"] == "No" or r["flag"] != "Y"))
        # CAPM WACC (raw) and implied cost of capital at the normalized margin
        tax = dict(COUNTRIES)[r["country"]]
        b = max(a["BetaFloor"], a["BlumeW"] * r["beta"] + (1 - a["BlumeW"]))
        ke = a["Rf"] + b * a["ERP"]
        kd = (a["Rf"] + a["CreditSpread"]) * (1 - tax)
        dw = max(0, r["nd"]) / (r["mcap"] + max(0, r["nd"]))
        gT, R = a["GrowthTerminal"], a["RONIC"]
        r.update(tax=tax, wacc_raw=(1 - dw) * ke + dw * kd)
        for lab, m in (("icc_cur", r["cur"]), ("icc_norm", r["norm"])):
            r[lab] = gT + r["rev_ttm"] * (1 + gT) * m * (1 - tax) * (1 - gT / R) / r["ev"]
    shift = (statistics.median([r["icc_norm"] for r in out]) - statistics.median([r["wacc_raw"] for r in out])
             if a["WACCMode"] == "Market-calibrated" else 0.0)
    for r in out:
        tax = r["tax"]
        wf = min(a["WACCMax"], max(a["WACCMin"], r["wacc_raw"] + shift))
        gT, gE, R = a["GrowthTerminal"], a["GrowthExplicit"], a["RONIC"]
        w = max(gT + 0.01, r["icc_cur"]) if a["DCFRate"] == "Market-implied" else wf
        r.update(wacc_fund=wf, wacc=w, wacc_shift=shift)
        r["implied"] = r["ev"] * (wf - gT) / (r["rev_ttm"] * (1 + gT) * (1 - tax) * (1 - gT / R))
        r["implied_gap"] = r["norm"] - r["implied"]
        # margin-fade DCF
        pv = 0.0
        rev_t = r["rev_ttm"]
        pv_rev = 0.0
        for t in range(1, 11):
            rev_t = r["rev_ttm"] * (1 + gE) ** t
            m_t = r["norm"] + r["phi"] ** t * (r["cur"] - r["norm"])
            pv += rev_t * m_t * (1 - tax) * (1 - gE / R) / (1 + w) ** t
            pv_rev += rev_t / (1 + w) ** t
        tv = rev_t * (1 + gT) * r["norm"] * (1 - tax) * (1 - gT / R) / (w - gT)
        fair_ev = pv + tv / (1 + w) ** 10
        bridge = r["ev"] - r["mcap"]
        r["fair_ev"] = fair_ev
        r["upside"] = (fair_ev - bridge) / r["mcap"] - 1
        sq = r["cur"] * ((1 - tax) * (1 - gE / R) * pv_rev
                         + rev_t * (1 + gT) * (1 - tax) * (1 - gT / R) / (w - gT) / (1 + w) ** 10)
        r["sq_upside"] = (sq - bridge) / r["mcap"] - 1
        r["rev_upside"] = (fair_ev - bridge) / (sq - bridge) - 1 if sq - bridge > 0 else 0.0
    # composite score
    fac = {"gap": "Wt_Gap", "negz": "Wt_Z", "implied_gap": "Wt_Implied", "rev_upside": "Wt_DCF"}
    for r in out:
        r["negz"] = -(r["z"] or 0)
    el = [r for r in out if r["eligible"]]
    for f, wname in fac.items():
        vals = [r[f] for r in el]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1))
        for r in out:
            r["z_" + f] = max(-a["ZCap"], min(a["ZCap"], (r[f] - mu) / sd)) if r["eligible"] else 0
    for k, r in enumerate(out):
        r["score"] = sum(a[w] * r["z_" + f] for f, w in fac.items()) if r["eligible"] else None
        r["_key"] = (r["score"] if r["eligible"] else -100) - (k + 6) / 1e9
    order = sorted(out, key=lambda r: -r["_key"])
    ne = len(el)
    for rank, r in enumerate(order, 1):
        r["rank"] = rank
        if r["eligible"]:
            r["pctile"] = 1 - (rank - 1) / max(1, ne - 1)
            if r["pctile"] >= a["LongPct"]:
                sig = "WATCH - value trap" if r["trap"] == "YES" else "LONG"
            elif r["pctile"] <= a["ShortPct"]:
                sig = "SHORT / AVOID"
            else:
                sig = "NEUTRAL"
        else:
            r["pctile"], sig = None, "EXCLUDED"
        r["signal"] = sig + (" (data flag)" if r["flag"] == "Y" else "")
    return out


def evidence_regression(companies=COMPANIES, a=None):
    """Pooled test: next-year margin change vs deviation from expanding mean (no look-ahead)."""
    a = a or default_assumptions()
    xs, ys = [], []
    for c in companies:
        if a["ExclFlagged"] == "Yes" and c["flag"] == "Y":
            continue
        for i, y in enumerate(YEARS[:-1]):
            if y < c["first"] or y + 1 > a["LastFY"]:
                continue
            m0, m1 = c["mar"][i], c["mar"][i + 1]
            hist = [c["mar"][j] for j in range(i + 1) if YEARS[j] >= c["first"] and c["mar"][j] is not None]
            if m0 is None or m1 is None or len(hist) < 3:
                continue
            xs.append(m0 / 100 - statistics.mean(hist) / 100)
            ys.append((m1 - m0) / 100)
    return len(xs), _ols(xs, ys)


# =============================================================================
# 3. EXCEL BUILDER
# =============================================================================
F = "Arial"
NAVY, BLUE_IN, GREEN_LINK = "1F3864", "0000FF", "008000"
F_HDR = PatternFill("solid", start_color=NAVY, end_color=NAVY)
F_SEC = PatternFill("solid", start_color="D9E1F2", end_color="D9E1F2")
F_KEY = PatternFill("solid", start_color="FFFF00", end_color="FFFF00")
F_IN = PatternFill("solid", start_color="EEF3FB", end_color="EEF3FB")
F_GREY = PatternFill("solid", start_color="F2F2F2", end_color="F2F2F2")
F_LONG = PatternFill("solid", start_color="C6EFCE", end_color="C6EFCE")
F_SHORT = PatternFill("solid", start_color="FFC7CE", end_color="FFC7CE")
F_WATCH = PatternFill("solid", start_color="FFEB9C", end_color="FFEB9C")
THIN = Side(style="thin", color="BFBFBF")
B_BOT = Border(bottom=THIN)

PCT = '0.0%;(0.0%);"-"'
PCT2 = '0.00%;(0.00%);"-"'
PCTS = '+0.0%;(0.0%);"-"'
NUM = '#,##0;(#,##0);"-"'
NUM1 = '#,##0.0;(#,##0.0);"-"'
NUM2 = '#,##0.00;(#,##0.00);"-"'
MULT = '0.0"x";(0.0"x");"-"'
DEC2 = '0.00;(0.00);"-"'
YR = "0"

R0, R1 = 6, 5 + NC          # company rows 6..35
HDR = 5
YC0 = 4                     # year columns D..P
YCOLS = [CL(YC0 + i) for i in range(N_Y)]
YFIRST, YLAST = YCOLS[0], YCOLS[-1]


def font(color="000000", bold=False, size=10, italic=False):
    return Font(name=F, color=color, bold=bold, size=size, italic=italic)


def put(ws, ref, value=None, fmt=None, color="000000", bold=False, fill=None, align=None,
        size=10, italic=False, wrap=False, border=None):
    c = ws[ref]
    if value is not None:
        c.value = value
    c.font = font(color, bold, size, italic)
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if align or wrap:
        c.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    if border:
        c.border = border
    return c


def title(ws, text, sub=None):
    put(ws, "A1", text, bold=True, size=16, color=NAVY)
    if sub:
        put(ws, "A2", sub, italic=True, color="595959")
    ws.sheet_view.showGridLines = False


def header_row(ws, row, labels, start_col=1, height=30):
    for j, lab in enumerate(labels):
        c = ws.cell(row=row, column=start_col + j, value=lab)
        c.font = font("FFFFFF", True)
        c.fill = F_HDR
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = height


def section(ws, row, text, c1=1, c2=12):
    for col in range(c1, c2 + 1):
        ws.cell(row=row, column=col).fill = F_SEC
    put(ws, f"{CL(c1)}{row}", text, bold=True, color=NAVY)


def widths(ws, d):
    for k, v in d.items():
        ws.column_dimensions[k].width = v


def company_cols(ws, row=HDR, with_name=True):
    """Columns A (#) and B (company name, linked to Universe)."""
    for i in range(NC):
        r = R0 + i
        put(ws, f"A{r}", i + 1, align="center", color="595959")
        if with_name:
            put(ws, f"B{r}", f"=Universe!$B{r}", color=GREEN_LINK)


def year_header(ws, row=HDR, link=True):
    for i, y in enumerate(YEARS):
        ref = f"{YCOLS[i]}{row}"
        if link:
            put(ws, ref, f"=Data_Margin!{YCOLS[i]}${HDR}", fmt=YR, bold=True, color="FFFFFF",
                fill=F_HDR, align="center")
        else:
            put(ws, ref, y, fmt=YR, bold=True, color="FFFFFF", fill=F_HDR, align="center")


def style_chart(ch, low_labels=False):
    """Show both axes explicitly (openpyxl >= 3.1 otherwise hides them in Excel)."""
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    if low_labels:
        ch.x_axis.tickLblPos = "low"
    return ch


def add_name(wb, name, ref):
    wb.defined_names[name] = DefinedName(name, attr_text=ref)


def signal_cf(ws, rng):
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("LONG",{rng.split(":")[0]}))'], fill=F_LONG))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("SHORT",{rng.split(":")[0]}))'], fill=F_SHORT))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("WATCH",{rng.split(":")[0]}))'], fill=F_WATCH))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("EXCLUDED",{rng.split(":")[0]}))'], fill=F_GREY))


def gap_scale(ws, rng):
    ws.conditional_formatting.add(rng, ColorScaleRule(start_type="num", start_value=-0.05, start_color="F8696B",
                                                      mid_type="num", mid_value=0, mid_color="FFFFFF",
                                                      end_type="num", end_value=0.05, end_color="63BE7B"))


# ----------------------------------------------------------------------------- sheets
def sh_readme(wb):
    ws = wb.create_sheet("README")
    title(ws, "Nordic Industrials - Margin Reversion Model",
          f"30 companies | SE, FI, NO, DK | history FY2013-FY2025 | market data snapshot {SNAPSHOT_DATE}")
    rows = [
        ("PHILOSOPHY", None),
        ("Operating margins mean-revert: competition erodes excess margins, restructuring and capacity exits repair depressed ones.", None),
        ("The market tends to extrapolate current margins. The model values companies on NORMALIZED margins and on the SPEED at which current margins fade toward normal.", None),
        ("Evidence: Fama & French (2000) find ~38% of a profitability deviation disappears per year; Koller et al. ('Valuation', McKinsey) show margin/ROIC fade toward industry medians. The Evidence sheet tests this on this universe.", None),
        ("", None),
        ("HOW THE MODEL WORKS", None),
        ("1. Margins: window of the last N fiscal years (Assumptions) -> mean, median, st.dev, percentile, z-score of the current margin.", None),
        ("2. Reversion: normalized margin = w_own x own median + w_peer x peer average + w_univ x universe median.", None),
        ("3. Persistence: AR(1) on margin deviations (Persistence sheet), shrunk toward a prior phi -> half-life of a deviation.", None),
        ("4. Market-implied margin: steady-state margin that justifies today's EV with the value-driver formula EV = Rev x m x (1-t) x (1-g/RONIC) / (WACC-g).", None),
        ("5. Margin-fade DCF: 10 years, m(t) = m_norm + phi^t x (m_now - m_norm); terminal value at m_norm. Reversion upside = fade value vs status-quo value (today's margin persists).", None),
        ("   Discount rates: the fade DCF uses each company's market-implied cost of capital (default) -> the only disagreement with the market is margin persistence.", None),
        ("   The implied-margin factor uses a fundamental CAPM WACC, by default shifted equally so the universe median is fairly priced -> cheapness is relative to the Nordic market.", None),
        ("6. Scoring: four factors standardized across eligible companies -> composite -> rank -> LONG / NEUTRAL / SHORT; value-trap filter.", None),
        ("", None),
        ("HOW TO USE", None),
        ("Change ONLY blue cells. Yellow = key assumptions (Assumptions sheet). Everything else recalculates.", None),
        ("Deep_Dive: pick any company from the drop-down in C3 for its full history, fade path and a WACC x margin sensitivity grid.", None),
        ("Update prices: re-run the Python script with --refresh-market (yfinance) or overwrite blue cells in Data_Market.", None),
        ("", None),
        ("COLOUR CODE", None),
    ]
    r = 4
    for text, _ in rows:
        is_h = text.isupper() and text != ""
        put(ws, f"A{r}", text, bold=is_h, color=NAVY if is_h else "000000", size=11 if is_h else 10)
        r += 1
    legend = [("Blue text", "Hard-coded input / raw data", BLUE_IN, None),
              ("Black text", "Formula", "000000", None),
              ("Green text", "Link to another sheet", GREEN_LINK, None),
              ("Yellow fill", "Key assumption", BLUE_IN, F_KEY)]
    for lab, desc, col, fill in legend:
        put(ws, f"A{r}", lab, color=col, fill=fill, bold=True)
        put(ws, f"B{r}", desc)
        r += 1
    r += 1
    put(ws, f"A{r}", "SHEET MAP", bold=True, color=NAVY, size=11)
    r += 1
    sheets = [("Dashboard", "KPIs, top/bottom 5, charts"),
              ("Assumptions", "All model levers"),
              ("Universe", "30 companies, peer groups, data-quality flags"),
              ("Data_Revenue / Data_Margin", "Raw FY2013-25 revenue and operating margin (sourced)"),
              ("Data_Market", "Price, market cap, net debt, EV, TTM revenue & EBIT"),
              ("EBIT_History", "EBIT = revenue x margin, revenue CAGR"),
              ("Margins", "Window-cleaned margins and statistics"),
              ("Persistence", "AR(1) regression sums, phi, margin trend"),
              ("Reversion", "Normalized margin, gap, expected path, value-trap flag"),
              ("Peers", "Peer-group summary"),
              ("WACC", "CAPM cost of capital per company"),
              ("Implied", "Market-implied steady-state margin"),
              ("DCF_Fade", "10-year margin-fade DCF + status-quo comparison"),
              ("Scoring", "Factor z-scores, composite, rank, signal"),
              ("Ranking", "Sorted league table (all 30)"),
              ("Deep_Dive", "Single-company view with sensitivity"),
              ("Evidence", "Pooled in-sample test of margin reversion"),
              ("Sources", "Data sources and caveats")]
    for s, d in sheets:
        put(ws, f"A{r}", s, bold=True)
        put(ws, f"B{r}", d)
        r += 1
    r += 1
    put(ws, f"A{r}", "Not investment advice. Data from third-party aggregators; verify against company reports before use.",
        italic=True, color="C00000")
    widths(ws, {"A": 28, "B": 70})


def sh_assumptions(wb):
    ws = wb.create_sheet("Assumptions")
    title(ws, "Assumptions", "Blue = input. Yellow = key lever. All model sheets reference these named cells.")
    header_row(ws, 3, ["Name", "Assumption", "Value", "Note"], 1)
    r = 4
    dvs = {}
    for row in ASSUMPTIONS:
        if row[0] == "H":
            section(ws, r, row[1], 1, 4)
            r += 1
            continue
        name, label, val, fmt, note, key, opts = row
        put(ws, f"A{r}", name, color="595959", italic=True)
        put(ws, f"B{r}", label)
        is_formula = isinstance(val, str) and val.startswith("=")
        put(ws, f"C{r}", val, fmt=fmt, color="000000" if is_formula else BLUE_IN,
            fill=F_KEY if key else (None if is_formula else F_IN), align="center", bold=is_formula)
        put(ws, f"D{r}", note, italic=True, color="595959")
        add_name(wb, name, f"Assumptions!$C${r}")
        if opts:
            dvs.setdefault(opts, []).append(f"C{r}")
        r += 1
    for opts, cells in dvs.items():
        dv = DataValidation(type="list", formula1=f'"{opts}"', allow_blank=False)
        ws.add_data_validation(dv)
        for c in cells:
            dv.add(c)
    # integer validation for window
    dv = DataValidation(type="whole", operator="between", formula1="2", formula2=str(N_Y))
    ws.add_data_validation(dv)
    dv.add("C6")
    # checks red if not 100%
    for nm in ("WSumCheck", "WtSumCheck"):
        ref = wb.defined_names[nm].attr_text.split("!")[1].replace("$", "")
        ws.conditional_formatting.add(ref, FormulaRule(formula=[f"ROUND({ref},6)<>1"], fill=F_SHORT))
    r += 1
    section(ws, r, "Corporate tax rates by country (statutory)", 1, 4)
    r += 1
    header_row(ws, r, ["", "Country", "Tax rate", "Note"], 1, 18)
    r += 1
    t0 = r
    for ctry, tax in COUNTRIES:
        put(ws, f"B{r}", ctry)
        put(ws, f"C{r}", tax, fmt="0.0%", color=BLUE_IN, fill=F_IN, align="center")
        put(ws, f"D{r}", "Statutory corporate income tax rate", italic=True, color="595959")
        r += 1
    add_name(wb, "TaxCountry", f"Assumptions!$B${t0}:$B${r - 1}")
    add_name(wb, "TaxRate", f"Assumptions!$C${t0}:$C${r - 1}")
    widths(ws, {"A": 15, "B": 44, "C": 12, "D": 86})
    ws.freeze_panes = "A4"


def sh_universe(wb):
    ws = wb.create_sheet("Universe")
    title(ws, "Universe - 30 Nordic industrial companies",
          "Peer groups drive the peer anchor of the normalized margin. 'First valid year' trims history before a structural break.")
    header_row(ws, HDR, ["#", "Company", "Ticker", "Country", "Peer group", "Reporting ccy (history)",
                         "Trading ccy (market data)", "History source", "First valid year", "Data flag (Y/N)",
                         "Data note", "History URL", "Market data URL"])
    dv_g = DataValidation(type="list", formula1=f"=Peers!$A${R0}:$A${R0 + len(GROUPS) - 1}")
    ws.add_data_validation(dv_g)
    dv_f = DataValidation(type="list", formula1='"Y,N"')
    ws.add_data_validation(dv_f)
    for i, c in enumerate(COMPANIES):
        r = R0 + i
        put(ws, f"A{r}", i + 1, align="center", color="595959")
        put(ws, f"B{r}", c["name"], color=BLUE_IN, bold=True)
        put(ws, f"C{r}", c["ticker"], color=BLUE_IN)
        put(ws, f"D{r}", c["country"], color=BLUE_IN)
        put(ws, f"E{r}", c["group"], color=BLUE_IN)
        put(ws, f"F{r}", c["rep"], color=BLUE_IN, align="center")
        put(ws, f"G{r}", c["trd"], color=BLUE_IN, align="center")
        put(ws, f"H{r}", c["src"], color=BLUE_IN)
        put(ws, f"I{r}", c["first"], fmt=YR, color=BLUE_IN, align="center", fill=F_IN)
        put(ws, f"J{r}", c["flag"], color=BLUE_IN, align="center", fill=F_IN)
        put(ws, f"K{r}", c["note"], color="595959", italic=True)
        put(ws, f"L{r}", c["hurl"], color="0563C1")
        ws[f"L{r}"].hyperlink = c["hurl"]
        put(ws, f"M{r}", c["murl"], color="0563C1")
        ws[f"M{r}"].hyperlink = c["murl"]
        dv_g.add(f"E{r}")
        dv_f.add(f"J{r}")
    ws.conditional_formatting.add(f"J{R0}:J{R1}", CellIsRule(operator="equal", formula=['"Y"'], fill=F_WATCH))
    widths(ws, {"A": 4, "B": 20, "C": 11, "D": 9, "E": 31, "F": 12, "G": 12, "H": 22, "I": 10, "J": 9,
                "K": 60, "L": 40, "M": 46})
    ws.freeze_panes = "C6"


def sh_data(wb):
    # ---------- revenue
    ws = wb.create_sheet("Data_Revenue")
    title(ws, "Raw data - Revenue (millions, reporting currency)",
          "Source: roic.ai standardized annual statements (Sales/Revenue/Turnover); stockanalysis.com for Ponsse, Veidekke, NKT. Retrieved 2026-11-07.")
    header_row(ws, HDR, ["#", "Company", "Ccy"] + [""] * N_Y + ["Source"])
    year_header(ws, link=False)
    company_cols(ws)
    for i, c in enumerate(COMPANIES):
        r = R0 + i
        put(ws, f"C{r}", f"=Universe!$F{r}", color=GREEN_LINK, align="center")
        for j, v in enumerate(c["rev"]):
            put(ws, f"{YCOLS[j]}{r}", v, fmt=NUM, color=BLUE_IN)
        put(ws, f"Q{r}", c["src"], color="595959", italic=True)
    widths(ws, {"A": 4, "B": 20, "C": 6, "Q": 24, **{k: 10 for k in YCOLS}})
    ws.freeze_panes = "D6"

    # ---------- margin
    ws = wb.create_sheet("Data_Margin")
    title(ws, "Raw data - Operating (EBIT) margin, reported",
          "Source: roic.ai 'Operating Margin (%)'; for Ponsse/Veidekke/NKT = stockanalysis.com operating income / revenue. Blank = not available.")
    header_row(ws, HDR, ["#", "Company", "Source"] + [""] * N_Y + ["Data note"])
    year_header(ws, link=False)
    company_cols(ws)
    for i, c in enumerate(COMPANIES):
        r = R0 + i
        put(ws, f"C{r}", c["src"].split(" (")[0], color="595959", italic=True)
        for j, v in enumerate(c["mar"]):
            put(ws, f"{YCOLS[j]}{r}", None if v is None else v / 100, fmt=PCT, color=BLUE_IN)
        put(ws, f"Q{r}", f"=Universe!$K{r}", color=GREEN_LINK, italic=True)
    gap_scale_cells = f"{YFIRST}{R0}:{YLAST}{R1}"
    ws.conditional_formatting.add(gap_scale_cells, ColorScaleRule(start_type="percentile", start_value=5, start_color="F8696B",
                                                                  mid_type="percentile", mid_value=50, mid_color="FFFFFF",
                                                                  end_type="percentile", end_value=95, end_color="63BE7B"))
    widths(ws, {"A": 4, "B": 20, "C": 14, "Q": 60, **{k: 8.5 for k in YCOLS}})
    ws.freeze_panes = "D6"

    # ---------- market
    ws = wb.create_sheet("Data_Market")
    title(ws, "Raw data - Market snapshot (millions, TRADING currency)",
          "Source: stockanalysis.com statistics pages (delayed quotes, dates per row). Net debt: positive = debt, negative = net cash.")
    header_row(ws, HDR, ["#", "Company", "Trading ccy", "Share price", "Price date", "Shares (m)",
                         "Market cap (m)", "Net debt (m)", "Enterprise value (m)", "Other EV items (m)",
                         "TTM revenue (m)", "TTM EBIT (m)", "TTM EBIT margin", "EV / Sales", "EV / EBIT",
                         "Beta (5y, raw)", "Source URL"])
    company_cols(ws)
    for i, c in enumerate(COMPANIES):
        r = R0 + i
        p, d, sh, mcap, nd, ev, rev, ebit, beta = c["mkt"]
        put(ws, f"C{r}", f"=Universe!$G{r}", color=GREEN_LINK, align="center")
        put(ws, f"D{r}", p, fmt=NUM2, color=BLUE_IN)
        put(ws, f"E{r}", d, color=BLUE_IN, align="center")
        put(ws, f"F{r}", sh, fmt=NUM2, color=BLUE_IN)
        put(ws, f"G{r}", mcap, fmt=NUM, color=BLUE_IN)
        put(ws, f"H{r}", nd, fmt=NUM, color=BLUE_IN)
        put(ws, f"I{r}", ev, fmt=NUM, color=BLUE_IN)
        put(ws, f"J{r}", f"=I{r}-G{r}-H{r}", fmt=NUM)
        put(ws, f"K{r}", rev, fmt=NUM, color=BLUE_IN)
        put(ws, f"L{r}", ebit, fmt=NUM, color=BLUE_IN)
        put(ws, f"M{r}", f"=IF(K{r}>0,L{r}/K{r},\"\")", fmt=PCT)
        put(ws, f"N{r}", f"=IF(K{r}>0,I{r}/K{r},\"\")", fmt=MULT)
        put(ws, f"O{r}", f"=IF(L{r}>0,I{r}/L{r},\"\")", fmt=MULT)
        put(ws, f"P{r}", beta, fmt=DEC2, color=BLUE_IN)
        put(ws, f"Q{r}", c["murl"], color="0563C1")
        ws[f"Q{r}"].hyperlink = c["murl"]
    ws["J5"].comment = Comment("EV - market cap - net debt: minorities, leases, pensions etc. as reported by the source. Kept constant in the equity bridge.", "Model")
    ws["E5"].comment = Comment("Delayed quote date shown on the source page when retrieved (2026-11-07).", "Model")
    widths(ws, {"A": 4, "B": 20, "C": 8, "D": 11, "E": 11, "F": 10, "G": 12, "H": 11, "I": 12, "J": 10,
                "K": 11, "L": 10, "M": 10, "N": 9, "O": 9, "P": 9, "Q": 46})
    ws.freeze_panes = "C6"


def sh_ebit(wb):
    ws = wb.create_sheet("EBIT_History")
    title(ws, "EBIT history (millions, reporting currency) = revenue x operating margin",
          "Informational; the reversion model works on margins (currency-free).")
    header_row(ws, HDR, ["#", "Company", "Ccy"] + [""] * N_Y + ["Revenue CAGR FY15-25", "EBIT CAGR FY15-25", "Avg margin (all yrs)"])
    year_header(ws)
    company_cols(ws)
    for i in range(NC):
        r = R0 + i
        put(ws, f"C{r}", f"=Universe!$F{r}", color=GREEN_LINK, align="center")
        for col in YCOLS:
            put(ws, f"{col}{r}",
                f"=IF(AND(ISNUMBER(Data_Revenue!{col}{r}),ISNUMBER(Data_Margin!{col}{r})),Data_Revenue!{col}{r}*Data_Margin!{col}{r},\"\")",
                fmt=NUM)
        put(ws, f"Q{r}", f"=IF(AND(ISNUMBER(Data_Revenue!F{r}),ISNUMBER(Data_Revenue!P{r})),(Data_Revenue!P{r}/Data_Revenue!F{r})^(1/10)-1,\"\")", fmt=PCT)
        put(ws, f"R{r}", f"=IF(AND(ISNUMBER(F{r}),ISNUMBER(P{r})),IF(AND(F{r}>0,P{r}>0),(P{r}/F{r})^(1/10)-1,\"\"),\"\")", fmt=PCT)
        put(ws, f"S{r}", f"=IFERROR(AVERAGE(Data_Margin!{YFIRST}{r}:{YLAST}{r}),\"\")", fmt=PCT)
    widths(ws, {"A": 4, "B": 20, "C": 6, "Q": 12, "R": 12, "S": 12, **{k: 10 for k in YCOLS}})
    ws.freeze_panes = "D6"


def sh_margins(wb):
    ws = wb.create_sheet("Margins")
    title(ws, "Margins in the look-back window + statistics",
          "Cell shows the margin only if FY >= start year and FY <= LastFY; otherwise blank (ignored by statistics).")
    header_row(ws, HDR, ["#", "Company", "Window start"] + [""] * N_Y +
               ["N obs", "Mean", "Median", "St.dev", "Min", "Max", "Last FY margin", "TTM margin",
                "CURRENT margin", "Percentile in own history", "Z-score vs own history"])
    year_header(ws)
    company_cols(ws)
    for i in range(NC):
        r = R0 + i
        put(ws, f"C{r}", f"=MAX(Universe!$I{r},LastFY-Lookback+1)", fmt=YR, align="center")
        for col in YCOLS:
            put(ws, f"{col}{r}",
                f"=IF(AND({col}${HDR}>=$C{r},{col}${HDR}<=LastFY,ISNUMBER(Data_Margin!{col}{r})),Data_Margin!{col}{r},\"\")",
                fmt=PCT)
        rng = f"{YFIRST}{r}:{YLAST}{r}"
        put(ws, f"Q{r}", f"=COUNT({rng})", fmt="0", align="center")
        put(ws, f"R{r}", f"=IF(Q{r}>0,AVERAGE({rng}),\"\")", fmt=PCT)
        put(ws, f"S{r}", f"=IF(Q{r}>0,MEDIAN({rng}),\"\")", fmt=PCT)
        put(ws, f"T{r}", f"=IF(Q{r}>=2,STDEV({rng}),\"\")", fmt=PCT)
        put(ws, f"U{r}", f"=IF(Q{r}>0,MIN({rng}),\"\")", fmt=PCT)
        put(ws, f"V{r}", f"=IF(Q{r}>0,MAX({rng}),\"\")", fmt=PCT)
        put(ws, f"W{r}", f"=IFERROR(INDEX(Data_Margin!${YFIRST}{r}:${YLAST}{r},MATCH(LastFY,Data_Margin!${YFIRST}${HDR}:${YLAST}${HDR},0)),\"\")", fmt=PCT)
        put(ws, f"X{r}", f"=Data_Market!M{r}", fmt=PCT, color=GREEN_LINK)
        put(ws, f"Y{r}", f"=IF(Basis=\"TTM\",X{r},W{r})", fmt=PCT, bold=True)
        put(ws, f"Z{r}", f"=IF(Q{r}>0,(COUNTIF({rng},\"<\"&Y{r})+0.5*COUNTIF({rng},Y{r}))/Q{r},\"\")", fmt="0%")
        put(ws, f"AA{r}", f"=IF(AND(Q{r}>=2,N(T{r})>0),(Y{r}-R{r})/T{r},\"\")", fmt=DEC2)
    ws.conditional_formatting.add(f"AA{R0}:AA{R1}", ColorScaleRule(start_type="num", start_value=-2, start_color="63BE7B",
                                                                   mid_type="num", mid_value=0, mid_color="FFFFFF",
                                                                   end_type="num", end_value=2, end_color="F8696B"))
    widths(ws, {"A": 4, "B": 20, "C": 8, **{k: 7.5 for k in YCOLS}, "Q": 6, "R": 8, "S": 8, "T": 8, "U": 8,
                "V": 8, "W": 9, "X": 9, "Y": 10, "Z": 11, "AA": 11})
    ws.freeze_panes = "D6"


def sh_persistence(wb):
    ws = wb.create_sheet("Persistence")
    title(ws, "Persistence of margin deviations - AR(1):  d(t) = a + phi x d(t-1)",
          "d = margin - own window mean. phi = OLS slope over consecutive valid pairs. Trend = OLS slope of margin on time (per year).")
    put(ws, "C4", "t index", bold=True, color="595959", align="right")
    for i, col in enumerate(YCOLS):
        put(ws, f"{col}4", i + 1, fmt="0", align="center", color="595959")
    header_row(ws, HDR, ["#", "Company", "Validity (1 = in window)"] + [""] * N_Y +
               ["", "Pairs n", "Sum x", "Sum y", "Sum xy", "Sum xx", "phi estimated",
                "Trend n", "Sum t", "Sum d", "Sum t*d", "Sum t*t", "Margin trend (per yr)"])
    year_header(ws)
    company_cols(ws)
    D0 = R0 + 35       # deviation block rows 41..70
    section(ws, D0 - 2, "Deviation from own window mean  d(t) = margin(t) - mean   (0 where not in window)", 1, 16)
    header_row(ws, D0 - 1, ["#", "Company", ""] + [""] * N_Y, height=18)
    for i, col in enumerate(YCOLS):
        put(ws, f"{col}{D0 - 1}", f"={col}${HDR}", fmt=YR, bold=True, color="FFFFFF", fill=F_HDR, align="center")
    for i in range(NC):
        r, d = R0 + i, D0 + i
        put(ws, f"A{d}", i + 1, align="center", color="595959")
        put(ws, f"B{d}", f"=Universe!$B{r}", color=GREEN_LINK)
        for col in YCOLS:
            put(ws, f"{col}{r}", f"=IF(ISNUMBER(Margins!{col}{r}),1,0)", fmt="0", align="center", color="808080")
            put(ws, f"{col}{d}", f"=IF({col}{r}=1,Margins!{col}{r}-Margins!$R{r},0)", fmt=PCT)
        Vp, Vc = f"$D{r}:$O{r}", f"$E{r}:$P{r}"
        Dp, Dc = f"$D{d}:$O{d}", f"$E{d}:$P{d}"
        put(ws, f"R{r}", f"=SUMPRODUCT({Vp},{Vc})", fmt="0", align="center")
        put(ws, f"S{r}", f"=SUMPRODUCT({Vp},{Vc},{Dp})", fmt="0.0000")
        put(ws, f"T{r}", f"=SUMPRODUCT({Vp},{Vc},{Dc})", fmt="0.0000")
        put(ws, f"U{r}", f"=SUMPRODUCT({Vp},{Vc},{Dp},{Dc})", fmt="0.000000")
        put(ws, f"V{r}", f"=SUMPRODUCT({Vp},{Vc},{Dp},{Dp})", fmt="0.000000")
        put(ws, f"W{r}", f"=IF(R{r}>=3,IFERROR((R{r}*U{r}-S{r}*T{r})/(R{r}*V{r}-S{r}^2),PhiPrior),PhiPrior)", fmt=DEC2, bold=True)
        Va, Da, Tt = f"$D{r}:$P{r}", f"$D{d}:$P{d}", "$D$4:$P$4"
        put(ws, f"X{r}", f"=SUM({Va})", fmt="0", align="center")
        put(ws, f"Y{r}", f"=SUMPRODUCT({Va},{Tt})", fmt="0")
        put(ws, f"Z{r}", f"=SUMPRODUCT({Va},{Da})", fmt="0.0000")
        put(ws, f"AA{r}", f"=SUMPRODUCT({Va},{Tt},{Da})", fmt="0.0000")
        put(ws, f"AB{r}", f"=SUMPRODUCT({Va},{Tt},{Tt})", fmt="0")
        put(ws, f"AC{r}", f"=IF(X{r}>=3,IFERROR((X{r}*AA{r}-Y{r}*Z{r})/(X{r}*AB{r}-Y{r}^2),0),0)", fmt=PCT2, bold=True)
    put(ws, f"R{R1 + 2}", "phi > 1 or < 0 is possible in small samples; the Reversion sheet shrinks toward the prior and clamps to [floor, cap].",
        italic=True, color="595959")
    widths(ws, {"A": 4, "B": 20, "C": 10, **{k: 6.5 for k in YCOLS}, "Q": 2, "R": 7, "S": 8, "T": 8, "U": 9,
                "V": 9, "W": 9, "X": 7, "Y": 7, "Z": 8, "AA": 8, "AB": 7, "AC": 11})
    ws.freeze_panes = "D6"


def sh_reversion(wb):
    ws = wb.create_sheet("Reversion")
    title(ws, "Margin reversion engine",
          "Normalized margin, gap to current, z-score, speed of reversion and expected margin path.")
    header_row(ws, HDR, ["#", "Company", "Peer group", "N obs", "CURRENT margin", "Own mean", "Own median",
                         "Own central", "Peer anchor", "Universe anchor", "NORMALIZED margin", "GAP (normal - current)",
                         "Z-score", "Percentile", "phi estimated", "phi used", "Half-life (yrs)",
                         "Expected margin t+1", "Expected margin t+3", "EBIT uplift t+1 from margin",
                         "Margin trend (per yr)", "Value-trap risk", "Data flag", "Eligible (1/0)"], height=42)
    company_cols(ws)
    for i in range(NC):
        r = R0 + i
        put(ws, f"C{r}", f"=Universe!$E{r}", color=GREEN_LINK)
        put(ws, f"D{r}", f"=Margins!Q{r}", fmt="0", align="center", color=GREEN_LINK)
        put(ws, f"E{r}", f"=Margins!Y{r}", fmt=PCT, color=GREEN_LINK, bold=True)
        put(ws, f"F{r}", f"=Margins!R{r}", fmt=PCT, color=GREEN_LINK)
        put(ws, f"G{r}", f"=Margins!S{r}", fmt=PCT, color=GREEN_LINK)
        put(ws, f"H{r}", f"=IF(Central=\"Median\",G{r},F{r})", fmt=PCT)
        put(ws, f"I{r}", f"=IFERROR(AVERAGEIFS($H${R0}:$H${R1},$C${R0}:$C${R1},C{r}),H{r})", fmt=PCT)
        put(ws, f"J{r}", f"=MEDIAN($H${R0}:$H${R1})", fmt=PCT)
        put(ws, f"K{r}", f"=W_Own*H{r}+W_Peer*I{r}+W_Univ*J{r}", fmt=PCT, bold=True)
        put(ws, f"L{r}", f"=K{r}-E{r}", fmt=PCTS, bold=True)
        put(ws, f"M{r}", f"=Margins!AA{r}", fmt=DEC2, color=GREEN_LINK)
        put(ws, f"N{r}", f"=Margins!Z{r}", fmt="0%", color=GREEN_LINK)
        put(ws, f"O{r}", f"=Persistence!W{r}", fmt=DEC2, color=GREEN_LINK)
        put(ws, f"P{r}", f"=MIN(PhiMax,MAX(PhiMin,ShrinkW*O{r}+(1-ShrinkW)*PhiPrior))", fmt=DEC2)
        put(ws, f"Q{r}", f"=IF(P{r}<=0.0001,0,LN(0.5)/LN(P{r}))", fmt="0.0")
        put(ws, f"R{r}", f"=K{r}+P{r}*(E{r}-K{r})", fmt=PCT)
        put(ws, f"S{r}", f"=K{r}+P{r}^3*(E{r}-K{r})", fmt=PCT)
        put(ws, f"T{r}", f"=IF(E{r}>0,R{r}/E{r}-1,\"\")", fmt=PCTS)
        put(ws, f"U{r}", f"=Persistence!AC{r}", fmt=PCT2, color=GREEN_LINK)
        put(ws, f"V{r}", f"=IF(AND(L{r}>0,U{r}<-TrendMax),\"YES\",\"no\")", align="center")
        put(ws, f"W{r}", f"=Universe!$J{r}", align="center", color=GREEN_LINK)
        put(ws, f"X{r}", f"=IF(AND(D{r}>=MinObs,OR(ExclFlagged=\"No\",W{r}<>\"Y\")),1,0)", fmt="0", align="center")
    gap_scale(ws, f"L{R0}:L{R1}")
    ws.conditional_formatting.add(f"V{R0}:V{R1}", CellIsRule(operator="equal", formula=['"YES"'], fill=F_WATCH))
    ws.conditional_formatting.add(f"X{R0}:X{R1}", CellIsRule(operator="equal", formula=["0"], fill=F_GREY))
    widths(ws, {"A": 4, "B": 20, "C": 28, "D": 6, **{CL(k): 10 for k in range(5, 25)}})
    ws.freeze_panes = "C6"


def sh_peers(wb):
    ws = wb.create_sheet("Peers")
    title(ws, "Peer-group summary", "Simple averages of company values within each peer group.")
    header_row(ws, HDR, ["Peer group", "# companies", "Avg own central margin", "Avg CURRENT margin",
                         "Avg NORMALIZED margin", "Avg gap", "Avg z-score", "Avg phi used", "Avg reversion upside"])
    for k, g in enumerate(GROUPS):
        r = R0 + k
        put(ws, f"A{r}", g, color=BLUE_IN, bold=True)
        put(ws, f"B{r}", f"=COUNTIF(Reversion!$C${R0}:$C${R1},A{r})", fmt="0", align="center")
        for col, src, fmt in (("C", "H", PCT), ("D", "E", PCT), ("E", "K", PCT), ("F", "L", PCTS),
                              ("G", "M", DEC2), ("H", "P", DEC2)):
            put(ws, f"{col}{r}", f"=IFERROR(AVERAGEIFS(Reversion!${src}${R0}:${src}${R1},Reversion!$C${R0}:$C${R1},$A{r}),\"\")", fmt=fmt)
        put(ws, f"I{r}", f"=IFERROR(AVERAGEIFS(DCF_Fade!$AD${R0}:$AD${R1},Reversion!$C${R0}:$C${R1},$A{r}),\"\")", fmt=PCTS)
    rt = R0 + len(GROUPS)
    put(ws, f"A{rt}", "UNIVERSE", bold=True, border=Border(top=THIN))
    put(ws, f"B{rt}", f"=SUM(B{R0}:B{rt - 1})", fmt="0", align="center", bold=True)
    for col, src, fmt in (("C", "H", PCT), ("D", "E", PCT), ("E", "K", PCT), ("F", "L", PCTS), ("G", "M", DEC2), ("H", "P", DEC2)):
        put(ws, f"{col}{rt}", f"=AVERAGE(Reversion!{src}{R0}:{src}{R1})", fmt=fmt, bold=True)
    put(ws, f"I{rt}", f"=AVERAGE(DCF_Fade!AD{R0}:AD{R1})", fmt=PCTS, bold=True)
    gap_scale(ws, f"F{R0}:F{rt}")
    ch = BarChart()
    ch.type = "bar"
    ch.title = "Current vs normalized margin by peer group"
    ch.y_axis.number_format = "0%"
    ch.y_axis.majorGridlines = None
    data = Reference(ws, min_col=4, max_col=5, min_row=HDR, max_row=rt - 1)
    ch.add_data(data, titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=R0, max_row=rt - 1))
    ch.height, ch.width = 9, 18
    style_chart(ch, True)
    ws.add_chart(ch, f"A{rt + 3}")
    widths(ws, {"A": 34, **{CL(k): 13 for k in range(2, 10)}})


def sh_wacc(wb):
    ws = wb.create_sheet("WACC")
    title(ws, "Cost of capital (CAPM)", "Ke = Rf + adjusted beta x ERP; Kd = (Rf + spread) x (1 - tax); market-value weights; clamped to [floor, cap].")
    header_row(ws, HDR, ["#", "Company", "Country", "Tax rate", "Raw beta", "Adjusted beta", "Cost of equity",
                         "Kd pre-tax", "Kd after tax", "Net debt (m)", "Market cap (m)", "Debt weight",
                         "CAPM WACC (raw)", "FUNDAMENTAL WACC", "Implied cost of capital @ current margin",
                         "DCF DISCOUNT RATE"], height=42)
    company_cols(ws)
    for i in range(NC):
        r = R0 + i
        put(ws, f"C{r}", f"=Universe!$D{r}", color=GREEN_LINK)
        put(ws, f"D{r}", f"=INDEX(TaxRate,MATCH(C{r},TaxCountry,0))", fmt="0.0%")
        put(ws, f"E{r}", f"=Data_Market!P{r}", fmt=DEC2, color=GREEN_LINK)
        put(ws, f"F{r}", f"=MAX(BetaFloor,BlumeW*E{r}+(1-BlumeW)*1)", fmt=DEC2)
        put(ws, f"G{r}", f"=Rf+F{r}*ERP", fmt=PCT2)
        put(ws, f"H{r}", "=Rf+CreditSpread", fmt=PCT2)
        put(ws, f"I{r}", f"=H{r}*(1-D{r})", fmt=PCT2)
        put(ws, f"J{r}", f"=Data_Market!H{r}", fmt=NUM, color=GREEN_LINK)
        put(ws, f"K{r}", f"=Data_Market!G{r}", fmt=NUM, color=GREEN_LINK)
        put(ws, f"L{r}", f"=MAX(0,J{r})/(K{r}+MAX(0,J{r}))", fmt=PCT)
        put(ws, f"M{r}", f"=(1-L{r})*G{r}+L{r}*I{r}", fmt=PCT2)
        put(ws, f"N{r}", f"=MIN(WACCMax,MAX(WACCMin,M{r}+WACCShift))", fmt=PCT2, bold=True)
        put(ws, f"O{r}", f"=Implied!P{r}", fmt=PCT2, color=GREEN_LINK)
        put(ws, f"P{r}", f"=IF(DCFRate=\"Market-implied\",MAX(GrowthTerminal+0.01,O{r}),N{r})", fmt=PCT2, bold=True)
    put(ws, f"O{R1 + 1}", "Floor: terminal g + 1.0%", italic=True, color="595959", size=8)
    r = R1 + 2
    section(ws, r, "Discount-rate calibration (Assumptions: WACCMode)", 1, 14)
    cal = [("Universe median CAPM WACC (raw)", f"=MEDIAN(M{R0}:M{R1})"),
           ("Universe median implied cost of capital @ normalized margin", f"=MEDIAN(Implied!Q{R0}:Q{R1})"),
           ("Calibration shift applied to every company", "=IF(WACCMode=\"Market-calibrated\",C{b}-C{a},0)")]
    for k, (lab, f) in enumerate(cal):
        rr = r + 1 + k
        put(ws, f"B{rr}", lab, bold=k == 2)
        put(ws, f"C{rr}", f.format(a=r + 1, b=r + 2), fmt=PCT2, bold=k == 2, align="right")
    add_name(wb, "WACCShift", f"WACC!$C${r + 3}")
    put(ws, f"B{r + 5}", "Market-calibrated: the median company's market EV is justified by its normalized margin at the "
                         "median implied cost of capital; individual WACCs keep their CAPM beta / leverage differences.",
        italic=True, color="595959")
    widths(ws, {"A": 4, "B": 20, "C": 10, **{CL(k): 11 for k in range(4, 15)}})
    ws.freeze_panes = "C6"


def sh_implied(wb):
    ws = wb.create_sheet("Implied")
    title(ws, "Market-implied steady-state margin",
          "Solve EV = Rev x (1+g) x m x (1-t) x (1 - g/RONIC) / (WACC - g) for m. If normal margin > implied, the market prices in margins below normal.")
    header_row(ws, HDR, ["#", "Company", "EV (m)", "TTM revenue (m)", "WACC", "Terminal g", "Tax", "RONIC",
                         "Reinvestment rate g/RONIC", "IMPLIED margin", "NORMALIZED margin", "CURRENT margin",
                         "Normal - implied", "EV / EBIT (TTM)", "EV / normalized EBIT",
                         "Implied cost of capital @ current margin", "Implied cost of capital @ normalized margin"], height=54)
    company_cols(ws)
    for i in range(NC):
        r = R0 + i
        put(ws, f"C{r}", f"=Data_Market!I{r}", fmt=NUM, color=GREEN_LINK)
        put(ws, f"D{r}", f"=Data_Market!K{r}", fmt=NUM, color=GREEN_LINK)
        put(ws, f"E{r}", f"=WACC!N{r}", fmt=PCT2, color=GREEN_LINK)
        put(ws, f"F{r}", "=GrowthTerminal", fmt=PCT)
        put(ws, f"G{r}", f"=WACC!D{r}", fmt=PCT, color=GREEN_LINK)
        put(ws, f"H{r}", "=RONIC", fmt=PCT)
        put(ws, f"I{r}", f"=F{r}/H{r}", fmt=PCT)
        put(ws, f"J{r}", f"=IFERROR(C{r}*(E{r}-F{r})/(D{r}*(1+F{r})*(1-G{r})*(1-I{r})),\"\")", fmt=PCT, bold=True)
        put(ws, f"K{r}", f"=Reversion!K{r}", fmt=PCT, color=GREEN_LINK)
        put(ws, f"L{r}", f"=Reversion!E{r}", fmt=PCT, color=GREEN_LINK)
        put(ws, f"M{r}", f"=IFERROR(K{r}-J{r},\"\")", fmt=PCTS, bold=True)
        put(ws, f"N{r}", f"=IFERROR(C{r}/(D{r}*L{r}),\"\")", fmt=MULT)
        put(ws, f"O{r}", f"=IFERROR(C{r}/(D{r}*K{r}),\"\")", fmt=MULT)
        for col, m in (("P", "L"), ("Q", "K")):
            put(ws, f"{col}{r}", f"=F{r}+D{r}*(1+F{r})*{m}{r}*(1-G{r})*(1-I{r})/C{r}", fmt=PCT2)
    gap_scale(ws, f"M{R0}:M{R1}")
    widths(ws, {"A": 4, "B": 20, **{CL(k): 11 for k in range(3, 18)}})
    ws.freeze_panes = "C6"


def sh_dcf(wb):
    ws = wb.create_sheet("DCF_Fade")
    title(ws, "Margin-fade DCF (10 years explicit + terminal at normalized margin)",
          "m(t) = m_norm + phi^t x (m_now - m_norm);  FCF = Rev x m x (1-t) x (1 - g/RONIC);  equity = EV - (market EV - market cap).")
    put(ws, "C4", "Year t", bold=True, align="right")
    tcols = [CL(4 + k) for k in range(10)]           # D..M
    for k, col in enumerate(tcols):
        put(ws, f"{col}4", k + 1, fmt="0", bold=True, align="center")
    blocks = [("A. Operating margin path", R0, PCT),
              ("B. Revenue (m, trading ccy)", R0 + 35, NUM),
              ("C. Free cash flow = NOPAT x (1 - g/RONIC)", R0 + 70, NUM),
              ("D. Present value of FCF", R0 + 105, NUM)]
    for name, b0, fmt in blocks:
        section(ws, b0 - 2, name, 1, 13)
        header_row(ws, b0 - 1, ["#", "Company", ""] + [f"Y{k + 1}" for k in range(10)], height=18)
    header_row(ws, HDR, ["#", "Company", ""] + [f"Y{k + 1}" for k in range(10)] + [""] +
               ["Sum PV explicit", "Terminal FCF (Y11)", "Terminal value (Y10)", "PV terminal",
                "FAIR EV", "Market EV", "EV - market cap bridge", "Fair equity", "Market cap",
                "UPSIDE (fade DCF)", "Fair value / share", "Status-quo EV (no reversion)",
                "Status-quo upside", "Value of reversion (EV)", "Reversion value / market cap",
                "REVERSION UPSIDE (equity vs status quo)"], height=54)
    bA, bB, bC, bD = R0, R0 + 35, R0 + 70, R0 + 105
    for i in range(NC):
        r = R0 + i
        for b0 in (bA, bB, bC, bD):
            put(ws, f"A{b0 + i}", i + 1, align="center", color="595959")
            put(ws, f"B{b0 + i}", f"=Universe!$B{r}", color=GREEN_LINK)
        for col in tcols:
            put(ws, f"{col}{bA + i}", f"=Reversion!$K{r}+Reversion!$P{r}^{col}$4*(Reversion!$E{r}-Reversion!$K{r})", fmt=PCT)
            put(ws, f"{col}{bB + i}", f"=Data_Market!$K{r}*(1+GrowthExplicit)^{col}$4", fmt=NUM)
            put(ws, f"{col}{bC + i}", f"={col}{bB + i}*{col}{bA + i}*(1-WACC!$D{r})*(1-GrowthExplicit/RONIC)", fmt=NUM)
            put(ws, f"{col}{bD + i}", f"={col}{bC + i}/(1+WACC!$P{r})^{col}$4", fmt=NUM)
        w, tax, rb = f"WACC!$P{r}", f"WACC!$D{r}", bB + i
        put(ws, f"O{r}", f"=SUM(D{bD + i}:M{bD + i})", fmt=NUM)
        put(ws, f"P{r}", f"=M{rb}*(1+GrowthTerminal)*Reversion!$K{r}*(1-{tax})*(1-GrowthTerminal/RONIC)", fmt=NUM)
        put(ws, f"Q{r}", f"=P{r}/({w}-GrowthTerminal)", fmt=NUM)
        put(ws, f"R{r}", f"=Q{r}/(1+{w})^$M$4", fmt=NUM)
        put(ws, f"S{r}", f"=O{r}+R{r}", fmt=NUM, bold=True)
        put(ws, f"T{r}", f"=Data_Market!I{r}", fmt=NUM, color=GREEN_LINK)
        put(ws, f"U{r}", f"=Data_Market!I{r}-Data_Market!G{r}", fmt=NUM)
        put(ws, f"V{r}", f"=S{r}-U{r}", fmt=NUM)
        put(ws, f"W{r}", f"=Data_Market!G{r}", fmt=NUM, color=GREEN_LINK)
        put(ws, f"X{r}", f"=IFERROR(V{r}/W{r}-1,\"\")", fmt=PCTS, bold=True)
        put(ws, f"Y{r}", f"=IFERROR(Data_Market!D{r}*(1+X{r}),\"\")", fmt=NUM2)
        put(ws, f"Z{r}", f"=Reversion!$E{r}*((1-{tax})*(1-GrowthExplicit/RONIC)*SUMPRODUCT(D{rb}:M{rb},1/(1+{w})^$D$4:$M$4)"
                         f"+M{rb}*(1+GrowthTerminal)*(1-{tax})*(1-GrowthTerminal/RONIC)/({w}-GrowthTerminal)/(1+{w})^$M$4)", fmt=NUM)
        put(ws, f"AA{r}", f"=IFERROR((Z{r}-U{r})/W{r}-1,\"\")", fmt=PCTS)
        put(ws, f"AB{r}", f"=S{r}-Z{r}", fmt=NUM)
        put(ws, f"AC{r}", f"=IFERROR(AB{r}/W{r},\"\")", fmt=PCTS)
        put(ws, f"AD{r}", f"=IFERROR(IF(Z{r}-U{r}>0,(S{r}-U{r})/(Z{r}-U{r})-1,0),0)", fmt=PCTS, bold=True)
    gap_scale(ws, f"X{R0}:X{R1}")
    gap_scale(ws, f"AC{R0}:AC{R1}")
    gap_scale(ws, f"AD{R0}:AD{R1}")
    widths(ws, {"A": 4, "B": 20, "C": 2, **{c: 9 for c in tcols}, "N": 2, **{CL(k): 12 for k in range(15, 31)}})
    ws.freeze_panes = "C6"


def sh_scoring(wb):
    ws = wb.create_sheet("Scoring")
    title(ws, "Scoring - four margin-reversion factors -> composite -> rank -> signal",
          "Factors standardized across ELIGIBLE companies (z = (x - mean)/sd, winsorized). Higher composite = more attractive.")
    header_row(ws, HDR, ["#", "Company", "Eligible", "F1 Margin gap", "F2 -Z-score", "F3 Normal - implied",
                         "F4 Reversion upside", "z F1", "z F2", "z F3", "z F4", "COMPOSITE", "Sort key", "RANK",
                         "Percentile", "Value-trap risk", "Data flag", "SIGNAL"], height=36)
    company_cols(ws)
    for i in range(NC):
        r = R0 + i
        put(ws, f"C{r}", f"=Reversion!X{r}", fmt="0", align="center", color=GREEN_LINK)
        put(ws, f"D{r}", f"=N(Reversion!L{r})", fmt=PCTS)
        put(ws, f"E{r}", f"=-N(Reversion!M{r})", fmt=DEC2)
        put(ws, f"F{r}", f"=N(Implied!M{r})", fmt=PCTS)
        put(ws, f"G{r}", f"=N(DCF_Fade!AD{r})", fmt=PCTS)
        for zc, fc in (("H", "D"), ("I", "E"), ("J", "F"), ("K", "G")):
            put(ws, f"{zc}{r}", f"=IF($C{r}=1,MAX(-ZCap,MIN(ZCap,IFERROR(({fc}{r}-{fc}${R1 + 2})/{fc}${R1 + 3},0))),0)", fmt=DEC2)
        put(ws, f"L{r}", f"=IF(C{r}=1,Wt_Gap*H{r}+Wt_Z*I{r}+Wt_Implied*J{r}+Wt_DCF*K{r},\"\")", fmt=DEC2, bold=True)
        put(ws, f"M{r}", f"=IF(C{r}=1,L{r},-100)-ROW()/1000000000", fmt="0.000000")
        put(ws, f"N{r}", f"=RANK(M{r},$M${R0}:$M${R1},0)", fmt="0", align="center", bold=True)
        put(ws, f"O{r}", f"=IF(C{r}=1,IF(SUM($C${R0}:$C${R1})>1,1-(N{r}-1)/(SUM($C${R0}:$C${R1})-1),1),\"\")", fmt="0%")
        put(ws, f"P{r}", f"=Reversion!V{r}", align="center", color=GREEN_LINK)
        put(ws, f"Q{r}", f"=Reversion!W{r}", align="center", color=GREEN_LINK)
        put(ws, f"R{r}", f"=IF(C{r}<>1,\"EXCLUDED\",IF(O{r}>=LongPct,IF(P{r}=\"YES\",\"WATCH - value trap\",\"LONG\"),"
                         f"IF(O{r}<=ShortPct,\"SHORT / AVOID\",\"NEUTRAL\")))&IF(Q{r}=\"Y\",\" (data flag)\",\"\")", bold=True)
    sm, sd = R1 + 2, R1 + 3
    put(ws, f"C{sm}", "Mean (eligible)", bold=True, align="right")
    put(ws, f"C{sd}", "St.dev (eligible)", bold=True, align="right")
    for fc in "DEFG":
        put(ws, f"{fc}{sm}", f"=IFERROR(SUMPRODUCT($C${R0}:$C${R1},{fc}{R0}:{fc}{R1})/SUM($C${R0}:$C${R1}),0)", fmt="0.0000", bold=True)
        put(ws, f"{fc}{sd}", f"=IFERROR(SQRT(SUMPRODUCT($C${R0}:$C${R1},({fc}{R0}:{fc}{R1}-{fc}{sm})^2)/(SUM($C${R0}:$C${R1})-1)),1)", fmt="0.0000", bold=True)
    signal_cf(ws, f"R{R0}:R{R1}")
    ws.conditional_formatting.add(f"L{R0}:L{R1}", ColorScaleRule(start_type="min", start_color="F8696B", mid_type="num",
                                                                 mid_value=0, mid_color="FFFFFF", end_type="max", end_color="63BE7B"))
    widths(ws, {"A": 4, "B": 20, "C": 8, **{CL(k): 10 for k in range(4, 18)}, "R": 26})
    ws.freeze_panes = "C6"


def sh_ranking(wb):
    ws = wb.create_sheet("Ranking")
    title(ws, "League table - all 30 companies ranked by composite margin-reversion score",
          "Sorted with INDEX/MATCH on the RANK column (no dynamic arrays needed).")
    header_row(ws, HDR, ["Rank", "Row", "Company", "Country", "Peer group", "CURRENT margin", "NORMALIZED margin",
                         "Gap", "Z-score", "Implied margin", "Reversion upside", "Fair-value upside (DCF)",
                         "Composite", "SIGNAL", "Half-life (yrs)", "phi used", "EV / EBIT (TTM)", "EV / norm. EBIT",
                         "Data note"], height=36)
    src = [("C", "Universe!$B"), ("D", "Universe!$D"), ("E", "Universe!$E"), ("F", "Reversion!$E"),
           ("G", "Reversion!$K"), ("H", "Reversion!$L"), ("I", "Reversion!$M"), ("J", "Implied!$J"),
           ("K", "DCF_Fade!$AD"), ("L", "DCF_Fade!$X"), ("M", "Scoring!$L"), ("N", "Scoring!$R"),
           ("O", "Reversion!$Q"), ("P", "Reversion!$P"), ("Q", "Implied!$N"), ("R", "Implied!$O"),
           ("S", "Universe!$K")]
    fmts = {"F": PCT, "G": PCT, "H": PCTS, "I": DEC2, "J": PCT, "K": PCTS, "L": PCTS, "M": DEC2, "O": "0.0",
            "P": DEC2, "Q": MULT, "R": MULT}
    for k in range(NC):
        r = R0 + k
        put(ws, f"A{r}", k + 1, fmt="0", align="center", bold=True)
        put(ws, f"B{r}", f"=MATCH(A{r},Scoring!$N${R0}:$N${R1},0)", fmt="0", align="center", color="808080")
        for col, s in src:
            col_letter = s.split("$")[1]
            sheet = s.split("!")[0]
            put(ws, f"{col}{r}", f"=INDEX({sheet}!${col_letter}${R0}:${col_letter}${R1},$B{r})" + ('&""' if col == "S" else ""),
                fmt=fmts.get(col), bold=col in ("C", "N"), color="595959" if col == "S" else "000000",
                italic=col == "S")
    signal_cf(ws, f"N{R0}:N{R1}")
    for c in "HKL":
        gap_scale(ws, f"{c}{R0}:{c}{R1}")
    widths(ws, {"A": 6, "B": 5, "C": 20, "D": 9, "E": 30, **{CL(k): 10 for k in range(6, 14)}, "N": 26,
                "O": 9, "P": 8, "Q": 9, "R": 9, "S": 60})
    ws.freeze_panes = "D6"


def sh_dashboard(wb):
    ws = wb.create_sheet("Dashboard", 1)
    title(ws, "NORDIC INDUSTRIALS  |  MARGIN REVERSION", None)
    put(ws, "A2", f'="Snapshot {SNAPSHOT_DATE}  |  window "&TEXT(MAX(2013,LastFY-Lookback+1),"0")&"-"&TEXT(LastFY,"0")&"  |  current margin basis: "&Basis&"  |  own central: "&Central',
        italic=True, color="595959")
    kpis = [("Companies", f"=COUNTA(Universe!B{R0}:B{R1})", "0"),
            ("Eligible", f"=SUM(Scoring!C{R0}:C{R1})", "0"),
            ("LONG", f'=COUNTIF(Scoring!R{R0}:R{R1},"LONG*")', "0"),
            ("SHORT / AVOID", f'=COUNTIF(Scoring!R{R0}:R{R1},"SHORT*")', "0"),
            ("Median current margin", f"=MEDIAN(Reversion!E{R0}:E{R1})", PCT),
            ("Median normalized margin", f"=MEDIAN(Reversion!K{R0}:K{R1})", PCT),
            ("Median half-life (yrs)", f"=MEDIAN(Reversion!Q{R0}:Q{R1})", "0.0"),
            ("Pooled phi (Evidence)", "=Evidence!P11", DEC2),
            ("WACC calibration shift", "=WACCShift", '+0.00%;(0.00%);0.00%')]
    for k, (lab, f, fmt) in enumerate(kpis):
        col = CL(1 + 2 * k)
        col2 = CL(2 + 2 * k)
        ws.merge_cells(f"{col}4:{col2}4")
        ws.merge_cells(f"{col}5:{col2}5")
        put(ws, f"{col}4", lab, color="FFFFFF", bold=True, fill=F_HDR, align="center", size=9)
        ws[f"{col2}4"].fill = F_HDR
        put(ws, f"{col}5", f, fmt=fmt, bold=True, size=18, color=NAVY, align="center", fill=F_SEC)
        ws[f"{col2}5"].fill = F_SEC
    ws.row_dimensions[5].height = 34
    # top / bottom tables
    cols = ["#", "Company", "Country", "Current", "Normal", "Gap", "Reversion upside", "Score", "Signal"]
    section(ws, 7, "TOP 5 - most attractive under margin reversion", 1, 9)
    header_row(ws, 8, cols, 1, 20)
    section(ws, 7, "BOTTOM 5 - least attractive (eligible)", 11, 19)
    header_row(ws, 8, cols, 11, 20)
    pull = [("C", None), ("D", None), ("F", PCT), ("G", PCT), ("H", PCTS), ("K", PCTS), ("M", DEC2), ("N", None)]
    for k in range(5):
        r = 9 + k
        put(ws, f"A{r}", k + 1, align="center", bold=True)
        put(ws, f"K{r}", f"=IF($C$5-{k}>=1,$C$5-{k},\"\")", fmt="0", align="center", bold=True)
        for j, (src, fmt) in enumerate(pull):
            put(ws, f"{CL(2 + j)}{r}", f"=INDEX(Ranking!${src}${R0}:${src}${R1},$A{r})", fmt=fmt,
                bold=j in (0, 7), border=B_BOT)
            put(ws, f"{CL(12 + j)}{r}", f"=IF(ISNUMBER($K{r}),INDEX(Ranking!${src}${R0}:${src}${R1},$K{r}),\"\")",
                fmt=fmt, bold=j in (0, 7), border=B_BOT)
    signal_cf(ws, "I9:I13")
    signal_cf(ws, "S9:S13")
    # charts
    ch = BarChart()
    ch.type = "col"
    ch.title = "Margin gap (normalized - current), ranked by composite score"
    ch.y_axis.number_format = "0%"
    ch.y_axis.majorGridlines = None
    ch.add_data(Reference(wb["Ranking"], min_col=8, min_row=HDR, max_row=R1), titles_from_data=True)
    ch.set_categories(Reference(wb["Ranking"], min_col=3, min_row=R0, max_row=R1))
    ch.legend = None
    ch.height, ch.width = 9, 34
    style_chart(ch, True)
    ws.add_chart(ch, "A16")

    sc = ScatterChart()
    sc.title = "Current vs normalized operating margin"
    sc.style = 13
    sc.x_axis.title = "Current margin"
    sc.y_axis.title = "Normalized margin"
    sc.x_axis.number_format = "0%"
    sc.y_axis.number_format = "0%"
    xs = Reference(wb["Reversion"], min_col=5, min_row=R0, max_row=R1)
    ys = Reference(wb["Reversion"], min_col=11, min_row=R0, max_row=R1)
    s = Series(ys, xs, title="Companies")
    s.marker.symbol = "circle"
    s.marker.size = 7
    s.marker.graphicalProperties.solidFill = NAVY
    s.marker.graphicalProperties.line.solidFill = NAVY
    s.graphicalProperties.line.noFill = True
    sc.series.append(s)
    # 45-degree line helper (far right, small grey)
    put(ws, "Z16", "45° line helper", italic=True, color="A6A6A6", size=8)
    for k, v in enumerate([0, 0.25]):
        put(ws, f"Z{17 + k}", v, fmt="0%", color="A6A6A6", size=8)
        put(ws, f"AA{17 + k}", f"=Z{17 + k}", fmt="0%", color="A6A6A6", size=8)
    s2 = Series(Reference(ws, min_col=27, min_row=17, max_row=18), Reference(ws, min_col=26, min_row=17, max_row=18),
                title="Current = normal")
    s2.marker.symbol = "none"
    s2.graphicalProperties.line.solidFill = "A6A6A6"
    s2.graphicalProperties.line.dashStyle = "dash"
    sc.series.append(s2)
    sc.height, sc.width = 9, 17
    style_chart(sc)
    ws.add_chart(sc, "A35")

    bc = BarChart()
    bc.type = "col"
    bc.title = "Composite score (ranked)"
    bc.add_data(Reference(wb["Ranking"], min_col=13, min_row=HDR, max_row=R1), titles_from_data=True)
    bc.set_categories(Reference(wb["Ranking"], min_col=3, min_row=R0, max_row=R1))
    bc.legend = None
    bc.y_axis.majorGridlines = None
    bc.height, bc.width = 9, 17
    style_chart(bc, True)
    ws.add_chart(bc, "K35")
    widths(ws, {CL(k): 10.5 for k in range(1, 21)})
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["L"].width = 18
    ws.column_dimensions["I"].width = 26
    ws.column_dimensions["S"].width = 26
    ws.column_dimensions["J"].width = 3


def sh_deepdive(wb):
    ws = wb.create_sheet("Deep_Dive")
    title(ws, "Company deep dive", "Select a company in C3 (drop-down). Every number below updates.")
    put(ws, "B3", "Company:", bold=True, align="right")
    put(ws, "C3", COMPANIES[2]["name"], color=BLUE_IN, bold=True, fill=F_KEY, size=12)
    ws.merge_cells("C3:E3")
    dv = DataValidation(type="list", formula1=f"=Universe!$B${R0}:$B${R1}")
    ws.add_data_validation(dv)
    dv.add("C3")
    put(ws, "G3", "Row #", color="808080", align="right")
    put(ws, "H3", f"=MATCH(C3,Universe!$B${R0}:$B${R1},0)", fmt="0", color="808080")
    ix = "$H$3"
    info = [("Ticker", "Universe!$C"), ("Country", "Universe!$D"), ("Peer group", "Universe!$E"),
            ("Data note", "Universe!$K")]
    for k, (lab, s) in enumerate(info):
        r = 5 + k
        put(ws, f"B{r}", lab, bold=True)
        col = s.split("$")[1]
        put(ws, f"C{r}", f"=INDEX({s.split('!')[0]}!${col}${R0}:${col}${R1},{ix})&\"\"")
    # history rows
    section(ws, 10, "Margin history vs normal", 1, 16)
    put(ws, "B11", "Fiscal year", bold=True)
    labels = [("Revenue (m, rep. ccy)", "Data_Revenue", NUM), ("Operating margin", "Data_Margin", PCT),
              ("In window", "Margins", PCT)]
    for j, col in enumerate(YCOLS):
        put(ws, f"{col}11", f"=Data_Margin!{col}${HDR}", fmt=YR, bold=True, color="FFFFFF", fill=F_HDR, align="center")
    for k, (lab, sh, fmt) in enumerate(labels):
        r = 12 + k
        put(ws, f"B{r}", lab, bold=True)
        for col in YCOLS:
            put(ws, f"{col}{r}", f"=IF(ISNUMBER(INDEX({sh}!{col}${R0}:{col}${R1},{ix})),INDEX({sh}!{col}${R0}:{col}${R1},{ix}),\"\")", fmt=fmt)
    put(ws, "B15", "Own central", bold=True)
    put(ws, "B16", "Normalized margin", bold=True)
    for col in YCOLS:
        put(ws, f"{col}15", f"=INDEX(Reversion!$H${R0}:$H${R1},{ix})", fmt=PCT, color="808080")
        put(ws, f"{col}16", f"=INDEX(Reversion!$K${R0}:$K${R1},{ix})", fmt=PCT, color="808080")
    # chart helper rows: #N/A (not 0) for missing years so the line shows a gap
    put(ws, "A49", "Chart data (NA() = intentional line gap for years without data)", italic=True, color="A6A6A6", size=8)
    for rr, lab, f in ((50, "Operating margin", "IF(ISNUMBER({c}13),{c}13,NA())"),
                       (51, "Own central", "{c}15"), (52, "Normalized margin", "{c}16")):
        put(ws, f"C{rr}", lab, color="A6A6A6", size=8)
        for col in YCOLS:
            put(ws, f"{col}{rr}", "=" + f.format(c=col), fmt=PCT, color="A6A6A6", size=8)
    # key stats
    section(ws, 18, "Key statistics", 1, 7)
    stats = [("Current margin", "Reversion!$E", PCT), ("Own mean", "Reversion!$F", PCT),
             ("Own median", "Reversion!$G", PCT), ("St.dev", "Margins!$T", PCT),
             ("Z-score", "Reversion!$M", DEC2), ("Percentile", "Reversion!$N", "0%"),
             ("Peer anchor", "Reversion!$I", PCT), ("NORMALIZED margin", "Reversion!$K", PCT),
             ("Gap (normal - current)", "Reversion!$L", PCTS), ("phi used", "Reversion!$P", DEC2),
             ("Half-life (yrs)", "Reversion!$Q", "0.0"), ("Margin trend (per yr)", "Reversion!$U", PCT2)]
    stats2 = [("Implied margin", "Implied!$J", PCT), ("DCF discount rate", "WACC!$P", PCT2),
              ("EV / EBIT (TTM)", "Implied!$N", MULT), ("EV / normalized EBIT", "Implied!$O", MULT),
              ("Reversion upside", "DCF_Fade!$AD", PCTS), ("Fair-value upside (DCF)", "DCF_Fade!$X", PCTS),
              ("Status-quo upside", "DCF_Fade!$AA", PCTS), ("Share price", "Data_Market!$D", NUM2),
              ("Fair value / share", "DCF_Fade!$Y", NUM2), ("Composite score", "Scoring!$L", DEC2),
              ("Rank (of 30)", "Scoring!$N", "0"), ("SIGNAL", "Scoring!$R", None)]
    for block, cl, cv in ((stats, "B", "C"), (stats2, "E", "H")):
        for k, (lab, s, fmt) in enumerate(block):
            r = 19 + k
            put(ws, f"{cl}{r}", lab, bold=lab.isupper() or lab == "SIGNAL")
            col = s.split("$")[1]
            put(ws, f"{cv}{r}", f"=INDEX({s.split('!')[0]}!${col}${R0}:${col}${R1},{ix})", fmt=fmt,
                bold=True, align="right")
    signal_cf(ws, "H30:H30")
    # fade path
    section(ws, 33, "Expected margin path (fade toward normal)", 1, 13)
    put(ws, "B34", "Year t", bold=True)
    put(ws, "B35", "Margin", bold=True)
    put(ws, "C34", "Now", bold=True, align="center")
    put(ws, "C35", "=INDEX(Reversion!$E$6:$E$35,$H$3)", fmt=PCT)
    for k in range(10):
        col = CL(4 + k)
        put(ws, f"{col}34", k + 1, fmt="0", bold=True, align="center")
        put(ws, f"{col}35", f"=INDEX(DCF_Fade!{col}${R0}:{col}${R1},{ix})", fmt=PCT)
    # sensitivity grid
    section(ws, 37, "Sensitivity: equity upside vs steady-state margin x discount rate (value-driver, immediate reversion)", 1, 11)
    put(ws, "B38", "Margin step (pp)", italic=True, color="595959")
    put(ws, "C38", 0.01, fmt="0.0%", color=BLUE_IN, fill=F_IN)
    put(ws, "D38", "Rate step", italic=True, color="595959", align="right")
    put(ws, "E38", 0.005, fmt="0.0%", color=BLUE_IN, fill=F_IN)
    put(ws, "B39", "Margin \\ disc. rate", bold=True, color="FFFFFF", fill=F_HDR, align="center")
    for j, s in enumerate(range(-3, 4)):
        col = CL(3 + j)
        put(ws, f"{col}39", f"=INDEX(WACC!$P${R0}:$P${R1},{ix})+({s})*$E$38", fmt=PCT2, bold=True, color="FFFFFF",
            fill=F_HDR, align="center")
    for k, s in enumerate(range(-3, 4)):
        r = 40 + k
        put(ws, f"B{r}", f"=INDEX(Reversion!$K${R0}:$K${R1},{ix})+({s})*$C$38", fmt=PCT, bold=True, fill=F_SEC, align="center")
        for j in range(7):
            col = CL(3 + j)
            rev = f"INDEX(Data_Market!$K${R0}:$K${R1},{ix})"
            tax = f"INDEX(WACC!$D${R0}:$D${R1},{ix})"
            bridge = f"(INDEX(Data_Market!$I${R0}:$I${R1},{ix})-INDEX(Data_Market!$G${R0}:$G${R1},{ix}))"
            mcap = f"INDEX(Data_Market!$G${R0}:$G${R1},{ix})"
            put(ws, f"{col}{r}",
                f"=IF({col}$39-GrowthTerminal<=0.005,\"n/m\",IFERROR(({rev}*(1+GrowthTerminal)*$B{r}*(1-{tax})*(1-GrowthTerminal/RONIC)/({col}$39-GrowthTerminal)-{bridge})/{mcap}-1,\"\"))",
                fmt=PCTS)
    gap_scale(ws, "C40:I46")
    ws["F43"].border = Border(left=Side(style="medium"), right=Side(style="medium"), top=Side(style="medium"),
                              bottom=Side(style="medium"))
    put(ws, "B47", "Outlined cell = base case (normalized margin, DCF discount rate). Steady-state value driver, terminal g; "
                   "differs from the fade DCF because reversion is assumed immediate.", italic=True, color="595959", size=8)
    # chart
    lc = LineChart()
    lc.title = "Operating margin vs own central and normalized"
    lc.y_axis.number_format = "0%"
    lc.y_axis.majorGridlines = None
    for rr in (50, 51, 52):
        lc.add_data(Reference(ws, min_col=3, max_col=16, min_row=rr), from_rows=True, titles_from_data=True)
    lc.set_categories(Reference(ws, min_col=4, max_col=16, min_row=11))
    for srs in lc.series:
        srs.smooth = False
    lc.series[1].graphicalProperties.line.dashStyle = "dash"
    lc.height, lc.width = 7.5, 15
    style_chart(lc)
    ws.add_chart(lc, "J18")
    widths(ws, {"A": 2, "B": 22, "C": 11, **{CL(k): 9 for k in range(4, 17)}})


def sh_evidence(wb):
    ws = wb.create_sheet("Evidence")
    title(ws, "Evidence - does margin reversion hold in this universe?",
          "Pooled OLS:  margin(t+1) - margin(t) = a + b x [margin(t) - expanding mean up to t].  b < 0 = reversion. No look-ahead.")
    header_row(ws, HDR, ["Co #", "Company", "FY t", "Margin t", "Margin t+1", "First valid", "Obs to t",
                         "Expanding mean", "Deviation", "Change t+1", "Valid", "x", "y", "Dev (valid)"], height=32)
    rows = []
    r = R0
    for ci in range(NC):
        for y in YEARS[:-1]:
            rows.append((r, ci + 1, y))
            r += 1
    E1 = r - 1
    DM = f"Data_Margin!${YFIRST}${R0}:${YLAST}${R1}"
    YR_ = f"Data_Margin!${YFIRST}${HDR}:${YLAST}${HDR}"
    for r, ci, y in rows:
        put(ws, f"A{r}", ci, align="center", color="808080")
        put(ws, f"B{r}", f"=INDEX(Universe!$B${R0}:$B${R1},A{r})")
        put(ws, f"C{r}", y, fmt=YR, align="center", color="808080")
        put(ws, f"D{r}", f"=IF(ISNUMBER(INDEX({DM},A{r},C{r}-2012)),INDEX({DM},A{r},C{r}-2012),\"\")", fmt=PCT)
        put(ws, f"E{r}", f"=IF(ISNUMBER(INDEX({DM},A{r},C{r}-2011)),INDEX({DM},A{r},C{r}-2011),\"\")", fmt=PCT)
        put(ws, f"F{r}", f"=INDEX(Universe!$I${R0}:$I${R1},A{r})", fmt=YR, align="center")
        put(ws, f"G{r}", f"=COUNTIFS({YR_},\">=\"&F{r},{YR_},\"<=\"&C{r},INDEX({DM},A{r},0),\"<>\")", fmt="0", align="center")
        put(ws, f"H{r}", f"=IF(G{r}>=3,AVERAGEIFS(INDEX({DM},A{r},0),{YR_},\">=\"&F{r},{YR_},\"<=\"&C{r}),\"\")", fmt=PCT)
        put(ws, f"I{r}", f"=IF(AND(ISNUMBER(D{r}),ISNUMBER(H{r})),D{r}-H{r},\"\")", fmt=PCTS)
        put(ws, f"J{r}", f"=IF(AND(ISNUMBER(D{r}),ISNUMBER(E{r}),C{r}+1<=LastFY),E{r}-D{r},\"\")", fmt=PCTS)
        put(ws, f"K{r}", f"=IF(AND(ISNUMBER(I{r}),ISNUMBER(J{r}),C{r}>=F{r},OR(ExclFlagged=\"No\",INDEX(Universe!$J${R0}:$J${R1},A{r})<>\"Y\")),1,0)",
            fmt="0", align="center")
        put(ws, f"L{r}", f"=IF(K{r}=1,I{r},0)", fmt="0.0000")
        put(ws, f"M{r}", f"=IF(K{r}=1,J{r},0)", fmt="0.0000")
        put(ws, f"N{r}", f"=IF(K{r}=1,I{r},\"\")", fmt=PCTS)
    K, L, M_, N_ = (f"{c}{R0}:{c}{E1}" for c in "KLMN")
    J = f"J{R0}:J{E1}"
    # summary block
    section(ws, 4, "Pooled regression result", 15, 20)
    summ = [("Observations n", f"=SUM({K})", "0"),
            ("Sum x", f"=SUM({L})", "0.0000"),
            ("Sum y", f"=SUM({M_})", "0.0000"),
            ("Sum xy", f"=SUMPRODUCT({L},{M_})", "0.000000"),
            ("Sum xx", f"=SUMPRODUCT({L},{L})", "0.000000"),
            ("Slope b (reversion coefficient)", "=IFERROR((P5*P8-P6*P7)/(P5*P9-P6^2),\"\")", "0.000"),
            ("Implied persistence phi = 1 + b", "=IFERROR(1+P10,\"\")", "0.00"),
            ("Half-life of a deviation (yrs)", "=IFERROR(IF(AND(P11>0,P11<1),LN(0.5)/LN(P11),\"\"),\"\")", "0.0"),
            ("Share of deviation removed per year", "=IFERROR(-P10,\"\")", "0%"),
            ("Hit rate: next change opposite to deviation", f"=IFERROR(SUMPRODUCT({K},--({L}*{M_}<0))/P5,\"\")", "0%"),
            ("Intercept a", "=IFERROR((P7-P10*P6)/P5,\"\")", PCT2)]
    for k, (lab, f, fmt) in enumerate(summ):
        r = 5 + k
        put(ws, f"O{r}", lab, bold=k in (5, 6, 7))
        put(ws, f"P{r}", f, fmt=fmt, bold=k in (5, 6, 7), align="right")
    put(ws, "O17", "Fama & French (2000) benchmark: ~38% of a deviation removed per year (phi ~0.62).", italic=True, color="595959")
    # quintiles
    section(ws, 19, "Next-year margin change by deviation quintile", 15, 19)
    header_row(ws, 20, ["Quintile", "Lower bound", "Upper bound", "Obs", "Avg deviation", "Avg change t+1"], 15, 30)
    for q in range(5):
        r = 21 + q
        put(ws, f"O{r}", f"Q{q + 1}" + (" (most below mean)" if q == 0 else " (most above mean)" if q == 4 else ""), bold=True)
        put(ws, f"P{r}", f"=PERCENTILE({N_},{q / 5})" if q else f"=MIN({N_})", fmt=PCTS)
        put(ws, f"Q{r}", f"=PERCENTILE({N_},{(q + 1) / 5})" if q < 4 else f"=MAX({N_})", fmt=PCTS)
        op = "<=" if q == 4 else "<"
        put(ws, f"R{r}", f'=COUNTIFS({K},1,{N_},">="&P{r},{N_},"{op}"&Q{r})', fmt="0", align="center")
        put(ws, f"S{r}", f'=IFERROR(AVERAGEIFS({L},{K},1,{N_},">="&P{r},{N_},"{op}"&Q{r}),"")', fmt=PCTS)
        put(ws, f"T{r}", f'=IFERROR(AVERAGEIFS({M_},{K},1,{N_},">="&P{r},{N_},"{op}"&Q{r}),"")', fmt=PCTS, bold=True)
    gap_scale(ws, "T21:T25")
    ch = BarChart()
    ch.type = "col"
    ch.title = "Avg next-year margin change by deviation quintile"
    ch.y_axis.number_format = "0.0%"
    ch.y_axis.majorGridlines = None
    ch.add_data(Reference(ws, min_col=20, min_row=20, max_row=25), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=15, min_row=21, max_row=25))
    ch.legend = None
    ch.height, ch.width = 8, 16
    style_chart(ch, True)
    ws.add_chart(ch, "O28")
    widths(ws, {"A": 5, "B": 20, "C": 6, **{c: 10 for c in "DEFGHIJ"}, "K": 6, "L": 8, "M": 8, "N": 10,
                "O": 42, "P": 12, "Q": 12, "R": 8, "S": 12, "T": 13})
    ws.freeze_panes = "C6"


def sh_sources(wb):
    ws = wb.create_sheet("Sources")
    title(ws, "Sources, methodology references and caveats")
    header_row(ws, 4, ["#", "Company", "History source", "History URL", "Market data URL", "Market price date"], 1, 20)
    for i, c in enumerate(COMPANIES):
        r = 5 + i
        put(ws, f"A{r}", i + 1, align="center")
        put(ws, f"B{r}", c["name"])
        put(ws, f"C{r}", c["src"])
        put(ws, f"D{r}", c["hurl"], color="0563C1")
        ws[f"D{r}"].hyperlink = c["hurl"]
        put(ws, f"E{r}", c["murl"], color="0563C1")
        ws[f"E{r}"].hyperlink = c["murl"]
        put(ws, f"F{r}", c["mkt"][1], align="center")
    r = 5 + NC + 1
    notes = [
        "METHODOLOGY REFERENCES",
        "Fama, E. & French, K. (2000): Forecasting Profitability and Earnings, Journal of Business 73(2) - profitability mean-reverts (~38%/yr).",
        "Koller, Goedhart & Wessels: Valuation - Measuring and Managing the Value of Companies (McKinsey) - value-driver formula, ROIC/margin fade.",
        "Value-driver formula: EV = NOPAT(t+1) x (1 - g/RONIC) / (WACC - g).",
        "",
        "CAVEATS",
        "Operating margins are as standardized by the data aggregator and can differ from company-reported (adjusted) EBIT(A) margins.",
        "History (roic.ai) and TTM (stockanalysis.com) come from different aggregators; set Basis = FY to compare like-for-like with history.",
        "Structural breaks (spin-offs, divestments, mergers) distort 'normal' margins: see Universe data flags and First valid year.",
        "Volvo: EV and net debt include Financial Services funding. Skanska: property development value is not separated.",
        "Market data are delayed snapshots (dates per company); refresh before use. Currency of market data = trading currency.",
        "Absolute CAPM valuations (WACCMode = CAPM) make most high-multiple compounders look expensive; the default market-calibrated mode reads upside relative to the universe.",
        "AR(1) estimates on <= 12 observations are noisy and biased toward zero; the model shrinks them toward a prior.",
        "Not investment advice.",
    ]
    for t in notes:
        is_h = t.isupper() and t != ""
        put(ws, f"A{r}", t, bold=is_h, color=NAVY if is_h else "000000")
        r += 1
    widths(ws, {"A": 5, "B": 22, "C": 24, "D": 44, "E": 48, "F": 14})


def build_workbook(path: str, companies=COMPANIES):
    global COMPANIES
    COMPANIES = companies
    wb = Workbook()
    wb.remove(wb.active)
    sh_readme(wb)
    sh_assumptions(wb)
    sh_universe(wb)
    sh_data(wb)
    sh_ebit(wb)
    sh_margins(wb)
    sh_persistence(wb)
    sh_reversion(wb)
    sh_peers(wb)
    sh_wacc(wb)
    sh_implied(wb)
    sh_dcf(wb)
    sh_scoring(wb)
    sh_ranking(wb)
    sh_dashboard(wb)
    sh_deepdive(wb)
    sh_evidence(wb)
    sh_sources(wb)
    # tab colours
    for name, col in (("Dashboard", NAVY), ("Assumptions", "FFC000"), ("Ranking", "70AD47"),
                      ("Deep_Dive", "70AD47"), ("Data_Revenue", "5B9BD5"), ("Data_Margin", "5B9BD5"),
                      ("Data_Market", "5B9BD5"), ("Universe", "5B9BD5")):
        wb[name].sheet_properties.tabColor = col
    wb.calculation.fullCalcOnLoad = True
    wb.active = wb.sheetnames.index("Dashboard")
    wb.save(path)
    return path


# =============================================================================
# 4. OPTIONAL: refresh prices with yfinance (run on your own machine)
# =============================================================================
def refresh_market(companies):
    """Update price and market cap from yfinance; EV is rebuilt as
    new market cap + snapshot net debt + snapshot other EV items.
    TTM revenue/EBIT and net debt stay from the snapshot (yfinance mixes
    reporting and trading currencies for several Nordic names)."""
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed (pip install yfinance) - using snapshot.")
        return companies
    out = copy.deepcopy(companies)
    for c in out:
        p, d, sh, mcap, nd, ev, rev, ebit, beta = c["mkt"]
        try:
            hist = yf.Ticker(c["yf"]).history(period="5d")
            if hist.empty:
                raise ValueError("no data")
            new_p = float(hist["Close"].iloc[-1])
            other = ev - mcap - nd
            new_mcap = mcap * new_p / p
            c["mkt"] = (round(new_p, 2), hist.index[-1].strftime("%Y-%m-%d"), sh, round(new_mcap, 1), nd,
                        round(new_mcap + nd + other, 1), rev, ebit, beta)
            print(f"  {c['name']:<20} {p:>10.2f} -> {new_p:>10.2f}")
        except Exception as e:  # noqa: BLE001
            print(f"  {c['name']:<20} kept snapshot ({e})")
    return out


# =============================================================================
# 5. CLI
# =============================================================================
def print_summary(res):
    print(f"\n{'Rk':>3} {'Company':<20} {'Current':>8} {'Normal':>8} {'Gap':>7} {'phi':>5} "
          f"{'Implied':>8} {'RevUp':>7} {'FairUp':>7} {'Score':>6}  Signal")
    for r in sorted(res, key=lambda x: x["rank"]):
        sc = "" if r["score"] is None else f"{r['score']:6.2f}"
        print(f"{r['rank']:>3} {r['name']:<20} {r['cur']:8.1%} {r['norm']:8.1%} {r['gap']:+7.1%} "
              f"{r['phi']:5.2f} {r['implied']:8.1%} {r['rev_upside']:+7.1%} {r['upside']:+7.1%} {sc:>6}  {r['signal']}")
    n, b = evidence_regression()
    if b is not None:
        print(f"\nEvidence: pooled b = {b:.3f} on {n} obs -> phi = {1 + b:.2f}, "
              f"half-life = {math.log(0.5) / math.log(1 + b):.1f} yrs" if 0 < 1 + b < 1 else "")


def main():
    ap = argparse.ArgumentParser(description="Nordic industrials margin-reversion model -> Excel")
    ap.add_argument("--out", default="Nordic_Industrials_Margin_Reversion.xlsx")
    ap.add_argument("--refresh-market", action="store_true", help="update prices via yfinance")
    ap.add_argument("--no-summary", action="store_true")
    args = ap.parse_args()
    comps = COMPANIES
    if args.refresh_market:
        print("Refreshing prices via yfinance ...")
        comps = refresh_market(COMPANIES)
    build_workbook(args.out, comps)
    print(f"Workbook written: {args.out}")
    if not args.no_summary:
        print_summary(compute_model(comps))


if __name__ == "__main__":
    main()
