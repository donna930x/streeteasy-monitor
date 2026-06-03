import random

from environs import Env


class Config:
    # -------------------------------------------------------------------
    # Search filters — edit these to match your criteria
    # -------------------------------------------------------------------
    defaults = {
        'min_price': 0,
        'max_price': 5000,
        'min_beds': 0,
        'max_beds': 1,
        'baths': 1,
        'areas': [
            #'Carroll Gardens',
            #'Clinton Hill',
            #'Cobble Hill',
            #'Fort Greene',
            #'Gowanus',
            #'Greenpoint',
            #'Park Slope',
            #'Prospect Heights',
            'Williamsburg',
            'Chelsea',
            'Greenwich Village',
            'Tribeca',
            'West Village',
            'Hudson Square',
            'Gramercy Park'
            #'Bedford-Stuyvesant',
            #'Boerum Hill',
            #'DUMBO',
            #'Downtown Brooklyn',
            #'Brooklyn Heights',
            #'Upper East Side',
        ],
        'amenities': [
            #'pets',
            # 'doorman',
            # 'laundry',
            # 'elevator',
            # 'private_outdoor_space',
            # 'dishwasher',
            # 'washer_dryer',
            # 'gym',
        ],
        'no_fee': False,

        # --- Optional filters (remove the key or set to '' to disable) ---

        # Only show listings available on or after this date (format: 'YYYYMMDD')
        'available_after': '20260710',

        # Restrict results to a geographic bounding box instead of (or in addition to) neighborhoods.
        # Values: 'lat_min,lat_max,lng_min,lng_max'
        # Tip: use maps.google.com to find lat/lng for your target area.
        # 'in_rect': '40.711,40.751,-74.028,-73.941',

        # Square footage range (format: 'min-max', e.g. '500-1200')
        # 'sqft': '600-1500',
    }

    # -------------------------------------------------------------------
    # Post-scrape filters — listings matching these substrings are dropped
    # -------------------------------------------------------------------
    filters = {
        'url': [
            '?featured=1',
            '?infeed=1',
        ],
        'address': [
            # 'Fulton',
            # 'Atlantic',
        ],
        'neighborhood': [
            #'Ocean Hill',
            #'Flatbush',
            #'Bushwick',
            #'Weeksville',
            #'Stuyvesant Heights',
            #'New Development',
        ],
    }

    # A few *consistent* desktop-Chrome identities. The UA string, the
    # sec-ch-ua client hints, and the platform all agree — a mismatch between
    # them (e.g. a Firefox UA with a Chrome sec-ch-ua) is itself a bot tell, so
    # we keep them as matched sets and pick one per session.
    IDENTITIES = [
        {
            'ua': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/125.0.0.0 Safari/537.36'),
            'ch_ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            'platform': '"macOS"',
        },
        {
            'ua': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
            'ch_ua': '"Google Chrome";v="124", "Chromium";v="124", "Not.A/Brand";v="24"',
            'platform': '"Windows"',
        },
        {
            'ua': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/123.0.0.0 Safari/537.36'),
            'ch_ua': '"Google Chrome";v="123", "Chromium";v="123", "Not.A/Brand";v="24"',
            'platform': '"macOS"',
        },
    ]

    def __init__(self):
        self.env = Env()
        self.env.read_env()

    def get_headers(self, identity: dict | None = None) -> dict:
        """Browser-like headers for a top-level navigation GET.

        Pass a specific ``identity`` (from ``IDENTITIES``) to keep the headers
        stable across a warm-up + search; otherwise one is chosen at random.
        """
        ident = identity or random.choice(self.IDENTITIES)
        return {
            'user-agent': ident['ua'],
            'accept': (
                'text/html,application/xhtml+xml,application/xml;q=0.9,'
                'image/avif,image/webp,image/apng,*/*;q=0.8,'
                'application/signed-exchange;v=b3;q=0.7'
            ),
            'accept-language': 'en-US,en;q=0.9',
            'sec-ch-ua': ident['ch_ua'],
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': ident['platform'],
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'referer': 'https://streeteasy.com/',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
        }
