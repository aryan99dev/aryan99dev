#!/usr/bin/env python3
"""Render self-contained animated SVG cards for aryan99dev's GitHub profile README.

Design system: High-contrast Manga Ink Noir aesthetic matching the avatar portrait
──────────────────────────────────────────────────────────────────────────────────
  • Tactile crisp white paper cards (#ffffff) with large rounded corners (rx="28")
  • Editorial typography: Instrument Serif (huge Roman name + Italic surname, size 78px)
  • Clean modern sans-serif for descriptions and bio
  • Monospace for tags, links, and metadata
  • Embedded high-resolution anime ink portrait on the right of the Hero card
  • Three monochromatic noir tiles:
      - BUILD: Pitch Black (#09090b) -> "3 projects" (white text)
      - BRAND: Deep Charcoal (#18181b) -> "10+ repos" (white text)
      - LEARN: Stark White (#ffffff) -> "BCA '26" (black ink text)
  • Contributions chart in clean paper aesthetic with solid black bars (#09090b)
  • GitHub contribution graph in 5-level monochrome ink scale (#f4f4f5 to #09090b)
  • CSS keyframes (rise, fade) + SMIL (bar grow, opacity stagger)
  • prefers-reduced-motion: disables all animations, static frame rendered
  • STATIC=1: frozen final frame, outputs to cards-static/ + preview.html
"""
from __future__ import annotations

import argparse
import base64
import calendar
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

# ═══════════════════════════════════════════════════════════════════ CONFIG

ROOT   = Path(__file__).resolve().parents[1]
STATIC = os.getenv("STATIC", "0") == "1"
OUT    = ROOT / ("cards-static" if STATIC else "cards")
DATA_FILE       = ROOT / "contribution-data.json"
ASSETS_DIR      = ROOT / "assets"
AVATAR_PATH     = ASSETS_DIR / "avatar.png"

# ── identity ──────────────────────────────────────────────────────────────────
USERNAME = "aryan99dev"
FIRST_NAME = "Aryan"
LAST_NAME  = "Sharma"
ROLE_TAG   = "FULLSTACK DEVELOPER · BCA STUDENT"
BIO_L1     = "I build modern web apps, learn new technologies,"
BIO_L2     = "and create useful digital experiences."
WEBSITE    = f"github.com/{USERNAME}"
EMAIL      = "aryan99dev00@gmail.com"

# ── palette (Manga Ink Noir: Black, Charcoal, Slate, White) ───────────────────
CARD_BG   = "#ffffff"     # crisp white paper canvas
CARD_STR  = "#e4e4e7"     # subtle slate border
TEXT_PRI  = "#09090b"     # rich pitch black
TEXT_SEC  = "#3f3f46"     # body text charcoal
TEXT_MUT  = "#71717a"     # metadata / tag grey
TEXT_SUB  = "#a1a1aa"     # subtle grey

# Tile colours (monochrome gradient: Black -> Charcoal -> White)
BLACK_TILE = "#09090b"    # BUILD tile
DARK_TILE  = "#18181b"    # BRAND tile
WHITE_TILE = "#ffffff"    # LEARN tile

# Contribution graph 5 levels (clean monochrome ink scale)
GRAPH_EMPTY = "#f4f4f5"   # level 0 (empty paper)
GRAPH_LVL1  = "#d4d4d8"   # level 1 (pencil sketch grey)
GRAPH_LVL2  = "#71717a"   # level 2 (medium ink)
GRAPH_LVL3  = "#27272a"   # level 3 (dark charcoal)
GRAPH_LVL4  = "#09090b"   # level 4 (pitch black peak)
GRAPH_LEVELS = [GRAPH_EMPTY, GRAPH_LVL1, GRAPH_LVL2, GRAPH_LVL3, GRAPH_LVL4]

