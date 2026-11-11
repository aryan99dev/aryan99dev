#!/usr/bin/env python3
"""Render self-contained animated SVG cards for Aryan's GitHub profile README.

Usage
-----
  python scripts/render_cards.py                           # render from contribution-data.json
  python scripts/render_cards.py --refresh-contributions  # fetch live data, then render
  python scripts/render_cards.py --skip-fonts             # skip font subsetting (fast iteration)
  STATIC=1 python scripts/render_cards.py                 # final frame → cards-static/ + preview.html

Design contract
---------------
* Cards are shown through <img> tags, so no JS, no external requests, and no <a> links inside SVGs.
  Links live exclusively in README.md. All motion is CSS keyframes + SMIL so GitHub's img proxy
  keeps them intact and `prefers-reduced-motion` can disable everything in one media query.
* Fonts (Jost, Syne Mono) are subset with fontTools (pyftsubset) using only the glyphs actually
  present in the cards, then embedded as base64 WOFF2 data URIs so there are zero network requests.
* Contribution data is read from contribution-data.json, which a GitHub Action refreshes daily.
  The same Action then runs this script and commits the refreshed SVGs.
* STATIC=1 freezes every animation at its final frame so you can screenshot before pushing.
"""
from __future__ import annotations

import argparse
import base64
import calendar
import datetime as dt
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

# ═══════════════════════════════════════════════════════════════════════ CONFIG

ROOT = Path(__file__).resolve().parents[1]
STATIC = os.getenv("STATIC", "0") == "1"
OUT    = ROOT / ("cards-static" if STATIC else "cards")
DATA_FILE          = ROOT / "contribution-data.json"
PORTRAIT_CANDIDATES = [ROOT / "assets" / "profile.png", ROOT / "assets" / "profile.jpg"]

# ── identity ─────────────────────────────────────────────────────────────────
USERNAME = "aryan99dev"
NAME     = "Aryan Sharma"
ROLE     = "Full-stack developer  ·  BCA student"
INTRO    = "I build modern web apps, learn new technologies and create useful digital experiences."
META     = "SHOOLINI UNIVERSITY  ·  INDIA"
EMAIL    = "aryan99dev00@gmail.com"

# ── palette  (matches the portfolio site) ────────────────────────────────────
# Dark-space near-blacks
BG_DEEP  = "#0b0a1a"   # richest dark for the gradient start
BG_BASE  = "#09090b"   # near-black base

# Brand colours (indigo → purple → cyan arc)
INDIGO   = "#312e81"   # deep indigo (contribution level 1)
INDIGO_M = "#4c46b6"   # medium indigo (level 2)
PURPLE   = "#8b7cff"   # brand purple accent
CYAN     = "#06b6d4"   # brand cyan accent

# Text & structural
TEXT     = "#f4f4ff"   # near-white body text
MUTED    = "#a1a1b5"   # subdued secondary text
BORDER   = "#1e1c3a"   # subtle card border (more visible than before)
EMPTY    = "#18181d"   # empty contribution cell

# Five-level contribution ramp: level 0 (empty) → 4 (peak)
LEVELS   = [EMPTY, INDIGO, INDIGO_M, PURPLE, CYAN]

# ── featured repos ───────────────────────────────────────────────────────────
FEATURED = [
    ("Portfolio",
     "Personal site built with Next.js and React, with modern UI and animation techniques.",
     "Next.js · React · TypeScript",
     f"https://github.com/{USERNAME}/Portfolio"),
    ("Prism",
     "Modern social platform: authentication, profiles, posts, real-time updates, interactive UI.",
     "React · TypeScript · Vite · Tailwind CSS · Appwrite",
     f"https://github.com/{USERNAME}/Prism"),
    ("Movie-App",
     "Movie discovery app — search, details, responsive card grid.",
     "React · Vite",
     f"https://github.com/{USERNAME}/Movie-App"),
]

