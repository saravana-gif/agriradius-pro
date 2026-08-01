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

---

## Login & access control (@oneroot.farm Google sign-in)

The app can require a Google sign-in and only let in emails an admin has
added. Password = the person's own @oneroot.farm Google password; the
app never sees or stores it.

**How it decides:**
- If an `[auth]` section is present in the app's Secrets → **Google
  sign-in is ON**. A visitor signs in with Google; if their email isn't
  in the allowlist they see *"signed in, but hasn't been given access
  yet — ask an admin."* Non-@oneroot.farm accounts are refused.
- If there's **no** `[auth]` section → the app stays open/legacy, so
  nothing breaks before you finish setup.

**One-time setup:**
1. Google Cloud Console → APIs & Services → **Credentials** → Create
   **OAuth client ID** → *Web application*.
2. Add the Authorised redirect URI **exactly**:
   `https://agriradius-pro-ytsri4v3cvjcwt3vnvjabl.streamlit.app/oauth2callback`
3. On Streamlit Cloud → App → **Settings → Secrets**, paste the `[auth]`
   block from `.streamlit/secrets.toml.example` with your `client_id`,
   `client_secret`, a random `cookie_secret`, and keep
   `OWNER_EMAIL = "saravana@oneroot.farm"` so you seed yourself as owner.
4. Reboot the app. You'll be asked to sign in; as owner you get the
   **People & Access** panel in the sidebar.

**Managing staff (live, no redeploy):** open the sidebar **People &
Access** panel (owners only). Add someone by **email + role**, change a
role from the dropdown, or **Remove** them — all written to the shared
Google Sheet (`Users` tab), so it persists across restarts.

Roles: **owner** (full + user admin), **analyst** (full app), **viewer**
(read-only). You can't remove yourself (prevents lock-out).

---

## Re-host at groundintel.oneroot.farm (Render) — keeps the URL + GitHub auto-deploy

Streamlit Community Cloud can't serve a custom domain, so to have the URL
stay `groundintel.oneroot.farm` we run the same repo on **Render** (native
Python, same `requirements.txt`). Pushes to `main` still auto-deploy.

**Steps (one-time):**
1. **render.com** → sign in **with GitHub** → **New → Blueprint** → pick the
   `agriradius-pro` repo. Render reads `render.yaml` and creates the service.
   (Blueprint uses the `starter` plan = always-on, ~$7/mo; switch to `free`
   in render.yaml if you accept cold starts.)
2. **Secrets:** service → **Environment → Secret Files** → add a file named
   `.streamlit/secrets.toml` and paste the SAME secrets from Streamlit Cloud,
   changing only the `[auth]` `redirect_uri` to
   `https://groundintel.oneroot.farm/oauth2callback`. Keep `[auth]` LAST.
3. **Custom domain:** service → **Settings → Custom Domains** → add
   `groundintel.oneroot.farm`. Render gives a CNAME target — add that CNAME
   at oneroot.farm's DNS host. (Only this subdomain; never touch MX/email.)
4. **Google OAuth:** Cloud Console → the OAuth client → add redirect URI
   `https://groundintel.oneroot.farm/oauth2callback` and JS origin
   `https://groundintel.oneroot.farm`.
5. Wait for DNS + Render's TLS cert (a few minutes to a couple of hours).
   Open `https://groundintel.oneroot.farm` → Google sign-in → app.

The old `…streamlit.app` app can stay as a backup or be deleted once the new
domain works.