# ── featured repos ────────────────────────────────────────────────────────────
FEATURED = [
    ("Portfolio",
     "Personal site built with Next.js and React, featuring modern UI and responsive layouts.",
     "Next.js · React · TypeScript",
     f"https://github.com/{USERNAME}/Portfolio",
     "#09090b"),
    ("Prism",
     "Modern social platform: authentication, profiles, real-time posts, and interactive UI.",
     "React · TypeScript · Vite · Tailwind · Appwrite",
     f"https://github.com/{USERNAME}/Prism",
     "#18181b"),
    ("Movie-App",
     "Movie discovery application with search, detailed view, and responsive media grid.",
     "React · Vite · Tailwind CSS",
     f"https://github.com/{USERNAME}/Movie-App",
     "#27272a"),
]

# ── 3 tiles in a row (BUILD, BRAND/EXPLORE, LEARN/CONNECT) ───────────────────
TILES = [
    ("tile-build.svg",
     "BUILD", "3", "projects",
     "Portfolio, Prism and Movie-App.",
     "Built with Next.js, React & TypeScript.",
     f"https://github.com/{USERNAME}/Portfolio",
     "Build — 3 featured projects",
     BLACK_TILE, "#ffffff", "#ffffff", BLACK_TILE),
    ("tile-explore.svg",
     "BRAND", "10+", "repos",
     "Open source contributions and experiments.",
     "Active development, animations & UI.",
     f"https://github.com/{USERNAME}?tab=repositories",
     "Brand — all repositories",
     DARK_TILE, "#ffffff", "#ffffff", DARK_TILE),
    ("tile-connect.svg",
     "LEARN", "BCA", "'26",
     "Shoolini University, India.",
     "Exploring web architecture & full-stack.",
     f"mailto:{EMAIL}",
     "Learn — BCA student at Shoolini",
     WHITE_TILE, "#09090b", "#27272a", "#e4e4e7"),
]

# ── fonts ─────────────────────────────────────────────────────────────────────
FONTS = {
    "Instrument Serif": ("Instrument+Serif:ital@0;1", [400]),
}
UNICODES  = "U+0020-007E,U+00B7,U+00B0,U+2014,U+2019,U+2192,U+2197,U+25A0,U+25CF"
CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FONT_CSS  = ""

# ═══════════════════════════════════════════════════════════════════ DATA

def refresh_contributions() -> None:
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        print("::warning::No GH_TOKEN — keeping existing data.", file=sys.stderr)
        return
    end   = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    start = end - dt.timedelta(days=365)
    query = textwrap.dedent("""\
        query($login:String!,$from:DateTime!,$to:DateTime!){
          user(login:$login){
            contributionsCollection(from:$from,to:$to){
              contributionCalendar{
                totalContributions
                weeks{contributionDays{date contributionCount}}
              }
            }
          }
        }""")
    body = json.dumps({
        "query": query,
        "variables": {"login": USERNAME, "from": start.isoformat(), "to": end.isoformat()},
    }).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": USERNAME},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read().decode())
        cal  = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        days = [d for week in cal["weeks"] for d in week["contributionDays"]]
    except Exception as exc:
        print(f"::warning::Contribution refresh failed ({exc}).", file=sys.stderr)
        return
    old = _load_json()
    if old.get("days") == days:
        print("Contribution data unchanged.")
        return
    DATA_FILE.write_text(
        json.dumps({"username": USERNAME, "updated_at": end.isoformat(),
                    "total_contributions": cal["totalContributions"], "days": days},
                   indent=2) + "\n", encoding="utf-8")
    print(f"Updated {DATA_FILE.name}: {len(days)} days, {cal['totalContributions']} contributions.")


def _load_json() -> dict:
    try:
        d = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def clean_days(raw) -> list[tuple[dt.date, int]]:
    out = []
    for item in (raw if isinstance(raw, list) else []):
        try:
            out.append((dt.date.fromisoformat(item["date"]),
                        max(0, int(item["contributionCount"]))))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out)


def _month_shift(d: dt.date, delta: int) -> tuple[int, int]:
    idx = d.year * 12 + d.month - 1 + delta
    return idx // 12, idx % 12 + 1


