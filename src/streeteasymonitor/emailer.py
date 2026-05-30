"""
Sends a single digest email for all new listings via Gmail SMTP.
One email per run, with each listing as a card in the HTML body.

Requires a Gmail App Password — not your regular Gmail password.
See: https://myaccount.google.com/apppasswords
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .utils import get_datetime


CARD_STYLE = (
    "font-family:Arial,sans-serif;max-width:600px;margin:0 auto 24px;"
    "border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;"
)
HEADER_STYLE = (
    "background:#1a1a2e;color:#ffffff;padding:12px 16px;"
    "font-size:18px;font-weight:bold;"
)
ROW_STYLE = "display:flex;padding:8px 16px;border-bottom:1px solid #f0f0f0;"
LABEL_STYLE = "color:#666;font-size:13px;width:130px;flex-shrink:0;padding-top:2px;"
VALUE_STYLE = "color:#1a1a2e;font-size:14px;font-weight:500;"
LINK_STYLE = "color:#0066cc;text-decoration:none;font-size:14px;"


def _listing_card(listing: dict) -> str:
    price = f"${int(listing.get('price', 0)):,}" if listing.get('price') else 'N/A'
    beds = listing.get('beds', 'N/A')
    baths = listing.get('baths', 'N/A')
    beds_baths = f"{beds} bed / {baths} bath"
    neighborhood = listing.get('neighborhood', 'N/A')
    days = listing.get('days_listed', 'N/A')
    days_label = f"{days} day{'s' if days not in ('0', '1', 'N/A') else ''} on market"
    date_avail = listing.get('date_available', 'N/A')
    url = listing.get('detail_url') or listing.get('url', '')
    address = listing.get('address', 'Unknown address')

    if url and not url.startswith('http'):
        url = f'https://streeteasy.com{url}'

    rows = [
        ('Price', price),
        ('Beds / Baths', beds_baths),
        ('Neighborhood', neighborhood),
        ('Days Listed', days_label),
        ('Date Available', date_avail),
    ]

    row_html = ''.join(
        f'<div style="{ROW_STYLE}">'
        f'<span style="{LABEL_STYLE}">{label}</span>'
        f'<span style="{VALUE_STYLE}">{value}</span>'
        f'</div>'
        for label, value in rows
    )

    view_link = (
        f'<div style="padding:12px 16px;">'
        f'<a href="{url}" style="{LINK_STYLE}">View listing →</a>'
        f'</div>'
        if url else ''
    )

    return (
        f'<div style="{CARD_STYLE}">'
        f'<div style="{HEADER_STYLE}">{address}</div>'
        f'{row_html}'
        f'{view_link}'
        f'</div>'
    )


def _build_html(listings: list[dict]) -> str:
    count = len(listings)
    plural = 's' if count != 1 else ''
    cards = '\n'.join(_listing_card(l) for l in listings)
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="background:#f5f5f5;padding:24px;margin:0;">
      <div style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;">
        <h2 style="color:#1a1a2e;margin-bottom:4px;">
          🏠 {count} New StreetEasy Listing{plural}
        </h2>
        <p style="color:#666;font-size:13px;margin-top:0;margin-bottom:24px;">
          {get_datetime()} — matches your saved filters
        </p>
        {cards}
        <p style="color:#aaa;font-size:11px;text-align:center;margin-top:32px;">
          Sent by your StreetEasy monitor ·
          <a href="https://streeteasy.com" style="color:#aaa;">streeteasy.com</a>
        </p>
      </div>
    </body>
    </html>
    """


def _build_plain(listings: list[dict]) -> str:
    lines = [f"New StreetEasy listings — {get_datetime()}\n"]
    for l in listings:
        price = f"${int(l.get('price', 0)):,}" if l.get('price') else 'N/A'
        url = l.get('detail_url') or l.get('url', '')
        if url and not url.startswith('http'):
            url = f'https://streeteasy.com{url}'
        lines.append(
            f"{l.get('address', 'Unknown')} | {l.get('neighborhood', 'N/A')} | "
            f"{price} | {l.get('beds', 'N/A')} bed / {l.get('baths', 'N/A')} bath | "
            f"Available: {l.get('date_available', 'N/A')} | "
            f"Days listed: {l.get('days_listed', 'N/A')}\n"
            f"{url}\n"
        )
    return '\n'.join(lines)


class Emailer:
    SMTP_HOST = 'smtp.gmail.com'
    SMTP_PORT = 587

    def __init__(self, monitor, listings: list[dict]):
        self.listings = listings
        self.db = monitor.db
        self.gmail_address = os.environ.get('GMAIL_ADDRESS', '')
        self.gmail_app_password = os.environ.get('GMAIL_APP_PASSWORD', '')
        self.to_email = os.environ.get('ALERT_TO_EMAIL', '')

    def send_alerts(self):
        if not self.listings:
            return

        if not all([self.gmail_address, self.gmail_app_password, self.to_email]):
            raise EnvironmentError(
                'Missing one or more required env vars: '
                'GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_TO_EMAIL'
            )

        count = len(self.listings)
        plural = 's' if count != 1 else ''
        subject = f"🏠 {count} new StreetEasy listing{plural} match your filters"

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.gmail_address
        msg['To'] = self.to_email
        msg.attach(MIMEText(_build_plain(self.listings), 'plain'))
        msg.attach(MIMEText(_build_html(self.listings), 'html'))

        try:
            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(self.gmail_address, self.gmail_app_password)
                server.sendmail(self.gmail_address, self.to_email, msg.as_string())

            print(f'{get_datetime()} Email sent — {count} listing{plural}')
            for listing in self.listings:
                self.db.insert_new_listing(listing)
        except Exception as e:
            print(f'{get_datetime()} Failed to send email: {e}')
            raise
