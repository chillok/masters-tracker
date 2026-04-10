#!/usr/bin/env python3
"""Fetch live Masters leaderboard from BBC and show entrant standings.

Usage:
    python3 live.py              # print grid to stdout
    python3 live.py --image      # also save standings.png
    python3 live.py --airdrop    # save image and open in Finder + AirDrop window
    python3 live.py --site       # write _site/index.html + _site/standings.png
"""
import re, json, urllib.request, sys, subprocess, os, shutil, html as html_mod, csv, random, math
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

MODEL_PATH = "masters_model.csv"
SIM_COUNT = 100_000
ALPHA = 0.65  # weight on pre-tournament model vs R1 actual
COMMENTARY_FILENAME = "commentary.json"
COMMENTARY_MAX = 5


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


def save_history(history, current_ranks, now, out_path, current_scores=None):
    """Append the current snapshot, trim old ones, write to out_path."""
    cutoff = now.timestamp() - HISTORY_WINDOW_MIN * 60
    trimmed = []
    for snap in history:
        try:
            if _parse_iso(snap["ts"]).timestamp() >= cutoff:
                trimmed.append(snap)
        except (KeyError, ValueError):
            continue
    snap = {
        "ts": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ranks": current_ranks,
    }
    if current_scores is not None:
        snap["scores"] = current_scores
    trimmed.append(snap)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"snapshots": trimmed}, f, indent=2)


def load_commentary():
    """Load previous commentary entries from _site or deployed site."""
    local = os.path.join("_site", COMMENTARY_FILENAME)
    if os.path.exists(local):
        try:
            with open(local) as f:
                return json.load(f).get("entries", [])
        except (json.JSONDecodeError, OSError):
            pass
    try:
        req = urllib.request.Request(
            f"{SITE_URL}/{COMMENTARY_FILENAME}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get("entries", [])
    except Exception:
        return []


def save_commentary(entries, out_path):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"entries": entries[:COMMENTARY_MAX]}, f, indent=2)


def _ordinal(n):
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{({1: 'st', 2: 'nd', 3: 'rd'}).get(n % 10, 'th')}"


def generate_day1_summary(rows, ranks):
    """Build an opening summary from the current standings."""
    leader_name, leader_scores, leader_total = rows[0]
    last_total = rows[-1][2]
    spread = last_total - leader_total
    gap = rows[1][2] - leader_total if len(rows) > 1 else 0

    # Leader's best and worst pick
    valid = [(p, s) for p, s, _, _ in leader_scores if s is not None]
    leader_best = min(valid, key=lambda x: x[1]) if valid else None
    leader_worst = max(valid, key=lambda x: x[1]) if valid else None

    # Best individual golfer across all entrants
    best_golfer, best_score, best_entrant = None, 999, None
    for name, scores, _ in rows:
        for pname, score, _, _ in scores:
            if score is not None and score < best_score:
                best_golfer, best_score, best_entrant = pname, score, name

    text = f"R1 in the books. {leader_name} leads at {fmt_total(leader_total)}"
    if gap > 0:
        text += f", {gap} shot{'s' if gap != 1 else ''} clear"
    text += "."

    if leader_best:
        text += f" {leader_best[0]} ({fmt_total(leader_best[1])}) doing the heavy lifting"
        if leader_worst and leader_worst[1] > 0:
            text += (f" while {leader_worst[0]} ({fmt_total(leader_worst[1])})"
                     " takes the scenic route")
        text += "."

    if best_golfer and best_entrant != leader_name:
        r = ranks.get(best_entrant, 0)
        # Find what's holding this entrant back
        worst_pick = None
        for name, scores, _ in rows:
            if name == best_entrant:
                worst_pick = max(
                    ((p, s) for p, s, _, _ in scores if s is not None),
                    key=lambda x: x[1], default=None,
                )
                break
        text += (f" {best_golfer} ({fmt_total(best_score)}) is the best pick"
                 f" in the field but {best_entrant} sits {_ordinal(r)}")
        if worst_pick and worst_pick[1] > 0:
            text += (f" \u2014 {worst_pick[0]} ({fmt_total(worst_pick[1])})"
                     " undoing all that good work")
        text += "."

    text += f" {spread} shots separate the field. Plenty of golf left."
    return text


