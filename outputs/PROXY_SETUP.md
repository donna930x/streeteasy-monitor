# Getting past StreetEasy's IP block (residential proxy)

## Why this is needed

StreetEasy uses PerimeterX bot protection. Requests from your Mac (a residential
IP) get through, but GitHub Actions runs from datacenter IPs that PerimeterX
blocks outright — every request returns **HTTP 403**, even with browser-like
headers and retries. A residential-proxy / scraping API routes the request
through a real residential IP (and can render JavaScript), which gets past the
block while keeping the monitor running in the cloud.

## How it works in the code

Set one environment variable, **`SCRAPER_PROXY_URL`**, to the proxy string your
provider gives you. When it's present:

- every request (search **and** listing detail pages) is routed through the proxy;
- TLS verification is disabled for the session (these services terminate TLS
  themselves, so the cert won't match `streeteasy.com`);
- the homepage warm-up is skipped (the proxy handles IP rotation/JS), and
  timeouts are extended to 70s to allow for rendering.

If `SCRAPER_PROXY_URL` is unset, nothing changes — it connects directly.

## 1. Pick a provider and get a proxy string

Any of these work; all have a free tier to start. Sign up, grab your API key,
and use the matching proxy string (replace `KEY` with your key):

| Provider | `SCRAPER_PROXY_URL` value | Notes |
|---|---|---|
| **ScraperAPI** | `http://scraperapi:KEY@proxy-server.scraperapi.com:8001` | Free tier ~1k req/mo |
| **ScrapingBee** | `http://KEY:render_js=True@proxy.scrapingbee.com:8887` | Free tier |
| **ZenRows** | `http://KEY:js_render=true@superproxy.zenrows.com:1337` | Free tier |
| **Bright Data (Web Unlocker)** | `http://brd-customer-CUSTOMER_ID-zone-UNLOCKER_ZONE:PASSWORD@brd.superproxy.io:33335` | Strongest vs PerimeterX; pay-as-you-go (trial credit, no perpetual free tier). Create a **Web Unlocker** zone; rendering/CAPTCHA is automatic. Port `33335` (old `22225` is being retired). |

Tips:
- **Start without JS rendering** if the provider lets you (cheaper, faster) — a
  residential IP alone often clears PerimeterX. If you still get 403s, switch on
  rendering: ScraperAPI add `.render=true` to the username
  (`http://scraperapi.render=true:KEY@...`), ScrapingBee/ZenRows already shown
  with rendering on above.
- Each request spends a credit, including each listing detail page. With ~1 run
  every 20 min and a handful of new listings, the free tiers (~1,000 req/mo) are
  usually enough; bump your search interval if you run low.

## 2. Add it as a GitHub secret

Repo ▸ **Settings ▸ Secrets and variables ▸ Actions ▸ New repository secret**:

- Name: `SCRAPER_PROXY_URL`
- Value: the string from the table above

The workflow already passes it to the run (`.github/workflows/monitor.yml`).

## 3. Trigger a run

**Actions ▸ StreetEasy Monitor ▸ Run workflow**, then check the log. On success
you'll see `Routing requests through SCRAPER_PROXY_URL.` followed by listings
parsed (instead of the 403). The sheet fills in and you get the summary email.

## Testing locally first (optional)

```bash
cd ~/Documents/streeteasy-monitor
export SCRAPER_PROXY_URL='http://scraperapi:KEY@proxy-server.scraperapi.com:8001'
python diag.py   # should show HTTP 200 and parsed listings
```

## If it still 403s

- Turn **on** JS rendering (see tip above).
- Confirm the key is active and you haven't exhausted the free tier.
- As a fallback, run on your Mac via the `cron/` scripts (residential IP, no
  proxy needed) — say the word and I'll set that up instead.
