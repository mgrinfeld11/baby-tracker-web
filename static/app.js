// Baby Tracker client-side glue:
//   1. Convert all <time data-utc="..."> elements to local time on load.
//   2. Wire up the feed-form: show/hide fields based on selected type.
//   3. Sleep timer ticking display.
//   4. "Next feed" countdown + in-page notification.
//   5. PWA: register service worker, request notification permission,
//      subscribe to Web Push.

(function () {
    "use strict";

    // ---------------------------------------------------------------
    // 1. UTC -> local time rendering
    // ---------------------------------------------------------------
    const TIME_FMT = new Intl.DateTimeFormat(undefined, {
        month: "short", day: "numeric",
        hour: "numeric", minute: "2-digit",
    });
    const TIME_ONLY = new Intl.DateTimeFormat(undefined, {
        hour: "numeric", minute: "2-digit",
    });

    function renderTimes() {
        document.querySelectorAll("time[data-utc]").forEach((el) => {
            const iso = el.getAttribute("data-utc");
            if (!iso) return;
            const d = new Date(iso);
            if (isNaN(d.getTime())) return;
            const fmt = el.getAttribute("data-fmt") === "time"
                ? TIME_ONLY : TIME_FMT;
            el.textContent = fmt.format(d);
            el.title = d.toString();
        });
    }
    renderTimes();

    // ---------------------------------------------------------------
    // 2. Feed form: show/hide fields based on type
    // ---------------------------------------------------------------
    const feedForm = document.querySelector('[data-form="feed"]');
    if (feedForm) {
        const typeSel = feedForm.querySelector('[name="feed_type"]');
        const ozLabel = feedForm.querySelector('[data-field="amount_oz"]');
        const durLabel = feedForm.querySelector('[data-field="duration_minutes"]');
        const sideLabel = feedForm.querySelector('[data-field="side"]');

        function applyFeedType() {
            const t = typeSel.value;
            const showOz = (t === "bottle" || t === "formula");
            const showBreastFields = (t === "breast");
            ozLabel.style.display = showOz ? "" : "none";
            durLabel.style.display = showBreastFields ? "" : "none";
            sideLabel.style.display = showBreastFields ? "" : "none";
        }
        typeSel.addEventListener("change", applyFeedType);
        applyFeedType();
    }

    // ---------------------------------------------------------------
    // 3. Active sleep timer: tick the elapsed time
    // ---------------------------------------------------------------
    const sleepTimerEl = document.getElementById("sleep-elapsed");
    if (sleepTimerEl) {
        const startIso = sleepTimerEl.getAttribute("data-start-utc");
        const start = new Date(startIso);
        function tick() {
            const ms = Date.now() - start.getTime();
            const total = Math.max(0, Math.floor(ms / 1000));
            const h = Math.floor(total / 3600);
            const m = Math.floor((total % 3600) / 60);
            const s = total % 60;
            sleepTimerEl.textContent =
                (h ? h + "h " : "") + m + "m " + String(s).padStart(2, "0") + "s";
        }
        tick();
        setInterval(tick, 1000);
    }

    // ---------------------------------------------------------------
    // 4. Next-feed countdown + in-page notification
    // ---------------------------------------------------------------
    const nextFeedEl = document.getElementById("next-feed-panel");
    if (nextFeedEl) {
        const nextIso = nextFeedEl.getAttribute("data-next-feed-utc");
        const reminderIso = nextFeedEl.getAttribute("data-reminder-utc");
        const intervalMin = parseInt(nextFeedEl.getAttribute("data-interval"), 10);
        const leadMin = parseInt(nextFeedEl.getAttribute("data-lead"), 10);
        const notificationsOn = nextFeedEl.getAttribute("data-notifications-on") === "1";

        const countdownEl = document.getElementById("next-feed-countdown");
        const statusEl = document.getElementById("next-feed-status");
        const localEl = document.getElementById("next-feed-local");

        if (nextIso) {
            const next = new Date(nextIso);
            if (localEl) localEl.textContent = TIME_ONLY.format(next);

            let firedReminder = false;
            const reminder = reminderIso ? new Date(reminderIso) : null;

            function tick() {
                const ms = next.getTime() - Date.now();
                const sign = ms < 0 ? -1 : 1;
                const abs = Math.abs(ms);
                const h = Math.floor(abs / 3600000);
                const m = Math.floor((abs % 3600000) / 60000);
                const s = Math.floor((abs % 60000) / 1000);
                const text = (sign < 0 ? "overdue by " : "in ")
                    + (h ? h + "h " : "") + m + "m " + String(s).padStart(2, "0") + "s";
                countdownEl.textContent = text;

                // Color-coded status
                nextFeedEl.classList.remove("status-ok", "status-soon", "status-overdue");
                if (ms < 0) {
                    nextFeedEl.classList.add("status-overdue");
                    statusEl.textContent = "Overdue";
                } else if (ms <= leadMin * 60000) {
                    nextFeedEl.classList.add("status-soon");
                    statusEl.textContent = "Coming up";
                } else {
                    nextFeedEl.classList.add("status-ok");
                    statusEl.textContent = "On track";
                }

                // In-page notification when the reminder time hits
                if (notificationsOn && reminder && !firedReminder
                    && Date.now() >= reminder.getTime()
                    && Date.now() < next.getTime() + 60000) {
                    firedReminder = true;
                    showLocalNotification(
                        "Feeding due soon",
                        "Next feed in about " + leadMin + " minutes."
                    );
                }
            }
            tick();
            setInterval(tick, 1000);
        } else {
            if (countdownEl) countdownEl.textContent =
                "Log your first feed to start the countdown.";
        }
    }

    function showLocalNotification(title, body) {
        if (!("Notification" in window)) return;
        if (Notification.permission !== "granted") return;
        try {
            new Notification(title, { body: body, icon: "/static/icon-192.png" });
        } catch (e) {
            // Some browsers (mobile Safari) require service worker for notifications.
            navigator.serviceWorker.getRegistration().then((reg) => {
                if (reg) reg.showNotification(title, {
                    body: body, icon: "/static/icon-192.png"
                });
            });
        }
    }

    // ---------------------------------------------------------------
    // 5. PWA + push subscription
    // ---------------------------------------------------------------
    const pushBtn = document.getElementById("enable-push");
    const pushStatus = document.getElementById("push-status");
    const VAPID_PUB = (document.documentElement.dataset.vapidPubkey || "").trim();

    function setPushStatus(text, kind) {
        if (!pushStatus) return;
        pushStatus.textContent = text;
        pushStatus.className = "push-status " + (kind || "");
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, "+").replace(/_/g, "/");
        const raw = atob(base64);
        const out = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
        return out;
    }

    async function registerSW() {
        if (!("serviceWorker" in navigator)) return null;
        try {
            return await navigator.serviceWorker.register("/sw.js");
        } catch (e) {
            console.error("SW registration failed", e);
            return null;
        }
    }

    async function subscribeToPush(reg) {
        if (!reg || !("PushManager" in window) || !VAPID_PUB) return;
        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
            sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(VAPID_PUB),
            });
        }
        await fetch("/push/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(sub),
        });
        setPushStatus("Notifications enabled on this device.", "ok");
    }

    async function enablePushFlow() {
        if (!("Notification" in window) || !("serviceWorker" in navigator)) {
            setPushStatus("Your browser doesn't support notifications.", "error");
            return;
        }
        let perm = Notification.permission;
        if (perm === "default") {
            perm = await Notification.requestPermission();
        }
        if (perm !== "granted") {
            setPushStatus("Permission denied — enable in browser settings.", "error");
            return;
        }
        const reg = await registerSW();
        await subscribeToPush(reg);
    }

    if (pushBtn) {
        pushBtn.addEventListener("click", enablePushFlow);
        // Auto-register SW (without prompting) so in-page notifs work for users
        // who already granted permission previously.
        registerSW().then((reg) => {
            if (reg && Notification.permission === "granted") {
                subscribeToPush(reg).catch(console.error);
            } else if (Notification.permission === "denied") {
                setPushStatus("Notifications blocked in browser settings.", "error");
            } else {
                setPushStatus("Notifications not enabled yet.", "muted");
            }
        });
    } else {
        // Pages other than settings: still register the SW silently.
        registerSW();
    }

    // ---------------------------------------------------------------
    // 6. Test push button (settings page)
    // ---------------------------------------------------------------
    const testBtn = document.getElementById("test-push");
    if (testBtn) {
        testBtn.addEventListener("click", async () => {
            testBtn.disabled = true;
            const old = testBtn.textContent;
            testBtn.textContent = "Sending…";
            try {
                const r = await fetch("/push/test", { method: "POST" });
                const j = await r.json();
                if (!r.ok) {
                    setPushStatus(j.error || "Test failed.", "error");
                } else {
                    setPushStatus(
                        "Test sent — sent " + (j.sent || 0)
                        + ", failed " + (j.failed || 0)
                        + (j.gone ? ", removed " + j.gone + " dead subscriptions" : "")
                        + ".", "ok"
                    );
                }
            } catch (e) {
                setPushStatus("Network error: " + e.message, "error");
            }
            testBtn.disabled = false;
            testBtn.textContent = old;
        });
    }

    // ---------------------------------------------------------------
    // 7. Manual sleep entry: prefill local times via JS
    // ---------------------------------------------------------------
    const manualSleepStart = document.querySelector('[data-prefill="sleep-start"]');
    const manualSleepEnd = document.querySelector('[data-prefill="sleep-end"]');
    if (manualSleepStart && manualSleepEnd) {
        // Use datetime-local format (no timezone — represents local wall clock).
        // We submit these values as-is; server interprets them as the user's
        // local wall clock plus the timezone offset hidden field.
        function localNow(offsetMinutes) {
            const d = new Date(Date.now() + (offsetMinutes || 0) * 60000);
            const pad = (n) => String(n).padStart(2, "0");
            return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
                + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
        }
        manualSleepStart.value = localNow(-60);
        manualSleepEnd.value = localNow(0);
    }

    // ---------------------------------------------------------------
    // 8. Convert local datetime-local fields to UTC ISO at submit time
    // ---------------------------------------------------------------
    document.querySelectorAll('form[data-utc-convert]').forEach((form) => {
        form.addEventListener("submit", () => {
            form.querySelectorAll('input[type="datetime-local"]').forEach((inp) => {
                const v = inp.value;
                if (!v) return;
                const d = new Date(v);  // interpreted as local
                if (isNaN(d.getTime())) return;
                inp.value = d.toISOString().replace(/\.\d{3}Z$/, "Z");
            });
        });
    });

})();
