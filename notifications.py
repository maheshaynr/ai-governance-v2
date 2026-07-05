import requests
import json
import logging

class TeamsNotifier:
    @staticmethod
    def send_alarm_alert(webhook_url: str, alarm: dict, subscriber_role: str):
        if not webhook_url or "http" not in webhook_url:
            return

        # Build an Adaptive Card or simple MessageCard for MS Teams
        title = f"🚨 Governance Alarm: Unmasked {alarm['missed_entity']['type']} Detected"
        text = (
            f"**Severity:** {alarm['severity']}\n\n"
            f"**Category:** {alarm['missed_entity']['type']}\n\n"
            f"**Reason:** {alarm['missed_entity']['reason']}\n\n"
            f"**Value Preview:** `{alarm['missed_entity']['value_preview']}`\n\n"
            f"**Action Required:** Please review in the Governance Dashboard. (Routed to {subscriber_role})"
        )

        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "D20000",
            "summary": title,
            "sections": [{
                "activityTitle": title,
                "activitySubtitle": f"Timestamp: {alarm['timestamp']}",
                "text": text
            }]
        }

        try:
            resp = requests.post(webhook_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
            if resp.status_code != 200:
                logging.error(f"Failed to send MS Teams notification. Status: {resp.status_code}, Response: {resp.text}")
        except Exception as e:
            logging.error(f"Error sending MS Teams notification: {str(e)}")
