"""
Sends a single summary email per run via Gmail SMTP.

The email no longer lists each listing — the Google Sheet is the system of
record. It just says "N new listings added" and links to the sheet so you can
open it with one click.

Requires a Gmail App Password — not your regular Gmail password.
See: https://myaccount.google.com/apppasswords

Env vars:
  GMAIL_ADDRESS        — sending Gmail account
  GMAIL_APP_PASSWORD   — 16-char app password
  ALERT_TO_EMAIL       — where the summary goes
  SHEET_URL            — link to the Google Sheet (shown/linked in the email)
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .utils import get_datetime


BTN_STYLE = (
    "display:inline-block;background:#1a1a2e;color:#ffffff;text-decoration:none;"
    "padding:12px 22px;border-radius:8px;font-size:15px;font-weight:bold;"
)


def _build_html(count: int, sheet_url: str) -> str:
    plural = 's' if count != 1 else ''
    button = (
        f'<a href="{sheet_url}" style="{BTN_STYLE}">Open the spreadsheet →</a>'
        if sheet_url else ''
    )
    return f"""\
<!DOCTYPE html>
<html>
<body style="background:#f5f5f5;padding:24px;margin:0;">
  <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
              background:#ffffff;border:1px solid #e0e0e0;border-radius:8px;
              padding:32px;text-align:center;">
    <h2 style="color:#1a1a2e;margin:0 0 8px;">
      🏠 {count} new StreetEasy listing{plural}
    </h2>
    <p style="color:#666;font-size:14px;margin:0 0 24px;">
      Added to your tracking spreadsheet — {get_datetime()}
    </p>
    {button}
    <p style="color:#aaa;font-size:11px;margin-top:28px;">
      Sent by your StreetEasy monitor
    </p>
  </div>
</body>
</html>
"""


def _build_plain(count: int, sheet_url: str) -> str:
    plural = 's' if count != 1 else ''
    lines = [
        f"{count} new StreetEasy listing{plural} added to your spreadsheet "
        f"— {get_datetime()}",
    ]
    if sheet_url:
        lines.append('')
        lines.append(f"Open the spreadsheet: {sheet_url}")
    return '\n'.join(lines)


class Emailer:
    SMTP_HOST = 'smtp.gmail.com'
    SMTP_PORT = 587

    def __init__(self, monitor):
        self.gmail_address = os.environ.get('GMAIL_ADDRESS', '')
        self.gmail_app_password = os.environ.get('GMAIL_APP_PASSWORD', '')
        self.to_email = os.environ.get('ALERT_TO_EMAIL', '')
        self.sheet_url = os.environ.get('SHEET_URL', '')

    def send_summary(self, count: int):
        """Send one summary email: N new listings + a link to the sheet."""
        if count <= 0:
            return

        if not all([self.gmail_address, self.gmail_app_password, self.to_email]):
            raise EnvironmentError(
                'Missing one or more required env vars: '
                'GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_TO_EMAIL'
            )

        plural = 's' if count != 1 else ''
        subject = f"🏠 {count} new StreetEasy listing{plural}"

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.gmail_address
        msg['To'] = self.to_email
        msg.attach(MIMEText(_build_plain(count, self.sheet_url), 'plain'))
        msg.attach(MIMEText(_build_html(count, self.sheet_url), 'html'))

        try:
            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(self.gmail_address, self.gmail_app_password)
                server.sendmail(self.gmail_address, self.to_email, msg.as_string())
            print(f'{get_datetime()} Summary email sent — {count} listing{plural}')
        except Exception as e:
            print(f'{get_datetime()} Failed to send email: {e}')
            raise
