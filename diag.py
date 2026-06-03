"""
diag.py — validate the StreetEasy scraper end-to-end against the LIVE site.

Drop this in the repo root (same folder as `src/`) and run:  python diag.py
It (1) builds the search URL from your config, (2) fetches + parses the search
results, and (3) fetches the first listing's detail page to confirm contact,
days-on-market and date-available extraction.

Run AFTER replacing search.py, config.py, detail_fetcher.py, database.py and
emailer.py with the patched versions.
"""

import os
import sys
import json

# --- make `src` importable no matter where python is invoked from ---------
_here = os.path.dirname(os.path.abspath(__file__))
for _root in (_here, os.getcwd()):
    if os.path.isdir(os.path.join(_root, 'src', 'streeteasymonitor')):
        sys.path.insert(0, _root)
        break
else:
    sys.exit("Could not find 'src/streeteasymonitor'. Put diag.py in the repo root.")

import requests
from src.streeteasymonitor.config import Config
from src.streeteasymonitor.search import Search, Parser
from src.streeteasymonitor.detail_fetcher import DetailFetcher


class _NoDB:
    def get_existing_ids(self):
        return set()


class _Monitor:
    def __init__(self):
        cfg = Config()
        self.session = requests.Session()
        self.session.headers.update(cfg.get_headers())
        self.db = _NoDB()
        self.kwargs = Config.defaults


def main():
    monitor = _Monitor()
    search = Search(monitor)

    print(f'URL: {search.url}\n')
    print('--- FETCHING SEARCH RESULTS ---')
    r = monitor.session.get(search.url)
    print(f'status   : {r.status_code}')
    print(f'bytes    : {len(r.content):,}')

    body = r.text.lower()
    blocked = any(t in body for t in (
        'press & hold', 'px-captcha', 'are you a human',
        'access to this page has been denied', 'captcha-delivery',
    ))
    print(f'blocked? : {blocked}')

    with open('debug.html', 'wb') as f:
        f.write(r.content)
    print('saved    : debug.html')

    if r.status_code != 200:
        print('\n=> Non-200 response. Likely an IP/rate-limit block.')
        return
    if blocked:
        print('\n=> Anti-bot wall. Run from a residential IP or add a proxy.')
        return

    print('\n--- PARSING SEARCH RESULTS ---')
    parser = Parser(r.content, _NoDB())
    listings = parser.listings
    print(f'new after filter : {len(listings)}')

    if not listings:
        print('\n=> 200, not blocked, but 0 listings parsed. Open debug.html to inspect.')
        return

    print('\n--- SAMPLE (first 3) ---')
    for l in listings[:3]:
        print(json.dumps(l, indent=2))

    # --- detail page: confirm contact / days / available -----------------
    print('\n--- FETCHING FIRST LISTING DETAIL PAGE ---')
    target = listings[0]
    detail_url = target['url']
    print(f'detail URL: {detail_url}')
    dr = monitor.session.get(detail_url)
    with open('detail_debug.html', 'wb') as f:
        f.write(dr.content)
    print('saved     : detail_debug.html')

    fetcher = DetailFetcher(monitor.session)
    enriched = fetcher.fetch(target)
    for field in ('address', 'price', 'beds', 'baths', 'neighborhood',
                  'date_available', 'days_listed', 'contacts', 'detail_url'):
        print(f'  {field:15}: {enriched.get(field, "N/A")}')

    # Is the phone number actually present in the page source at all?
    import re as _re
    raw = dr.text
    flight = fetcher._flight_text(fetcher_soup := __import__('bs4').BeautifulSoup(dr.content, 'html.parser'))
    tel = _re.search(r'tel:\s*\+?[\d().\-\s]{10,20}', raw)
    keyed = _re.search(r'"[A-Za-z]*[Pp]hone[A-Za-z]*"\s*:\s*"[^"]*\d{3}[^"]*\d{4}', flight)
    anydigits = _re.search(r'\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}', flight or raw)
    print('\n--- PHONE SOURCE PROBE ---')
    print(f'  tel: link in HTML      : {"yes" if tel else "no"}'
          + (f'  ->  {tel.group(0)}' if tel else ''))
    print(f'  phone-keyed Flight key : {"yes" if keyed else "no"}'
          + (f'  ->  {keyed.group(0)[:60]}' if keyed else ''))
    print(f'  any phone-like digits  : {"yes" if anydigits else "no"}')
    if not (tel or keyed):
        print('  => The number is NOT in the page source. StreetEasy only')
        print('     reveals it via an on-click API. Open detail_debug.html, click')
        print('     "Show phone number" in a browser with DevTools > Network open,')
        print('     and send me the request that returns the number — I will wire a')
        print('     read-only fetch for it (this does NOT message the broker).')

    missing = [f for f in ('date_available', 'days_listed', 'contacts')
               if enriched.get(f, 'N/A') in ('N/A', '')]
    if missing:
        print(f'\n=> Detail parsed, but these came back N/A: {missing}. '
              f'Inspect detail_debug.html.')
    else:
        print('\n=> SUCCESS: search + detail extraction both working.')


if __name__ == '__main__':
    main()
