#!/usr/bin/env python3
"""Fetch live Masters leaderboard from BBC and show entrant standings.

Usage:
    python3 live.py              # print grid to stdout
    python3 live.py --image      # also save standings.png
    python3 live.py --airdrop    # save image and open in Finder + AirDrop window
    python3 live.py --site       # write _site/index.html + _site/standings.png
"""
import re, json, urllib.request, sys, subprocess, os, shutil, html as html_mod
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# entrants.json name → BBC leaderboard fullName
BBC_ALIASES = {
    "Min Woo Lee": "Min-Woo Lee",
    "Si Woo Kim": "Si-Woo Kim",
    "Nicolai Hojgaard": "Nicolai Hoejgaard",
    "Rasmus Hojgaard": "Rasmus Hoejgaard",
    "Ludvig Aberg": "Ludvig Aaberg",
    "Matt Fitzpatrick": "Matthew Fitzpatrick",
}

BBC_URL = "https://www.bbc.com/sport/golf/leaderboard"
ENTRANTS_PATH = "entrants.json"
SITE_URL = "https://chillok.github.io/masters-tracker"
BANNER_SRC = "banner.jpg"
HISTORY_FILENAME = "history.json"
HISTORY_WINDOW_MIN = 90       # trim snapshots older than this
DELTA_TARGET_AGE_MIN = 30     # preferred age of reference snapshot for rank-delta arrow
DELTA_MAX_AGE_MIN = 90        # ignore snapshots older than this when picking a reference
DUBLIN = ZoneInfo("Europe/Dublin")


