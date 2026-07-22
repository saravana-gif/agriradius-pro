# Deploying OneRoot AgriRadius Pro to Streamlit Community Cloud

Streamlit Cloud runs your app **from a GitHub repo** (not your laptop).
Flow: edit locally → `git commit` → `git push` → the app **auto-redeploys**.
Your `secrets.toml` never goes to GitHub; you paste secrets into the app's
settings instead.

---

## 0. One-time prerequisites
- A **GitHub** account (github.com).
- **Git** installed on your PC (git-scm.com). Check: `git --version`.
- A **Streamlit Community Cloud** account — sign in at
  https://share.streamlit.io with your GitHub account (free).
- **Rotate the service-account key first** (it was shared in chat): in
  Google Cloud → IAM → Service Accounts → Keys, delete the old key,
  create a new JSON key, and use that new JSON in step 4.

---

## 1. Create an empty GitHub repo
On github.com → **New repository** → name it e.g. `agriradius-pro` →
set **Private** (recommended) → do **not** add a README/gitignore →
Create. Copy the repo URL (e.g. `https://github.com/you/agriradius-pro.git`).

## 2. Push your project (run in `F:\AgriRadiusPro`)
```
cd F:\AgriRadiusPro
git add .
git commit -m "Deploy AgriRadius Pro"
git branch -M main
git remote add origin https://github.com/YOU/agriradius-pro.git
git push -u origin main
```
If it says a remote already exists, use `git remote set-url origin <URL>`.
`secrets.toml` is gitignored, so it will NOT be uploaded (correct).

*(Optional, to keep live field data out of the repo — Sheets is the
source of truth when deployed):*
```
git rm --cached data/ground_truth/ground_truth.csv
git commit -m "Untrack live field data (lives in Google Sheets)"
git push
```

## 3. Create the app on Streamlit Cloud
share.streamlit.io → **Create app** → **Deploy a public app from GitHub** →
- Repository: `YOU/agriradius-pro`
- Branch: `main`
- Main file path: `app.py`
- (Advanced) Python version: **3.11**
→ **Deploy**. First build takes a few minutes (it installs
`requirements.txt`).

## 4. Add the secrets
In the app → **⋮ / Manage app → Settings → Secrets**, paste the same
contents as your local `.streamlit/secrets.toml`:
```toml
DATA_GOV_API_KEY = "your-new-key"
GSHEET_ID = "your-sheet-id"
GCP_SERVICE_ACCOUNT = '''{ ...the NEW service-account JSON... }'''
```
Save — the app reboots and picks them up.

## 5. Grant the service account access (once)
The service-account **email** (inside the JSON, `client_email`) needs:
- **Earth Engine** access on project `agriradius`.
- **Monitoring Viewer** (`roles/monitoring.viewer`) — for the EECU gauge.
- **Editor** access to the shared Google Sheet (share the Sheet with
  that email) — for team ground-truth / soil cards.

---

## Updating the live app later
```
cd F:\AgriRadiusPro
git add .
git commit -m "what changed"
git push
```
Streamlit Cloud redeploys automatically within a minute or two.

## Important behaviours
- **One-way:** GitHub repo → cloud app. The running app can't write back
  to your files.
- **Ephemeral disk:** anything the app writes at runtime (caches, CSVs) is
  wiped on restart/redeploy. That's why field data uses **Google Sheets**.
  Bundled data (boundaries, calibration ground truth, reference CSVs) lives
  in the repo and is always present.
- **Sleep:** free apps sleep after inactivity and wake on the next visit
  (a few seconds).

## If the build fails on geo libraries
Add a file named `packages.txt` at the repo root with:
```
libgdal-dev
gdal-bin
```
commit & push. (Only needed if geopandas/fiona fail to install.)
