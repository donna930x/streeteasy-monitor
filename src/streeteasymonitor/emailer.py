"""
Sends one email per run via Gmail SMTP: a header with the count + a link to the
tracking spreadsheet, followed by a card for each new listing in the body.

Requires a Gmail App Password — not your regular Gmail password.
See: https://myaccount.google.com/apppasswords

Env vars:
  GMAIL_ADDRESS        — sending Gmail account
  GMAIL_APP_PASSWORD   — 16-char app password
  ALERT_TO_EMAIL       — where the email goes
  SHEET_URL            — link to the Google Sheet (button in the email)
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
CARD_STYLE = (
    "font-family:Arial,sans-serif;max-width:560px;margin:0 auto 16px;"
    "border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;text-align:left;"
)
HEADER_STYLE = (
    "background:#1a1a2e;color:#ffffff;padding:10px 16px;font-size:16px;"
    "font-weight:bold;"
)
ROW_STYLE = "padding:6px 16px;border-bottom:1px solid #f0f0f0;font-size:14px;"
LABEL_STYLE = "color:#666;display:inline-block;width:120px;"
VALUE_STYLE = "color:#1a1a2e;font-weight:500;"
LINK_STYLE = "color:#0066cc;text-decoration:none;font-size:14px;font-weight:bold;"


def _price(listing) -> str:
    p = listing.get('price', '')
    try:
        return f"${int(float(p)):,}"
    except (TypeError, ValueError):
        return str(p) if p else 'N/A'


def _url(listing) -> str:
    u = listing.get('detail_url') or listing.get('url', '')
    if u and not u.startswith('http'):
        u = f'https://streeteasy.com{u}'
    return u


def _contact(listing) -> str:
    parts = [listing.get(k, '') for k in
             ('contact_name', 'contact_company', 'contact_phone')]
    parts = [p for p in parts if p and p != 'N/A']
    return ' · '.join(parts) if parts else 'N/A'


def _row(label, value) -> str:
    return (
        f'<div style="{ROW_STYLE}">'
        f'<span style="{LABEL_STYLE}">{label}</span>'
        f'<span style="{VALUE_STYLE}">{value}</span></div>'
    )


def _card(listing) -> str:
    beds = listing.get('beds', 'N/A')
    baths = listing.get('baths', 'N/A')
    url = _url(listing)
    rows = [
        _row('Price', _price(listing)),
        _row('Beds / Baths', f'{beds} bed / {baths} bath'),
        _row('Neighborhood', listing.get('neighborhood', 'N/A')),
        _row('Available', listing.get('date_available', 'N/A')),
        _row('Days on market', listing.get('days_listed', 'N/A')),
        _row('Laundry', listing.get('laundry', 'N/A')),
        _row('Elevator', listing.get('elevator', 'N/A')),
        _row('Doorman', listing.get('doorman', 'N/A')),
        _row('Contact', _contact(listing)),
    ]
    link = (
        f'<div style="padding:10px 16px;">'
        f'<a href="{url}" style="{LINK_STYLE}">View listing →</a></div>'
        if url else ''
    )
    return (
        f'<div style="{CARD_STYLE}">'
        f'<div style="{HEADER_STYLE}">{listing.get("address", "Listing")}</div>'
        f'{"".join(rows)}{link}</div>'
    )


def _build_html(count: int, sheet_url: str, listings: list) -> str:
    plural = 's' if count != 1 else ''
    button = (
        f'<div style="text-align:center;margin:0 0 24px;">'
        f'<a href="{sheet_url}" style="{BTN_STYLE}">Open the spreadsheet →</a></div>'
        if sheet_url else ''
    )
    cards = ''.join(_card(l) for l in listings)
    return f"""\
<!DOCTYPE html>
<html>
<body style="background:#f5f5f5;padding:24px;margin:0;">
  <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
    <h2 style="color:#1a1a2e;margin:0 0 4px;text-align:center;">
      🏠 {count} new StreetEasy listing{plural}
    </h2>
    <p style="color:#666;font-size:13px;margin:0 0 20px;text-align:center;">
      {get_datetime()}
    </p>
    {button}
    {cards}
    <p style="color:#aaa;font-size:11px;text-align:center;margin-top:24px;">
      Sent by your StreetEasy monitor
    </p>
  </div>
</body>
</html>
"""


def _build_plain(count: int, sheet_url: str, listings: list) -> str:
    plural = 's' if count != 1 else ''
    lines = [f"{count} new StreetEasy listing{plural} — {get_datetime()}"]
    if sheet_url:
        lines += ['', f"Spreadsheet: {sheet_url}"]
    for l in listings:
        lines += [
            '',
            l.get('address', 'Listing'),
            f"  {_price(l)} | {l.get('beds','N/A')} bed / {l.get('baths','N/A')} bath "
            f"| {l.get('neighborhood','N/A')}",
            f"  Available: {l.get('date_available','N/A')} | "
            f"Days on market: {l.get('days_listed','N/A')}",
            f"  Laundry: {l.get('laundry','N/A')} | Elevator: {l.get('elevator','N/A')} "
            f"| Doorman: {l.get('doorman','N/A')}",
            f"  Contact: {_contact(l)}",
            f"  {_url(l)}",
        ]
    return '\n'.join(lines)


class Emailer:
    SMTP_HOST = 'smtp.gmail.com'
    SMTP_PORT = 587

    def __init__(self, monitor):
        self.gmail_address = os.environ.get('GMAIL_ADDRESS', '')
        self.gmail_app_password = os.environ.get('GMAIL_APP_PASSWORD', '')
        self.to_email = os.environ.get('ALERT_TO_EMAIL', '')
        self.sheet_url = os.environ.get('SHEET_URL', '')

    def send_summary(self, listings: list):
        """Send one email: count + spreadsheet link + a card per new listing."""
        count = len(listings)
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
        msg.attach(MIMEText(_build_plain(count, self.sheet_url, listings), 'plain'))
        msg.attach(MIMEText(_build_html(count, self.sheet_url, listings), 'html'))

        try:
            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(self.gmail_address, self.gmail_app_password)
                server.sendmail(self.gmail_address, self.to_email, msg.as_string())
            print(f'{get_datetime()} Email sent — {count} listing{plural}')
        except Exception as e:
            print(f'{get_datetime()} Failed to send email: {e}')
            raise