def generate_commentary(rows, ranks, history, now):
    """Compare current state to the most recent snapshot with scores.

    Returns a commentary string, or None if nothing meaningful changed.
    """
    prev = None
    for snap in reversed(history):
        if "scores" in snap:
            prev = snap
            break
    if not prev:
        return None

    prev_ranks = prev.get("ranks", {})
    prev_scores = prev.get("scores", {})
    current_scores = {name: total for name, _, total in rows}

    # Check if anything changed
    changed = False
    for name in ranks:
        if (ranks[name] != prev_ranks.get(name)
                or current_scores.get(name) != prev_scores.get(name)):
            changed = True
            break
    if not changed:
        return None

    leader_name, _, leader_total = rows[0]

    # New leader?
    prev_leader = None
    for name, r in prev_ranks.items():
        if r == 1:
            prev_leader = name
            break
    if prev_leader and prev_leader != leader_name:
        gap = rows[1][2] - leader_total if len(rows) > 1 else 0
        text = (f"Shakeup at the top \u2014 {leader_name} takes the lead"
                f" at {fmt_total(leader_total)}")
        if gap > 0:
            text += f", {gap} clear"
        text += f". {prev_leader} drops to {_ordinal(ranks.get(prev_leader, 0))}."
        text += " The WhatsApp group will be busy."
        return text

    # Biggest rank mover
    movers = []
    for name in ranks:
        prev_r = prev_ranks.get(name)
        if prev_r is None:
            continue
        diff = prev_r - ranks[name]  # positive = climbed
        if abs(diff) >= 2:
            prev_sc = prev_scores.get(name)
            curr_sc = current_scores.get(name)
            sc_text = ""
            if prev_sc is not None and curr_sc is not None and prev_sc != curr_sc:
                d = curr_sc - prev_sc
                if d < 0:
                    sc_text = (f" after gaining {abs(d)}"
                               f" shot{'s' if abs(d) != 1 else ''}")
                else:
                    sc_text = (f" after dropping {d}"
                               f" shot{'s' if d != 1 else ''}")
            movers.append((name, diff, ranks[name], prev_r, sc_text))

    if movers:
        movers.sort(key=lambda m: abs(m[1]), reverse=True)
        name, diff, curr_r, prev_r, sc_text = movers[0]
        if diff > 0:
            return (f"{name} on the charge \u2014 up from {_ordinal(prev_r)}"
                    f" to {_ordinal(curr_r)}{sc_text}."
                    f" The group chat will be heating up.")
        else:
            return (f"Not the update {name} wanted \u2014 slides from"
                    f" {_ordinal(prev_r)} to {_ordinal(curr_r)}{sc_text}."
                    f" Still plenty of holes to play.")

    # No big rank moves, but scores changed — report the state of play
    gap = rows[1][2] - leader_total if len(rows) > 1 else 0
    prev_leader_sc = prev_scores.get(leader_name)
    if prev_leader_sc is not None and leader_total != prev_leader_sc:
        d = leader_total - prev_leader_sc
        if d < 0:
            return (f"{leader_name} extends the advantage \u2014 now"
                    f" at {fmt_total(leader_total)}, {gap}"
                    f" shot{'s' if gap != 1 else ''} clear."
                    f" Starting to look comfortable up there.")
        else:
            return (f"{leader_name} gives back {abs(d)}"
                    f" shot{'s' if abs(d) != 1 else ''}, now"
                    f" at {fmt_total(leader_total)} ({gap}"
                    f" shot{'s' if gap != 1 else ''} clear)."
                    f" The chasing pack will sense blood.")

    return (f"{leader_name} holds firm at {fmt_total(leader_total)}"
            f", {gap} shot{'s' if gap != 1 else ''} clear."
            f" As you were.")


