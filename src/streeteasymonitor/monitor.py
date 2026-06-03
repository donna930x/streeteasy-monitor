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

        # 2. Enrich each new listing with detail-page data
        #    (contact, phone, days on market, date available).
        fetcher = DetailFetcher(self.session)
        enriched = [fetcher.fetch(listing) for listing in listings]

        # 3. Push to the Google Sheet. The Apps Script de-dupes by listing_id
        #    and is the authority for what counts as "new", returning the count
        #    actually appended.
        added = SheetsWriter().push(enriched)

        # 4. Keep the local DB in sync so it stays an accurate pre-filter.
        for listing in enriched:
            self.db.insert_new_listing(listing)

        # 5. One summary email — only if rows were actually added to the sheet.
        if added > 0:
            Emailer(self).send_summary(added)
