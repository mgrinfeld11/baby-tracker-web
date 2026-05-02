# Deploying Baby Tracker to PythonAnywhere

Follow this in order. Total time: ~15 minutes the first time.

You'll end up with a public URL like `https://yourname.pythonanywhere.com` that anyone can use from any browser, including phones.

---

## Step 0 — One-time cleanup on your machine

I started a `.git` folder while building, but the Linux mount couldn't finish it cleanly. Open **PowerShell** and remove it:

```powershell
cd C:\projects\baby-tracker-web
Remove-Item -Recurse -Force .git
```

---

## Step 1 — Push the project to GitHub

You said you have a GitHub account but haven't pushed this project yet. Here's the fastest path.

### 1a. Create an empty repo on GitHub

1. Go to https://github.com/new.
2. Repository name: `baby-tracker-web` (or whatever you like).
3. **Visibility: Private** (recommended — your secret key is in `pythonanywhere_wsgi.py`, which you'll see why we add to `.gitignore` in 1b).
4. Don't initialize with README, .gitignore, or license — leave those unchecked.
5. Click **Create repository**.

GitHub will show you a "quick setup" page with your repo URL — copy it. It looks like `https://github.com/<your-username>/baby-tracker-web.git`.

### 1b. Don't commit the WSGI file (it has your secret key)

In PowerShell:

```powershell
cd C:\projects\baby-tracker-web
Add-Content .gitignore "`npythonanywhere_wsgi.py"
```

(That appends a line so the WSGI file with your secret stays on your machine and on PythonAnywhere only — never on GitHub.)

### 1c. Initialize git and push

```powershell
cd C:\projects\baby-tracker-web

git init -b main
git config user.email "maximgrinfeld@gmail.com"
git config user.name "Maxim Grinfeld"
git add .
git commit -m "Initial commit: baby tracker web app"

# Replace the URL with the one GitHub showed you
git remote add origin https://github.com/<your-username>/baby-tracker-web.git
git push -u origin main
```

If git asks for credentials, GitHub now requires a Personal Access Token instead of your password. If you get prompted, generate one at https://github.com/settings/tokens (give it the `repo` scope) and paste it as the password.

---

## Step 2 — Create your PythonAnywhere account

1. Go to https://www.pythonanywhere.com/registration/register/beginner/.
2. Pick a **username** — it becomes part of your public URL (`<username>.pythonanywhere.com`). Choose carefully.
3. Confirm your email.

The free "Beginner" tier is fine for this app. No credit card required.

---

## Step 3 — Clone the project on PythonAnywhere

1. From the PythonAnywhere dashboard, click **Consoles** in the top nav.
2. Click **Bash** (under "Start a new console").
3. In the console, run:

   ```bash
   git clone https://github.com/<your-github-username>/baby-tracker-web.git
   cd baby-tracker-web
   pip3.10 install --user -r requirements.txt
   ```

   The `pip install` will take a minute. You should see Flask, gunicorn, and Werkzeug install successfully.

---

## Step 4 — Configure the web app

1. Click **Web** in the top nav.
2. Click **Add a new web app**.
3. On the prompt about your domain, just click **Next** (free accounts get `<username>.pythonanywhere.com`).
4. Choose **Manual configuration** (NOT "Flask" — manual gives us full control).
5. Choose **Python 3.10**.
6. Click **Next** to finish creating the app.

You'll land on the Web tab for your new app. Scroll down to the **Code** section. You'll see a link labeled **WSGI configuration file** — click it. (It's a path like `/var/www/<username>_pythonanywhere_com_wsgi.py`.)

The file opens in PythonAnywhere's web editor with default placeholder content. **Delete everything in the file**, then paste in the contents of `pythonanywhere_wsgi.py` from your project.

To get those contents:

- Open `C:\projects\baby-tracker-web\pythonanywhere_wsgi.py` in PyCharm or Notepad.
- Copy all of it into PythonAnywhere's editor.
- **Important**: replace both occurrences of `YOUR_USERNAME` with your actual PythonAnywhere username.

Click **Save** (top right of the editor).

---

## Step 5 — Reload and visit

1. Go back to the **Web** tab.
2. Click the big green **Reload** button at the top.
3. Click your domain link (e.g. `https://yourname.pythonanywhere.com`).

You should see the login page. Click **Create one** to register your first account.

That's it — share the URL with anyone you want.

---

## Updating the app later

When you change code on your computer:

```powershell
cd C:\projects\baby-tracker-web
git add .
git commit -m "describe what you changed"
git push
```

Then on PythonAnywhere, in a Bash console:

```bash
cd ~/baby-tracker-web
git pull
```

Then click **Reload** on the Web tab. Done.

---

## Backing up your data

The whole app's data lives in one file: `/home/<username>/baby_tracker.db` on PythonAnywhere.

To back it up: **Files** tab → navigate to your home folder → click `baby_tracker.db` → **Download**. Save it somewhere safe (cloud storage, etc.).

I'd suggest doing this once a week, or whenever you've logged a meaningful amount of data you don't want to lose.

---

## If something goes wrong

The PythonAnywhere **Web** tab has a **Log files** section near the bottom with three logs:

- **Error log** — Python tracebacks if the app crashes. This is the most useful one.
- **Server log** — startup messages from the server.
- **Access log** — every request.

Open the error log first if the site shows a "Something went wrong" page. Send me what it says and I'll help debug.

---

## What about HTTPS?

PythonAnywhere serves your site over HTTPS automatically (the URL starts with `https://`). Passwords are encrypted in transit.
