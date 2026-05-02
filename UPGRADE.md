# Upgrading your live deploy with the new features

This is the steps to ship the timezone fix, oz-based feeds, sleep chart, settings page, and PWA + push notifications to your already-running PythonAnywhere site.

## Step 1 — Push the new code from your PC

```powershell
cd C:\projects\baby-tracker-web
git add .
git commit -m "Timezone fix, feed oz, sleep chart, settings, PWA + push notifications"
git push
```

## Step 2 — Pull on PythonAnywhere

Open a Bash console (Consoles tab → Bash):

```bash
cd ~/baby-tracker-web
git pull
pip3.10 install --user -r requirements.txt
```

The `pip install` will pull in `pywebpush` and its dependencies (mostly `cryptography`). It takes a minute.

## Step 3 — Generate VAPID keys (one time)

In the same Bash console:

```bash
cd ~/baby-tracker-web
python3 generate_vapid_keys.py
```

It prints two lines, like:

```
VAPID_PUBLIC_KEY  = BAh3-7L....long-string
VAPID_PRIVATE_KEY = m1n4....shorter-string
```

**Keep that console open** — you need both values in the next step.

## Step 4 — Update your WSGI file

1. Web tab → click your WSGI file link.
2. Find the lines:
   ```python
   os.environ["VAPID_PUBLIC_KEY"]  = "PASTE_YOUR_VAPID_PUBLIC_KEY_HERE"
   os.environ["VAPID_PRIVATE_KEY"] = "PASTE_YOUR_VAPID_PRIVATE_KEY_HERE"
   ```
   Replace the placeholders with the values from Step 3.
3. Click **Save**.

The `REMINDER_CRON_TOKEN` is already pre-filled — copy that value, you'll need it in Step 6.

## Step 5 — Reload

Web tab → big green **Reload** button.

Visit your site. You should now see:

- The sleep timer and feed times in **your local time** (no more -6h).
- A **Next feed** countdown panel at the top.
- A **Settings** link in the top nav.
- The feed form's amount changes from ml → oz, and amount/duration/side fields show or hide based on the type you pick.
- A **Sleep — last 7 days** bar chart.

If you don't see them, hard-refresh (Ctrl+F5).

## Step 6 — Set up the cron pinger (so notifications fire when the app is closed)

This is what makes notifications work even when you don't have the app open.

1. Sign up for a free account at https://cron-job.org.
2. Click **+ Create cronjob**.
3. Fill in:
   - **Title**: `Baby tracker reminders`
   - **URL**: `https://mgrinfeld11.pythonanywhere.com/internal/cron/check-reminders?token=fdPmXZHFzHdPpjB-BL57zFbbFdaxPhse`
     (Yes, that's the exact token I generated and put in your WSGI file. If you change the token in the WSGI file, change it here too.)
   - **Schedule**: Click **Every minute** (or set "Every 1 Minutes" under the schedule editor).
   - **Notifications**: turn off "On failure" if you don't want emails when PA is briefly unreachable.
4. Save. The job starts firing every minute.

You can verify it's working: cron-job.org's dashboard shows each ping with the response. A successful ping returns:
```json
{"checked": true, "reminders_sent": 0}
```
…until a reminder is actually due, at which point `reminders_sent` will be > 0.

## Step 7 — Subscribe each device to push

On your phone (and any other device you want notifications on):

1. Open your site in Chrome/Edge/Safari.
2. Log in.
3. Go to **Settings**.
4. Click **Enable notifications on this device**.
5. Approve the browser's permission prompt.
6. Click **Send a test notification** to verify it works.

Repeat for any other phone or browser you want pushes on. All subscriptions are tied to the same account.

### iOS-specific note

iOS Safari only supports Web Push when the site is **added to the Home Screen as a PWA**. Steps:

1. In Safari, open your site → tap the Share button → **Add to Home Screen**.
2. Open the app from the home screen icon.
3. Go to Settings → Enable notifications.

This is an Apple limitation — there's no workaround for getting web push to work in regular Safari tabs on iOS.

## Quick sanity checks

After Step 7, visit Settings and click "Send a test notification". Within a couple seconds the notification should pop up on the device, even if you switch to another app first.

To test the full reminder flow:
- Set the interval to **2 minutes** and lead to **1 minute** (in Settings, just for testing).
- Log a feed.
- Wait ~1 minute. The cron-job pings every minute and you should see a notification fire.
- Set them back to 180 / 20 when done testing.

## Troubleshooting

**"VAPID_PRIVATE_KEY not set"** when sending a test → the WSGI file env vars didn't load. Make sure you saved the WSGI file and clicked Reload.

**Test notification works but real reminders don't** → check the cron-job.org dashboard. If pings are failing with 403, your `?token=` doesn't match `REMINDER_CRON_TOKEN`. If pings are 200 but `reminders_sent` is always 0, your interval/lead times haven't elapsed yet since the last feed — log a feed in the past for testing or shorten the interval temporarily.

**iOS doesn't show notifications** → must be installed as a PWA from the home screen. Regular Safari tabs can't receive push on iOS.

**The Mozilla push service may not work from PythonAnywhere free tier** — if Firefox users on your account never receive pushes, check the cron endpoint response for failures. Chrome/Edge/Safari all use Google's FCM, which IS whitelisted on the free tier.
