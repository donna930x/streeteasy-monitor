import json
import re

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
        self.r = self.session.get(self.url)
        if self.r.status_code == 200:
            parser = Parser(self.r.content, self.db)
            self.listings = parser.listings

        if not self.listings:
            print(f'{get_datetime()} No new listings.\n')

        return self.listings


class Parser:
    price_pattern = re.compile(r'[$,]')

    def __init__(self, content: bytes, db) -> None:
        self.soup = BeautifulSoup(content, 'html.parser')
        self.existing_ids = db.get_existing_ids()

    def parse(self, card) -> dict:
        listing_id = card.select_one('div.SRPCarousel-container')['data-listing-id']
        url = card.select_one('a.listingCard-globalLink')['href']
        price = Parser.price_pattern.sub('', card.select_one('span.price').text)
        address = card.select_one('address.listingCard-addressLabel').text.strip()
        neighborhood = (
            card.select_one('div.listingCardBottom--upperBlock p.listingCardLabel')
            .text.split(' in ')[-1]
            .strip()
        )

        # Beds / baths from the search card (best-effort; detail_fetcher fills gaps)
        beds = 'N/A'
        baths = 'N/A'
        details_el = card.select_one('div.listingCardBottom--lowerBlock, p.listingDetailDefinitions')
        if details_el:
            text = details_el.get_text(' ', strip=True).lower()
            bed_m = re.search(r'(\d+)\s*br|(\d+)\s*bed|studio', text)
            bath_m = re.search(r'(\d+)\s*ba|(\d+)\s*bath', text)
            if bed_m:
                beds = 'Studio' if 'studio' in text else (bed_m.group(1) or bed_m.group(2))
            if bath_m:
                baths = bath_m.group(1) or bath_m.group(2)

        return {
            'listing_id': listing_id,
            'url': url,
            'price': price,
            'address': address,
            'neighborhood': neighborhood,
            'beds': beds,
            'baths': baths,
        }

    def filter(self, target) -> bool:
        if target['listing_id'] in self.existing_ids:
            return False
        for key, substrings in Config.filters.items():
            target_value = target.get(key, '')
            if any(substring in target_value for substring in substrings):
                return False
        return True

    @property
    def listings(self) -> list[dict]:
        cards = self.soup.select('li.searchCardList--listItem')
        print(f'Cards found: {len(cards)}')  # add this
        parsed = [self.parse(card) for card in cards]
        return [card for card in parsed if self.filter(card)]
