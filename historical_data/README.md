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

## 2024 Replay: tuotantodata, rakenne ja käyttöönotto

Tämä osio on tarkoitettu oikean historiallisen tutkimusaineiston luomiseen.
**Julkaistavaan dataan ei saa lisätä testien synteettisiä rivejä.**

**1. Käynnistä viimeisen joulukuun 2023 sulun jälkeisestä tiedosta.**
Vuoden 2024 ensimmäinen päätös tarvitsee vähintään edellisen
markkinasession hintatiedot sekä alkuperäiset Q3/2023-raportit
ja aiemmin julkaistut vuosimarginaalit. **Vuonna 2024 ei saa
käyttää vuoden 2024 FY-raporttia ennen sen alkuperäistä
julkistamispäivää**, eikä vuosien 2025–2026 tilinpäätöstietoja.

**2. Kerää financials-taulukot issuer-sivustojen alkuperäisistä
Q1–Q4-raporteista ja vahvistetuista arkistoista.**
`filings.csv` vaatii kullekin yhtiölle
`published_on`, `period_end`, alkuperäisen raportin `source_url`,
`revenue_ttm_m`, `ebit_ttm_m`, `net_debt_m`,
`shares_m`, `beta`, `tax_rate` ja
`structural_flag` (Y/N). Beta ja muita omia arvostusoletuksia
ei saa rekonstruoida nykyisestä vuoden 2026 tilannekuvasta.
Kaikki rahamäärät ovat alkuperäisessä **raportointivaluutassa**
ja miljoonina; `shares_m` on osakkeiden määrä miljoonina.

`annual_margins.csv` sisältää vain vuosimarginaaleja, jotka
oli todella julkaistu kyseiseen päätösajankohtaan mennessä.
Tarvitaan myös alkuperäistä 2024-vuotta edeltävä aikasarja:
myöhemmin vuoden 2026 tilinpäätöstiedoista kerätty,
mahdollisesti oikaistu vuosihistoria ei itsessään ole
vuoden 2024 julkaisuhetkellä tunnettu sarja.

**3. Hanki markkinahistoria.** Paikallisesti voi ajaa:

```bash
python historical_data/collect_market_history.py --through 2026-11-07
```

Skripti käyttää Yahoo Finance -palvelun kurssisarjoja ja liittää
yhtiön, kaupankäyntipäivän, alkuperäisen sulun, ex-päivän
osingot ja splitit sekä aiemman saatavilla olevan valuuttakurssin.
Se **ei** hanki talousraportteja tai korjaa issuer-fundamenttien
puutteita, ja pitkien kurssisarjojen oikeellisuus on tarkastettava
itsenäisesti. Markkinadatan käyttö- ja uudelleenjakeluehdot on
selvitettävä ennen sen julkaisua julkisessa repositoriossa.

Uudet pakolliset hintarivit:

| Sarake | Merkitys |
| --- | --- |
| `company`, `date`, `close` | Yhtiö, kaupankäyntipäivä ja sulku paikallisessa kaupankäyntivaluutassa |
| `dividend`, `split_factor` | Osinko ja split-kerroin täsmällisenä tapahtumapäivänä |
| `fx_to_eur` | Yksi kaupankäyntivaluutan yksikkö euroissa, ilman tulevaa FX-tietoa |
| `reporting_fx_to_eur` | Yksi raportointivaluutan yksikkö euroissa, ilman tulevaa FX-tietoa |
| `price_currency` | Oikea `trd`-valuutta; yhtiön raportointivaluutta voi poiketa |
| `source_url`, `fx_source_url` | Alkuperäiset tarkistettavat kurssi- ja FX-lähteet |

Useat yhtiöt raportoivat eri valuutassa kuin niiden osakkeilla
käydään kauppaa (esimerkiksi EUR/DKK tai USD/DKK).
Historiallinen arvonmääritys muuntaa sekä liikevaihdon,
EBIT:n että nettovelan oikeaan kaupankäyntivaluuttaan
**signaalin as-of-FX-kurssilla** ennen mallin laskemista.

**4. Tarkista ja julkaise tutkimus, ei keksittyä historiaa.**

```bash
python historical_data/refresh_status.py
python historical_backtest.py --inputs historical_data --output historical-backtest.json
```

`refresh_status.py` luo aina `historical-status.json`-tiedoston,
josta näkee rivimäärät ja datan puuttumisen syyn.
Jos rivit puuttuvat tai lähteet/ajo epäonnistuvat,
`historical-backtest.json`-tiedostoa ei julkaista.
Kun alkuperäinen Q- ja kurssiaineisto on valmis, GitHub
Actions rakentaa hyväksytyn historian uudelleen
arkipäivän datapäivityksen yhteydessä.

**5. Mitä replay näyttää vahvistetun datan jälkeen?**
Päivittäisen EUR-NAV:n, yhtä painotetun benchmarkin, mallin
kuukausittaiset päätökset, hinnat ja kulut,
sen hetkisen 5 osakkeen painot,
tulosjulkistukset, osingot, splitit, havaitut 5 %:n
päiväkohtaiset laskut sekä perustelun yhteydessä
jokaisen päätöksessä käytetyn Q-raportin
`published_on`-ajankohdan ja lähteen.
Kukin Play-hetki näyttää vain valittuun päivään mennessä
tapahtuneet asiat.

**Rajoitteet:** Kiinteä nykyisin valittu 30 yhtiön joukko
aiheuttaa selviytymisharhaa, ja nykyisin muodostetut
mallisäännöt ovat myös jälkikäteen valittuja.
Tulos on lähteistämisen jälkeenkin **hypoteettinen
tutkimusbacktest, ei vuoden 2024 alkaen toteutunut
sijoitussalkku**. GitHub Pages tarkistaa uuden julkaistun
datan noin 90 sekunnin välein; lähdemarkkinadata
päivittyy käytännössä vain EOD-ajastuksen mukaisesti.
