import requests

from src.streeteasymonitor.search import Search
from src.streeteasymonitor.database import Database
from src.streeteasymonitor.emailer import Emailer
from src.streeteasymonitor.detail_fetcher import DetailFetcher
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
        self.search = Search(self)
        listings = self.search.fetch()

        if listings:
            fetcher = DetailFetcher(self.session)
            enriched = [fetcher.fetch(listing) for listing in listings]
            emailer = Emailer(self, enriched)
            emailer.send_alerts()
