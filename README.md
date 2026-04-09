# Masters Tracker

Live standings for a Masters golf sweepstake. Each entrant picks 3 golfers
(combined odds ≥ 125/1); the entrant whose 3 players post the lowest combined
score (relative to par) wins.

**Live leaderboard:** https://chillok.github.io/masters-tracker/

The page auto-refreshes every 10 minutes and is regenerated server-side on the
same cadence via GitHub Actions pulling from the BBC golf leaderboard.
Scheduled GitHub Actions runs are often delayed or skipped on free public
repos, so the page shows a "X min ago" staleness indicator (red past 20 min).

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
