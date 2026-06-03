"""
Pushes new listings to a Google Sheet via an Apps Script web-app webhook.

The Apps Script endpoint is the single source of truth for de-duplication:
it keys on ``listing_id`` and only appends rows it has not seen before,
returning how many were actually added. This module is a no-op (returns 0)
if the webhook env vars are unset, so the monitor still runs without it.

Env vars:
  SHEETS_WEBHOOK_URL     — the Apps Script web-app /exec URL
  SHEETS_WEBHOOK_SECRET  — shared secret, must match the script's SECRET
"""

import os

import requests

from .utils import get_datetime


# Columns sent to the sheet, in display order. The Apps Script builds its
# header row from these same keys, so order here == column order in the sheet.
SHEET_FIELDS = [
    'address',
    'neighborhood',
    'price',
    'beds',
    'baths',
    'date_available',
    'days_listed',
    'contact_name',
    'contact_company',
    'contact_phone',
    'url',
    'listing_id',
]


class SheetsWriter:
    """POSTs new listings to the Apps Script webhook and reports the count added."""

    def __init__(self):
        self.url = os.environ.get('SHEETS_WEBHOOK_URL', '')
        self.secret = os.environ.get('SHEETS_WEBHOOK_SECRET', '')

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.secret)

    @staticmethod
    def _row(listing: dict) -> dict:
        """Normalize a listing into the exact keys the sheet expects."""
        url = listing.get('detail_url') or listing.get('url', '')
        if url and not url.startswith('http'):
            url = f'https://streeteasy.com{url}'

        price = listing.get('price', '')
        # Keep price numeric where possible so the sheet column sorts correctly.
        try:
            price = int(float(price))
        except (TypeError, ValueError):
            pass

        return {
            'address': listing.get('address', 'N/A'),
            'neighborhood': listing.get('neighborhood', 'N/A'),
            'price': price,
            'beds': listing.get('beds', 'N/A'),
            'baths': listing.get('baths', 'N/A'),
            'date_available': listing.get('date_available', 'N/A'),
            'days_listed': listing.get('days_listed', 'N/A'),
            'contact_name': listing.get('contact_name', 'N/A'),
            'contact_company': listing.get('contact_company', 'N/A'),
            'contact_phone': listing.get('contact_phone', 'N/A'),
            'url': url,
            'listing_id': listing.get('listing_id', url),
        }

    def push(self, listings: list[dict]) -> int:
        """Send listings to the sheet. Returns the number of NEW rows appended.

        Returns 0 (and prints a notice) if the webhook is not configured, or on
        any transport/endpoint error — the monitor should not crash because the
        sheet is unreachable.
        """
        if not listings:
            return 0

        if not self.enabled:
            print(
                f'{get_datetime()} SHEETS_WEBHOOK_URL/SECRET not set — '
                f'skipping Google Sheet sync.'
            )
            return 0

        payload = {
            'secret': self.secret,
            'fields': SHEET_FIELDS,
            'listings': [self._row(l) for l in listings],
        }

        try:
            resp = requests.post(self.url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f'{get_datetime()} Google Sheet sync failed: {e}')
            return 0

        if data.get('ok') is not True:
            print(
                f'{get_datetime()} Google Sheet rejected the request: '
                f'{data.get("error", data)}'
            )
            return 0

        added = int(data.get('added', 0))
        total = data.get('total')
        print(
            f'{get_datetime()} Google Sheet sync: {added} new row(s) appended'
            + (f' (sheet now holds {total}).' if total is not None else '.')
        )
        return added
