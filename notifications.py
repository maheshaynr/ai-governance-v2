import requests
import json
import logging
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class EmailNotifier:
    @staticmethod
    def send_alarm_email(to_email: str, alarm: dict, subscriber_role: str):
        if not to_email or "@" not in to_email:
            return

        smtp_host = os.environ.get('SMTP_HOST', 'smtp.office365.com')
        smtp_port = int(os.environ.get('SMTP_PORT', 587))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_pass = os.environ.get('SMTP_PASSWORD')

        if not smtp_user or not smtp_pass:
            logging.error("SMTP_USER or SMTP_PASSWORD environment variables not set. Cannot send email.")
            return

        subject = f"🚨 Governance Alarm: Unmasked {alarm['missed_entity']['type']} Detected"
        
        # HTML formatting for the email
        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #cf222e;">🚨 Enterprise Governance Shield Alert</h2>
            <p>An unmasked sensitive entity has been detected by the LLM Watchdog and routed to you ({subscriber_role}).</p>
            <table style="border-collapse: collapse; width: 100%; max-width: 600px; margin-bottom: 20px;">
              <tr>
                <td style="padding: 10px; border: 1px solid #ddd; background-color: #f6f8fa; font-weight: bold;">Severity</td>
                <td style="padding: 10px; border: 1px solid #ddd; color: #cf222e; font-weight: bold;">{alarm['severity']}</td>
              </tr>
              <tr>
                <td style="padding: 10px; border: 1px solid #ddd; background-color: #f6f8fa; font-weight: bold;">Category</td>
                <td style="padding: 10px; border: 1px solid #ddd;">{alarm['missed_entity']['type']}</td>
              </tr>
              <tr>
                <td style="padding: 10px; border: 1px solid #ddd; background-color: #f6f8fa; font-weight: bold;">AI Reason</td>
                <td style="padding: 10px; border: 1px solid #ddd;">{alarm['missed_entity']['reason']}</td>
              </tr>
              <tr>
                <td style="padding: 10px; border: 1px solid #ddd; background-color: #f6f8fa; font-weight: bold;">Extracted Value</td>
                <td style="padding: 10px; border: 1px solid #ddd; font-family: monospace;">{alarm['missed_entity']['value_preview']}</td>
              </tr>
            </table>
            
            <h3 style="margin-bottom: 5px;">Context Snippet</h3>
            <div style="background-color: #f6f8fa; padding: 15px; border-left: 4px solid #0969da; border-radius: 4px; font-style: italic;">
              {alarm['context_snippet']}
            </div>
            
            <p style="margin-top: 20px; font-size: 0.9em; color: #57606a;">
              Please review this incident in the Enterprise Governance Dashboard immediately.<br>
              Timestamp: {alarm['timestamp']}
            </p>
          </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email

        # Attach HTML content
        part = MIMEText(html_content, "html")
        msg.attach(part)

        try:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
            server.quit()
            logging.info(f"Successfully sent alert email to {to_email}")
        except Exception as e:
            logging.error(f"Failed to send email to {to_email}: {str(e)}")
