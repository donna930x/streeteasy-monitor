"""
Fetches additional listing details (beds, baths, days listed, date available)
from an individual StreetEasy listing page.

Falls back to 'N/A' for any field that can't be parsed so a scraping failure
never blocks the email from sending.
"""

import re
import json
from bs4 import BeautifulSoup


class DetailFetcher:
    # Patterns for embedded JSON data StreetEasy inlines in the page
    _json_pattern = re.compile(r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});</script>', re.DOTALL)
    _next_pattern = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.DOTALL)

    def __init__(self, session):
        self.session = session

    def fetch(self, listing: dict) -> dict:
        """Return listing dict enriched with beds, baths, days_listed, date_available."""
        url = listing.get('url', '')
        if not url.startswith('http'):
            url = f'https://streeteasy.com{url}'

        enriched = {**listing, 'beds': 'N/A', 'baths': 'N/A',
                    'days_listed': 'N/A', 'date_available': 'N/A', 'detail_url': url}

        try:
            r = self.session.get(url, timeout=10)
            if r.status_code != 200:
                return enriched
            enriched.update(self._parse(r.content, url))
        except Exception:
            pass

        return enriched

    def _parse(self, content: bytes, url: str) -> dict:
        result = {}
        soup = BeautifulSoup(content, 'html.parser')

        # --- Try JSON blobs first (most reliable) ---
        for pattern in (self._next_pattern, self._json_pattern):
            match = pattern.search(content.decode('utf-8', errors='ignore'))
            if match:
                try:
                    data = json.loads(match.group(1))
                    extracted = self._extract_from_json(data)
                    if extracted:
                        result.update(extracted)
                        break
                except (json.JSONDecodeError, KeyError):
                    pass

        # --- Fall back to HTML scraping ---
        if 'beds' not in result:
            result.update(self._extract_from_html(soup))

        return result

    def _extract_from_json(self, data: dict) -> dict:
        """Walk common StreetEasy JSON shapes to find listing details."""
        result = {}

        # Flatten nested props from Next.js __NEXT_DATA__
        listing_data = (
            data.get('props', {})
                .get('pageProps', {})
                .get('listing', {})
            or data.get('props', {})
                   .get('pageProps', {})
                   .get('rentalListing', {})
            or data.get('listing', {})
        )

        if not listing_data:
            return result

        # beds / baths
        beds = listing_data.get('beds') or listing_data.get('bedrooms')
        baths = listing_data.get('baths') or listing_data.get('bathrooms')
        if beds is not None:
            result['beds'] = str(beds) if beds != 0 else 'Studio'
        if baths is not None:
            result['baths'] = str(baths)

        # days listed
        days = listing_data.get('daysOnMarket') or listing_data.get('days_on_market')
        if days is not None:
            result['days_listed'] = str(days)

        # date available
        avail = (listing_data.get('availableOn')
                 or listing_data.get('available_on')
                 or listing_data.get('dateAvailable'))
        if avail:
            result['date_available'] = str(avail)

        return result

    def _extract_from_html(self, soup: BeautifulSoup) -> dict:
        """Parse the rendered HTML as a fallback."""
        result = {}

        # Beds / baths — StreetEasy renders these in a detail summary block
        detail_items = soup.select('ul.DetailsSummary-item, li.DetailsSummary-item, '
                                   'span[data-testid="beds"], span[data-testid="baths"]')
        for item in detail_items:
            text = item.get_text(separator=' ', strip=True).lower()
            bed_match = re.search(r'(\d+)\s*bed', text)
            bath_match = re.search(r'(\d+)\s*bath', text)
            if bed_match:
                result['beds'] = bed_match.group(1)
            if bath_match:
                result['baths'] = bath_match.group(1)

        # Studio check
        page_text = soup.get_text()
        if 'beds' not in result:
            if re.search(r'\bstudio\b', page_text, re.IGNORECASE):
                result['beds'] = 'Studio'

        # Days listed — look for "X days on StreetEasy" pattern
        days_match = re.search(r'(\d+)\s+day[s]?\s+on\s+StreetEasy', page_text, re.IGNORECASE)
        if days_match:
            result['days_listed'] = days_match.group(1)
        elif re.search(r'listed\s+today', page_text, re.IGNORECASE):
            result['days_listed'] = '0'

        # Date available
        avail_match = re.search(
            r'available\s+(?:on\s+)?([A-Z][a-z]+\.?\s+\d{1,2}(?:,\s*\d{4})?)',
            page_text, re.IGNORECASE
        )
        if avail_match:
            result['date_available'] = avail_match.group(1).strip()
        elif re.search(r'available\s+(?:now|immediately)', page_text, re.IGNORECASE):
            result['date_available'] = 'Now'

        return result
