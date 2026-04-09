#!/usr/bin/env python3
"""Fetch live Masters leaderboard from BBC and show entrant standings.

Usage:
    python3 live.py              # print grid to stdout
    python3 live.py --image      # also save standings.png
    python3 live.py --airdrop    # save image and open in Finder + AirDrop window
    python3 live.py --site       # write _site/index.html + _site/standings.png
"""
import re, json, urllib.request, sys, subprocess, os, html as html_mod
from datetime import datetime, timezone

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


def render_html(rows, out_path, updated_at):
    """Render the standings as a self-contained HTML page styled like the PNG."""
    esc = html_mod.escape

    header_cells = ["#", "Entrant", "Total", "Player 1", "Player 2", "Player 3"]
    thead = "".join(f"<th>{esc(h)}</th>" for h in header_cells)

    tbody_rows = []
    for i, (name, scores, total) in enumerate(rows, 1):
        picks = [fmt_pick(p, raw, thru) for p, _, thru, raw in scores]
        cls = ' class="leader"' if i == 1 else ""
        cells = [
            f"<td class=\"num\">{i}</td>",
            f"<td>{esc(name)}</td>",
            f"<td class=\"num total\">{esc(fmt_total(total))}</td>",
            f"<td>{esc(picks[0])}</td>",
            f"<td>{esc(picks[1])}</td>",
            f"<td>{esc(picks[2])}</td>",
        ]
        tbody_rows.append(f"<tr{cls}>{''.join(cells)}</tr>")
    tbody = "\n".join(tbody_rows)

    updated_str = updated_at.strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Masters Tracker — Live Standings</title>
<style>
  :root {{
    --green: #006747;
    --cream: #f5f1e8;
    --alt:   #eae4d3;
    --border:#c8c0a8;
    --dark:  #1a1a1a;
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
    max-width: 1400px;
    margin: 0 auto;
  }}
  h1 {{
    color: var(--green);
    margin: 0 0 .25rem;
    font-size: 1.6rem;
    letter-spacing: .02em;
  }}
  .meta {{
    color: #6b6550;
    font-size: .85rem;
    margin-bottom: 1.25rem;
  }}
  .meta a {{ color: var(--green); }}
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
    white-space: nowrap;
  }}
  thead th {{
    background: var(--green);
    color: white;
    text-align: left;
    padding: .7rem .9rem;
    font-weight: 600;
    letter-spacing: .02em;
  }}
  tbody td {{
    padding: .55rem .9rem;
    border-top: 1px solid var(--border);
  }}
  tbody tr:nth-child(even) td {{ background: var(--alt); }}
  tbody tr.leader td {{ font-weight: 700; color: var(--green); }}
  td.num {{ text-align: right; }}
  td.total {{ font-weight: 600; }}
  footer {{
    margin-top: 1.5rem;
    font-size: .8rem;
    color: #6b6550;
  }}
</style>
</head>
<body>
<main>
  <h1>LIVE STANDINGS — The Masters</h1>
  <div class="meta">
    Updated {esc(updated_str)} · auto-refreshes every 5 min ·
    source: <a href="https://www.bbc.com/sport/golf/leaderboard">BBC leaderboard</a>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>{thead}</tr></thead>
      <tbody>
{tbody}
      </tbody>
    </table>
  </div>
  <footer>Lowest combined total wins. Scores relative to par.</footer>
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
        render_png(rows, "_site/standings.png")
        render_html(rows, "_site/index.html", datetime.now(timezone.utc))
        print("\nWrote _site/index.html and _site/standings.png")


if __name__ == "__main__":
    main()