def fetch_leaderboard():
    req = urllib.request.Request(BBC_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        html = r.read().decode()
    m = re.search(r'window\.__INITIAL_DATA__="(.+?)";</script>', html, re.DOTALL)
    if not m:
        sys.exit("Could not find __INITIAL_DATA__ in BBC HTML")
    data = json.loads(json.loads('"' + m.group(1) + '"'))
    lb_key = next(k for k in data["data"] if "golf-leaderboard" in k)
    return data["data"][lb_key]["data"]["leaderboard"]


def find_participants(obj, depth=0):
    if depth > 8:
        return None
    if isinstance(obj, dict):
        if "participants" in obj and isinstance(obj["participants"], list):
            return obj["participants"]
        for v in obj.values():
            r = find_participants(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = find_participants(item, depth + 1)
            if r:
                return r
    return None


def score_val(s):
    """Parse BBC totalScore.value into an int relative to par (None if cut/WD)."""
    s = s.strip()
    if s in ("E", "Even", "EVEN"):
        return 0
    if s.upper() in ("CUT", "WD", "DQ", "MC"):
        return None
    if s in ("-", ""):
        return 0  # not yet teed off
    try:
        return int(s.replace("+", ""))
    except ValueError:
        return None


def thru_display(s):
    s = s.strip()
    if ":" in s:
        return f"tee {s}"
    if s in ("-", ""):
        return "—"
    return f"thru {s}"


def fmt_total(t):
    return "E" if t == 0 else f"{t:+d}"


def fmt_pick(pick_name, raw, thru):
    """Render a single pick as 'Name raw(thru)'."""
    return f"{pick_name} {raw} ({thru_display(thru)})"


def render_grid(rows):
    """Render rows as a fixed-width grid with box-drawing characters."""
    headers = ["#", "Entrant", "Total", "Player 1", "Player 2", "Player 3"]
    body = []
    for i, (name, scores, total) in enumerate(rows, 1):
        picks = [fmt_pick(p, raw, thru) for p, _, thru, raw in scores]
        body.append([str(i), name, fmt_total(total), picks[0], picks[1], picks[2]])

    widths = [max(len(r[c]) for r in [headers] + body) for c in range(len(headers))]

    def sep(l, m, r):
        return l + m.join("─" * (w + 2) for w in widths) + r

    def row(cells, aligns):
        parts = []
        for cell, w, a in zip(cells, widths, aligns):
            if a == ">":
                parts.append(f" {cell:>{w}} ")
            else:
                parts.append(f" {cell:<{w}} ")
        return "│" + "│".join(parts) + "│"

    aligns = [">", "<", ">", "<", "<", "<"]
    lines = [
        sep("┌", "┬", "┐"),
        row(headers, ["<"] * len(headers)),
        sep("├", "┼", "┤"),
    ]
    lines.extend(row(r, aligns) for r in body)
    lines.append(sep("└", "┴", "┘"))
    return "\n".join(lines)


def render_png(rows, out_path):
    """Render the standings as a PNG using PIL."""
    from PIL import Image, ImageDraw, ImageFont

    # Try to get a nice monospace font
    font_paths = [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
    ]
    font = None
    bold = None
    for p in font_paths:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, 20)
                bold = ImageFont.truetype(p, 22)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()
        bold = font

    headers = ["#", "Entrant", "Total", "Player 1", "Player 2", "Player 3"]
    body = []
    for i, (name, scores, total) in enumerate(rows, 1):
        picks = [fmt_pick(p, raw, thru) for p, _, thru, raw in scores]
        body.append([str(i), name, fmt_total(total), picks[0], picks[1], picks[2]])

    def text_w(s, f):
        bbox = f.getbbox(s)
        return bbox[2] - bbox[0]

    # Column widths in pixels
    col_widths = []
    for c in range(len(headers)):
        w = max([text_w(headers[c], bold)] + [text_w(r[c], font) for r in body])
        col_widths.append(w + 24)  # padding

    row_h = 32
    title_h = 50
    header_h = 40
    pad = 20
    total_w = sum(col_widths) + pad * 2
    total_h = title_h + header_h + row_h * len(body) + pad * 2

    img = Image.new("RGB", (total_w, total_h), "#f5f1e8")  # Masters cream
    draw = ImageDraw.Draw(img)

    GREEN = "#006747"   # Masters green
    DARK = "#1a1a1a"
    ALT = "#eae4d3"     # alt row shading
    BORDER = "#c8c0a8"

    # Title
    title = "LIVE STANDINGS — The Masters"
    draw.text((pad, pad), title, fill=GREEN, font=bold)

    # Header row
    y = pad + title_h
    x = pad
    draw.rectangle((pad, y, pad + sum(col_widths), y + header_h), fill=GREEN)
    for c, h in enumerate(headers):
        draw.text((x + 12, y + 8), h, fill="white", font=bold)
        x += col_widths[c]

    # Body rows
    y += header_h
    for ridx, r in enumerate(body):
        if ridx % 2 == 1:
            draw.rectangle(
                (pad, y, pad + sum(col_widths), y + row_h), fill=ALT
            )
        x = pad
        for c, cell in enumerate(r):
            color = DARK
            if c == 0 and ridx == 0:
                color = GREEN  # highlight leader
            draw.text((x + 12, y + 6), cell, fill=color, font=font)
            x += col_widths[c]
        draw.line((pad, y + row_h, pad + sum(col_widths), y + row_h), fill=BORDER)
        y += row_h

    img.save(out_path)
    return out_path


def compute_ranks(rows):
    """Competition ranks based on total: ties share a rank (1, 2, 2, 4)."""
    ranks = {}
    current_rank = 0
    sentinel = object()
    prev_total = sentinel
    for i, (name, _scores, total) in enumerate(rows, 1):
        if total != prev_total:
            current_rank = i
            prev_total = total
        ranks[name] = current_rank
    return ranks


def _parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_history():
    """Return previous snapshots list.

    Prefers a local _site/history.json (dev), otherwise fetches the previously
    deployed history.json from the live site so state survives across CI runs.
    """
    local = os.path.join("_site", HISTORY_FILENAME)
    if os.path.exists(local):
        try:
            with open(local) as f:
                return json.load(f).get("snapshots", [])
        except (json.JSONDecodeError, OSError):
            pass
    try:
        req = urllib.request.Request(
            f"{SITE_URL}/{HISTORY_FILENAME}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get("snapshots", [])
    except Exception:
        return []


def compute_deltas(history, current_ranks, now):
    """Return {entrant_name: 'up'|'down'|None} comparing to a reference snapshot.

    The reference is the snapshot whose age is closest to DELTA_TARGET_AGE_MIN,
    ignoring anything older than DELTA_MAX_AGE_MIN. With a 15-min CI cadence the
    second run already has a ~15-min-old reference, so arrows appear quickly.
    """
    usable = []
    for snap in history:
        try:
            age_min = (now - _parse_iso(snap["ts"])).total_seconds() / 60
        except (KeyError, ValueError):
            continue
        if age_min <= 0 or age_min > DELTA_MAX_AGE_MIN:
            continue
        usable.append((age_min, snap))
    if not usable:
        return {name: None for name in current_ranks}
    _, ref = min(usable, key=lambda c: abs(c[0] - DELTA_TARGET_AGE_MIN))
    prev_ranks = ref.get("ranks", {})
    deltas = {}
    for name, rank in current_ranks.items():
        prev = prev_ranks.get(name)
        if prev is None or prev == rank:
            deltas[name] = None
        elif prev > rank:
            deltas[name] = "up"
        else:
            deltas[name] = "down"
    return deltas


def save_history(history, current_ranks, now, out_path):
    """Append the current snapshot, trim old ones, write to out_path."""
    cutoff = now.timestamp() - HISTORY_WINDOW_MIN * 60
    trimmed = []
    for snap in history:
        try:
            if _parse_iso(snap["ts"]).timestamp() >= cutoff:
                trimmed.append(snap)
        except (KeyError, ValueError):
            continue
    trimmed.append({
        "ts": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ranks": current_ranks,
    })
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"snapshots": trimmed}, f, indent=2)


