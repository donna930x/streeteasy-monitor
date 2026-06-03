import json
import random
import re
import time

from bs4 import BeautifulSoup

from .config import Config
from .utils import build_url, get_datetime, get_area_map


class Search:
    """Constructs a StreetEasy search URL and fetches matching listings."""

    area_map: dict[str, str] = get_area_map()

    def __init__(self, monitor) -> None:
        self.session = monitor.session
        self.db = monitor.db
        self.kwargs = monitor.kwargs

        self.codes = [Search.area_map[area] for area in self.kwargs['areas']]

        self.area = ','.join(self.codes)
        self.price = f"{self.kwargs['min_price']}-{self.kwargs['max_price']}"
        self.beds = f"{self.kwargs['min_beds']}-{self.kwargs['max_beds']}"
        self.baths = f">={self.kwargs['baths']}"
        self.amenities = f"{','.join(self.kwargs['amenities'])}"
        self.no_fee = f"{1 if self.kwargs['no_fee'] == True else ''}"

        # Optional params — only included if set in config
        available_after = self.kwargs.get('available_after', '')   # 'YYYYMMDD'
        in_rect = self.kwargs.get('in_rect', '')                   # 'lat_min,lat_max,lng_min,lng_max'
        sqft = self.kwargs.get('sqft', '')                         # e.g. '500-1200'
        listing_type = self.kwargs.get('listing_type', '')         # e.g. 'rentals'

        self.parameters = {
            'status': 'open',
            'price': self.price,
            'area': self.area,
            'beds': self.beds,
            'baths': self.baths,
            'amenities': self.amenities,
            'no_fee': self.no_fee,
            # optional — empty strings are filtered out by build_url
            'available_after': available_after,
            'in_rect': in_rect,
            'sqft': sqft,
            'listing_type': listing_type,
        }

        # Strip params with no value before building the URL
        self.parameters = {k: v for k, v in self.parameters.items() if v}

        self.url = build_url(**self.parameters)
        self.listings = []

    def fetch(self) -> list[dict]:
        print(f'Running with parameters:\n{json.dumps(self.parameters, indent=2)}\n')
        print(f'URL: {self.url}')

        self.r = self._get_with_retry(self.url)
        status = self.r.status_code

        # --- 1. Transport-level failure (block, redirect, rate-limit) ---
        if status != 200:
            print(
                f'{get_datetime()} HTTP {status} from StreetEasy — request rejected '
                f'or blocked. No parse attempted.\n'
            )
            return self.listings

        parser = Parser(self.r.content, self.db)
        self.listings = parser.listings
        cards_seen = parser.card_count

        # --- 2. 200 but nothing parsed: stale selectors OR an anti-bot wall ---
        if cards_seen == 0:
            body = self.r.text.lower()
            blocked = any(
                token in body
                for token in (
                    'press & hold',
                    'px-captcha',
                    'are you a human',
                    'access to this page has been denied',
                    'captcha-delivery',
                )
            )
            if blocked:
                print(
                    f'{get_datetime()} HTTP 200 but an anti-bot challenge was served '
                    f'(captcha / press-and-hold). No listings parsed.\n'
                )
            else:
                print(
                    f'{get_datetime()} HTTP 200 but 0 listings found in the markup. '
                    f'Either the search genuinely returned nothing or the parser '
                    f'selectors are stale — open the URL above in a browser to check.\n'
                )
            return self.listings

        # --- 3. Parsed listings, but none are new after dedup/filter ---
        if not self.listings:
            print(
                f'{get_datetime()} Parsed {cards_seen} listing(s), but all were '
                f'already seen or filtered out — no NEW listings.\n'
            )
            return self.listings

        # --- 4. Success ---
        print(f'{get_datetime()} {len(self.listings)} new listing(s) found.\n')
        return self.listings

    # ------------------------------------------------------------------ #
    # Anti-bot mitigation: warm-up + retry with backoff
    # ------------------------------------------------------------------ #
    def _warm_up(self) -> None:
        """Hit the homepage first so the session picks up baseline cookies and
        the search looks like in-site navigation rather than a cold deep-link.

        Note: StreetEasy's bot wall (PerimeterX) sets its real token via
        JavaScript, which a plain HTTP client can't run — so this helps with
        the easy checks but won't defeat a hard datacenter-IP block.
        """
        try:
            self.session.get('https://streeteasy.com/', timeout=15)
            time.sleep(random.uniform(0.8, 2.0))
        except Exception:
            pass

    def _get_with_retry(self, url, attempts: int = 4):
        """GET ``url`` with a warm-up and exponential backoff, rotating the
        browser identity on each retry. Retries only on block-like statuses
        (403 / 429 / 503); returns immediately on anything else."""
        response = None
        for i in range(attempts):
            # Fresh identity per attempt (keeps UA + client hints consistent).
            self.session.headers.update(Config().get_headers())
            self._warm_up()

            response = self.session.get(url, timeout=20)
            if response.status_code == 200:
                if i:
                    print(f'{get_datetime()} Search succeeded on attempt {i + 1}.')
                return response
            if response.status_code not in (403, 429, 503):
                return response  # a different error — don't hammer the server

            if i < attempts - 1:
                wait = 2 ** i + random.uniform(0, 1.5)
                print(
                    f'{get_datetime()} HTTP {response.status_code} on attempt '
                    f'{i + 1}/{attempts} — retrying in {wait:.1f}s.'
                )
                time.sleep(wait)
        return response