def contribution_stats(days: list[tuple[dt.date, int]],
                       today: dt.date | None = None) -> dict:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    months_keys = [_month_shift(today, -i) for i in range(11, -1, -1)]
    start       = dt.date(*months_keys[0], 1)
    window      = [(d, c) for d, c in days if start <= d <= today]
    per_month    = Counter()
    weekday_sum  = Counter()
    weekday_days = Counter()
    for d, c in window:
        per_month[(d.year, d.month)] += c
        if c:
            n = calendar.day_name[d.weekday()]
            weekday_sum[n] += c; weekday_days[n] += 1
    active = {d for d, c in window if c}
    cursor = today if today in active else today - dt.timedelta(days=1)
    streak = 0
    while cursor in active:
        streak += 1; cursor -= dt.timedelta(days=1)
    months  = [(calendar.month_abbr[m], per_month.get((y, m), 0)) for y, m in months_keys]
    busiest = (max(weekday_sum, key=lambda k: (weekday_sum[k], weekday_days[k]))
               if weekday_sum else "None yet")
    return {"months": months, "streak": streak, "active_days": len(active),
            "busiest": busiest, "total": sum(c for _, c in window),
            "max_month": max(v for _, v in months) or 1,
            "range": (f"{calendar.month_abbr[months_keys[0][1]]} {months_keys[0][0]}"
                      f" – {calendar.month_abbr[months_keys[-1][1]]} {months_keys[-1][0]}")}

# ═══════════════════════════════════════════════════════════════════ FONTS

def subset_font(family: str) -> str:
    try:
        spec, _ = FONTS[family]
        req = urllib.request.Request(
            f"https://fonts.googleapis.com/css2?family={spec}&display=swap",
            headers={"User-Agent": CHROME_UA})
        css_data = urllib.request.urlopen(req, timeout=10).read().decode()
        urls = re.findall(r"url\((https://[^)]+)\)", css_data)
        if not urls:
            return ""
        data = urllib.request.urlopen(urls[0], timeout=10).read()
        b64 = base64.b64encode(data).decode()
        return (f"@font-face{{font-family:'{family}';font-weight:400;font-style:normal;"
                f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}")
    except Exception:
        return ""

# ═══════════════════════════════════════════════════════════════════ AVATAR HELPER

def get_avatar_b64() -> str:
    """Load, optimize, and encode avatar image as base64 PNG."""
    if not AVATAR_PATH.exists():
        return ""
    try:
        from PIL import Image
        im = Image.open(AVATAR_PATH)
        # Resize to clean 450x450 for crisp display at 340x340
        im_opt = im.resize((450, 450), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im_opt.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return base64.b64encode(AVATAR_PATH.read_bytes()).decode("utf-8")

# ═══════════════════════════════════════════════════════════════════ SVG HELPERS

def _css_styles() -> str:
    anim = "" if STATIC else (
        "@keyframes enter{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}"
        "@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}"
        ".enter{animation:enter .75s cubic-bezier(.16,1,.3,1) both}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;animation:grow .8s cubic-bezier(.16,1,.3,1) both}"
        "@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important} animate{display:none}}"
    )
    return (
        f"<style>"
        f"{FONT_CSS}"
        f".serif{{font-family:'Instrument Serif',Georgia,serif;}}"
        f".sans{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;}}"
        f".mono{{font-family:ui-monospace,'JetBrains Mono',SFMono-Regular,Menlo,Monaco,Consolas,monospace;}}"
        f"{anim}"
        f"</style>"
    )


def _svg_open(w: int, h: int, label: str, bg_color: str = CARD_BG, rx: int = 28, stroke_color: str = CARD_STR) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">\n'
        f'{_css_styles()}\n'
        f'<rect width="{w}" height="{h}" rx="{rx}" fill="{bg_color}" '
        f'stroke="{stroke_color}" stroke-width="1"/>\n'
    )


def _enter(delay: float) -> str:
    if STATIC:
        return "<g>"
    return f'<g class="enter" style="animation-delay:{delay:.2f}s">'