def is_pending(thru):
    """True if the player hasn't teed off yet (tee time or unknown)."""
    t = (thru or "").strip()
    return ":" in t or t in ("-", "")


def render_html(rows, out_path, updated_at, deltas):
    """Render the standings as a self-contained HTML page."""
    esc = html_mod.escape

    header_cells = ["#", "Entrant", "Players"]
    thead = "".join(f"<th>{esc(h)}</th>" for h in header_cells)

    ranks = compute_ranks(rows)
    tbody_rows = []
    for name, scores, total in rows:
        rank = ranks[name]
        cls = ' class="leader"' if rank == 1 else ""

        delta = deltas.get(name)
        if delta == "up":
            arrow = ' <span class="arrow up">⬆</span>'
        elif delta == "down":
            arrow = ' <span class="arrow down">⬇</span>'
        else:
            arrow = ""

        player_lines = []
        for p, _score, thru, raw in scores:
            pcls = "player pending" if is_pending(thru) else "player"
            main = f"{p} {raw}"
            sub = thru_display(thru)
            player_lines.append(
                f'<div class="{pcls}">'
                f'<div class="player-main">{esc(main)}</div>'
                f'<div class="player-sub">{esc(sub)}</div>'
                f"</div>"
            )
        players_html = "".join(player_lines)

        entrant_cell = (
            f'<td class="entrant">'
            f'<div class="entrant-name">{esc(name)}</div>'
            f'<div class="score-badge">{esc(fmt_total(total))}</div>'
            f"</td>"
        )

        cells = [
            f'<td class="num">{rank}{arrow}</td>',
            entrant_cell,
            f'<td class="players">{players_html}</td>',
        ]
        tbody_rows.append(f"<tr{cls}>{''.join(cells)}</tr>")
    tbody = "\n".join(tbody_rows)

    updated_str = updated_at.astimezone(DUBLIN).strftime("%Y-%m-%d %H:%M %Z")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>The Guinness Storehouse — Live Standings</title>
<style>
  :root {{
    --green:  #006747;
    --cream:  #f5f1e8;
    --alt:    #eae4d3;
    --border: #c8c0a8;
    --dark:   #1a1a1a;
    --muted:  #6b6550;
    --faded:  #a8a08a;
    --up:     #2e7d32;
    --down:   #c62828;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 2rem 1rem;
    background: var(--cream);
    color: var(--dark);
    font-family: Menlo, Monaco, "SF Mono", Consolas, monospace;
    font-size: 15px;
  }}
  main {{
    max-width: 1100px;
    margin: 0 auto;
  }}
  .header {{
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: .75rem;
    margin-bottom: 1.5rem;
  }}
  .banner {{
    width: 180px;
    height: 180px;
    border-radius: 50%;
    object-fit: cover;
    border: 4px solid var(--green);
    box-shadow: 0 2px 6px rgba(0,0,0,.15);
  }}
  h1 {{
    color: var(--green);
    margin: 0 0 .25rem;
    font-size: 1.4rem;
    letter-spacing: .02em;
    line-height: 1.2;
  }}
  .meta {{
    color: var(--muted);
    font-size: .85rem;
  }}
  .table-wrap {{
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--cream);
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
  }}
  thead th {{
    background: var(--green);
    color: white;
    text-align: left;
    padding: .7rem .9rem;
    font-weight: 600;
    letter-spacing: .02em;
    white-space: nowrap;
  }}
  tbody td {{
    padding: .6rem .9rem;
    border-top: 1px solid var(--border);
    vertical-align: top;
  }}
  tbody tr:nth-child(even) td {{ background: var(--alt); }}
  tbody tr.leader td.num,
  tbody tr.leader td.entrant .entrant-name {{ font-weight: 700; color: var(--green); }}
  td.num {{ text-align: right; white-space: nowrap; }}
  td.entrant {{ white-space: nowrap; }}
  td.entrant .entrant-name {{ line-height: 1.3; }}
  .score-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 2.6em;
    height: 2.2em;
    padding: 0 .6em;
    margin-top: .4rem;
    border-radius: 1.1em;
    background: var(--green);
    color: white;
    font-weight: 700;
    font-size: .9em;
    letter-spacing: .02em;
  }}
  td.players .player {{
    display: block;
    line-height: 1.3;
    margin: 0 0 .45rem;
  }}
  td.players .player:last-child {{ margin-bottom: 0; }}
  td.players .player-main {{ white-space: nowrap; }}
  td.players .player-sub {{
    font-size: .72em;
    color: var(--muted);
    line-height: 1.2;
    margin-top: .05rem;
    white-space: nowrap;
  }}
  td.players .player.pending .player-main {{ color: var(--faded); }}
  td.players .player.pending .player-sub {{ color: var(--faded); }}
  .arrow {{ font-size: .9em; }}
  .arrow.up   {{ color: var(--up); }}
  .arrow.down {{ color: var(--down); }}
  footer {{
    margin-top: 1.5rem;
    font-size: .78rem;
    color: var(--muted);
  }}
  @media (max-width: 640px) {{
    body {{ padding: 1rem .5rem; font-size: 14px; }}
    h1 {{ font-size: 1.1rem; }}
    .banner {{ width: 140px; height: 140px; border-width: 3px; }}
    thead th, tbody td {{ padding: .5rem .55rem; }}
    td.players .player-main,
    td.players .player-sub {{ white-space: normal; }}
  }}