def _build_standings_prompt(rows, ranks, prev_ranks, prev_scores, predictions,
                            existing_commentary):
    """Build the structured data block for the AI commentary prompt."""
    current_scores = {name: total for name, _, total in rows}
    lines = []
    for name, scores, total in rows:
        golfers = ", ".join(
            f"{p} ({fmt_total(s)})" for p, s, _, _ in scores if s is not None
        )
        rank = ranks[name]
        extras = []
        pr = prev_ranks.get(name)
        if pr and pr != rank:
            extras.append(f"was {_ordinal(pr)}")
        ps = prev_scores.get(name)
        if ps is not None and ps != total:
            d = total - ps
            extras.append(f"{'gained' if d < 0 else 'dropped'} {abs(d)}")
        ex = f" ({', '.join(extras)})" if extras else ""
        lines.append(f"  {_ordinal(rank)}: {name} {fmt_total(total)}{ex}"
                      f" \u2014 picks: {golfers}")
    standings = "\n".join(lines)

    pred_line = ""
    if predictions:
        top = predictions[:3]
        pred_line = ("\nAI win probabilities: "
                     + ", ".join(f"{n} {w:.1f}%" for n, w, _, _ in top))

    prev_lines = ""
    if existing_commentary:
        texts = [e["text"] for e in existing_commentary[:3]]
        prev_lines = ("\n\nPrevious commentary (don't repeat yourself):\n"
                      + "\n".join(f"- {t}" for t in texts))

    return standings, pred_line, prev_lines


def _call_haiku(api_key, prompt, max_tokens=120):
    """Call Claude Haiku and return the text response, or None on failure."""
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body.encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.load(r)
        return resp["content"][0]["text"].strip().strip('"')
    except Exception as e:
        print(f"Haiku API call failed ({e})")
        return None


def generate_ai_commentary(rows, ranks, history, predictions,
                           existing_commentary, is_first=False):
    """Use Claude to generate natural commentary. Returns str or None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prev_ranks, prev_scores = {}, {}
    if not is_first:
        prev = None
        for snap in reversed(history):
            if "scores" in snap:
                prev = snap
                break
        if not prev:
            return None
        prev_ranks = prev.get("ranks", {})
        prev_scores = prev.get("scores", {})
        current_scores = {name: total for name, _, total in rows}
        if not any(
            ranks.get(n) != prev_ranks.get(n)
            or current_scores.get(n) != prev_scores.get(n)
            for n in ranks
        ):
            return None

    standings, pred_line, prev_lines = _build_standings_prompt(
        rows, ranks, prev_ranks, prev_scores, predictions,
        existing_commentary,
    )

    preamble = (
        'You are the commentator for a Masters golf sweepstake among friends '
        'called "The Guinness Storehouse". Each entrant picked 3 golfers '
        '\u2014 lowest combined score wins.'
    )

    if is_first:
        task = (
            "This is the end-of-R1 summary. Summarise the standings "
            "\u2014 who leads, who's the best individual pick, any "
            "interesting storylines (e.g. a great golfer whose entrant "
            "is held back by other picks)."
            "\n\nWrite 2\u20133 sentences, max 60 words."
        )
    else:
        task = (
            "This is a live update. Focus on what changed since the "
            "last update \u2014 new leader, big movers, score swings."
            "\n\nWrite 1\u20132 sentences, max 40 words."
        )

    tone = (
        "Tone: knowledgeable friend in the group chat \u2014 "
        "lighthearted, a bit of dry humour, but not cheesy. "
        "No exclamation marks. No hashtags or emojis. "
        "Be specific \u2014 use real names and numbers.\n\n"
        "Subtle running jokes to weave in ONLY where they fit naturally "
        "(don't force them, don't use all of them in one update):\n"
        "- Gentle digs at Noel Smyth (underperforming, questionable picks, etc.)\n"
        "- Light ribbing of P\u00e1draig Connery (unlucky, cursed, etc.)\n"
        "- Quietly optimistic spin on Barry Dunne even when he's clearly struggling\n"
        "These should be understated and wry, not mean-spirited. "
        "If there's nothing natural to say about them, just skip it."
    )

    accuracy = (
        "IMPORTANT: Only state facts that are directly supported by the "
        "data above. Do not invent scores, rankings, or claims. "
        "Double-check every number you cite against the standings."
    )

    prompt = (f"{preamble}\n\nCurrent standings:\n{standings}{pred_line}"
              f"\n\n{task}\n\n{tone}\n\n{accuracy}{prev_lines}")

    text = _call_haiku(api_key, prompt, max_tokens=120)
    if not text:
        return None

    # Fact-check the generated commentary against the raw data
    verify_prompt = (
        f"You are a fact-checker. Here is the data:\n\n{standings}{pred_line}"
        f"\n\nHere is a commentary written about this data:\n\"{text}\"\n\n"
        "Check ONLY for hard factual errors:\n"
        "- Wrong scores (e.g. saying a player is -3 when they are +2)\n"
        "- Wrong rankings or positions\n"
        "- Wrong player-to-entrant assignments\n"
        "- Wrong counts or quantities (e.g. saying 'three players' when "
        "it's actually two \u2014 count carefully against the data)\n"
        "- Misuse of golf terminology (e.g. calling a bad score an 'albatross')\n\n"
        "Do NOT flag:\n"
        "- Figurative language, hyperbole, humour, or rhetorical phrases\n"
        "- Subjective opinions like 'MVP', 'heavy lifting', 'best pick'\n"
        "- Nicknames or informal references to players\n\n"
        "Only FAIL if a concrete number, score, ranking, count, or "
        "player-entrant link is demonstrably wrong.\n\n"
        "First, briefly verify each factual claim in the commentary against "
        "the data. Then on a NEW line write your final verdict: either "
        "VERDICT: PASS or VERDICT: FAIL with a brief reason."
    )
    verdict = _call_haiku(api_key, verify_prompt, max_tokens=600)
    if not verdict or "VERDICT: PASS" not in verdict.upper():
        print(f"AI commentary failed fact-check ({verdict}), "
              "falling back to templates")
        return None

    return text


def is_pending(thru):
    """True if the player hasn't teed off yet (tee time or unknown)."""
    t = (thru or "").strip()
    return ":" in t or t in ("-", "")


