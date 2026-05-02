// Baby Tracker service worker.
// Handles push events from the server and click-to-focus.

const CACHE_NAME = "baby-tracker-v1";

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

// Display incoming push messages.
self.addEventListener("push", (event) => {
    let payload = { title: "Baby Tracker", body: "Notification", url: "/" };
    if (event.data) {
        try {
            payload = Object.assign(payload, event.data.json());
        } catch (e) {
            payload.body = event.data.text();
        }
    }
    event.waitUntil(
        self.registration.showNotification(payload.title, {
            body: payload.body,
            icon: "/static/icon-192.png",
            badge: "/static/icon-192.png",
            tag: "baby-tracker-reminder",
            renotify: true,
            requireInteraction: false,
            data: { url: payload.url },
        })
    );
});

// When the user taps the notification, open or focus the app.
self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || "/";
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true })
            .then((clientList) => {
                for (const client of clientList) {
                    if ("focus" in client) {
                        client.navigate(targetUrl);
                        return client.focus();
                    }
                }
                if (self.clients.openWindow) {
                    return self.clients.openWindow(targetUrl);
                }
            })
    );
});
