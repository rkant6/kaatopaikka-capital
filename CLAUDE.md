# Kaatopaikka Capital – ohjeet Claudelle

Tämä repo on Kaatopaikka Capital Investment Terminal: 30 pohjoismaista teollisuusyhtiötä, margin reversion -malli ja 10 000 euron paperisalkku. Uudessa terminaalissa on analyysit, perustelut, sijoituspäätösten journal, margin lab ja alkuperäinen 3D-maapallo.

Kaksi ihmistä muokkaa repoa omilla Claude-istunnoillaan, usein samaan aikaan. Siksi jokainen muutos tehdään omaan branchiin ja pull requestiin. Vastaa käyttäjälle suomeksi.

## Miten kokonaisuus toimii

- GitHub Pages julkaisee repon juuren staattisena sivuna. Backendiä ei ole.
- `.github/workflows/daily-update.yml` ajetaan arkisin klo 17.20 UTC. Se hakee kurssit (yfinance), laskee mallin, päivittää salkun, simulaation ja Excelin, committaa ne `main`iin ja julkaisee sivun.
- Sama workflow julkaisee sivun heti, kun `main`iin tulee push, eli kun PR mergataan. Silloin kursseja ei haeta.
- `.github/workflows/check.yml` ajaa jokaiselle PR:lle `python check_site.py`:n ja tarkistaa, ettei PR muuta botin tiedostoja.

## Tiedostot

| Tiedosto | Sisältö |
|---|---|
| `index.html` | Terminaalin semanttinen HTML ja seitsemän sivun rakenne. |
| `assets/terminal.css` | Terminaalin tyylit, responsiiviset näkymät ja design tokenit. |
| `assets/terminal.js` | JSON-datan lataus, dashboard, screener, sijoitusmuistiot, journal, margin lab ja kaaviot. |
| `classic.html` | Alkuperäinen suuri 3D-maapallosivu. three.js r128 ja upotettu GEO-data. |
| `update_site.py` | Päivittäinen skripti. Tiedoston alussa ovat `HQ` (pääkonttorit ja koordinaatit), `STRATEGY` (salkun säännöt), `RULES` (sivulla näkyvät säännöt) ja `SIM` (Monte Carlo). |
| `nordic_margin_reversion.py` | Malli. Sisältää `COMPANIES` (tilinpäätösdata FY2013–FY2025 ja markkinadata), `ASSUMPTIONS`, `compute_model` ja `build_workbook` (Excel, 20 sheetiä kaavoineen). |
| `check_site.py` | Tarkistukset ennen julkaisua. Ajaa testin väliaikaisessa kansiossa. |
| `data.json`, `portfolio.json`, `simulation.json`, `model.xlsx` | **Botin tiedostot.** Päivittäinen ajo kirjoittaa nämä. |

## Käyttöliittymä ja data

- Uusi `index.html` lataa ulkoiset `assets/terminal.css` ja `assets/terminal.js`. Pidä HTML, CSS ja JavaScript erillään; älä lisää valtavia upotettuja datasettejä.
- Vanhan `classic.html`-sivun rivit `const EMB_DATA`, `const EMB_PORT`, `const EMB_SIM` ja `const GEO` sisältävät suurta varadataa. GEO-rivi on yli 500 000 merkkiä; älä tulosta sitä kokonaan. Säilytä klassinen näkymä toimivana.
- Terminaali hakee verkosta `data.json`, `portfolio.json` ja `simulation.json`, jotka päivittäinen botti kirjoittaa. Käyttöliittymä ei saa tehdä kaupankäyntipäätöksiä eikä tallentaa mallin tuloksia.
- Kaikki yritysmuistion perustelut on johdettava julkaistun laskennan numeroista. Älä generoi keksittyjä yritysuutisia, katalyyttejä tai sijoitussuosituksia.
- Tuo näkyviin hintoihin liittyvät päivämäärät, datan vanhentumisen ja mallin oletukset. Älä esitä paperisalkkua oikeana tuottona tai Monte Carlo -tuloksia empiirisinä ennusteina.
- Teema on tumma grafiitinharmaa, Bloomberg-henkinen oranssi, hillitty vihreä ja punainen. Noudata nykyisiä design-tokeneita ja responsiivisuutta. Etusivun maapallon valaistus ja aikajana käyttävät `assets/solar-globe.js` / `assets/solar-home.css` -tiedostoja.
- Vuoden 2024 historiallisia tuloksia EI saa rekonstruoida suoraan vuoden 2026 `COMPANIES`-tilinpäätöshistoriasta. Käytä vain lähde- ja julkaisupäivitettyä `historical_data/`-aineistoa, `historical_backtest.py`:n vuotovarmistuksia ja ilmoita survivorship bias. Älä lisää generoituja menneitä kauppoja tai meteoreja julkiseen dataan.

## Säännöt

1. **Oma branch ja PR jokaiselle muutokselle.** Älä pushaa suoraan `main`iin.
2. **Älä commitoi botin tiedostoja** (`data.json`, `portfolio.json`, `simulation.json`, `model.xlsx`). Jos ne ovat muuttuneet, palauta ne: `git checkout origin/main -- data.json portfolio.json simulation.json model.xlsx`.
3. **Älä aja `update_site.py`:tä repon kansiossa.** Se kirjoittaa botin tiedostot. Testaa komennolla `python check_site.py`, joka ajaa skriptin kopiossa. Pilvi-istunnosta ei pääse Yahoo Financeen, joten oikeita kursseja ei voi hakea. Testiajot käyttävät `--mock`-kursseja.
4. **Aja `python check_site.py` ennen jokaista pushia** ja korjaa virheet.
5. **Pidä PR pienenä:** yksi asia kerrallaan. Kirjoita kuvaus suomeksi: mitä muuttui, miksi ja mistä sen näkee sivulla.
6. **Strategian tai mallin muutos** (`STRATEGY`, `ASSUMPTIONS`, `COMPANIES`): kerro PR:ssä, mitä se tekee salkulle. Muutos vaikuttaa seuraavaan kuukauden tasapainotukseen, ja aiemmat kaupat jäävät ennalleen. Älä muokkaa `portfolio.json`:ia käsin.
7. **Uusi tai poistettava yhtiö:** muuta sekä `COMPANIES` (`nordic_margin_reversion.py`) että `HQ` (`update_site.py`). `check_site.py` tarkistaa, että ne täsmäävät.
8. **Repo on julkinen.** Älä lisää API-avaimia, salasanoja tai henkilötietoja.
9. **Workflow-tiedostot** (`.github/workflows/`): muuta niitä vain, jos käyttäjä pyytää erikseen.

## Kun toinen on muuttanut mainia samaan aikaan

```bash
git fetch origin
git rebase origin/main      # ratkaise mahdolliset konfliktit
python check_site.py
git push --force-with-lease
```

Konfliktissa säilytä molempien muutokset, ellei käyttäjä sano toisin, ja kerro käyttäjälle, mitä yhdistit.
