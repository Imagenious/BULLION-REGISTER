# Bullion Register

Your gold book: own bullion reserve, gold issued to karigars, customer advances (cash, old gold, gold booked with cash), settlements, rate-risk alerts and the rate SOP. All gold figures are fine (24K-equivalent) grams.

## Run it on this computer

Double-click **`start.bat`**. It opens <http://127.0.0.1:8000> in your browser.

The first time, the app asks you to create your owner account (username + password). Your records are saved in `instance\bullion.db`.

To bring over your records from the browser version, go to **Settings & backup → Import a backup** and choose `backups\from-browser-version.json`.

To use it from your phone on the same Wi-Fi, run `start.bat --lan` and open the address it prints.

## Put it on the cloud (PythonAnywhere)

Your records are kept in a file on PythonAnywhere's disk (`instance/bullion.db`), so there's no database to pay for or expire.

1. **Bash console** (Consoles tab → Bash):
   ```bash
   git clone https://github.com/Imagenious/BULLION-REGISTER.git
   cd BULLION-REGISTER
   python3.12 -m venv ~/.venvs/bullion
   ~/.venvs/bullion/bin/pip install -r requirements.txt
   ```
   If the repository is private, GitHub asks for a username and a *personal access token* instead of your password.
2. **Web tab → Add a new web app** → *Manual configuration* → **Python 3.12**.
3. On the Web tab set:
   - **Source code**: `/home/<you>/BULLION-REGISTER`
   - **Virtualenv**: `/home/<you>/.venvs/bullion`
   - **Static files**: URL `/static/` → directory `/home/<you>/BULLION-REGISTER/app/static`
   - **Force HTTPS**: on
4. Open the **WSGI configuration file** link and replace its contents with `deploy/pythonanywhere_wsgi.py`. Fill in your PythonAnywhere username and the owner username/password, then save.
5. Press **Reload**, open `https://<you>.pythonanywhere.com` and sign in.
6. Copy your records up: on your laptop **Settings & backup → Download backup**; on the cloud copy **Import a backup**.

**Updating later:** in a Bash console run `cd BULLION-REGISTER && git pull && ~/.venvs/bullion/bin/pip install -r requirements.txt`, then press **Reload** on the Web tab.

**Free plan:** log in at least once every 3 months and press **"Run until 3 months from today"** on the Web tab, or the site is switched off.

## Put it on the cloud (Render, alternative)

You need a free GitHub account and a Render account (<https://render.com>).

1. **Put this folder on GitHub.** Create a new *private* repository and upload everything in this folder. `.venv`, `instance` and `backups` are left out automatically by `.gitignore`, so your data and passwords stay on your PC.
2. **Create the service.** In Render: **New → Blueprint**, then pick the repository. Render reads `render.yaml` and creates the web app and a PostgreSQL database.
3. **Set your login.** Render asks for `ADMIN_USERNAME` and `ADMIN_PASSWORD`. Choose a strong password. This becomes the owner account on the cloud copy.
4. **Open it.** Wait for the deploy to finish, open the `https://bullion-register-….onrender.com` address and sign in.
5. **Copy your records up.** On your PC: **Settings & backup → Download backup**. On the cloud copy: **Import a backup**.

Things to know about Render's free plan:

- **The free database is deleted after 30 days.** For a business book, switch the database to Render's paid *Basic* plan (about $7/month). Or create a free database at <https://neon.tech> and paste its connection string into the web service's `DATABASE_URL` setting.
- **The free web service sleeps after 15 minutes idle.** The first visit afterwards takes about a minute to wake it.
- **Keep a backup either way.** Download one from **Settings & backup** every week.

PC and cloud each keep their own records. Choose one as your main book, and use backup/import to move records between them.

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

`tests/test_calc.py` checks the gold arithmetic against the worked examples. `tests/test_app.py` drives the whole app: login, orders, advances, settlement, backup and security checks.

## How the numbers work

| Figure | Formula |
|---|---|
| Karigar fine | weight × (karigar touch % + karigar wastage %) |
| Customer fine | weight × (1 + wastage %) × purity % (or purity rate ÷ order rate) |
| Gold received | (gross − stones) × purity % × (1 − melting loss %); credited at the order rate unless you enter a lower buying rate |
| Gold booked | cash ÷ rate actually paid |
| Own reserve | bullion lodged − gold issued to karigars + gold back from settled orders |
| Customer advances | gold received + gold booked, for open orders |
| Gold gain | gold back from customer − karigar fine |
| Break-even rate | unbooked money ÷ (karigar fine − advance gold) |

## Project layout

```
app/calc.py        gold arithmetic, alerts, statement (no database)
app/services.py    saving orders, advances, settlement, backup import/export
app/views.py       web pages and live previews
app/auth.py        owner login, first-run setup, lockout after wrong passwords
app/templates/     pages
run.py             local server (waitress)
wsgi.py            cloud server entry (gunicorn)
render.yaml        Render blueprint
```
