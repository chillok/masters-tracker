# Masters Tracker

A small tool to track a Masters golf sweepstake/pool. Each entrant picks three golfers (with combined odds of at least 125/1), and we compute a combined score from the live BBC leaderboard to rank the entrants.

## Data sources

- **Live leaderboard**: https://www.bbc.com/sport/golf/leaderboard
  - Fetched via `curl` (works without auth/JS).
  - The page embeds JSON inside the HTML. Extract with regex on the escaped fields:
    - `\"rank\":`
    - `\"fullName\":`
    - `\"totalScore\":`
    - `\"thru\":`
- **Entrants**: `entrants.json` — each entrant's name and their three picked golfers with odds.
  - Built from screenshots in `./screenshots/` (JotForm "Thank You" confirmation pages).
  - `unknown_entrants` holds submissions where the screenshot did not include the submitter's name (user has since filled these in manually).
- **Ranking model**: `masters_model.csv` — cleaned export of "The Masters Model 2026 - Free" Google Sheet.
  - Source: https://docs.google.com/spreadsheets/d/1wGx4NzODFWoziaHM6SPpKJsKS__Xy0iGDCTM5vMY_30/edit
  - Fetchable as CSV via: `curl -sL "https://docs.google.com/spreadsheets/d/1wGx4NzODFWoziaHM6SPpKJsKS__Xy0iGDCTM5vMY_30/export?format=csv&gid=0"`
  - 91 players with Rank, Upside, Safety, DFS salaries, Ownership, and a 0–1000 Overall Model Score (Scheffler = 1000, Cabrera = 1).
  - Also includes sub-rankings for Stats (40%), Course History (30%), Recent Form (30%).

## Files

- `entrants.json` — mapping of entrants → their 3 golfers (source of truth for picks).
- `masters_model.csv` — cleaned projection/ranking model for all 91 players in the field.
- `live.py` — fetches BBC leaderboard, joins against `entrants.json`, prints live standings (run with `python3 live.py`).
- `screenshots/` — original JotForm confirmation screenshots the entrants data was extracted from.

## BBC leaderboard parsing notes

- The live data lives in `window.__INITIAL_DATA__` inside a `<script>` tag — it's a JSON string with escaped quotes. Decode by `json.loads(json.loads('"' + raw + '"'))`.
- Path to player list: `data["data"]["golf-leaderboard?urn=..."]["data"]["leaderboard"]` then walk for `participants` (list of 91 dicts).
- Each participant has `name.fullName`, `totalScore.value` (e.g. `"-2"`, `"E"`, `"+1"`, `"-"` if not started, `"CUT"` after the cut), `thru.value` (holes played as a number, OR a tee time like `"18:44"` if they haven't started).
- **Name aliases** — BBC uses slightly different spellings than our entrants. The canonical map (in `live.py` as `BBC_ALIASES`):
  - `Min Woo Lee` → `Min-Woo Lee`
  - `Si Woo Kim` → `Si-Woo Kim`
  - `Nicolai Hojgaard` → `Nicolai Hoejgaard`
  - `Rasmus Hojgaard` → `Rasmus Hoejgaard`
  - `Ludvig Aberg` → `Ludvig Aaberg`
  - `Matt Fitzpatrick` → `Matthew Fitzpatrick`

## Scoring rules

- Each entrant picks 3 golfers (combined odds must be ≥ 125/1).
- The entrant's score is the **sum of their 3 golfers' total scores** (to par) from the live Masters leaderboard.
- **Lowest combined total wins.**
- A golfer's `totalScore` comes from the BBC leaderboard JSON (relative to par).
- Handling of missed cuts / WDs: TBD (not yet specified — assume the leaderboard's final value stands for now).

## Notes for future sessions

- Player names in `entrants.json` must be matched against `fullName` from the BBC JSON; watch for diacritics (e.g. "Nicolai Højgaard" vs "Nicolai Hojgaard") and name spelling variants.
- Odds in the screenshots are informational only (not used for scoring unless rules say otherwise).
