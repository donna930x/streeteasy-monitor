from environs import Env
from fake_useragent import UserAgent


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

    def __init__(self):
        self.env = Env()
        self.env.read_env()

    def get_headers(self):
        ua = UserAgent()
        user_agent = ua.random or (
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        )
        return {
            'user-agent': user_agent,
            'accept-language': 'en-US,en;q=0.9',
            'referer': 'https://streeteasy.com/',
            'cache-control': 'no-cache',
            'content-type': 'application/json',
            'origin': 'https://streeteasy.com',
        }
