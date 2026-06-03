# Google Sheets integration — setup

This wires the monitor to your spreadsheet
([link](https://docs.google.com/spreadsheets/d/1tdFeH60up1P5DUJciu6BGnyihHiIGZJHwJEUlxFn5Mk/edit?gid=0#gid=0)).
On each cron run it appends **only listings not already in the sheet**, one
column per data element, with a clickable link and the date it was added — then
emails you a one-line summary instead of a card per listing.

## How it works

```
Search ──▶ DetailFetcher ──▶ SheetsWriter.push() ──▶ Apps Script webhook ──▶ Sheet
  (DB pre-filter)              (POST JSON+secret)      (dedup by Listing ID,
                                                        append new rows)
                                     │
                                     └──▶ returns N added ──▶ summary email (if N>0)
```

- **The sheet is the dedup authority.** The Apps Script keys on the hidden
  `Listing ID` column and skips any ID already present, so re-runs never create
  duplicates even if the local DB is wiped.
- **The local SQLite DB is a pre-filter** — it stops the scraper from re-fetching
  detail pages for units it already knows about, which keeps runs fast.

## Sheet columns

`Date Added · Address · Neighborhood · Price · Beds · Baths · Available ·
Days on Market · Contact Name · Contact Company · Contact Phone · Listing
(clickable "View") · Listing ID`

The header row is written automatically on the first run. `Listing ID` is the
dedup key — leave it in place (you can hide the column if you don't want to see it).

## One-time setup

### 1. Deploy the Apps Script webhook

1. Open your spreadsheet → **Extensions ▸ Apps Script**.
2. Delete any boilerplate, paste the contents of **`apps_script.gs`** (repo root).
3. At the top, set `SECRET` to a long random string. Save it — you'll reuse it.
4. **Deploy ▸ New deployment ▸ Web app**:
   - *Execute as:* **Me**
   - *Who has access:* **Anyone**  ← the secret is what protects the endpoint, not Google auth
5. Authorize when prompted, then copy the **Web app URL** (ends in `/exec`).

### 2. Add the GitHub Actions secrets

The monitor already runs on a schedule via **GitHub Actions**
(`.github/workflows/monitor.yml`, every 20 min, 8am–11pm ET). The workflow now
passes three new secrets to the run — add them under
**Repo ▸ Settings ▸ Secrets and variables ▸ Actions ▸ New repository secret**:

| Secret | Value |
|---|---|
| `SHEETS_WEBHOOK_URL` | the `/exec` URL from step 1.4 |
| `SHEETS_WEBHOOK_SECRET` | the exact `SECRET` string from the script |
| `SHEET_URL` | `https://docs.google.com/spreadsheets/d/1tdFeH60up1P5DUJciu6BGnyihHiIGZJHwJEUlxFn5Mk/edit` (used as the email's button link) |

(`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `ALERT_TO_EMAIL` are already configured.)

If `SHEETS_WEBHOOK_URL`/`SECRET` are missing, the monitor still runs and just
skips the sheet sync — nothing crashes.

> Running locally instead? Export the same variables in your shell / cron env
> before `python main.py`.

### 3. Run

Nothing else to do — the next scheduled run (or a manual **Actions ▸ Run
workflow**) will append new rows and, if anything was added, send the summary
email.

## Verify

- **End to end:** trigger a run; new rows should appear with today's date and a
  clickable **View** link, and you should get one summary email.
- **Dedup:** run again immediately — `Google Sheet sync: 0 new row(s)` and **no
  email**.
- **Webhook only** (optional smoke test):

  ```bash
  curl -L -X POST "$SHEETS_WEBHOOK_URL" -H 'Content-Type: application/json' \
    -d '{"secret":"YOUR_SECRET","fields":["address","url","listing_id"],
         "listings":[{"address":"Test","url":"https://streeteasy.com/x","listing_id":"smoke-1"}]}'
  # => {"ok":true,"added":1,"total":1}   (second call: "added":0)
  ```

## What changed in the code

| File | Change |
|---|---|
| `src/streeteasymonitor/sheets_writer.py` | **new** — POSTs new listings to the webhook, returns count added; no-op if unconfigured |
| `apps_script.gs` | **new** — webhook: dedup by Listing ID, header row, `=HYPERLINK` link, Date Added; returns `{added,total}` |
| `src/streeteasymonitor/emailer.py` | rewritten — single summary email (N listings + sheet link) instead of per-listing cards |
| `src/streeteasymonitor/monitor.py` | wired: search → enrich → sheet push → DB insert → summary email |
| `src/streeteasymonitor/detail_fetcher.py` | contact split into `contact_name` / `contact_company` / `contact_phone` |
| `src/streeteasymonitor/database.py` | added `contact_name` / `contact_company` / `contact_phone` columns |

## Notes

- The monitor still **never messages brokers** — it only writes to your sheet and
  emails you. (`messager.py` remains unused dead code; say the word and I'll delete it.)
- Want this on a schedule? I can set up a recurring run for you.
