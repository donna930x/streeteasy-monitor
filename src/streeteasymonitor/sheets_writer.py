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
import re

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
    'laundry',
    'elevator',
    'doorman',
    'date_available',
    'days_listed',
    'contact_first',
    'contact_last',
    'contact_company',
    'contact_phone',
    'url',
    'message',
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
    def _split_name(name: str):
        """('Jane Q Broker') -> ('Jane', 'Q Broker'). One word -> ('', '')."""
        name = (name or '').strip()
        if not name or name == 'N/A':
            return '', ''
        parts = name.split()
        if len(parts) == 1:
            return parts[0], ''
        return parts[0], ' '.join(parts[1:])

    @staticmethod
    def _street_without_unit(listing: dict) -> str:
        """Street address with the unit number removed."""
        street = (listing.get('street') or '').strip()
        if street:
            return street
        # Fall back: strip a trailing unit token off the full address.
        addr = (listing.get('address') or '').strip()
        unit = (listing.get('unit') or '').strip()
        if unit and addr.endswith(unit):
            addr = addr[: -len(unit)].strip()
        else:
            # e.g. "325 Kent Ave 5B" / "12 Main St #4F" / "5 E 22 St Apt 3"
            addr = re.sub(
                r'\s+(?:#|apt\.?|unit|ph)?\s*[\w\-]*\d[\w\-]*$', '', addr, flags=re.I
            ).strip()
        return addr or listing.get('address', 'N/A')

    @classmethod
    def _build_message(cls, listing: dict, first: str) -> str:
        """A copy-paste viewing-request message for the listing."""
        greeting_name = first or 'there'
        street = cls._street_without_unit(listing)
        avail = (listing.get('date_available') or '').strip()
        if avail in ('Now', 'Today'):
            unit_clause = 'the unit available now'
        elif avail and avail != 'N/A':
            unit_clause = f'the unit available starting {avail}'
        else:
            unit_clause = 'the unit'
        return (
            f"Hi {greeting_name}\n\n"
            f"I'm very interested in {unit_clause} at {street}. "
            f"Please let me know when the unit would be available for a viewing.\n\n"
            f"Thank you!\nDonnya"
        )

    @classmethod
    def _row(cls, listing: dict) -> dict:
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

        first, last = cls._split_name(listing.get('contact_name', ''))

        return {
            'address': listing.get('address', 'N/A'),
            'neighborhood': listing.get('neighborhood', 'N/A'),
            'price': price,
            'beds': listing.get('beds', 'N/A'),
            'baths': listing.get('baths', 'N/A'),
            'laundry': listing.get('laundry', 'N/A'),
            'elevator': listing.get('elevator', 'N/A'),
            'doorman': listing.get('doorman', 'N/A'),
            'date_available': listing.get('date_available', 'N/A'),
            'days_listed': listing.get('days_listed', 'N/A'),
            'contact_first': first or 'N/A',
            'contact_last': last or 'N/A',
            'contact_company': listing.get('contact_company', 'N/A'),
            'contact_phone': listing.get('contact_phone', 'N/A'),
            'url': url,
            'message': cls._build_message(listing, first),
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
