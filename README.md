# Masters Tracker

Live standings for a Masters golf sweepstake. Each entrant picks 3 golfers
(combined odds ≥ 125/1); the entrant whose 3 players post the lowest combined
score (relative to par) wins.

**Live leaderboard:** https://chillok.github.io/masters-tracker/

The page auto-refreshes every 5 minutes and is regenerated server-side on the
same cadence. Because GitHub's own `schedule` trigger is unreliable on free
public repos, a Cloudflare Worker (`sync-worker/`) + cron-job.org ping drives
the rebuilds instead; the GitHub cron is kept as a 30-min fallback. The page
shows a "X min ago" staleness indicator that turns red past 15 min.

## Running locally

```bash
python3 live.py              # print grid to terminal
python3 live.py --image      # also save standings.png
python3 live.py --site       # write _site/index.html + _site/standings.png
```

No dependencies for terminal output; `--image` / `--site` require Pillow
(`pip install Pillow`).

## Files

- `live.py` — fetches BBC leaderboard, joins entrants, renders terminal / PNG / HTML
- `entrants.json` — entrants and their 3 picked golfers
- `masters_model.csv` — pre-tournament projection model (for reference)
- `.github/workflows/update.yml` — scheduled workflow that rebuilds the site
