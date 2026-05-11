# -*- coding: utf-8 -*-
# ============================================================
# MLB QUANT PROP ENGINE — RAILWAY FASTAPI ONE-FILE BUILD
# Markets:
#   - Pitcher Strikeouts
#   - Pitching Outs
#   - Hits
#   - Hits + Runs + RBIs
#
# Railway-safe Uvicorn version.
# Real prop lines only from Underdog / PrizePicks.
# No fake prop lines.
# ============================================================

import os
import re
import json
import math
import difflib
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from statistics import mean

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

APP_VERSION = "v3310 FASTAPI ALL MARKETS"
DB = "bets.db"

MLB_BASE = "https://statsapi.mlb.com/api/v1"
PRIZEPICKS_URL = "https://api.prizepicks.com/projections"
UNDERDOG_URLS = [
    "https://api.underdogfantasy.com/beta/v6/over_under_lines",
    "https://api.underdogfantasy.com/beta/v5/over_under_lines",
    "https://api.underdogfantasy.com/beta/v4/over_under_lines",
    "https://api.underdogfantasy.com/beta/v3/over_under_lines",
    "https://api.underdogfantasy.com/v1/over_under_lines",
]

REQUEST_TIMEOUT = 14
CACHE = {}
CACHE_TTL = 300

app = FastAPI(title="MLB Quant Engine All Markets")

# =========================
# DATABASE
# =========================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player TEXT,
            market TEXT,
            source TEXT,
            line REAL,
            projection REAL,
            edge REAL,
            signal TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# =========================
# HELPERS
# =========================
def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def strip_accents(text):
    try:
        return "".join(
            ch for ch in unicodedata.normalize("NFKD", str(text or ""))
            if not unicodedata.combining(ch)
        )
    except Exception:
        return str(text or "")

def normalize_name(name):
    s = strip_accents(name).lower().strip()
    for ch in [".", ",", "'", "-", "_"]:
        s = s.replace(ch, " ")
    for suf in [" jr", " sr", " ii", " iii", " iv"]:
        s = s.replace(suf, "")
    return " ".join(s.split())