# ── tiles (file, eyebrow, title, detail, href, alt-text) ─────────────────────
TILES = [
    ("tile-build.svg",
     "01 / MAKE", "BUILD", "Portfolio & projects",
     f"https://github.com/{USERNAME}/Portfolio",
     "Build — view the portfolio repository"),
    ("tile-explore.svg",
     "02 / LEARN", "EXPLORE", "All repositories",
     f"https://github.com/{USERNAME}?tab=repositories",
     "Explore — all repositories"),
    ("tile-connect.svg",
     "03 / SAY HI", "CONNECT", "Let's make something",
     f"mailto:{EMAIL}",
     "Connect — send an email"),
]

# ── fonts ─────────────────────────────────────────────────────────────────────
FONTS = {
    "Jost":      ("Jost:wght@400;700", [400, 700]),
    "Syne Mono": ("Syne+Mono",         [400]),
}
# BMP Latin, mid-dot, em-dash, right-single-quote, degree – covers every glyph we use
UNICODES  = "U+0020-007E,U+00B7,U+00B0,U+2014,U+2019"
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Module-level font CSS; filled by main() and shared across all card builders.
FONT_CSS = ""

# ═══════════════════════════════════════════════════════════════════════ DATA

def refresh_contributions() -> None:
    """Fetch last-year contribution calendar via GitHub GraphQL. Never crashes the render."""
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        print("::warning::No GH_TOKEN/GITHUB_TOKEN — keeping existing contribution-data.json.",
              file=sys.stderr)
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
        print(f"::warning::Contribution refresh failed ({exc}) — keeping existing data.",
              file=sys.stderr)
        return

    old = _load_json()
    if old.get("days") == days:
        print("Contribution data unchanged — skipping write (no pointless daily commit).")
        return
    DATA_FILE.write_text(
        json.dumps({
            "username": USERNAME,
            "updated_at": end.isoformat(),
            "total_contributions": cal["totalContributions"],
            "days": days,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {DATA_FILE.name}: {len(days)} days, {cal['totalContributions']} contributions.")


def _load_json() -> dict:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def clean_days(raw) -> list[tuple[dt.date, int]]:
    """Normalise raw JSON rows → sorted (date, count), silently dropping malformed ones."""
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
    """Compute all dashboard stats from the data window (last 12 calendar months)."""
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
            name = calendar.day_name[d.weekday()]
            weekday_sum[name]  += c
            weekday_days[name] += 1

    active = {d for d, c in window if c}
    # a quiet "today" does not break a streak in progress
    cursor = today if today in active else today - dt.timedelta(days=1)
    streak = 0
    while cursor in active:
        streak += 1
        cursor -= dt.timedelta(days=1)

    months = [(calendar.month_abbr[m], per_month.get((y, m), 0))
              for y, m in months_keys]
    busiest = (max(weekday_sum, key=lambda k: (weekday_sum[k], weekday_days[k]))
               if weekday_sum else "None yet")
    return {
        "months":      months,
        "streak":      streak,
        "active_days": len(active),
        "busiest":     busiest,
        "total":       sum(c for _, c in window),
        "max_month":   max(v for _, v in months) or 1,
        "range":       (f"{calendar.month_abbr[months_keys[0][1]]} {months_keys[0][0]}"
                        f" – "
                        f"{calendar.month_abbr[months_keys[-1][1]]} {months_keys[-1][0]}"),
    }

# ═══════════════════════════════════════════════════════════════════ FONTS

def _google_font_files(family: str) -> list[tuple[int, bytes]]:
    spec, _ = FONTS[family]
    req  = urllib.request.Request(
        f"https://fonts.googleapis.com/css2?family={spec}&display=swap",
        headers={"User-Agent": CHROME_UA},
    )
    css  = urllib.request.urlopen(req, timeout=20).read().decode()
    out  = []
    for subset, block in re.findall(
            r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", css, re.S):
        if subset != "latin":
            continue
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url    = re.search(r"url\((https://[^)]+)\)", block)
        if url:
            data = urllib.request.urlopen(url.group(1), timeout=20).read()
            out.append((int(weight.group(1)) if weight else 400, data))
    return out


def _local_font_files(family: str) -> list[tuple[int, bytes]]:
    stem  = family.replace(" ", "").lower()
    fonts_dir = ROOT / "assets" / "fonts"
    if not fonts_dir.exists():
        return []
    out = []
    for p in sorted(fonts_dir.glob("*")):
        if p.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}:
            n = p.name.lower().replace("-", "")
            if n.startswith(stem):
                out.append((700 if "bold" in p.name.lower() else 400, p.read_bytes()))
    return out


def subset_font(family: str) -> str:
    """Return @font-face CSS with subsetted base64 font data, or '' if unavailable."""
    try:
        sources = _google_font_files(family)
    except Exception as exc:
        print(f"Google Fonts unavailable for {family} ({exc}); trying assets/fonts/",
              file=sys.stderr)
        sources = []
    sources = sources or _local_font_files(family)
    if not sources:
        print(f"::warning::No font source for {family}; cards fall back to system fonts.",
              file=sys.stderr)
        return ""

    try:
        import brotli  # noqa: F401
        flavor, mime = "woff2", "font/woff2"
    except ImportError:
        flavor, mime = "woff", "font/woff"

    css = ""
    with tempfile.TemporaryDirectory() as tmp:
        for i, (weight, data) in enumerate(sources):
            src = Path(tmp, f"src{i}")
            dst = Path(tmp, f"out{i}.{flavor}")
            src.write_bytes(data)
            proc = subprocess.run(
                [sys.executable, "-m", "fontTools.subset", str(src),
                 f"--unicodes={UNICODES}",
                 f"--output-file={dst}",
                 f"--flavor={flavor}",
                 "--layout-features=*",
                 "--name-IDs=0,1,2,4,6"],
                capture_output=True, text=True,
            )
            if proc.returncode or not dst.exists():
                print(f"::warning::pyftsubset failed for {family} {weight}: "
                      f"{proc.stderr.strip()[:300]}", file=sys.stderr)
                continue
            b64 = base64.b64encode(dst.read_bytes()).decode()
            css += (
                f"@font-face{{font-family:'{family}';font-weight:{weight};"
                f"font-style:normal;"
                f"src:url(data:{mime};base64,{b64}) format('{flavor}')}}"
            )
    return css

# ═══════════════════════════════════════════════════════════════════ SVG HELPERS

def _css_keyframes() -> str:
    """All shared keyframes + utility classes. Empty string in STATIC mode."""
    if STATIC:
        return ""
    return (
        # ── entrance: slide up from 16 px below, fade in
        "@keyframes rise{"
            "from{opacity:0;transform:translateY(16px)}"
            "to{opacity:1;transform:translateY(0)}"
        "}"
        # ── bar chart: scale up from baseline (transform-origin set per-element)
        "@keyframes grow{"
            "from{transform:scaleY(0)}"
            "to{transform:scaleY(1)}"
        "}"
        # ── ambient glow blob pulsing
        "@keyframes pulse{"
            "0%,100%{opacity:.28}"
            "50%{opacity:.70}"
        "}"
        # ── accent dot / SMIL fallback blink
        "@keyframes blink{"
            "0%,100%{opacity:.18}"
            "50%{opacity:1}"
        "}"
        # ── underline expands from left
        "@keyframes wipe{"
            "from{transform:scaleX(0)}"
            "to{transform:scaleX(1)}"
        "}"
        # utility classes
        ".enter{animation:rise .80s cubic-bezier(.2,.75,.25,1) both}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;"
              "animation:grow .90s cubic-bezier(.2,.75,.25,1) both}"
        ".pulse{animation:pulse 4s ease-in-out infinite}"
        ".blink{animation:blink 2.8s ease-in-out infinite}"
        ".wipe{transform-origin:left center;animation:wipe .6s ease both}"
        # kill all motion under prefers-reduced-motion
        "@media(prefers-reduced-motion:reduce){"
            "*{animation:none!important;transition:none!important}"
            "animate{display:none}"
        "}"
    )


def _svg_open(w: int, h: int, label: str, glow_x: int | None = None) -> str:
    """Return the opening SVG tag, defs, shared style block, background rect, and glow blobs."""
    gx    = glow_x if glow_x is not None else w - 60
    anim  = _css_keyframes()
    pulse = "" if STATIC else ' class="pulse"'

    defs = (
        # background gradient: very deep indigo → near-black
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{BG_DEEP}"/>'
        f'<stop offset="1" stop-color="{BG_BASE}"/>'
        f'</linearGradient>'
        # accent: purple → cyan (used for underlines, arrows, stat values)
        f'<linearGradient id="ac" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{PURPLE}"/>'
        f'<stop offset="1" stop-color="{CYAN}"/>'
        f'</linearGradient>'
        # bar gradient: indigo base → purple mid → cyan peak
        f'<linearGradient id="bar" x1="0" y1="1" x2="0" y2="0">'
        f'<stop offset="0" stop-color="{INDIGO}"/>'
        f'<stop offset=".5" stop-color="{PURPLE}"/>'
        f'<stop offset="1" stop-color="{CYAN}"/>'
        f'</linearGradient>'
        # soft glow blur
        f'<filter id="glow" x="-60%" y="-60%" width="220%" height="220%">'
        f'<feGaussianBlur stdDeviation="32"/>'
        f'</filter>'
        # card clip
        f'<clipPath id="card"><rect width="{w}" height="{h}" rx="20"/></clipPath>'
    )

    style = (
        f'<style>'
        f'{FONT_CSS}'
        f'text{{font-family:Jost,"Segoe UI",Arial,sans-serif}}'
        f'.mono{{font-family:"Syne Mono","SFMono-Regular",Consolas,monospace}}'
        f'.t{{fill:{TEXT}}}'
        f'.m{{fill:{MUTED}}}'
        f'.p{{fill:{PURPLE}}}'
        f'.c{{fill:{CYAN}}}'
        f'{anim}'
        f'</style>'
    )

    # Two decorative glow blobs per card (top-right accent, bottom-left cyan hint)
    blobs = (
        f'<circle{pulse} cx="{gx}" cy="10" r="80" fill="{PURPLE}" opacity=".22" filter="url(#glow)"/>'
        f'<circle cx="30" cy="{h}" r="60" fill="{CYAN}" opacity=".07" filter="url(#glow)"/>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">'
        f'<defs>{defs}</defs>'
        f'{style}'
        f'<g clip-path="url(#card)">'
        f'<rect width="{w}" height="{h}" fill="url(#bg)"/>'
        f'{blobs}'
        f'</g>'
        # border sits on top of clip (so it's never clipped itself)
        f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="20" '
        f'fill="none" stroke="{BORDER}" stroke-width="1"/>'
    )


def _enter(delay: float) -> str:
    """Open an animated entrance group (or a plain <g> in STATIC mode)."""
    if STATIC:
        return "<g>"
    return f'<g class="enter" style="animation-delay:{delay:.2f}s">'


def _arrow(x: float, y: float, color: str = PURPLE, size: float = 10) -> str:
    """Small ↗ arrow indicator at (x, y)."""
    s = size
    return (
        f'<path d="M{x} {y+s} L{x+s} {y} M{x+.5} {y} H{x+s} V{y+s-.5}" '
        f'fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
    )


def _underline(x: float, y: float, w: float, color: str = "url(#ac)",
               delay: float = 0.0) -> str:
    """Animated expanding underline bar."""
    cls  = "" if STATIC else f' class="wipe" style="animation-delay:{delay:.2f}s"'
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="2.5" '
        f'rx="1.25" fill="{color}"{cls}/>'
    )


def _save(name: str, svg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(svg + "</svg>\n", encoding="utf-8")

# ═══════════════════════════════════════════════════════════════════ CARDS

# ── 1. Hero ──────────────────────────────────────────────────────────────────

def hero_card() -> None:
    """
    Layout (900 × 260)
    ──────────────────
    y=52   HELLO, WORLD / I'M      (Syne Mono, purple, 13 px, 3 ls)
    y=130  Aryan Sharma            (Jost 700, 60 px, near-white)
    y=148  ───── accent bar ─────
    y=179  Full-stack developer…   (Jost 400, 20 px, muted)
    y=206  intro sentence          (Jost 400, 14.5 px, muted)
    y=234  SHOOLINI UNIVERSITY…   (Syne Mono, cyan, 11 px, 2.5 ls)
           optional portrait (right, cx=800)
    """
    portrait = next((p for p in PORTRAIT_CANDIDATES if p.exists()), None)
    img_defs  = ""
    img_els   = ""
    right_pad = 900

    if portrait:
        mime  = "image/png" if portrait.suffix.lower() == ".png" else "image/jpeg"
        data  = base64.b64encode(portrait.read_bytes()).decode()
        right_pad = 740   # keep text from overlapping the portrait
        img_defs  = '<clipPath id="pc"><circle cx="800" cy="130" r="68"/></clipPath>'
        img_els   = (
            f'<image href="data:{mime};base64,{data}" '
            f'x="732" y="62" width="136" height="136" '
            f'preserveAspectRatio="xMidYMid slice" clip-path="url(#pc)"/>'
            f'<circle cx="800" cy="130" r="71" fill="none" stroke="url(#ac)" stroke-width="1.5"/>'
            # pulsing ring
            f'<circle cx="800" cy="130" r="71" fill="none" stroke="{CYAN}" stroke-width="1" opacity="0">'
            + ("" if STATIC else
               f'<animate attributeName="opacity" values="0;.6;0" dur="3.5s" '
               f'repeatCount="indefinite" begin="0.5s"/>'
               f'<animate attributeName="r" values="71;78;71" dur="3.5s" '
               f'repeatCount="indefinite" begin="0.5s"/>')
            + f'</circle>'
        )

    # pulsing accent dot (top-right corner hint)
    dot = (
        f'<circle cx="862" cy="22" r="3.5" fill="{CYAN}" opacity=".8">'
        + ("" if STATIC else
           '<animate attributeName="opacity" values=".15;1;.15" dur="2.6s" '
           'repeatCount="indefinite"/>')
        + "</circle>"
    )

    s = _svg_open(900, 260, f"{NAME} — {ROLE}")
    if img_defs:
        s += f"<defs>{img_defs}</defs>"
    s += _enter(0.0)
    s += (
        f'<text x="48" y="52" class="mono p" font-size="13" letter-spacing="3">'
        f'HELLO, WORLD / I\'M</text>'
        f'<text x="46" y="130" class="t" font-size="60" font-weight="700">{escape(NAME)}</text>'
        + _underline(48, 143, 72, delay=0.4)
        + f'<text x="48" y="179" class="m" font-size="20">{escape(ROLE)}</text>'
        f'<text x="48" y="206" class="m" font-size="14.5">{escape(INTRO)}</text>'
        f'<text x="48" y="234" class="mono c" font-size="11" letter-spacing="2.5">'
        f'{escape(META)}</text>'
        + img_els
        + "</g>"
        + dot
    )
    _save("hero.svg", s)


# ── 2. Tiles ─────────────────────────────────────────────────────────────────

def tile_card(i: int, tile: tuple) -> None:
    """
    Layout (300 × 136) — compact square tile
    ─────────────────────────────────────────
    y=32  01 / MAKE   (mono, purple, 11 px, 2 ls)
    y=76  BUILD       (Jost 700, 28 px)
         ── bar ──
    y=108 detail      (muted, 13 px)
    ↗ arrow top-right
    """
    file, eyebrow, title, detail, _href, _alt = tile
    s = _svg_open(300, 136, title, glow_x=240)
    s += _enter(0.35 + i * 0.14)
    s += (
        f'<text x="22" y="32" class="mono p" font-size="11" letter-spacing="2">'
        f'{escape(eyebrow)}</text>'
        f'<text x="22" y="76" class="t" font-size="28" font-weight="700">'
        f'{escape(title)}</text>'
        + _underline(22, 83, 36, delay=0.5 + i * 0.14)
        + f'<text x="22" y="108" class="m" font-size="13">{escape(detail)}</text>'
        + _arrow(258, 20, CYAN)
        + "</g>"
    )
    _save(file, s)


# ── 3. Contributions chart ────────────────────────────────────────────────────

def contribution_card(st: dict) -> None:
    """
    Layout (900 × 300)
    ──────────────────
    Header row: title + 3 stat badges
    Bar chart (12 months) with grow animation
    Footer: summary line
    """
    s = _svg_open(900, 300, "Contribution analytics")
    s += _enter(0.80)

    # ── header ──
    s += (
        f'<text x="34" y="44" class="t" font-size="22" font-weight="700" letter-spacing=".5">'
        f'CONTRIBUTION PULSE</text>'
        f'<text x="34" y="68" class="m" font-size="13">'
        f'Real GitHub activity · last 12 months</text>'
    )

    # ── stat badges ──
    badges = [
        (str(st["streak"]),      "DAY STREAK"),
        (str(st["active_days"]), "ACTIVE DAYS"),
        (st["busiest"],          "BUSIEST WEEKDAY"),
    ]
    for j, (val, lab) in enumerate(badges):
        bx = 476 + j * 142
        s += (
            f'<rect x="{bx-8}" y="22" width="{max(len(val)*13, len(lab)*7)+18}" '
            f'height="52" rx="10" fill="{BORDER}" opacity=".8"/>'
            f'<text x="{bx}" y="46" class="p" font-size="22" font-weight="700">'
            f'{escape(val)}</text>'
            f'<text x="{bx}" y="66" class="mono m" font-size="9" letter-spacing="1">'
            f'{lab}</text>'
        )

    # ── bar chart ──
    cx, cy, cw, ch, gap = 42, 100, 816, 140, 12
    months = st["months"]
    bw     = (cw - gap * (len(months) - 1)) / len(months)

    # baseline
    s += (
        f'<line x1="{cx}" y1="{cy+ch}" x2="{cx+cw}" y2="{cy+ch}" '
        f'stroke="{BORDER}" stroke-width="1.5"/>'
    )

    for k, (m, v) in enumerate(months):
        bar_h = max(3.0, ch * v / st["max_month"]) if v else 3.0
        bx    = cx + k * (bw + gap)
        by    = cy + ch - bar_h

        # filled bar (always visible — STATIC-safe final state)
        # animated bar on top using SMIL
        fill  = f"url(#bar)" if v else EMPTY
        s += f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" rx="5" fill="{fill}"/>'

        if not STATIC:
            # SMIL animate so GitHub's img proxy keeps the motion
            begin = f"{1.0 + k * 0.07:.2f}s"
            s += (
                f'<rect x="{bx:.1f}" y="{cy+ch}" width="{bw:.1f}" height="0" rx="5" fill="{fill}">'
                f'<animate attributeName="height" from="0" to="{bar_h:.1f}" '
                f'dur=".75s" begin="{begin}" fill="freeze"/>'
                f'<animate attributeName="y" from="{cy+ch}" to="{by:.1f}" '
                f'dur=".75s" begin="{begin}" fill="freeze"/>'
                f'</rect>'
            )

        # value label above bar
        if v:
            s += (
                f'<text x="{bx+bw/2:.1f}" y="{by-5:.1f}" text-anchor="middle" '
                f'class="mono t" font-size="10">{v}</text>'
            )
        # month label below baseline
        s += (
            f'<text x="{bx+bw/2:.1f}" y="{cy+ch+16}" text-anchor="middle" '
            f'class="mono m" font-size="10">{m}</text>'
        )

    # ── footer ──
    note = (
        f'{st["total"]} contributions  ·  {st["range"]}'
        if st["total"] else
        "No contribution data yet — the next scheduled refresh will fill this in."
    )
    s += (
        f'<text x="42" y="284" class="mono m" font-size="11">{escape(note)}</text>'
        f'</g>'
    )
    _save("contributions.svg", s)


# ── 4. Repo cards ─────────────────────────────────────────────────────────────

def repo_card(i: int, repo: tuple) -> None:
    """
    Layout (900 × 158)
    ──────────────────
    y=38   FEATURED REPOSITORY / 0N   (mono, purple, 11 px)
    y=82   Repo Name                  (Jost 700, 30 px)
    y=100  ── bar ──
    y=116  Description                (muted, 14 px)
    y=138  stack · line               (mono, cyan, 11 px, 1 ls)
    ↗ arrow right
    """
    name, desc, stack, _url = repo
    s = _svg_open(900, 158, f"{name} — featured repository")
    s += _enter(1.5 + i * 0.22)
    s += (
        f'<text x="32" y="38" class="mono p" font-size="11" letter-spacing="2">'
        f'FEATURED REPOSITORY / 0{i}</text>'
        f'<text x="32" y="82" class="t" font-size="30" font-weight="700">'
        f'{escape(name)}</text>'
        + _underline(32, 92, 48, delay=1.6 + i * 0.22)
        + f'<text x="32" y="116" class="m" font-size="14">{escape(desc)}</text>'
        f'<text x="32" y="138" class="mono c" font-size="11" letter-spacing="1">'
        f'{escape(stack)}</text>'
        + _arrow(850, 68, PURPLE)
        + "</g>"
    )
    _save(f"repo-{i}-{_slug(name)}.svg", s)


# ── 5. Contribution graph (heat-map) ─────────────────────────────────────────

def graph_card(days: list[tuple[dt.date, int]]) -> None:
    """
    GitHub-style 52-week contribution heat-map rendered in brand colours.
    Layout (900 × 238)
    """
    today  = dt.datetime.now(dt.timezone.utc).date()
    counts = dict(days)

    # Align start to the Sunday on or before 52 weeks ago
    start = today - dt.timedelta(weeks=52)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)

    total_days = 53 * 7
    mx = max(
        [counts.get(start + dt.timedelta(days=k), 0) for k in range(total_days)] + [1]
    )

    s   = _svg_open(900, 238, "GitHub contribution graph — last 52 weeks")
    s  += _enter(2.4)
    s  += (
        f'<text x="34" y="40" class="t" font-size="21" font-weight="700" letter-spacing=".5">'
        f'THE CONSISTENCY MAP</text>'
        f'<text x="34" y="62" class="m" font-size="13">'
        f'Daily contribution activity — last 52 weeks</text>'
    )

    pitch, x0, y0 = 15, 34, 90
    last_month = None
    cells = []

    for k in range(total_days):
        d   = start + dt.timedelta(days=k)
        col, row = divmod(k, 7)

        # month label (Sunday of that week, only if changed and not in future)
        if row == 0 and d.month != last_month and d <= today:
            last_month = d.month
            s += (
                f'<text x="{x0 + col * pitch}" y="82" class="mono m" font-size="9">'
                f'{calendar.month_abbr[d.month].upper()}</text>'
            )

        if d > today:
            continue

        c   = counts.get(d, 0)
        lvl = 0 if c == 0 else min(4, 1 + int(3.999 * c / mx))
        cx2  = x0 + col * pitch
        cy2  = y0 + row * pitch
        cells.append((cx2, cy2, LEVELS[lvl], d, c))

    # Render cells — static fills + optional SMIL entrance stagger
    for idx, (cx2, cy2, color, d, c) in enumerate(cells):
        col_idx = (cx2 - x0) // pitch   # week column index for stagger
        s += (
            f'<rect x="{cx2}" y="{cy2}" width="12" height="12" rx="3" fill="{color}">'
            f'<title>{d.isoformat()}: {c} contribution{"s" if c != 1 else ""}</title>'
        )
        if not STATIC and c > 0:
            begin = f"{2.6 + col_idx * 0.015:.3f}s"
            s += (
                f'<animate attributeName="opacity" values="0;1" '
                f'dur=".35s" begin="{begin}" fill="freeze"/>'
            )
        s += "</rect>"

    # legend
    s += f'<text x="34" y="220" class="mono m" font-size="10" letter-spacing="1">LESS</text>'
    for k, col in enumerate(LEVELS):
        s += f'<rect x="{82 + k*18}" y="210" width="12" height="12" rx="3" fill="{col}"/>'
    s += (
        f'<text x="{82 + len(LEVELS)*18 + 4}" y="220" class="mono m" '
        f'font-size="10" letter-spacing="1">MORE</text>'
        f'</g>'
    )
    _save("contribution-graph.svg", s)

# ═══════════════════════════════════════════════════════════════════ README

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _readme() -> str:
    tiles = "\n".join(
        f'<a href="{t[4]}"><img src="cards/{t[0]}" width="32.5%" alt="{escape(t[5])}" /></a>'
        for t in TILES
    )
    repos = "\n".join(
        f'<a href="{r[3]}"><img src="cards/repo-{i}-{_slug(r[0])}.svg" '
        f'width="100%" alt="{escape(r[0])} repository: {escape(r[2])}" /></a>'
        for i, r in enumerate(FEATURED, 1)
    )
    return (
        f'<div align="center">\n\n'
        f'<img src="cards/hero.svg" width="100%" alt="{escape(NAME)}, {escape(ROLE)}" />\n\n'
        f'{tiles}\n\n'
        f'<img src="cards/contributions.svg" width="100%" '
        f'alt="Monthly contributions, current streak, active days and busiest weekday" />\n\n'
        f'</div>\n\n'
        f'## Selected work\n\n'
        f'{repos}\n\n'
        f'<div align="center">\n\n'
        f'<img src="cards/contribution-graph.svg" width="100%" '
        f'alt="Contribution graph — last 52 weeks" />\n\n'
        f'[GitHub](https://github.com/{USERNAME})'
        f' · [Portfolio repository](https://github.com/{USERNAME}/Portfolio)'
        f' · [Business email](mailto:{EMAIL})\n\n'
        f'</div>\n\n'
        f'<!-- Cards are generated by scripts/render_cards.py.'
        f' Edit FEATURED and visual settings there. -->\n'
    )


def _preview_html() -> str:
    names = (
        ["hero.svg"]
        + [t[0] for t in TILES]
        + ["contributions.svg"]
        + [f"repo-{i}-{_slug(r[0])}.svg" for i, r in enumerate(FEATURED, 1)]
        + ["contribution-graph.svg"]
    )
    imgs = "".join(f'<img src="cards-static/{n}" alt="{n}">' for n in names)
    return (
        '<!doctype html><meta charset="utf-8"><title>Static card preview</title>'
        '<style>'
        'body{background:#0b0a1a;margin:0;padding:24px}'
        '.w{max-width:900px;margin:auto;display:flex;flex-wrap:wrap;gap:10px}'
        'img{width:100%}'
        'img[src*="tile-"]{width:calc(33.33% - 7px)}'
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
                    help="Skip font subsetting (uses system fallbacks — fast for iteration).")
    args = ap.parse_args()

    if args.refresh_contributions:
        refresh_contributions()

    if not args.skip_fonts:
        print("Subsetting fonts (this takes a few seconds)…")
        FONT_CSS = "".join(subset_font(f) for f in FONTS)
    else:
        print("--skip-fonts: using system font fallbacks.")

    days  = clean_days(_load_json().get("days"))
    stats = contribution_stats(days)

    # Render all cards
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
        print(
            f"STATIC=1 mode: {card_count} cards → {OUT.name}/   preview.html written.\n"
            f"README.md not modified."
        )
    else:
        (ROOT / "README.md").write_text(_readme(), encoding="utf-8")
        print(f"{card_count} cards → {OUT.name}/   README.md updated.")

    embedded = sorted(set(re.findall(r"font-family:'([^']+)'", FONT_CSS)))
    print(f"Embedded fonts : {embedded or ['none — system fallback']}")
    print(f"Stats summary  : {json.dumps({k: v for k, v in stats.items() if k != 'months'})}")


if __name__ == "__main__":
    main()