def _save(name: str, svg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(svg + "</svg>\n", encoding="utf-8")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

# ═══════════════════════════════════════════════════════════════════ CARDS

# ── 1. Hero Card (Manga Ink Noir Aesthetic) ──────────────────────────────────

def hero_card() -> None:
    """
    920 × 380  Paper Card
    ─────────────────────
    Top Tag:    ■ FULLSTACK DEVELOPER · BCA STUDENT
    Name:       Aryan (Roman)
                Sharma (Italic) — 78px Instrument Serif
    Bio:        I build modern web apps, learn new technologies,
                and create useful digital experiences.
    Link:       github.com/aryan99dev ↗
    Right side: Embedded anime ink portrait (seamless white-on-white)
    """
    W, H = 920, 380
    avatar_b64 = get_avatar_b64()

    s = _svg_open(W, H, f"{FIRST_NAME} {LAST_NAME} — {ROLE_TAG}", bg_color=CARD_BG, rx=28)
    s += _enter(0.0)

    # 1. Top tag: black square + all-caps tracking
    s += (
        f'<rect x="48" y="44" width="9" height="9" rx="2" fill="{TEXT_PRI}"/>\n'
        f'<text x="68" y="52" class="mono" font-size="11" font-weight="600" '
        f'letter-spacing="2.5" fill="{TEXT_MUT}">{escape(ROLE_TAG)}</text>\n'
    )

    # 2. Huge editorial serif name (stacked)
    s += (
        f'<text x="46" y="146" class="serif" font-size="78" fill="{TEXT_PRI}">{escape(FIRST_NAME)}</text>\n'
        f'<text x="46" y="218" class="serif" font-size="78" font-style="italic" fill="{TEXT_PRI}">{escape(LAST_NAME)}</text>\n'
    )

    # 3. Bio text in clean sans-serif
    s += (
        f'<text x="48" y="272" class="sans" font-size="15.5" fill="{TEXT_SEC}">{escape(BIO_L1)}</text>\n'
        f'<text x="48" y="296" class="sans" font-size="15.5" fill="{TEXT_SEC}">{escape(BIO_L2)}</text>\n'
    )

    # 4. Link at bottom
    s += (
        f'<text x="48" y="340" class="mono" font-size="13.5" fill="{TEXT_PRI}">{escape(WEBSITE)}</text>\n'
        f'<text x="238" y="340" class="sans" font-size="14" font-weight="bold" fill="{TEXT_PRI}">&#x2197;</text>\n'
    )

    s += "</g>\n"

    # 5. Right side: Embedded high-resolution anime portrait
    # Placed seamlessly on the white paper card with gentle clip to match card's rx
    if avatar_b64:
        img_w, img_h = 330, 330
        img_x = W - img_w - 35
        img_y = (H - img_h) // 2

        s += _enter(0.2)
        s += (
            f'<defs><clipPath id="hero-img-clip">'
            f'<rect x="{img_x}" y="{img_y}" width="{img_w}" height="{img_h}" rx="24"/>'
            f'</clipPath></defs>\n'
            f'<image href="data:image/png;base64,{avatar_b64}" '
            f'x="{img_x}" y="{img_y}" width="{img_w}" height="{img_h}" '
            f'preserveAspectRatio="xMidYMid meet" clip-path="url(#hero-img-clip)"/>\n'
            f'</g>\n'
        )

    _save("hero.svg", s)


# ── 2. Three Tiles (Monochrome Noir Gradient) ────────────────────────────────

def tile_card(i: int, tile: tuple) -> None:
    """
    300 × 330  Solid Monochrome Tile
    ─────────────────────────────────
    Tile 1: Jet Black (#09090b) -> BUILD (3 projects)
    Tile 2: Deep Charcoal (#18181b) -> BRAND (10+ repos)
    Tile 3: Stark White (#ffffff) -> LEARN (BCA '26)
    """
    file, label, val_num, val_word, desc1, desc2, _href, _alt, bg_col, text_col, sub_col, stroke_col = tile
    W, H = 300, 330

    s = _svg_open(W, H, f"{label} tile", bg_color=bg_col, rx=26, stroke_color=stroke_col)
    s += _enter(0.25 + i * 0.12)

    # Top row: all-caps label + arrow
    s += (
        f'<text x="28" y="44" class="mono" font-size="12" font-weight="600" '
        f'letter-spacing="2" fill="{text_col}" opacity="0.95">{escape(label)}</text>\n'
        f'<text x="{W-28}" y="44" class="sans" font-size="18" font-weight="bold" '
        f'text-anchor="end" fill="{text_col}">&#x2192;</text>\n'
    )

    # Big Instrument Serif Metric
    s += (
        f'<text x="26" y="156" class="serif" font-size="48" fill="{text_col}">'
        f'{escape(val_num)} <tspan font-style="italic">{escape(val_word)}</tspan>'
        f'</text>\n'
    )

    # Description lines
    s += (
        f'<text x="28" y="214" class="sans" font-size="14" fill="{sub_col}" opacity="0.95">'
        f'{escape(desc1)}</text>\n'
        f'<text x="28" y="238" class="sans" font-size="14" fill="{sub_col}" opacity="0.95">'
        f'{escape(desc2)}</text>\n'
    )

    s += "</g>\n"
    _save(file, s)


# ── 3. Contributions Activity Card ───────────────────────────────────────────

def contribution_card(st: dict) -> None:
    """
    920 × 320  Paper Card
    ─────────────────────
    Top Tag:    ■ CONTRIBUTION PULSE
    Title:      Activity Dashboard (Instrument Serif 38px)
    Subtitle:   Real GitHub activity across the last 12 calendar months
    Pills:      Day Streak, Active Days, Busiest Day in slate noir tones
    Bars:       Solid pitch black (#09090b) with rounded top corners
    """
    W, H = 920, 320
    s = _svg_open(W, H, "Contribution analytics", bg_color=CARD_BG, rx=28)
    s += _enter(0.65)

    # 1. Top tag
    s += (
        f'<rect x="48" y="38" width="8" height="8" rx="2" fill="{TEXT_PRI}"/>\n'
        f'<text x="66" y="46" class="mono" font-size="11" font-weight="600" '
        f'letter-spacing="2" fill="{TEXT_MUT}">CONTRIBUTION PULSE</text>\n'
    )

    # 2. Title
    s += (
        f'<text x="46" y="86" class="serif" font-size="36" fill="{TEXT_PRI}">'
        f'Activity <tspan font-style="italic">Dashboard</tspan></text>\n'
        f'<text x="48" y="108" class="sans" font-size="13" fill="{TEXT_SEC}">'
        f'Real GitHub activity across the last 12 calendar months</text>\n'
    )

    # 3. Stat pills on top-right in monochrome noir style
    badges = [
        (str(st["streak"]),      "DAY STREAK",      "#f4f4f5", "#09090b"),
        (str(st["active_days"]), "ACTIVE DAYS",      "#09090b", "#ffffff"),
        (st["busiest"],          "BUSIEST",          "#f4f4f5", "#09090b"),
    ]
    for j, (val, lab, pill_bg, pill_fg) in enumerate(badges):
        bx = 520 + j * 126
        s += (
            f'<rect x="{bx}" y="44" width="118" height="52" rx="14" fill="{pill_bg}"/>\n'
            f'<text x="{bx+16}" y="67" class="sans" font-size="18" font-weight="bold" fill="{pill_fg}">'
            f'{escape(val)}</text>\n'
            f'<text x="{bx+16}" y="84" class="mono" font-size="9" font-weight="600" letter-spacing="1" fill="{pill_fg}">'
            f'{lab}</text>\n'
        )

    # 4. Bar chart
    cx, cy, cw, ch, gap = 48, 142, 824, 126, 12
    months = st["months"]
    bw     = (cw - gap * (len(months) - 1)) / len(months)

    # baseline
    s += f'<line x1="{cx}" y1="{cy+ch}" x2="{cx+cw}" y2="{cy+ch}" stroke="{CARD_STR}" stroke-width="1"/>\n'

    for k, (m, v) in enumerate(months):
        bar_h = max(4.0, ch * v / st["max_month"]) if v else 4.0
        bx    = cx + k * (bw + gap)
        by    = cy + ch - bar_h
        fill  = TEXT_PRI if v else GRAPH_EMPTY

        # Static bar
        s += f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" rx="6" fill="{fill}"/>\n'

        if not STATIC and v:
            begin = f"{0.85 + k * 0.05:.2f}s"
            s += (
                f'<rect x="{bx:.1f}" y="{cy+ch}" width="{bw:.1f}" height="0" rx="6" fill="{fill}">\n'
                f'<animate attributeName="height" from="0" to="{bar_h:.1f}" dur=".65s" begin="{begin}" fill="freeze"/>\n'
                f'<animate attributeName="y" from="{cy+ch}" to="{by:.1f}" dur=".65s" begin="{begin}" fill="freeze"/>\n'
                f'</rect>\n'
            )

        # Count above bar
        if v:
            s += (
                f'<text x="{bx+bw/2:.1f}" y="{by-6:.1f}" text-anchor="middle" '
                f'class="sans" font-size="11" font-weight="600" fill="{TEXT_PRI}">{v}</text>\n'
            )
        # Month label below
        s += (
            f'<text x="{bx+bw/2:.1f}" y="{cy+ch+18}" text-anchor="middle" '
            f'class="mono" font-size="11" fill="{TEXT_MUT}">{m}</text>\n'
        )

    # Summary note
    note = (
        f'{st["total"]} contributions in the last 12 months  ·  {st["range"]}'
        if st["total"] else "No contribution data yet."
    )
    s += f'<text x="48" y="{H-16}" class="mono" font-size="11" fill="{TEXT_MUT}">{escape(note)}</text>\n'
    s += "</g>\n"
    _save("contributions.svg", s)


# ── 4. Featured Repo Cards ───────────────────────────────────────────────────

def repo_card(i: int, repo: tuple) -> None:
    """
    920 × 165  Paper Card
    ─────────────────────
    Tag:         ■ FEATURED REPOSITORY / 01
    Title:       Portfolio (Instrument Serif 38px)
    Description: Personal site built with Next.js...
    Stack pill:  Next.js · React · TypeScript
    Arrow:       → top-right
    """
    name, desc, stack, _url, accent = repo
    W, H = 920, 165

    s = _svg_open(W, H, f"{name} — featured repository", bg_color=CARD_BG, rx=24)
    s += _enter(1.3 + i * 0.18)

    # Tag
    s += (
        f'<rect x="44" y="32" width="7" height="7" rx="1.5" fill="{accent}"/>\n'
        f'<text x="60" y="39" class="mono" font-size="10.5" font-weight="600" '
        f'letter-spacing="2" fill="{TEXT_MUT}">FEATURED REPOSITORY / 0{i}</text>\n'
    )

    # Title in Instrument Serif
    s += (
        f'<text x="42" y="80" class="serif" font-size="38" fill="{TEXT_PRI}">'
        f'{escape(name)}</text>\n'
    )

    # Description in sans-serif
    s += (
        f'<text x="44" y="108" class="sans" font-size="14" fill="{TEXT_SEC}">'
        f'{escape(desc)}</text>\n'
    )

    # Stack line
    s += (
        f'<text x="44" y="136" class="mono" font-size="11.5" font-weight="500" fill="{TEXT_PRI}">'
        f'{escape(stack)}</text>\n'
    )

    # Top right arrow
    s += f'<text x="{W-44}" y="60" class="sans" font-size="22" font-weight="bold" fill="{TEXT_PRI}">&#x2192;</text>\n'

    s += "</g>\n"
    _save(f"repo-{i}-{_slug(name)}.svg", s)


# ── 5. Contribution Graph (Heatmap) ──────────────────────────────────────────

def graph_card(days: list[tuple[dt.date, int]]) -> None:
    """
    920 × 240  Paper Card
    ─────────────────────
    Tag:      ■ CONSISTENCY MAP
    Title:    Activity Graph (Instrument Serif 32px)
    Subtitle: Daily contribution activity, last 52 weeks
    Grid:     52 columns of 7 clean rounded squares in monochrome ink scale
    """
    today  = dt.datetime.now(dt.timezone.utc).date()
    counts = dict(days)
    start  = today - dt.timedelta(weeks=52)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)
    total  = 53 * 7
    mx     = max([counts.get(start + dt.timedelta(days=k), 0) for k in range(total)] + [1])

    W, H = 920, 240
    s = _svg_open(W, H, "Contribution graph", bg_color=CARD_BG, rx=28)
    s += _enter(1.8)

    # Tag & Title
    s += (
        f'<rect x="44" y="32" width="7" height="7" rx="1.5" fill="{TEXT_PRI}"/>\n'
        f'<text x="60" y="39" class="mono" font-size="10.5" font-weight="600" '
        f'letter-spacing="2" fill="{TEXT_MUT}">CONSISTENCY MAP</text>\n'
        f'<text x="42" y="74" class="serif" font-size="32" fill="{TEXT_PRI}">'
        f'Activity <tspan font-style="italic">Graph</tspan></text>\n'
        f'<text x="44" y="94" class="sans" font-size="12.5" fill="{TEXT_SEC}">'
        f'Daily contribution activity — last 52 weeks</text>\n'
    )

    pitch, x0, y0 = 15.2, 44, 116
    last_month = None

    for k in range(total):
        d   = start + dt.timedelta(days=k)
        col, row = divmod(k, 7)

        # Month header
        if row == 0 and d.month != last_month and d <= today:
            last_month = d.month
            s += (
                f'<text x="{x0+col*pitch:.1f}" y="{y0-10}" class="mono" font-size="9" fill="{TEXT_MUT}">'
                f'{calendar.month_abbr[d.month].upper()}</text>\n'
            )

        if d > today:
            continue

        c   = counts.get(d, 0)
        lvl = 0 if c == 0 else min(4, 1 + int(3.999 * c / mx))
        col_color = GRAPH_LEVELS[lvl]
        cx2 = x0 + col * pitch
        cy2 = y0 + row * pitch

        s += (
            f'<rect x="{cx2:.1f}" y="{cy2:.1f}" width="12" height="12" rx="3" fill="{col_color}">'
            f'<title>{d.isoformat()}: {c} contribution{"s" if c!=1 else ""}</title>'
        )
        if not STATIC and c > 0:
            begin = f"{1.9 + col * 0.012:.3f}s"
            s += f'<animate attributeName="opacity" values="0;1" dur=".25s" begin="{begin}" fill="freeze"/>'
        s += "</rect>\n"

    # Legend at bottom right
    leg_x = W - 180
    leg_y = H - 24
    s += f'<text x="{leg_x-36}" y="{leg_y+9}" class="mono" font-size="9" fill="{TEXT_MUT}">LESS</text>\n'
    for k, col in enumerate(GRAPH_LEVELS):
        s += f'<rect x="{leg_x + k * 16}" y="{leg_y}" width="11" height="11" rx="2.5" fill="{col}"/>\n'
    s += f'<text x="{leg_x + len(GRAPH_LEVELS) * 16 + 8}" y="{leg_y+9}" class="mono" font-size="9" fill="{TEXT_MUT}">MORE</text>\n'

    s += "</g>\n"
    _save("contribution-graph.svg", s)

