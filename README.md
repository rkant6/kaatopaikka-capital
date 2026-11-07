# Kaatopaikka Capital – nettisivu

3D-maapallo, jolla näkyy 30 pohjoismaista teollisuusyhtiötä ja margin reversion -mallin signaalit. Mukana on Kaatopaikka Capitalin 10 000 euron paperisalkku. Sivu päivittyy automaattisesti joka arkipäivä.

| Tiedosto | Mitä se tekee |
|---|---|
| `index.html` | Itse nettisivu. |
| `update_site.py` | Päivittäinen skripti: kurssit → malli → salkku → simulaatio → Excel. |
| `nordic_margin_reversion.py` | Margin reversion -malli ja tilinpäätösdata (FY2013–FY2025). |
| `data.json`, `portfolio.json`, `simulation.json` | Sivun data. Skripti kirjoittaa nämä joka päivä. |
| `model.xlsx` | Excel-malli päivän kursseilla. Ladattavissa sivulta. |
| `.github/workflows/daily-update.yml` | Ajastus: GitHub ajaa skriptin ja julkaisee sivun. Julkaisee sivun myös heti, kun muutos mergataan. |
| `.github/workflows/check.yml` | Tarkistaa jokaisen pull requestin ennen kuin se menee sivulle. |
| `check_site.py` | Tarkistukset: Python, sivun JavaScript ja testiajo keksityillä kursseilla. |
| `CLAUDE.md` | Ohjeet Claudelle: projektin rakenne ja säännöt. Claude Code lukee tämän automaattisesti. |
| `requirements.txt` | Python-kirjastot, jotka skripti tarvitsee. |

## Sivun julkaisu (tehdään kerran, noin 10 min)

1. **Pura zip-tiedosto** johonkin kansioon.
2. **Tee GitHub-tili** osoitteessa https://github.com/signup. Ilmainen tili riittää.
3. **Luo repository:** paina oikean yläkulman **+** ja valitse **New repository**.
   - Repository name: `kaatopaikka-capital`
   - Valitse **Public**. Ilmaisella tilillä sivu julkaistaan vain julkisesta reposta.
   - Paina **Create repository**.
4. **Lataa tiedostot:** klikkaa uuden repon sivulla linkkiä **uploading an existing file**. Vedä puretun kansion **koko sisältö** selaimeen, myös `.github`-kansio. Paina **Commit changes**.
   - Tarkista, että tiedostolistassa näkyy `.github`. Jos ei näy: valitse **Add file → Create new file**, kirjoita nimeksi `.github/workflows/daily-update.yml`, liitä tiedoston sisältö ja paina **Commit changes**.
5. **Laita sivu päälle:** **Settings → Pages → Build and deployment → Source:** valitse **GitHub Actions**.
6. **Anna skriptille kirjoitusoikeus:** **Settings → Actions → General → Workflow permissions:** valitse **Read and write permissions** ja paina **Save**.
7. **Aja ensimmäinen päivitys:** avaa **Actions**-välilehti, valitse vasemmalta **Daily update** ja paina **Run workflow → Run workflow**. Odota 2–3 minuuttia, kunnes ajon kohdalla näkyy vihreä ✓.
8. **Valmis.** Sivu on osoitteessa `https://KÄYTTÄJÄNIMESI.github.io/kaatopaikka-capital/`. Linkki näkyy myös kohdassa Settings → Pages. Tätä linkkiä voit jakaa.

## Mitä tapahtuu joka päivä

- GitHub ajaa `update_site.py`:n arkisin klo 17.20 UTC. Se on talviaikaan klo 19.20 ja kesäaikaan klo 20.20 Suomen aikaa, eli pohjoismaisten pörssien sulkeuduttua. GitHubin ajastus voi myöhästyä muutamia minuutteja.
- Skripti hakee jokaisen osakkeen päätöskurssin ja EUR-valuuttakurssit (yfinance / Yahoo Finance) ja laskee mallin uudelleen. Upsidet, implied-marginaalit, pisteet ja signaalit päivittyvät.
- **Salkku:**
  - Ensimmäinen ajo toteuttaa Päätöksen 1 eli ostaa 5 osaketta päivän päätöskursseilla.
  - Sen jälkeen salkku arvostetaan joka päivä uusilla kursseilla.
  - Kuukauden ensimmäinen ajo tasapainottaa salkun mallin uusimpien signaalien mukaan.
- Vertailuindeksi on kaikki 30 yhtiötä yhtä suurilla painoilla.

## Yhteistyö kaverin kanssa

1. **Kutsu kaveri:** **Settings → Collaborators → Add people** → kaverin GitHub-käyttäjänimi. Hän hyväksyy kutsun sähköpostista.
2. **Molemmat muokkaavat Claude Codella** osoitteessa https://claude.ai/code. Valitse repoksi `kaatopaikka-capital` ja kerro, mitä haluat muuttaa.
3. **Claude tekee muutoksen omaan branchiinsa.** Kun diff näyttää hyvältä, paina **Create PR**.
4. **GitHub tarkistaa PR:n** (Check-ajo). Kun se on vihreä, paina PR:ssä **Merge pull request**. Sivu päivittyy parissa minuutissa.

Älkää muokatko `data.json`-, `portfolio.json`-, `simulation.json`- ja `model.xlsx`-tiedostoja. Ne ovat päivittäisen botin tiedostoja. `CLAUDE.md` kertoo tämän myös Claudelle.

## Säännöllinen ylläpito

- **Tilinpäätösdata** (marginaalit) muuttuu vain tulosjulkistusten yhteydessä. Kerran neljännesvuodessa päivitä `nordic_margin_reversion.py`:n `COMPANIES`-lista ja lataa tiedosto uudelleen repoon.
- **Strategian säännöt** (osakkeiden määrä, maksimipaino, kaupankäyntikulu) ovat `update_site.py`:n alussa kohdassa `STRATEGY`.
- **Salkun nollaus:** poista `portfolio.json` reposta. Seuraava ajo aloittaa uuden 10 000 euron salkun.

## Ajo omalla koneella (vapaaehtoinen)

```powershell
cd kaatopaikka-capital
python -m pip install -r requirements.txt
python update_site.py
```

## Jos jokin menee pieleen

- **Ajo punaisena ja virheessä lukee `Permission denied` tai `403`:** tee kohta 6.
- **`Get Pages site failed`:** tee kohta 5 ja aja päivitys uudelleen.
- **Kurssit eivät päivittyneet:** Yahoo rajoittaa välillä hakuja. Skripti käyttää silloin edellisiä kursseja ja yrittää uudelleen seuraavana päivänä.
- **Ajastus on pysähtynyt:** GitHub voi pysäyttää julkisen repon ajastuksen pitkän hiljaisuuden jälkeen. Käynnistä se uudelleen Actions-välilehdeltä (**Enable workflow**).

Paperisalkku ja simulaatio ovat havainnollistuksia. Ne eivät ole sijoitusneuvontaa.
