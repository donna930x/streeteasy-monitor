"""
Fetches additional details from an individual StreetEasy listing page:
beds, baths, days on market, date available, and the listing contact
(name / company / phone shown under "Listed by").

StreetEasy listing pages are a Next.js app. The data lives in the React
"Flight" payload (self.__next_f.push([...])); some of it is also
server-rendered as visible text under labels like "Available",
"Days on market" and "Listed by".

The phone number is hidden in the UI behind a "Show phone number" button, so
it is NOT in the rendered text. We dig it out of the page source instead — a
`tel:` link or a phone-keyed field inside the Flight payload — and only fall
back to rendered text for the name/company.

Every field falls back to 'N/A' so a scraping failure never blocks the email.
"""

import re
import json
import random
import time
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from .config import Config
from .utils import get_datetime


class DetailFetcher:
    # Phone like "+1 (646) 989-8537", "(646) 989-8537", "646-989-8537"
    _phone_re = re.compile(
        r'(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}'
    )
    # lines under "Listed by" that are NOT a contact (buttons, prompts, etc.)
    _contact_noise = re.compile(
        r'listed by|ask a question|save|share|report|hide|message|'
        r'request|schedule|tour|email|view|show\s+(?:phone|number)|'
        r'reveal|phone number|see\s+phone',
        re.I,
    )

    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------------ #
    def fetch(self, listing: dict) -> dict:
        url = listing.get('url', '')
        if not url.startswith('http'):
            url = f'https://streeteasy.com{url}'

        enriched = {
            **listing,
            'beds': listing.get('beds', 'N/A'),
            'baths': listing.get('baths', 'N/A'),
            'days_listed': 'N/A',
            'listed_date': 'N/A',
            'date_available': 'N/A',
            'contacts': 'N/A',
            'contact_name': 'N/A',
            'contact_company': 'N/A',
            'contact_phone': 'N/A',
            'laundry': 'N/A',
            'elevator': 'N/A',
            'doorman': 'N/A',
            # True for new-dev / lease-up units that show "Leasing Starts"
            # instead of "Days on market" — the caller omits these.
            'leasing': False,
            'detail_url': url,
            # False until the detail page is actually fetched + parsed, so the
            # caller can retry failures next run instead of recording N/A rows.
            'detail_ok': False,
        }

        try:
            r = self._get_with_retry(url)
            if r is None or r.status_code != 200:
                print(
                    f'{get_datetime()} Detail fetch failed for {url} '
                    f'(status {getattr(r, "status_code", "no response")}).'
                )
                return enriched
            enriched.update(self._parse(r.content))
            enriched['detail_ok'] = True
        except Exception as e:
            print(f'{get_datetime()} Detail fetch error for {url}: {e}')

        return enriched

    def _get_with_retry(self, url, attempts: int = 3):
        """GET a listing detail page with backoff + identity rotation. Retries
        only on block-like statuses (403 / 429 / 503)."""
        proxied = bool(getattr(self.session, 'proxies', None))
        timeout = 70 if proxied else 20
        response = None
        for i in range(attempts):
            try:
                self.session.headers.update(Config().get_headers())
            except Exception:
                pass
            try:
                response = self.session.get(url, timeout=timeout)
            except Exception:
                response = None
            if response is not None and response.status_code == 200:
                return response
            if response is not None and response.status_code not in (403, 429, 503):
                return response  # genuine other error (e.g. 404) — don't hammer
            if i < attempts - 1:
                time.sleep(2 ** i + random.uniform(0, 1.5))
        return response

    # ------------------------------------------------------------------ #
    def _parse(self, content: bytes) -> dict:
        soup = BeautifulSoup(content, 'html.parser')
        text = soup.get_text('\n', strip=True)
        raw = content.decode('utf-8', errors='ignore') if isinstance(
            content, (bytes, bytearray)) else content
        flight_text = self._flight_text(soup)
        flight = self._flight_object(flight_text)

        result = {}

        # --- beds / baths ----------------------------------------------
        beds = flight.get('bedroomCount')
        if beds is not None:
            result['beds'] = 'Studio' if beds in (0, '0') else str(beds)
        baths = flight.get('fullBathroomCount')
        if baths is not None:
            result['baths'] = str(baths)

        # --- date available --------------------------------------------
        avail = self._available_from_text(text) or self._iso_to_us(flight.get('availableAt'))
        if avail:
            result['date_available'] = avail
        available_now = avail == 'Now' or bool(
            re.search(r'available\s+(?:today|now|immediately)', text, re.I)
        )

        # --- days on market --------------------------------------------
        days = self._days_from_text(text)
        if days is None:
            days = self._days_from_flight(flight)
        # Reject implausible values (e.g. a stray year like 2026, or an
        # original-listing date-diff) — a rental's days-on-market is never
        # negative and realistically well under ~2 years.
        if days is not None and not (0 <= days <= 1000):
            days = None
        # A unit available today/now hasn't been on market — call it 0.
        if days is None and available_now:
            days = 0
        if days is not None:
            result['days_listed'] = str(days)
            # Store the listing DATE so the sheet can recompute days-on-market
            # itself (=TODAY()-date) and never go stale.
            result['listed_date'] = (
                date.today() - timedelta(days=days)
            ).strftime('%Y-%m-%d')

        # --- new-dev / lease-up flag -----------------------------------
        # These units show "Leasing Starts" instead of "Days on market"; the
        # caller omits them entirely.
        result['leasing'] = bool(re.search(r'leasing\s+starts', text, re.I))

        # --- amenities (laundry / elevator / doorman) ------------------
        laundry, elevator, doorman = self._extract_amenities(text)
        result['laundry'] = laundry
        result['elevator'] = elevator
        result['doorman'] = doorman

        # --- contact (name / company / phone in separate fields) -------
        name, company, phone = self._extract_contact(text, raw, flight_text, flight)
        result['contact_name'] = name or 'N/A'
        result['contact_company'] = company or 'N/A'
        result['contact_phone'] = phone or 'N/A'
        # keep a combined string too, for backward compatibility
        joined = ' · '.join(p for p in (name, company, phone) if p)
        result['contacts'] = joined or 'N/A'

        return result

    # ------------------------------------------------------------------ #
    # Contact assembly
    # ------------------------------------------------------------------ #
    def _extract_contact(self, text, raw, flight_text, flight):
        """Return a (name, company, phone) tuple, each '' if not found.

        Name + company come from the rendered "Listed by" block (first two
        non-noise lines), with a Flight-payload fallback. Phone always comes
        from page source — never the rendered "Show phone number" button.
        """
        # 1. name / company lines from the rendered "Listed by" block
        lines = self._listed_by_lines(text)
        name = lines[0] if len(lines) >= 1 else ''
        company = lines[1] if len(lines) >= 2 else ''

        # fall back to Flight fields if the block wasn't rendered
        if not name:
            for key in ('contactName', 'agentName'):
                v = flight.get(key)
                if v:
                    name = str(v)
                    break
        if not company:
            for key in ('sourceGroupLabel', 'brokerName', 'agentName'):
                v = flight.get(key)
                if v and str(v) != name:
                    company = str(v)
                    break

        # 2. phone — never from rendered text (it's behind a button); always
        #    from source: tel: link, then phone-keyed JSON fields.
        phone = self._phone_from_source(raw, flight_text, flight)
        if not phone:
            phone = self._phone_from_text(text)

        return name, company, phone

    def _listed_by_lines(self, text) -> list:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for i, line in enumerate(lines):
            if line.lower().startswith('listed by'):
                picked = []
                for b in lines[i + 1:i + 8]:
                    if self._phone_re.search(b):
                        break                       # reached the phone region
                    if self._contact_noise.search(b):
                        continue                    # skip buttons / prompts
                    if re.search(r'[A-Za-z]', b) and len(b) <= 60:
                        picked.append(b)
                    if len(picked) >= 2:            # name + company is plenty
                        break
                return picked
        return []

    def _phone_from_source(self, raw, flight_text, flight) -> str:
        # a) tel: link in the raw HTML (most reliable when present)
        m = re.search(r'tel:\s*(\+?[\d().\-\s]{10,20})', raw)
        if m:
            return self._format_phone(m.group(1))

        # b) phone-keyed fields inside the decoded Flight payload
        for km in re.finditer(
            r'"([A-Za-z]*[Pp]hone[A-Za-z]*)"\s*:\s*"([^"]{7,25})"', flight_text
        ):
            if self._phone_re.search(km.group(2)):
                return self._format_phone(km.group(2))

        # c) explicit keys on the parsed listing object
        for key in ('phone', 'phoneNumber', 'formattedPhone',
                    'displayPhone', 'contactPhone', 'phoneNumberFormatted'):
            v = flight.get(key)
            if v and self._phone_re.search(str(v)):
                return self._format_phone(str(v))
        return ''

    def _phone_from_text(self, text) -> str:
        """Last resort: a real phone number (with digits) shown in the
        rendered "Listed by" block. Never matches the 'Show phone number'
        button because that has no digits."""
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for i, line in enumerate(lines):
            if line.lower().startswith('listed by'):
                for b in lines[i + 1:i + 8]:
                    m = self._phone_re.search(b)
                    if m:
                        return self._format_phone(m.group(0))
        return ''

    @staticmethod
    def _format_phone(s) -> str:
        """Return a plain 10-digit string, e.g. '7186827712'.

        No '+', spaces, or parens — a leading '+' makes Google Sheets treat the
        cell as a formula and error out.
        """
        d = re.sub(r'\D', '', str(s))
        if len(d) == 11 and d[0] == '1':
            d = d[1:]
        if len(d) == 10:
            return d
        return d or str(s).strip()

    # ------------------------------------------------------------------ #
    # Flight payload helpers
    # ------------------------------------------------------------------ #
    def _flight_object(self, flight_text) -> dict:
        if not flight_text:
            return {}
        for data in self._objects_with_keys(
            flight_text, '"availableAt"', ('availableAt', 'price')
        ):
            return data
        for data in self._objects_with_keys(flight_text, '"urlPath"', ('urlPath', 'price')):
            return data
        return {}

    @staticmethod
    def _flight_text(soup) -> str:
        chunks = []
        for script in soup.find_all('script'):
            txt = script.string or script.get_text() or ''
            if '__next_f.push' not in txt:
                continue
            m = re.search(r'__next_f\.push\((\[.*\])\)', txt, re.DOTALL)
            if not m:
                continue
            try:
                arr = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                continue
            for el in arr:
                if isinstance(el, str):
                    chunks.append(el)
        return ''.join(chunks)

    def _objects_with_keys(self, text, anchor, required):
        for m in re.finditer(re.escape(anchor), text):
            idx = m.start()
            window = max(0, idx - 8000)
            for o in range(idx, window - 1, -1):
                if text[o] != '{':
                    continue
                obj = self._balanced_object(text, o)
                if obj is None or (o + len(obj)) <= idx:
                    continue
                try:
                    data = json.loads(obj)
                except (json.JSONDecodeError, ValueError):
                    continue
                if all(k in data for k in required):
                    yield data
                    break

    @staticmethod
    def _balanced_object(text, start):
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
        return None

    def _days_from_flight(self, flight):
        # Explicit, trustworthy day-count fields first.
        for key in ('daysOnMarket', 'daysOnStreetEasy', 'daysListed'):
            v = flight.get(key)
            if isinstance(v, int) and 0 <= v <= 3650:
                return v
        # Date-diff only from the *current* listing date (resets on relist).
        # We deliberately ignore createdAt / firstListedAt: those point at the
        # original listing years ago, so a unit that is actually "Today" would
        # otherwise read ~2000 days. Bound the result to a plausible window.
        d = self._parse_iso(flight.get('listedAt'))
        if d:
            diff = (date.today() - d).days
            if 0 <= diff <= 730:
                return diff
        return None

    # ------------------------------------------------------------------ #
    # Amenities
    # ------------------------------------------------------------------ #
    def _extract_amenities(self, text):
        """Return (laundry, elevator, doorman) from the rendered amenity lists.

        StreetEasy only renders amenities a listing *has*, so presence-matching
        on the visible text is reliable.
          - laundry:  'In unit' | 'In building' | 'None'
          - elevator: 'Yes' | 'No'
          - doorman:  'Virtual' | 'Yes' | 'No'
        """
        hay = text.lower()

        in_unit = bool(
            re.search(r'(?:washer\s*/?\s*dryer|laundry)[^.\n]{0,15}in[\s-]*unit', hay)
            or re.search(r'in[\s-]*unit[^.\n]{0,15}(?:washer|dryer|laundry)', hay)
        )
        in_building = bool(
            re.search(r'laundry[^.\n]{0,15}in[\s-]*building', hay)
            or 'laundry in building' in hay
        )
        if in_unit:
            laundry = 'In unit'
        elif in_building:
            laundry = 'In building'
        else:
            laundry = 'None'

        elevator = 'Yes' if re.search(r'\belevator\b', hay) else 'No'

        if re.search(r'virtual\s+doorman', hay):
            doorman = 'Virtual'
        elif re.search(r'\bdoorman\b', hay):
            doorman = 'Yes'
        else:
            doorman = 'No'

        return laundry, elevator, doorman

    # ------------------------------------------------------------------ #
    # Rendered-text helpers
    # ------------------------------------------------------------------ #
    def _available_from_text(self, text) -> str:
        m = re.search(r'\bavailable\b[^0-9A-Za-z]{0,20}(\d{1,2}/\d{1,2}/\d{2,4})',
                      text, re.I | re.S)
        if m:
            return m.group(1)
        m = re.search(r'\bavailable\b[^0-9A-Za-z]{0,20}'
                      r'([A-Z][a-z]+\.?\s+\d{1,2}(?:,\s*\d{4})?)', text, re.I | re.S)
        if m:
            return m.group(1).strip()
        if re.search(r'available\s+(?:now|immediately|today)', text, re.I):
            return 'Now'
        return ''

    def _days_from_text(self, text):
        # "Days on market: Today" / "less than a day" / "0 days" → 0.
        # Checked first so it wins over any stale date in the Flight payload.
        if re.search(
            r'days?\s+on\s+market[^0-9A-Za-z]{0,20}'
            r'(?:today|less\s+than\s+a\s+day|<\s*1\s*day|0\s*days?\b)',
            text, re.I,
        ):
            return 0
        m = re.search(r'days?\s+on\s+market[^0-9]{0,20}(\d+)\s*days?', text, re.I | re.S)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d+)\s+days?\s+on\s+(?:street\s*easy|market)', text, re.I)
        if m:
            return int(m.group(1))
        # "Listed today" / "listed less than a day ago" / "listed N hours ago" → 0
        if re.search(
            r'listed\s+(?:today|less\s+than\s+a\s+day|\d+\s+(?:hours?|minutes?)\s+ago)',
            text, re.I,
        ):
            return 0
        return None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_iso(s):
        if not s or not isinstance(s, str):
            return None
        try:
            return datetime.strptime(s[:10], '%Y-%m-%d').date()
        except ValueError:
            return None

    def _iso_to_us(self, s):
        d = self._parse_iso(s)
        return f'{d.month}/{d.day}/{d.year}' if d else ''