# ═══════════════════════════════════════════════════════════════════ README

def _readme() -> str:
    tiles = "\n".join(
        f'<a href="{t[6]}"><img src="cards/{t[0]}" width="32.5%" alt="{escape(t[7])}" /></a>'
        for t in TILES
    )
    repos = "\n".join(
        f'<a href="{r[3]}"><img src="cards/repo-{i}-{_slug(r[0])}.svg" '
        f'width="100%" alt="{escape(r[0])} - {escape(r[2])}" /></a>'
        for i, r in enumerate(FEATURED, 1)
    )
    return (
        f'<div align="center">\n\n'
        f'<img src="cards/hero.svg" width="100%" alt="{escape(FIRST_NAME)} {escape(LAST_NAME)} - {escape(ROLE_TAG)}" />\n\n'
        f'{tiles}\n\n'
        f'<img src="cards/contributions.svg" width="100%" '
        f'alt="Monthly contributions, streak, active days and busiest weekday" />\n\n'
        f'</div>\n\n'
        f'## Selected work\n\n'
        f'{repos}\n\n'
        f'<div align="center">\n\n'
        f'<img src="cards/contribution-graph.svg" width="100%" '
        f'alt="Contribution graph - last 52 weeks" />\n\n'
        f'[GitHub](https://github.com/{USERNAME})'
        f' · [Portfolio](https://github.com/{USERNAME}/Portfolio)'
        f' · [Email](mailto:{EMAIL})\n\n'
        f'</div>\n\n'
        f'<!-- Cards generated by scripts/render_cards.py.'
        f' Edit FEATURED / TILES / palette there, never the SVGs. -->\n'
    )