def name_score(a, b):
    a_norm = normalize_name(a)
    b_norm = normalize_name(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    if a_norm in b_norm or b_norm in a_norm:
        return 0.94

    a_parts = a_norm.split()
    b_parts = b_norm.split()
    if a_parts and b_parts:
        if a_parts[-1] == b_parts[-1] and a_parts[0][:1] == b_parts[0][:1]:
            return 0.93

    return difflib.SequenceMatcher(None, a_norm, b_norm).ratio()

def safe_float(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def cached_get_json(url, params=None, headers=None, ttl=CACHE_TTL):
    key = json.dumps([url, params or {}, headers or {}], sort_keys=True)
    rec = CACHE.get(key)
    if rec and (datetime.now() - rec["time"]).total_seconds() < ttl:
        return rec["data"]

    try:
        h = {
            "User-Agent": "Mozilla/5.0 MLBQuantEngine/3310",
            "Accept": "application/json,text/plain,*/*",
        }
        if headers:
            h.update(headers)
        r = requests.get(url, params=params, headers=h, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        CACHE[key] = {"time": datetime.now(), "data": data}
        return data
    except Exception:
        return None

def flatten_json(obj):
    items = []
    if isinstance(obj, dict):
        items.append(obj)
        for v in obj.values():
            items.extend(flatten_json(v))
    elif isinstance(obj, list):
        for x in obj:
            items.extend(flatten_json(x))
    return items

def text_from_obj(obj):
    if not isinstance(obj, dict):
        return ""
    parts = []
    for k, v in obj.items():
        if isinstance(v, (str, int, float)):
            parts.append(f"{k}:{v}")
    return " | ".join(parts)

def first_value(d, keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] not in [None, ""]:
            return d[k]
    return None

def baseball_ip_to_float(ip):
    if ip is None:
        return None
    try:
        s = str(ip)
        if "." not in s:
            return float(s)
        whole, frac = s.split(".", 1)
        outs = int(frac[:1]) if frac else 0
        if outs not in [0, 1, 2]:
            return float(s)
        return int(whole) + outs / 3
    except Exception:
        return None

# =========================
# MARKET DETECTION
# =========================
MARKETS = {
    "pitcher_strikeouts": {
        "label": "Pitcher Strikeouts",
        "aliases": [
            "pitcher strikeouts", "pitcher strikeout", "strikeouts", "strikeout",
            "pitcher k", "pitcher ks", "ks"
        ],
        "min_line": 1.5,
        "max_line": 12.5,
    },
    "pitching_outs": {
        "label": "Pitching Outs",
        "aliases": [
            "pitching outs", "pitcher outs", "outs recorded", "recorded outs",
            "pitcher recorded outs"
        ],
        "min_line": 8.5,
        "max_line": 24.5,
    },
    "hits": {
        "label": "Hits",
        "aliases": [
            "hits", "hit", "batter hits", "hitter hits"
        ],
        "min_line": 0.5,
        "max_line": 3.5,
    },
    "hrrbi": {
        "label": "Hits + Runs + RBIs",
        "aliases": [
            "hits+runs+rbis", "hits + runs + rbis", "hits runs rbis",
            "hits+runs+rbi", "hits + runs + rbi", "h+r+rbi", "hrrbi",
            "hits runs and rbis"
        ],
        "min_line": 0.5,
        "max_line": 5.5,
    },
}

BAD_SPORT_TERMS = [
    " nba ", " basketball", " wnba ", " nfl ", " football", " nhl ",
    " soccer", " tennis", " golf", " ncaab", " college basketball"
]

def is_bad_sport_text(text):
    t = f" {str(text or '').lower()} "
    return any(x in t for x in BAD_SPORT_TERMS)

def detect_market(text):
    t = normalize_name(text)
    raw = str(text or "").lower()

    # More specific combo first
    for key in ["hrrbi", "pitching_outs", "pitcher_strikeouts", "hits"]:
        for alias in MARKETS[key]["aliases"]:
            a = normalize_name(alias)
            if a and a in t:
                if key == "hits" and any(combo in raw for combo in ["hits+runs", "hits + runs", "hrrbi"]):
                    continue
                return key
    return None

def valid_line_for_market(line, market_key):
    val = safe_float(line)
    if val is None or market_key not in MARKETS:
        return None

    lo = MARKETS[market_key]["min_line"]
    hi = MARKETS[market_key]["max_line"]

    if not (lo <= val <= hi):
        return None

    # Prop lines usually step by .5. Allow whole number for pitching outs.
    if abs(val * 2 - round(val * 2)) > 1e-9:
        return None

    return float(val)

def extract_line_from_text(text, market_key):
    vals = []
    for m in re.finditer(r"(?<!\d)(\d{1,2}(?:\.5|\.0)?)(?!\d)", str(text or "")):
        v = safe_float(m.group(1))
        if valid_line_for_market(v, market_key) is not None:
            vals.append(float(v))
    return vals[0] if vals else None

# =========================
# MLB STATS PROJECTIONS
# =========================
def search_mlb_player(player_name):
    data = cached_get_json(f"{MLB_BASE}/people/search", params={"names": player_name}, ttl=86400)
    people = data.get("people", []) if isinstance(data, dict) else []
    if not people:
        return None

    scored = sorted(
        people,
        key=lambda p: name_score(player_name, p.get("fullName", "")),
        reverse=True
    )
    best = scored[0]
    if name_score(player_name, best.get("fullName", "")) < 0.70:
        return None
    return best

def get_player_season_stats(player_id, group):
    data = cached_get_json(
        f"{MLB_BASE}/people/{player_id}/stats",
        params={"stats": "season", "group": group},
        ttl=1800
    )
    try:
        return data["stats"][0]["splits"][0]["stat"]
    except Exception:
        return {}

def project_hitter(player_name, market_key):
    player = search_mlb_player(player_name)
    if not player:
        return None, "No MLB player match"

    stat = get_player_season_stats(player.get("id"), "hitting")

    games = safe_float(stat.get("gamesPlayed"), 0) or 0
    if games <= 0:
        return None, "No season hitter games"

    hits = safe_float(stat.get("hits"), 0) or 0
    runs = safe_float(stat.get("runs"), 0) or 0
    rbi = safe_float(stat.get("rbi"), 0) or 0

    if market_key == "hits":
        base = hits / games
        projection = clamp(base * 1.02, 0.05, 3.25)
        return round(projection, 2), "Season hits/game projection"

    if market_key == "hrrbi":
        base = (hits + runs + rbi) / games
        projection = clamp(base * 1.02, 0.10, 5.25)
        return round(projection, 2), "Season H+R+RBI/game projection"

    return None, "Unsupported hitter market"

def project_pitcher(player_name, market_key):
    player = search_mlb_player(player_name)
    if not player:
        return None, "No MLB pitcher match"

    stat = get_player_season_stats(player.get("id"), "pitching")

    games_started = safe_float(stat.get("gamesStarted"), None)
    games_played = safe_float(stat.get("gamesPlayed"), 0) or 0
    starts = games_started if games_started and games_started > 0 else games_played

    ip = baseball_ip_to_float(stat.get("inningsPitched"))
    strikeouts = safe_float(stat.get("strikeOuts"), 0) or 0

    if not starts or starts <= 0:
        return None, "No pitcher starts/games"

    if market_key == "pitching_outs":
        avg_ip = (ip or 0) / starts
        projection = clamp(avg_ip * 3, 6.0, 24.0)
        return round(projection, 2), "Season average IP converted to pitching outs"

    if market_key == "pitcher_strikeouts":
        projection = clamp(strikeouts / starts, 0.5, 12.0)
        return round(projection, 2), "Season strikeouts/start projection"

    return None, "Unsupported pitcher market"

def make_projection(player_name, market_key):
    if market_key in ["hits", "hrrbi"]:
        return project_hitter(player_name, market_key)
    if market_key in ["pitching_outs", "pitcher_strikeouts"]:
        return project_pitcher(player_name, market_key)
    return None, "Unsupported market"

def calculate_signal(proj, line):
    if proj is None or line is None:
        return "NO PROJECTION", 0.0, "pass"
    edge = round(((proj - line) / max(line, 0.1)) * 100, 2)
    side = "OVER" if proj > line else "UNDER"
    gap = abs(proj - line)

    if gap >= 1.0 and abs(edge) >= 18:
        return f"🔥 STRONG {side}", edge, "good"
    if gap >= 0.55 and abs(edge) >= 10:
        return f"✅ WATCH {side}", edge, "watch"
    return f"PASS / LEAN {side}", edge, "pass"

# =========================
# PROP SOURCE PARSERS
# =========================
def parse_prizepicks():
    data = cached_get_json(PRIZEPICKS_URL, ttl=180)
    rows = []

    if not isinstance(data, dict):
        return rows

    included = data.get("included", []) or []
    players = {}

    for x in included:
        if x.get("type") in ["new_player", "player"]:
            attrs = x.get("attributes", {}) or {}
            pid = x.get("id")
            name = (
                attrs.get("name")
                or attrs.get("display_name")
                or attrs.get("full_name")
                or f"{attrs.get('first_name','')} {attrs.get('last_name','')}".strip()
            )
            league = attrs.get("league") or attrs.get("league_id") or ""
            players[str(pid)] = {"name": name, "league": league}

    for item in data.get("data", []) or []:
        attrs = item.get("attributes", {}) or {}
        rel = item.get("relationships", {}) or {}

        stat_type = (
            attrs.get("stat_type")
            or attrs.get("market")
            or attrs.get("description")
            or attrs.get("display_stat")
            or ""
        )

        blob = text_from_obj(attrs) + " | " + stat_type
        if is_bad_sport_text(blob):
            continue

        market_key = detect_market(blob)
        if not market_key:
            continue

        line = first_value(attrs, ["line_score", "stat_value", "line", "target_value"])
        line = valid_line_for_market(line, market_key)
        if line is None:
            line = extract_line_from_text(blob, market_key)

        if line is None:
            continue

        player_id = None
        try:
            player_id = rel.get("new_player", {}).get("data", {}).get("id")
        except Exception:
            pass
        if not player_id:
            try:
                player_id = rel.get("player", {}).get("data", {}).get("id")
            except Exception:
                pass

        info = players.get(str(player_id), {})
        player_name = info.get("name") or attrs.get("name") or attrs.get("description") or ""

        if not player_name:
            continue

        if "mlb" not in str(info.get("league", "mlb")).lower() and "baseball" not in blob.lower():
            # Many feeds omit league. Only reject when clear non-MLB was found above.
            pass

        rows.append({
            "source": "PrizePicks",
            "player": player_name,
            "market_key": market_key,
            "market": MARKETS[market_key]["label"],
            "line": line,
            "matched_name": player_name,
            "raw_market": stat_type,
        })

    return rows

def parse_underdog():
    all_rows = []

    for url in UNDERDOG_URLS:
        data = cached_get_json(url, ttl=180)
        if not data:
            continue

        objects = flatten_json(data)

        # Build player-name lookup from all objects.
        player_candidates = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            name = first_value(obj, [
                "player_name", "full_name", "display_name", "title", "name",
                "first_name", "last_name"
            ])
            if name:
                if obj.get("first_name") and obj.get("last_name"):
                    name = f"{obj.get('first_name')} {obj.get('last_name')}"
                player_candidates.append(str(name))

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            blob = text_from_obj(obj)
            if is_bad_sport_text(blob):
                continue

            market_key = detect_market(blob)
            if not market_key:
                continue

            line = first_value(obj, ["stat_value", "line_score", "over_under_line", "target_value", "line"])
            line = valid_line_for_market(line, market_key)
            if line is None:
                line = extract_line_from_text(blob, market_key)
            if line is None:
                continue

            player_name = first_value(obj, [
                "player_name", "full_name", "display_name", "title", "name"
            ])

            if not player_name:
                # Fuzzy find a name in the blob from known player objects
                blob_norm = normalize_name(blob)
                best_name = ""
                best_score = 0
                for cand in player_candidates:
                    cand_norm = normalize_name(cand)
                    if cand_norm and cand_norm in blob_norm:
                        sc = len(cand_norm)
                        if sc > best_score:
                            best_name = cand
                            best_score = sc
                player_name = best_name

            if not player_name:
                continue

            status_blob = str(first_value(obj, ["status", "state", "display_status", "hidden", "active"]) or "").lower()
            if any(x in status_blob for x in ["suspended", "removed", "hidden", "inactive", "closed", "disabled"]):
                continue

            all_rows.append({
                "source": "Underdog",
                "player": str(player_name),
                "market_key": market_key,
                "market": MARKETS[market_key]["label"],
                "line": float(line),
                "matched_name": str(player_name),
                "raw_market": blob[:220],
            })

    # Deduplicate
    seen = set()
    clean = []
    for r in all_rows:
        key = (normalize_name(r["player"]), r["market_key"], r["line"], r["source"])
        if key in seen:
            continue
        seen.add(key)
        clean.append(r)

    return clean

def get_all_live_props():
    rows = []
    rows.extend(parse_prizepicks())
    rows.extend(parse_underdog())

    final = []
    seen = set()

    for r in rows:
        player = r["player"]
        market_key = r["market_key"]
        line = r["line"]
        source = r["source"]

        key = (normalize_name(player), market_key, line, source)
        if key in seen:
            continue
        seen.add(key)

        proj, proj_source = make_projection(player, market_key)
        signal, edge, tier = calculate_signal(proj, line)

        final.append({
            **r,
            "projection": proj,
            "projection_source": proj_source,
            "edge": edge,
            "signal": signal,
            "tier": tier,
        })

    final.sort(key=lambda x: abs(x.get("edge") or 0), reverse=True)
    return final

# =========================
# HTML UI
# =========================
def render_table(rows):
    if not rows:
        return """
        <tr>
            <td colspan="8">No real MLB prop lines found right now. Refresh later or confirm Underdog/PrizePicks has MLB props live.</td>
        </tr>
        """

    html = ""
    for r in rows:
        cls = "green" if r["tier"] == "good" else "orange" if r["tier"] == "watch" else "muted"
        proj = "" if r["projection"] is None else r["projection"]
        html += f"""
        <tr>
            <td>{r['player']}</td>
            <td>{r['market']}</td>
            <td>{r['source']}</td>
            <td>{r['line']}</td>
            <td>{proj}</td>
            <td class="{cls}">{r['edge']}%</td>
            <td class="{cls}">{r['signal']}</td>
            <td><a class="small-btn" href="/log?player={safe_url(r['player'])}&market={safe_url(r['market'])}&source={safe_url(r['source'])}&line={r['line']}&projection={proj}&edge={r['edge']}&signal={safe_url(r['signal'])}">Log</a></td>
        </tr>
        """
    return html

def safe_url(x):
    from urllib.parse import quote
    return quote(str(x or ""))

def get_history():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        SELECT player, market, source, line, projection, edge, signal, created_at
        FROM bets
        ORDER BY id DESC
        LIMIT 50
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def render_history(rows):
    if not rows:
        return '<tr><td colspan="8">No logged picks yet.</td></tr>'
    html = ""
    for h in rows:
        html += f"""
        <tr>
            <td>{h[0]}</td>
            <td>{h[1]}</td>
            <td>{h[2]}</td>
            <td>{h[3]}</td>
            <td>{h[4]}</td>
            <td>{h[5]}%</td>
            <td>{h[6]}</td>
            <td>{h[7]}</td>
        </tr>
        """
    return html

@app.get("/", response_class=HTMLResponse)
def home(market: str = "all"):
    props = get_all_live_props()

    if market != "all":
        props = [p for p in props if p["market_key"] == market]

    strong = [p for p in props if p["tier"] == "good"]
    watch = [p for p in props if p["tier"] == "watch"]

    by_market = {}
    for p in props:
        by_market[p["market"]] = by_market.get(p["market"], 0) + 1

    market_options = '<a class="filter" href="/">All</a>'
    for key, meta in MARKETS.items():
        active = "active" if market == key else ""
        market_options += f'<a class="filter {active}" href="/?market={key}">{meta["label"]}</a>'

    history = get_history()

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MLB Quant Engine</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin:0;
                font-family: Arial, Helvetica, sans-serif;
                background: radial-gradient(circle at top,#260000 0%,#090909 42%,#020202 100%);
                color:white;
            }}
            .wrap {{
                padding:28px;
                max-width:1400px;
                margin:auto;
            }}
            .hero {{
                background:linear-gradient(135deg,rgba(50,0,0,.92),rgba(8,8,8,.96));
                border:1px solid rgba(255,70,70,.42);
                border-radius:24px;
                padding:22px;
                margin-bottom:18px;
                box-shadow:0 0 34px rgba(255,0,0,.18);
            }}
            .title {{
                font-size:42px;
                font-weight:950;
            }}
            .subtitle {{
                color:#d3d3d3;
                margin-top:6px;
            }}
            .grid {{
                display:grid;
                grid-template-columns:repeat(4, minmax(0,1fr));
                gap:14px;
                margin:18px 0;
            }}
            .card {{
                background:linear-gradient(145deg,#101010,#180000);
                border:1px solid rgba(255,45,45,.36);
                border-radius:18px;
                padding:16px;
                box-shadow:0 0 20px rgba(255,0,0,.12);
            }}
            .metric {{
                font-size:30px;
                font-weight:900;
                color:#31e84f;
            }}
            .label {{
                color:#aaa;
                font-size:13px;
                font-weight:800;
                text-transform:uppercase;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                margin-top:10px;
                font-size:14px;
            }}
            th, td {{
                padding:12px;
                border-bottom:1px solid rgba(255,255,255,.10);
                text-align:left;
            }}
            th {{
                color:#31e84f;
                background:#130000;
            }}
            tr:hover {{
                background:rgba(255,255,255,.04);
            }}
            .green {{
                color:#31e84f;
                font-weight:900;
            }}
            .orange {{
                color:#ffbe3c;
                font-weight:900;
            }}
            .muted {{
                color:#bdbdbd;
                font-weight:700;
            }}
            .filter {{
                display:inline-block;
                color:white;
                text-decoration:none;
                border:1px solid rgba(255,255,255,.18);
                border-radius:999px;
                padding:8px 13px;
                margin:4px;
                background:#111;
                font-weight:800;
            }}
            .filter.active, .filter:hover {{
                border-color:#31e84f;
                color:#31e84f;
            }}
            .small-btn {{
                display:inline-block;
                background:#31e84f;
                color:#061006;
                padding:7px 10px;
                border-radius:8px;
                text-decoration:none;
                font-weight:900;
            }}
            .note {{
                color:#bdbdbd;
                font-size:13px;
                margin-top:8px;
            }}
            @media(max-width:900px) {{
                .grid {{grid-template-columns:1fr 1fr;}}
                .wrap {{padding:14px;}}
                table {{font-size:12px;}}
            }}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="hero">
                <div class="title">⚾ MLB Quant Engine</div>
                <div class="subtitle">{APP_VERSION} • Real lines only • Underdog + PrizePicks • Uvicorn/Railway ready</div>
                <div class="note">Markets added: Pitcher Strikeouts, Pitching Outs, Hits, Hits + Runs + RBIs.</div>
            </div>

            <div class="grid">
                <div class="card"><div class="metric">{len(props)}</div><div class="label">Live Props</div></div>
                <div class="card"><div class="metric">{len(strong)}</div><div class="label">Strong Edges</div></div>
                <div class="card"><div class="metric">{len(watch)}</div><div class="label">Watch List</div></div>
                <div class="card"><div class="metric">{len(by_market)}</div><div class="label">Markets Live</div></div>
            </div>

            <div class="card">
                <b>Filter:</b> {market_options}
            </div>

            <h2>Live MLB Props</h2>
            <div class="card">
                <table>
                    <thead>
                        <tr>
                            <th>Player</th>
                            <th>Market</th>
                            <th>Source</th>
                            <th>Line</th>
                            <th>Projection</th>
                            <th>Edge</th>
                            <th>Signal</th>
                            <th>Log</th>
                        </tr>
                    </thead>
                    <tbody>
                        {render_table(props)}
                    </tbody>
                </table>
            </div>

            <h2>Bet History</h2>
            <div class="card">
                <table>
                    <thead>
                        <tr>
                            <th>Player</th>
                            <th>Market</th>
                            <th>Source</th>
                            <th>Line</th>
                            <th>Projection</th>
                            <th>Edge</th>
                            <th>Signal</th>
                            <th>Logged</th>
                        </tr>
                    </thead>
                    <tbody>
                        {render_history(history)}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.get("/log")
def log_pick(player: str, market: str, source: str, line: float, projection: str = "", edge: float = 0.0, signal: str = ""):
    proj_val = safe_float(projection)

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO bets (
            player, market, source, line, projection, edge, signal, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (player, market, source, line, proj_val, edge, signal, now_iso())
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/", status_code=302)

@app.get("/api/props")
def api_props():
    return JSONResponse(get_all_live_props())

@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION}
