import random
import time

import requests

from src.streeteasymonitor.search import Search
from src.streeteasymonitor.database import Database
from src.streeteasymonitor.emailer import Emailer
from src.streeteasymonitor.detail_fetcher import DetailFetcher
from src.streeteasymonitor.sheets_writer import SheetsWriter
from src.streeteasymonitor.config import Config


class Monitor:
    def __init__(self, **kwargs):
        self.config = Config()
        self.db = Database()

        self.session = requests.Session()
        self.session.headers.update(self.config.get_headers())

        # Optional: route everything through a residential proxy / scraping API
        # to get past StreetEasy's datacenter-IP block (set SCRAPER_PROXY_URL).
        proxies = self.config.get_proxies()
        if proxies:
            self.session.proxies.update(proxies)
            # These services terminate TLS themselves, so cert verification
            # against streeteasy.com would fail — disable it for the proxied
            # session and silence the resulting warning.
            self.session.verify = False
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
            print('Routing requests through SCRAPER_PROXY_URL.')

        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.session.close()

    def run(self):
        # 1. Search — the local DB acts as a pre-filter so we don't re-fetch
        #    detail pages for units we've already seen.
        self.search = Search(self)
        listings = self.search.fetch()
        if not listings:
            return

        # 2. Enrich each new listing with detail-page data (contact, phone, days
        #    on market, date available). A short delay between requests avoids
        #    StreetEasy throttling the detail pages mid-batch.
        fetcher = DetailFetcher(self.session)
        enriched = []
        for i, listing in enumerate(listings):
            enriched.append(fetcher.fetch(listing))
            if i < len(listings) - 1:
                time.sleep(random.uniform(0.8, 1.8))

        # 2a. Drop listings whose detail page couldn't be fetched. They are NOT
        #     recorded as seen, so they'll be retried on the next run instead of
        #     being frozen as all-N/A rows.
        ok = [l for l in enriched if l.get('detail_ok')]
        failed = len(enriched) - len(ok)
        if failed:
            print(f'{failed} listing(s) had a detail-page fetch failure — '
                  f'not recorded, will retry next run.')

        # 2b. Omit listings we don't want in the sheet:
        #     - new-dev / lease-up units (show "Leasing Starts", no days-on-market)
        #     - units on the market longer than the day limit
        #     Unknown ('N/A') day counts are kept rather than silently dropped.
        max_days = self.kwargs.get('max_days_on_market', 20)
        fresh, omitted_leasing, omitted_old = [], 0, 0
        for listing in ok:
            if listing.get('leasing'):
                omitted_leasing += 1
                continue
            raw = str(listing.get('days_listed', 'N/A'))
            if max_days is not None and raw.isdigit() and int(raw) > max_days:
                omitted_old += 1
                continue
            fresh.append(listing)
        if omitted_leasing:
            print(f'Omitting {omitted_leasing} new-dev/lease-up listing(s) '
                  f'("Leasing Starts").')
        if omitted_old:
            print(f'Omitting {omitted_old} listing(s) with more than {max_days} '
                  f'days on market.')

        # 3. Push the kept listings to the Google Sheet. The Apps Script de-dupes
        #    by listing_id and is the authority for what counts as "new",
        #    returning the count actually appended.
        added = SheetsWriter().push(fresh)

        # 4. Mark successfully-fetched listings as seen (including the omitted
        #    too-old ones) so we don't re-fetch them every run. Failed fetches are
        #    intentionally excluded above so they get another chance next time.
        for listing in ok:
            self.db.insert_new_listing(listing)

        # 5. One email — only if rows were actually added to the sheet. It lists
        #    the new listings in the body and links to the spreadsheet.
        if added > 0:
            Emailer(self).send_summary(fresh)