class Parser:
    """Parses StreetEasy search-results markup.

    StreetEasy's results page is a Next.js app. The authoritative per-listing
    data lives in the React Server Components ("Flight") payload inside
    ``self.__next_f.push([...])`` script tags, NOT in hand-written CSS classes
    (which are build-hashed and change on every redesign). We parse that JSON
    first and fall back to the rendered ``data-testid="listing-card"`` DOM only
    if the payload shape changes.
    """

    price_pattern = re.compile(r'[$,]')

    # Keys that uniquely identify a *listing* object inside the Flight payload
    _required_keys = ('urlPath', 'price', 'bedroomCount')

    def __init__(self, content, db) -> None:
        self.soup = BeautifulSoup(content, 'html.parser')
        self.html = (
            content.decode('utf-8', errors='ignore')
            if isinstance(content, (bytes, bytearray))
            else content
        )
        self.existing_ids = db.get_existing_ids()
        self.card_count = 0          # raw listings parsed, before dedup/filter
        self._listings = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def listings(self) -> list[dict]:
        if self._listings is None:
            parsed = self._listings_from_flight()
            source = 'flight-json'
            if not parsed:
                parsed = self._listings_from_dom()
                source = 'dom-fallback'
            self.card_count = len(parsed)
            print(f'Listings parsed: {self.card_count} (source: {source})')
            self._listings = [card for card in parsed if self.filter(card)]
        return self._listings

    def filter(self, target) -> bool:
        if target['listing_id'] in self.existing_ids:
            return False
        for key, substrings in Config.filters.items():
            target_value = target.get(key, '') or ''
            if any(substring in target_value for substring in substrings):
                return False
        return True

    # ------------------------------------------------------------------ #
    # Primary path: Next.js Flight JSON payload
    # ------------------------------------------------------------------ #
    def _listings_from_flight(self) -> list[dict]:
        flight = self._flight_text()
        if not flight:
            return []

        out, seen = [], set()
        for data in self._objects_with_keys(flight, '"urlPath"', self._required_keys):
            path = data.get('urlPath')
            if not path or path in seen:
                continue
            # Skip building-level / non-listing rows that slipped through
            if not isinstance(data.get('price'), (int, float)):
                continue
            seen.add(path)

            url = path if path.startswith('http') else f'https://streeteasy.com{path}'
            beds_n = data.get('bedroomCount')
            beds = 'Studio' if beds_n in (0, '0') else str(beds_n)
            baths_n = data.get('fullBathroomCount')
            baths = str(baths_n) if baths_n is not None else 'N/A'

            street = (data.get('street') or '').strip()
            unit = (data.get('displayUnit') or data.get('unit') or '').strip()
            address = f'{street} {unit}'.strip() if street else (unit or 'N/A')

            out.append(
                {
                    'listing_id': path,                      # unique per unit
                    'url': url,
                    'price': str(data.get('price')),
                    'address': address,
                    'street': street or address,             # without the unit #
                    'unit': unit,
                    'neighborhood': data.get('areaName') or 'N/A',
                    'beds': beds,
                    'baths': baths,
                }
            )
        return out

    def _flight_text(self) -> str:
        """Concatenate the decoded string chunks from every
        ``self.__next_f.push([...])`` script tag."""
        chunks = []
        for script in self.soup.find_all('script'):
            txt = script.string or script.get_text() or ''
            if '__next_f.push' not in txt:
                continue
            m = re.search(r'__next_f\.push\((\[.*\])\)', txt, re.DOTALL)
            if not m:
                continue
            try:
                arr = json.loads(m.group(1))   # e.g. [1, "<flight row text>"]
            except (json.JSONDecodeError, ValueError):
                continue
            for el in arr:
                if isinstance(el, str):
                    chunks.append(el)
        return ''.join(chunks)

    def _objects_with_keys(self, text, anchor, required):
        """Yield parsed JSON objects that contain ``anchor`` and all
        ``required`` keys, found by brace-matching outward from each anchor."""
        for m in re.finditer(re.escape(anchor), text):
            idx = m.start()
            # Candidate opening braces before the anchor, nearest first
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
                    break  # smallest enclosing object that qualifies

    @staticmethod
    def _balanced_object(text, start):
        """Return the brace-balanced JSON object substring beginning at
        ``start``, respecting string literals/escapes. None if unbalanced."""
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

    # ------------------------------------------------------------------ #
    # Fallback path: rendered DOM cards
    # ------------------------------------------------------------------ #
    def _listings_from_dom(self) -> list[dict]:
        out, seen = [], set()
        cards = self.soup.select('[data-testid="listing-card"]')
        for card in cards:
            link = card.select_one(
                'a[class*="addressTextAction"], a[href*="/building/"], a[href*="/rental/"]'
            )
            if not link or not link.get('href'):
                continue
            href = link['href']
            url = href if href.startswith('http') else f'https://streeteasy.com{href}'
            path = re.sub(r'^https?://[^/]+', '', url)
            if path in seen:
                continue
            seen.add(path)

            price_el = card.select_one('[class*="PriceInfo-module__price"], [class*="price"]')
            price = (
                self.price_pattern.sub('', price_el.get_text(strip=True))
                if price_el else 'N/A'
            )
            title_el = card.select_one('[class*="ListingDescription-module__title"]')
            neighborhood = (
                title_el.get_text(strip=True).split(' in ')[-1].strip()
                if title_el else 'N/A'
            )
            address = link.get_text(' ', strip=True) or 'N/A'

            beds = baths = 'N/A'
            bb = card.select_one('[class*="BedsBathsSqft"]')
            if bb:
                t = bb.get_text(' ', strip=True).lower()
                bm = re.search(r'(\d+)\s*bed|studio', t)
                am = re.search(r'(\d+)\s*bath', t)
                if bm:
                    beds = 'Studio' if 'studio' in t else bm.group(1)
                if am:
                    baths = am.group(1)

            out.append(
                {
                    'listing_id': path,
                    'url': url,
                    'price': price,
                    'address': address,
                    'street': address,   # unit not separable from rendered DOM
                    'unit': '',
                    'neighborhood': neighborhood,
                    'beds': beds,
                    'baths': baths,
                }
            )
        return out