</style>
</head>
<body>
<main>
  <div class="header">
    <img class="banner" src="banner.jpg" alt="">
    <h1>The Guinness Storehouse LIVE STANDINGS</h1>
    <div class="meta">Updated {esc(updated_str)} · auto-refreshes every 15 min</div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>{thead}</tr></thead>
      <tbody>
{tbody}
      </tbody>
    </table>
  </div>
  <footer>Lowest combined total wins. Scores relative to par. ⬆ / ⬇ marks rank change over the last ~30 min. Faded players have not yet teed off.</footer>
</main>
</body>
</html>
"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(page)
    return out_path


def airdrop(image_path):
    """Open Finder AirDrop window and reveal the file so it can be dragged."""
    abs_path = os.path.abspath(image_path)
    script = f'''
    tell application "Finder"
        activate
        reveal POSIX file "{abs_path}" as alias
    end tell
    delay 0.3
    tell application "Finder" to activate
    tell application "System Events"
        keystroke "r" using {{command down, shift down}}
    end tell
    '''
    subprocess.run(["osascript", "-e", script], check=False)
    print(f"\nOpened AirDrop in Finder and revealed {abs_path}")
    print("Drag the file from the Finder window onto the recipient in AirDrop.")


def main():
    save_image = "--image" in sys.argv or "--airdrop" in sys.argv
    do_airdrop = "--airdrop" in sys.argv
    build_site = "--site" in sys.argv

    participants = find_participants(fetch_leaderboard())
    players = {
        p["name"]["fullName"]: {
            "total": score_val(p["totalScore"]["value"]),
            "raw_total": p["totalScore"]["value"],
            "thru": p["thru"]["value"],
        }
        for p in participants
    }

    with open(ENTRANTS_PATH) as f:
        edata = json.load(f)
    all_entrants = edata["entrants"] + edata.get("unknown_entrants", [])

    rows = []
    for e in all_entrants:
        scores = []
        for pick in e["players"]:
            name = pick["name"]
            rec = players.get(BBC_ALIASES.get(name, name))
            if rec is None:
                scores.append((name, None, None, "?"))
            else:
                scores.append((name, rec["total"], rec["thru"], rec["raw_total"]))
        total = sum(s[1] for s in scores if s[1] is not None)
        rows.append((e["name"], scores, total))

    rows.sort(key=lambda r: r[2])

    print("LIVE STANDINGS — The Masters (lower = better)")
    print(render_grid(rows))

    if save_image:
        out = render_png(rows, "standings.png")
        print(f"\nSaved {out}")
        if do_airdrop:
            airdrop(out)

    if build_site:
        os.makedirs("_site", exist_ok=True)
        now = datetime.now(timezone.utc)

        ranks = compute_ranks(rows)
        history = load_history()
        deltas = compute_deltas(history, ranks, now)

        render_png(rows, "_site/standings.png")
        render_html(rows, "_site/index.html", now, deltas)
        save_history(history, ranks, now, os.path.join("_site", HISTORY_FILENAME))

        if os.path.exists(BANNER_SRC):
            shutil.copy(BANNER_SRC, os.path.join("_site", BANNER_SRC))
        else:
            print(f"Warning: {BANNER_SRC} not found; site banner will be missing")

        print("\nWrote _site/index.html, _site/standings.png, _site/history.json, _site/banner.jpg")


if __name__ == "__main__":
    main()
