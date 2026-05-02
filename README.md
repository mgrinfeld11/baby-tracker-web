# Baby Tracker (web version)

A multi-user web app for tracking a baby's sleep, feeds, and diaper changes.
Works in any browser — phones, tablets, desktops. Each account's data is private.

Built with Flask + SQLite. The whole app is roughly 600 lines of Python plus templates.

## Features

- Email/password accounts (each family has its own login; share the password between parents)
- One-tap "Start sleep" / "Stop sleep" with a live timer
- Quick-log diaper buttons (wet / dirty / both)
- Feed logging with type, amount in ml, duration, side
- Today's summary on the dashboard
- Full history per category, with delete
- Daily summary for any date
- CSV export per category (great for the pediatrician)

## Run it locally first

You'll want to test it locally before deploying.

```bash
cd baby-tracker-web
python -m venv .venv

# Activate the venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# Set a real secret key for sessions (any random string):
# Windows (PowerShell):
$env:FLASK_SECRET_KEY = "change-me-to-something-random"
# macOS/Linux:
export FLASK_SECRET_KEY="change-me-to-something-random"

python web_app.py
```

Open http://127.0.0.1:5000 — register an account and start logging.

To open the project in PyCharm: **File → Open** → pick this folder. PyCharm will detect `requirements.txt` and offer to set up a venv. Right-click `web_app.py` → **Run 'web_app'**.

## Deploying so other people can use it

Pick one of these. Both are free for a small personal app like this.

### Option A — PythonAnywhere (easiest, no card needed)

1. Sign up for a free account at https://www.pythonanywhere.com.
2. Open a **Bash console** (Consoles tab → Bash).
3. Upload your code. Easiest is to push it to GitHub first, then:
   ```bash
   git clone https://github.com/<you>/baby-tracker-web.git
   cd baby-tracker-web
   pip3.10 install --user -r requirements.txt
   ```
4. Go to the **Web** tab → **Add a new web app** → **Manual configuration** → Python 3.10.
5. In the WSGI configuration file, replace the contents with:
   ```python
   import sys, os
   path = '/home/<your-username>/baby-tracker-web'
   if path not in sys.path: sys.path.insert(0, path)
   os.environ['FLASK_SECRET_KEY'] = '<paste a long random string here>'
   from web_app import app as application
   ```
6. Click the green **Reload** button. Visit `https://<your-username>.pythonanywhere.com`.

The free tier sleeps inactive apps after a few months but is otherwise always-on. The SQLite file lives in your home directory and persists.

### Option B — Fly.io (free tier with persistent storage)

Fly's free allowance covers a small Python app + 3GB volume.

1. Install the `flyctl` CLI: https://fly.io/docs/hands-on/install-flyctl/
2. From the project folder:
   ```bash
   fly launch              # accept defaults; pick a name
   fly volumes create babydata --region <your-region> --size 1
   ```
3. Edit the generated `fly.toml` to mount the volume:
   ```toml
   [mounts]
     source = "babydata"
     destination = "/data"

   [env]
     BABY_TRACKER_DB = "/data/baby_tracker.db"
   ```
4. Set the secret key and deploy:
   ```bash
   fly secrets set FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
   fly deploy
   ```
5. `fly open` opens the public URL.

### Option C — Render.com

Render's free web service tier works but spins down after 15 minutes of inactivity (cold starts ~30s) and the free tier has no persistent disk. Use the **paid Starter** tier (~$7/mo) and add a disk if you want a fully reliable deploy here.

1. Push the project to GitHub.
2. On Render: **New → Web Service** → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn web_app:app`
5. Add an env var `FLASK_SECRET_KEY` set to a long random string.
6. Add a **Disk** mounted at `/data`, then add env var `BABY_TRACKER_DB=/data/baby_tracker.db`.

## Sharing it with people

Once it's deployed, just send them the URL. They each register their own account (private data) — or you give your partner your password so you both see the same baby's data.

## Files

```
baby-tracker-web/
  web_app.py        Flask routes + auth
  web_db.py         SQLite layer (multi-user, all queries scoped by user_id)
  templates/        Jinja2 HTML (mobile-first)
  static/style.css  Styles
  requirements.txt  Flask, gunicorn
  Procfile          For Render/Heroku-style hosts
  runtime.txt       Pins Python version on hosts that respect it
  .gitignore        Keeps the DB and venv out of git
```

## Security notes

- Passwords are hashed with PBKDF2 via Werkzeug — never stored in plaintext.
- All DB queries are scoped by `user_id`, so users can't read or delete each other's data.
- **Always set `FLASK_SECRET_KEY` to a real random value in production.** The app uses session cookies signed with that key.
- The `.gitignore` excludes `*.db` files so the live database never gets committed.

## Backing up the data

The whole app's data lives in one SQLite file (`baby_tracker.db`). To back it up, copy that file somewhere safe. On Fly.io: `fly ssh console` → `cp /data/baby_tracker.db /tmp/backup.db` and then `fly ssh sftp get /tmp/backup.db`. On PythonAnywhere: download from the Files tab.
