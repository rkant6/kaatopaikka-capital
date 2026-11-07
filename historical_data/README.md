# Historiallinen backtest: lähteet ja tietovaatimukset

Tässä hakemistossa on CSV-pohjat. Ne ovat **tarkoituksella tyhjiä**: nykyinen
2026-tasoinen tilinpäätössnapshot ei kelpaa simuloimaan tammikuussa 2024 tehtyjä
päätöksiä. Backtest ei julkaise keksittyä tuottokäyrää eikä tulevaisuuden dataa.

## Tarvittavat aineistot

1. `filings.csv`: jokainen Q1–Q4-tulosjulkistus ja sen todellinen alkuperäinen
   `published_on`. Rivillä oltava tuolloin julkaistut TTM-liikevaihto/EBIT,
   netto-velka, osakemäärä, tuolloin estimoitu beta, veroaste ja dokumentoitu
   rakennemuutoksen `structural_flag`. Kaikki määrät ovat miljoonina yhtiön
   omassa raportointivaluutassa. `source_url` osoittaa kyseiseen raporttiin.
2. `annual_margins.csv`: historialliset vertailukelpoiset vuosimarginaalit
   prosenttiyksikköinä (esim. `12.5`, **ei** `0.125`). Käytä alkuperäisen
   vuositilinpäätöksen julkaisupäivää ja osoitetta. Historiassa ei voi käyttää
   jälkikäteen 2026 korjattua sarjaa ilman korjausjulkaisun päivämäärää.
3. `prices.csv`: päiväkohtaiset päätöskurssit jokaiselle silloiselle yhtiölle,
   kurssin valuutta, EUR-muuntokerroin, osinkotuotto per osake ja split-kerroin
   ex-päivänä. Myös vuoden 2023 viimeinen kaupankäyntipäivä tarvitaan, jotta
   tammikuun 2024 alun signaalit voivat käyttää edellistä päätöskurssia.

Hinta- ja FX-rivit on pidettävä pisteajallisina. Osakekohtaiset hinnat ovat
**oikaisemattomia** silloin, kun splitit ja käteisosingot kirjataan erikseen.
Lähteen tulee olla todellinen issuer-relations-, pörssi- tai datatoimittajan URL.
URL-merkintä ei vielä itsessään takaa lähteen oikeellisuutta.

Tässä toteutuksessa käytetään nykyistä 30 yhtiön joukkoa myös historiassa.
Tästä seuraa **selvä survivorship bias**. Täysin investoitava historiallisen
universumin testi vaatii myös vuonna 2024 listatut ja sittemmin poistuneet
yhtiöt sekä tapahtumahistorian. Julkinen raportti ei saa kutsua tätä
korjaamatonta aineistoa aidosti sijoitettavaksi backtestiksi.

## Vuotoraja ja toteutushinta

Kuukauden ensimmäisen kaupankäyntipäivän sijoituspäätös käyttää vain
**edellisen session päätöskurssia** ja raportteja, joiden julkaisupäivä on
**ennen tätä edellistä sessiota**. Osto ja myynti simuloidaan uuden session
päätöskurssiin, jolloin kaupankäynti ei tiedä toteutuskurssia etukäteen.
0,15 % kustannus per toteutunut vaihto. Päivittäiset osingot ja splitit
käsitellään kirjanpidollisesti erillisinä.

## Ajo

```bash
python historical_backtest.py --inputs historical_data --output historical-backtest.json
```

Ilman datarivejä ajo päättyy **CoverageError**-virheeseen eikä julkaise
mitään. Älä lisää generoituja/synteettisiä testirivejä tuotantotiedostoihin.
Tutkimuksen jatkovaihe: 2024-universumin arkisto, jokaisen Q1–Q4-raportin
alkuperäinen julkaisuaika, yritysjärjestelyt sekä päivätason kurssi- ja FX-data.
