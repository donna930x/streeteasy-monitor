# Run the monitor locally on your Mac (every 20 min)

StreetEasy blocks GitHub's datacenter IPs (403), but your Mac's home IP works.
This runs the monitor on a schedule via a macOS **LaunchAgent** — every 20
minutes while your Mac is awake, and once on wake if it was asleep at a
scheduled time.

> Tradeoff: nothing runs while the Mac is fully **asleep or powered off**. On a
> laptop that's closed overnight, expect a gap until you reopen it. That's
> usually fine for a rental search.

## 1. Create your `.env`

```bash
cd ~/Documents/streeteasy-monitor
cp .env.example .env
open -e .env            # fill in your real values, then save
```

Fill in: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (a Gmail **App Password**),
`ALERT_TO_EMAIL`, `SHEETS_WEBHOOK_URL`, `SHEETS_WEBHOOK_SECRET`, `SHEET_URL`.
Leave `SCRAPER_PROXY_URL` empty — no proxy is needed locally.

## 2. Test it once by hand

```bash
cd ~/Documents/streeteasy-monitor
python3 main.py
```

You want to see listings parsed (HTTP 200), then the sheet fill in and a summary
email arrive. If you get a 403 here too, your IP is being challenged — wait a bit
and retry, or open the search URL in a browser once to clear it.

## 3. Install the scheduler

```bash
cd ~/Documents/streeteasy-monitor
bash cron/install_launchd.sh
```

This installs `~/Library/LaunchAgents/com.donnya.streeteasy-monitor.plist`,
loads it, and runs once immediately. Check the log:

```bash
tail -n 40 cron/launchd.log
```

It will now run every 20 minutes automatically.

## Managing it

- **Stop / remove:** `bash cron/uninstall_launchd.sh`
- **See if it's loaded:** `launchctl list | grep streeteasy`
- **Change the interval:** edit `StartInterval` (seconds) in
  `cron/install_launchd.sh`, then re-run the install script.
- **Logs:** `cron/launchd.log` (StreetEasy responses, counts, errors).

## If a run does nothing / errors in the log

- `Missing one or more required env vars` → your `.env` is incomplete or wasn't
  found. Confirm it's at the repo root and you ran the agent from there.
- `python3: command not found` in the log → install Python (e.g. `brew install
  python`) and re-run `cron/install_launchd.sh` so it picks up the path.

## Note on the cloud workflow

The GitHub Actions **schedule is now disabled** (it only 403'd). You can still
trigger it manually from the Actions tab, and it'll work again automatically if
you ever set a working `SCRAPER_PROXY_URL` secret and re-enable the schedule in
`.github/workflows/monitor.yml`.
