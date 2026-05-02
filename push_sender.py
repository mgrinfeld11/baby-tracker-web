"""
push_sender.py - Send Web Push notifications using pywebpush + VAPID.

Imported lazily by web_app.py so that the app still boots even if
pywebpush isn't installed yet (you'll just get errors when you actually
try to send a push).
"""

from __future__ import annotations

import json
import os
from typing import Iterable

from pywebpush import WebPushException, webpush

import web_db as db


def _vapid_claims() -> dict:
    return {"sub": "mailto:" + os.environ.get(
        "VAPID_CONTACT_EMAIL", "admin@example.com"
    )}


def send_to_subscriptions(subs: Iterable[dict],
                          title: str, body: str,
                          url: str = "/") -> dict:
    """Send the same notification payload to many subscriptions.
    Returns {sent, failed, gone} where `gone` are subscriptions removed
    because the push service told us they're invalid (HTTP 404/410)."""
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "")
    if not private_key:
        return {"sent": 0, "failed": len(list(subs)),
                "gone": 0, "error": "VAPID_PRIVATE_KEY not set"}

    payload = json.dumps({"title": title, "body": body, "url": url})
    sent = failed = gone = 0
    for s in subs:
        sub_info = {
            "endpoint": s["endpoint"],
            "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
        }
        try:
            webpush(
                subscription_info=sub_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=_vapid_claims(),
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                # Subscription is dead — remove it.
                db.delete_push_subscription(s["endpoint"])
                gone += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    return {"sent": sent, "failed": failed, "gone": gone}