def load_model():
    """Read masters_model.csv → {player_name: {rank, safety, score}}."""
    model = {}
    with open(MODEL_PATH, newline="") as f:
        for row in csv.DictReader(f):
            model[row["Player"].strip()] = {
                "rank": int(row["Rank"]),
                "safety": int(row["Safety"]),
                "score": int(row["OverallModelScore"]),
            }
    return model


def run_predictions(rows, model):
    """Monte Carlo win-probability for each entrant (blends model + R1)."""
    rng = random.Random(42)
    ROUNDS_LEFT = 3  # assumes post-R1

    # Build per-golfer simulation parameters
    golfer_params = {}
    for _name, scores, _total in rows:
        for pname, score, thru, _raw in scores:
            if pname in golfer_params:
                continue
            if score is None:
                # CUT / WD / DQ — fixed at 0 (matches current scoring)
                golfer_params[pname] = (0, 0.0, 0.0)
                continue
            m = model.get(pname)
            rank = m["rank"] if m else 45
            safety = m["safety"] if m else 45
            # Model expected per round (to par): rank 1 ≈ −3.0, rank 91 ≈ +6.0
            model_exp = -3.0 + (rank - 1) * 9.0 / 90
            # Blend model with actual score (between rounds, thru shows
            # next-round tee time but totalScore already has R1)
            adj_exp = ALPHA * model_exp + (1 - ALPHA) * score
            # SD: lower safety rank → tighter distribution
            sd = 2.5 + 1.5 * (safety / 91)
            golfer_params[pname] = (
                score,
                ROUNDS_LEFT * adj_exp,
                math.sqrt(ROUNDS_LEFT) * sd,
            )

    n = len(rows)
    wins = [0] * n
    top3 = [0] * n
    final_sums = [0.0] * n
    golfer_names = list(golfer_params.keys())

    for _ in range(SIM_COUNT):
        # Simulate remaining rounds for each unique golfer once
        sim_final = {}
        for pname in golfer_names:
            cur, rm, rsd = golfer_params[pname]
            sim_final[pname] = cur + rng.gauss(rm, rsd)

        finals = []
        for idx, (_name, scores, _total) in enumerate(rows):
            t = sum(sim_final[pname] for pname, *_ in scores)
            finals.append((t, idx))
        finals.sort()
        wins[finals[0][1]] += 1
        for i in range(min(3, n)):
            top3[finals[i][1]] += 1
        for t, idx in finals:
            final_sums[idx] += t

    results = []
    for i, (name, _, _) in enumerate(rows):
        results.append((
            name,
            100.0 * wins[i] / SIM_COUNT,
            100.0 * top3[i] / SIM_COUNT,
            final_sums[i] / SIM_COUNT,
        ))
    results.sort(key=lambda r: -r[1])
    return results