def _preview_html() -> str:
    names = (
        ["hero.svg"] + [t[0] for t in TILES] + ["contributions.svg"]
        + [f"repo-{i}-{_slug(r[0])}.svg" for i, r in enumerate(FEATURED, 1)]
        + ["contribution-graph.svg"]
    )
    imgs = "".join(f'<img src="cards-static/{n}" alt="{n}">' for n in names)
    return (
        '<!doctype html><meta charset="utf-8"><title>Static card preview</title>'
        '<style>'
        'body{background:#09090b;margin:0;padding:24px}'
        '.w{max-width:920px;margin:auto;display:flex;flex-wrap:wrap;gap:14px}'
        'img{width:100%}'
        'img[src*="tile-"]{width:calc(33.333% - 10px)}'
        '</style>'
        f'<div class="w">{imgs}</div>'
    )

# ═══════════════════════════════════════════════════════════════════ MAIN

def main() -> None:
    global FONT_CSS
    ap = argparse.ArgumentParser(description="Render animated SVG cards for aryan99dev's README.")
    ap.add_argument("--refresh-contributions", action="store_true",
                    help="Fetch live data from GitHub GraphQL before rendering.")
    ap.add_argument("--skip-fonts", action="store_true",
                    help="Skip font subsetting (fast iteration, system fonts).")
    args = ap.parse_args()

    if args.refresh_contributions:
        refresh_contributions()

    if not args.skip_fonts:
        print("Subsetting fonts (Instrument Serif)…")
        FONT_CSS = "".join(subset_font(f) for f in FONTS)
    else:
        print("--skip-fonts: using system font fallbacks.")

    days  = clean_days(_load_json().get("days"))
    stats = contribution_stats(days)

    print("Rendering cards…")
    hero_card()
    for idx, tile in enumerate(TILES):
        tile_card(idx, tile)
    contribution_card(stats)
    for idx, repo in enumerate(FEATURED, 1):
        repo_card(idx, repo)
    graph_card(days)

    card_count = len(list(OUT.glob("*.svg")))

    if STATIC:
        (ROOT / "preview.html").write_text(_preview_html(), encoding="utf-8")
        print(f"STATIC=1: {card_count} cards → {OUT.name}/   preview.html written (README untouched).")
    else:
        (ROOT / "README.md").write_text(_readme(), encoding="utf-8")
        print(f"{card_count} cards → {OUT.name}/   README.md updated.")

    embedded = sorted(set(re.findall(r"font-family:'([^']+)'", FONT_CSS)))
    print(f"Embedded fonts : {embedded or ['none — system fallback']}")
    print(f"Stats summary  : {json.dumps({k: v for k, v in stats.items() if k != 'months'})}")


if __name__ == "__main__":
    main()
