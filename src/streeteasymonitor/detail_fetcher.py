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
from datetime import date, datetime

from bs4 import BeautifulSoup


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
            'date_available': 'N/A',
            'contacts': 'N/A',
            'detail_url': url,
        }

        try:
            r = self.session.get(url, timeout=15)
            if r.status_code != 200:
                return enriched
            enriched.update(self._parse(r.content))
        except Exception:
            pass

        return enriched

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

        # --- days on market --------------------------------------------
        days = self._days_from_text(text)
        if days is None:
            days = self._days_from_flight(flight)
        if days is not None:
            result['days_listed'] = str(days)

        # --- contact (name / company / phone) --------------------------
        result['contacts'] = self._build_contacts(text, raw, flight_text, flight)

        return result

    # ------------------------------------------------------------------ #
    # Contact assembly
    # ------------------------------------------------------------------ #
    def _build_contacts(self, text, raw, flight_text, flight) -> str:
        # 1. name / company lines from the rendered "Listed by" block
        parts = self._listed_by_lines(text)

        # fall back to Flight source/agent name if the block wasn't rendered
        if not parts:
            for key in ('sourceGroupLabel', 'agentName', 'brokerName', 'contactName'):
                v = flight.get(key)
                if v and str(v) not in parts:
                    parts.append(str(v))

        # 2. phone — never from rendered text (it's behind a button); always
        #    from source: tel: link, then phone-keyed JSON fields.
        phone = self._phone_from_source(raw, flight_text, flight)
        if not phone:
            phone = self._phone_from_text(text)
        if phone:
            parts.append(phone)

        parts = [p for p in dict.fromkeys(parts) if p]
        return ' · '.join(parts[:4]) if parts else 'N/A'

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
        d = re.sub(r'\D', '', str(s))
        if len(d) == 11 and d[0] == '1':
            d = d[1:]
        if len(d) == 10:
            return f'+1 ({d[0:3]}) {d[3:6]}-{d[6:10]}'
        return str(s).strip()

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
        for key in ('daysOnMarket', 'daysOnStreetEasy', 'daysListed'):
            if isinstance(flight.get(key), int):
                return flight[key]
        for key in ('listedAt', 'firstListedAt', 'createdAt'):
            d = self._parse_iso(flight.get(key))
            if d:
                return (date.today() - d).days
        return None

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
        if re.search(r'available\s+(?:now|immediately)', text, re.I):
            return 'Now'
        return ''

    def _days_from_text(self, text):
        m = re.search(r'days?\s+on\s+market[^0-9]{0,20}(\d+)\s*days?', text, re.I | re.S)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d+)\s+days?\s+on\s+(?:street\s*easy|market)', text, re.I)
        if m:
            return int(m.group(1))
        if re.search(r'listed\s+today', text, re.I):
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