def render_html(rows, out_path, updated_at, deltas, predictions=None, commentary=None):
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
    updated_iso = updated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build predictions section
    pred_section = ""
    if predictions:
        max_win = max(p[1] for p in predictions) or 1
        pred_rows_html = []
        for pname, win_pct, top3_pct, exp_final in predictions:
            bar_w = win_pct / max_win * 100 if max_win > 0 else 0
            pred_rows_html.append(
                f'<tr><td>{esc(pname)}</td>'
                f'<td class="pred-bar-cell"><div class="pred-bar-outer">'
                f'<div class="pred-bar-track"><div class="pred-bar-fill" style="width:{bar_w:.1f}%"></div></div>'
                f'<span class="pred-pct">{win_pct:.1f}%</span></div></td>'
                f'<td class="pred-num">{top3_pct:.1f}%</td>'
                f'<td class="pred-num">{exp_final:+.1f}</td></tr>'
            )
        pred_tbody = "\n".join(pred_rows_html)
        pred_section = (
            '  <div class="predictions">\n'
            '    <h2>AI Win Probability</h2>\n'
            '    <div class="pred-note">Monte Carlo simulation &middot; pre-tournament model + live scores</div>\n'
            '    <table class="pred-table">\n'
            '      <thead><tr><th>Entrant</th><th>Win %</th><th>Top 3 %</th><th>Exp. Final</th></tr></thead>\n'
            '      <tbody>\n'
            f'{pred_tbody}\n'
            '      </tbody>\n'
            '    </table>\n'
            '  </div>'
        )

    # Build commentary section
    comm_section = ""
    if commentary:
        comm_entries = []
        for entry in commentary[:5]:
            ts_raw = entry.get("ts", "")
            try:
                dt = _parse_iso(ts_raw).astimezone(DUBLIN)
                time_str = dt.strftime("%H:%M")
            except (ValueError, AttributeError):
                time_str = ts_raw
            text = entry.get("text", "")
            comm_entries.append(
                f'<div class="comm-entry">'
                f'<span class="comm-time">{esc(time_str)}</span>'
                f'<span class="comm-text">{esc(text)}</span>'
                f'</div>'
            )
        comm_html = "\n".join(comm_entries)
        comm_section = (
            '  <div class="commentary">\n'
            '    <div class="comm-header">Live Commentary</div>\n'
            f'{comm_html}\n'
            '  </div>'
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
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
  .rel-time {{ font-variant-numeric: tabular-nums; }}
  .rel-time.stale {{
    color: var(--down);
    font-weight: 600;
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
  .predictions {{
    margin-top: 2rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--cream);
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
    padding: 1.2rem 1.4rem;
  }}
  .predictions h2 {{
    color: var(--green);
    font-size: 1rem;
    margin: 0 0 .25rem;
    letter-spacing: .02em;
  }}
  .pred-note {{
    color: var(--muted);
    font-size: .72rem;
    margin-bottom: 1rem;
  }}
  .pred-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .pred-table th {{
    text-align: left;
    padding: .45rem .6rem;
    font-size: .78rem;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  .pred-table td {{
    padding: .4rem .6rem;
    border-top: 1px solid var(--border);
    font-size: .85rem;
  }}
  .pred-table tr:nth-child(even) td {{ background: var(--alt); }}
  .pred-bar-cell {{ min-width: 140px; }}
  .pred-bar-outer {{
    display: flex;
    align-items: center;
    gap: .5rem;
  }}
  .pred-bar-track {{
    flex: 1;
    background: var(--alt);
    border-radius: 3px;
    height: .9rem;
    overflow: hidden;
    min-width: 60px;
  }}
  .pred-bar-fill {{
    background: var(--green);
    height: 100%;
    border-radius: 3px;
  }}
  .pred-pct {{
    font-size: .78rem;
    white-space: nowrap;
    min-width: 3.5em;
  }}
  .pred-num {{
    white-space: nowrap;
    text-align: right;
  }}
  .commentary {{
    margin-bottom: 1.5rem;
    border: 1px solid var(--border);
    border-left: 3px solid var(--green);
    border-radius: 0 6px 6px 0;
    background: var(--cream);
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
    padding: .7rem 1.2rem;
  }}
  .comm-header {{
    color: var(--green);
    font-size: .78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .08em;
    margin-bottom: .5rem;
  }}
  .comm-entry {{
    display: flex;
    gap: .7rem;
    padding: .4rem 0;
    font-size: .82rem;
    line-height: 1.45;
  }}
  .comm-entry + .comm-entry {{
    border-top: 1px solid var(--border);
  }}
  .comm-entry:first-of-type {{
    font-weight: 500;
  }}
  .comm-entry:not(:first-of-type) .comm-text {{
    color: var(--muted);
  }}
  .comm-time {{
    color: var(--muted);
    white-space: nowrap;
    min-width: 3.2em;
    font-size: .75rem;
    padding-top: .05rem;
  }}
  @media (max-width: 640px) {{
    body {{ padding: 1rem .5rem; font-size: 14px; }}
    h1 {{ font-size: 1.1rem; }}
    .banner {{ width: 140px; height: 140px; border-width: 3px; }}
    thead th, tbody td {{ padding: .5rem .55rem; }}
    td.players .player-main,
    td.players .player-sub {{ white-space: normal; }}
    .predictions {{ padding: .8rem; }}
    .pred-bar-track {{ min-width: 40px; }}
    .commentary {{ padding: .5rem .8rem; }}
  }}
</style>
</head>
<body>
<main>
  <div class="header">
    <img class="banner" src="banner.jpg" alt="">
    <h1>The Guinness Storehouse LIVE STANDINGS</h1>
    <div class="meta">Updated {esc(updated_str)} · <span class="rel-time" data-iso="{esc(updated_iso)}">just now</span> · refreshes every 5 min</div>
  </div>
  {comm_section}
  <div class="table-wrap">
    <table>
      <thead><tr>{thead}</tr></thead>
      <tbody>
{tbody}
      </tbody>
    </table>
  </div>
  {pred_section}
  <footer>Lowest combined total wins. Scores relative to par. ⬆ / ⬇ marks rank change over the last ~30 min. Faded players have not yet teed off.</footer>
</main>
<script>
(function () {{
  var el = document.querySelector('.rel-time');
  if (!el) return;
  var ts = Date.parse(el.dataset.iso);
  if (isNaN(ts)) return;
  function render() {{
    var mins = Math.max(0, Math.round((Date.now() - ts) / 60000));
    var txt;
    if (mins < 1) txt = 'just now';
    else if (mins === 1) txt = '1 min ago';
    else if (mins < 60) txt = mins + ' min ago';
    else {{
      var hrs = Math.floor(mins / 60);
      txt = hrs + 'h ' + (mins % 60) + 'm ago';
    }}
    el.textContent = txt;
    el.classList.toggle('stale', mins >= 15);
  }}
  render();
  setInterval(render, 30000);
}})();
</script>
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

        model = load_model()
        predictions = run_predictions(rows, model)

        current_scores = {name: total for name, _, total in rows}
        commentary = load_commentary()
        ts = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Try AI commentary for live changes, fall back to templates
        entry = generate_ai_commentary(
            rows, ranks, history, predictions, commentary,
        ) or generate_commentary(rows, ranks, history, now)
        if entry:
            # Real change detected — prepend new entry
            commentary = [{"ts": ts, "text": entry}] + commentary
            commentary = commentary[:COMMENTARY_MAX]
        elif not entry:
            # No changes — regenerate the summary (keeps it fresh between rounds)
            fresh = generate_ai_commentary(
                rows, ranks, history, predictions, commentary, is_first=True,
            ) or generate_day1_summary(rows, ranks)
            commentary = [{"ts": ts, "text": fresh}] + commentary[1:]
        save_commentary(commentary, os.path.join("_site", COMMENTARY_FILENAME))

        render_png(rows, "_site/standings.png")
        render_html(rows, "_site/index.html", now, deltas, predictions, commentary)
        save_history(history, ranks, now, os.path.join("_site", HISTORY_FILENAME),
                     current_scores=current_scores)

        if os.path.exists(BANNER_SRC):
            shutil.copy(BANNER_SRC, os.path.join("_site", BANNER_SRC))
        else:
            print(f"Warning: {BANNER_SRC} not found; site banner will be missing")

        print("\nWrote _site/index.html, _site/standings.png, _site/history.json, _site/banner.jpg")


if __name__ == "__main__":
    main()
