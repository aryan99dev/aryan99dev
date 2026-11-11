#!/usr/bin/env python3
"""Render self-contained animated SVG cards for aryan99dev's GitHub profile README.

Design language: terminal-meets-editorial (inspired by avivashishta.com)
─────────────────────────────────────────────────────────────────────────
  • Dark terminal base  (#0d1117) + warm paper accent (#fdfbf7 highlights)
  • Instrument Serif (editorial headings) + JetBrains Mono (terminal metadata)
  • Three-colour accent system:  BUILD → blue  BRAND/CONNECT → red  EXPLORE/LEARN → amber
  • Cards feel like terminal windows: rounded rects with a subtle header bar,
    prompt-string decoration, and line-by-line typewriter entrance animations
  • ASCII/neofetch side card rendered as monospace text grid in hero
  • All motion: CSS keyframes (rise, type, blink, bar-grow) + SMIL (bar grow,
    cursor blink, cell fade) so GitHub's img proxy keeps it
  • prefers-reduced-motion: kills all animation, final frame is always visible
  • Fonts subset via pyftsubset → base64 WOFF2 data URIs (no network in browser)

Usage
─────
  python scripts/render_cards.py                           # render from JSON
  python scripts/render_cards.py --refresh-contributions  # fetch + render
  python scripts/render_cards.py --skip-fonts             # fast, system fonts
  STATIC=1 python scripts/render_cards.py --skip-fonts   # screenshot mode
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

# ═══════════════════════════════════════════════════════════════════ CONFIG

ROOT   = Path(__file__).resolve().parents[1]
STATIC = os.getenv("STATIC", "0") == "1"
OUT    = ROOT / ("cards-static" if STATIC else "cards")
DATA_FILE           = ROOT / "contribution-data.json"
PORTRAIT_CANDIDATES = [ROOT / "assets" / "profile.png", ROOT / "assets" / "profile.jpg"]

# ── identity ──────────────────────────────────────────────────────────────────
USERNAME = "aryan99dev"
NAME     = "Aryan Sharma"
ROLE     = "Full-stack developer  ·  BCA student"
INTRO    = "I build modern web apps, learn new technologies and create useful digital experiences."
META     = "Shoolini University  ·  India"
EMAIL    = "aryan99dev00@gmail.com"

# ── Avi Vashishta design system ───────────────────────────────────────────────
# Dark terminal base
BG       = "#0d1117"      # GitHub dark background
BG2      = "#161b22"      # card surface (slightly lighter)
BG3      = "#21262d"      # header bar / subtle surface
BORDER   = "#30363d"      # border (GitHub dark)

# Text
TEXT     = "#e6edf3"      # near-white primary
TEXT_DIM = "#8b949e"      # GitHub muted grey
TEXT_MUT = "#6e7681"      # very muted

# Three-world accent system (BUILD / EXPLORE / CONNECT)
BLUE     = "#3b82f6"      # BUILD — electric blue
BLUE_D   = "#1d4ed8"      # blue dark variant
RED      = "#ef4444"      # CONNECT / BRAND — crimson
RED_D    = "#b91c1c"
AMBER    = "#f59e0b"      # EXPLORE / LEARN — warm amber
AMBER_D  = "#b45309"

# Contribution graph ramp  (empty → peak)  in blue
EMPTY    = "#161b22"
LEVELS   = [EMPTY, "#0e3463", "#1d4ed8", "#3b82f6", "#93c5fd"]

# Tile accent map
TILE_ACCENTS = [
    (BLUE,  BG2),   # BUILD
    (AMBER, BG2),   # EXPLORE
    (RED,   BG2),   # CONNECT
]

# ── featured repos ────────────────────────────────────────────────────────────
FEATURED = [
    ("Portfolio",
     "Personal site built with Next.js and React, with modern UI and animation techniques.",
     "Next.js · React · TypeScript",
     f"https://github.com/{USERNAME}/Portfolio",
     BLUE),
    ("Prism",
     "Modern social platform: auth, profiles, posts, real-time updates, interactive UI.",
     "React · TypeScript · Vite · Tailwind CSS · Appwrite",
     f"https://github.com/{USERNAME}/Prism",
     AMBER),
    ("Movie-App",
     "Movie discovery app — search, details, responsive card grid.",
     "React · Vite",
     f"https://github.com/{USERNAME}/Movie-App",
     RED),
]

# ── tiles  (file, eyebrow, title, detail, href, alt, accent) ─────────────────
TILES = [
    ("tile-build.svg",
     "01 / BUILD", "BUILD", "Portfolio & projects",
     f"https://github.com/{USERNAME}/Portfolio",
     "Build — view the portfolio repository",
     BLUE),
    ("tile-explore.svg",
     "02 / EXPLORE", "EXPLORE", "All repositories",
     f"https://github.com/{USERNAME}?tab=repositories",
     "Explore — all repositories",
     AMBER),
    ("tile-connect.svg",
     "03 / CONNECT", "CONNECT", "Let's make something",
     f"mailto:{EMAIL}",
     "Connect — send an email",
     RED),
]

# ── fonts ─────────────────────────────────────────────────────────────────────
# Instrument Serif for editorial headings, JetBrains Mono for terminal metadata
FONTS = {
    "Instrument Serif": ("Instrument+Serif", [400]),
    "JetBrains Mono":   ("JetBrains+Mono:wght@400;500", [400, 500]),
}
UNICODES  = "U+0020-007E,U+00B7,U+00B0,U+2014,U+2019,U+25CF,U+25CB,U+2502,U+2500,U+256D,U+256E,U+2570,U+256F"
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

FONT_CSS = ""   # filled by main()

# ── neofetch ASCII info lines ─────────────────────────────────────────────────
NEOFETCH_LINES = [
    ("OS",       "Arch Linux (Hackintosh)",),
    ("Host",     f"github.com/{USERNAME}",),
    ("Role",     "Full-stack dev · BCA",),
    ("Stack",    "React · Next.js · TypeScript",),
    ("Editor",   "VS Code",),
    ("Location", "India",),
    ("Email",    EMAIL,),
]

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

def _google_font_files(family: str) -> list[tuple[int, bytes]]:
    spec, _ = FONTS[family]
    req = urllib.request.Request(
        f"https://fonts.googleapis.com/css2?family={spec}&display=swap",
        headers={"User-Agent": CHROME_UA})
    css = urllib.request.urlopen(req, timeout=20).read().decode()
    out = []
    for subset, block in re.findall(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", css, re.S):
        if subset != "latin":
            continue
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url    = re.search(r"url\((https://[^)]+)\)", block)
        if url:
            data = urllib.request.urlopen(url.group(1), timeout=20).read()
            out.append((int(weight.group(1)) if weight else 400, data))
    return out


def _local_font_files(family: str) -> list[tuple[int, bytes]]:
    stem = family.replace(" ", "").lower()
    fonts_dir = ROOT / "assets" / "fonts"
    if not fonts_dir.exists():
        return []
    out = []
    for p in sorted(fonts_dir.glob("*")):
        if p.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}:
            n = p.name.lower().replace("-", "").replace("_", "")
            if n.startswith(stem.replace(" ", "")):
                out.append((700 if "bold" in p.name.lower() else 400, p.read_bytes()))
    return out


def subset_font(family: str) -> str:
    try:
        sources = _google_font_files(family)
    except Exception as exc:
        print(f"Google Fonts unavailable for {family} ({exc}); trying assets/fonts/", file=sys.stderr)
        sources = []
    sources = sources or _local_font_files(family)
    if not sources:
        print(f"::warning::No font source for {family}; falling back to system fonts.", file=sys.stderr)
        return ""
    try:
        import brotli  # noqa: F401
        flavor, mime = "woff2", "font/woff2"
    except ImportError:
        flavor, mime = "woff", "font/woff"
    css = ""
    with tempfile.TemporaryDirectory() as tmp:
        for i, (weight, data) in enumerate(sources):
            src = Path(tmp, f"src{i}"); dst = Path(tmp, f"out{i}.{flavor}")
            src.write_bytes(data)
            proc = subprocess.run(
                [sys.executable, "-m", "fontTools.subset", str(src),
                 f"--unicodes={UNICODES}", f"--output-file={dst}",
                 f"--flavor={flavor}", "--layout-features=*", "--name-IDs=0,1,2,4,6"],
                capture_output=True, text=True)
            if proc.returncode or not dst.exists():
                print(f"::warning::pyftsubset failed for {family} {weight}: "
                      f"{proc.stderr.strip()[:300]}", file=sys.stderr)
                continue
            b64 = base64.b64encode(dst.read_bytes()).decode()
            css += (f"@font-face{{font-family:'{family}';font-weight:{weight};"
                    f"font-style:normal;"
                    f"src:url(data:{mime};base64,{b64}) format('{flavor}')}}")
    return css

# ═══════════════════════════════════════════════════════════════════ SVG HELPERS

def _css_keyframes() -> str:
    if STATIC:
        return ""
    return (
        # entrance: fade + rise
        "@keyframes rise{"
            "from{opacity:0;transform:translateY(12px)}"
            "to{opacity:1;transform:translateY(0)}"
        "}"
        # typewriter: individual lines appear
        "@keyframes type{"
            "from{opacity:0}"
            "to{opacity:1}"
        "}"
        # cursor block blink
        "@keyframes cur{"
            "0%,49%{opacity:1}"
            "50%,100%{opacity:0}"
        "}"
        # bar grow from baseline (SMIL preferred; CSS fallback)
        "@keyframes grow{"
            "from{transform:scaleY(0)}"
            "to{transform:scaleY(1)}"
        "}"
        # prompt pulse — the coloured dot that blinks
        "@keyframes dot{"
            "0%,100%{opacity:.3}"
            "50%{opacity:1}"
        "}"
        # utility classes
        ".enter{animation:rise .65s cubic-bezier(.2,.75,.25,1) both}"
        ".tl{animation:type .15s linear both}"
        ".cursor{animation:cur .9s step-end infinite}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;"
              "animation:grow .8s cubic-bezier(.2,.75,.25,1) both}"
        ".dot{animation:dot 2.4s ease-in-out infinite}"
        "@media(prefers-reduced-motion:reduce){"
            "*{animation:none!important;transition:none!important}"
            "animate{display:none}"
        "}"
    )


def _svg_open(w: int, h: int, label: str) -> str:
    """Return opening SVG tag, defs, style block, and background."""
    anim = _css_keyframes()
    defs = (
        f'<linearGradient id="hdr" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{BG3}"/>'
        f'<stop offset="1" stop-color="{BG2}"/>'
        f'</linearGradient>'
        f'<clipPath id="card"><rect width="{w}" height="{h}" rx="12"/></clipPath>'
    )
    style = (
        f"<style>"
        f"{FONT_CSS}"
        f"text{{font-family:'JetBrains Mono','Fira Code','SFMono-Regular',Consolas,monospace}}"
        f".serif{{font-family:'Instrument Serif',Georgia,serif}}"
        f".t{{fill:{TEXT}}}.d{{fill:{TEXT_DIM}}}.m{{fill:{TEXT_MUT}}}"
        f".bl{{fill:{BLUE}}}.am{{fill:{AMBER}}}.rd{{fill:{RED}}}"
        f"{anim}"
        f"</style>"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">'
        f"<defs>{defs}</defs>"
        f"{style}"
        f'<g clip-path="url(#card)">'
        f'<rect width="{w}" height="{h}" fill="{BG}"/>'
        f'</g>'
        f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="12" '
        f'fill="none" stroke="{BORDER}" stroke-width="1"/>'
    )


def _term_header(w: int, title: str, dot_color: str = BLUE) -> str:
    """Terminal window title bar with coloured traffic-light dots."""
    dot_cls = "" if STATIC else ' class="dot"'
    return (
        f'<rect x="0" y="0" width="{w}" height="38" fill="{BG3}"/>'
        f'<rect x="0" y="37" width="{w}" height="1" fill="{BORDER}"/>'
        # traffic-light dots
        f'<circle cx="20" cy="19" r="6" fill="{RED}"{dot_cls}/>'
        f'<circle cx="40" cy="19" r="6" fill="{AMBER}"/>'
        f'<circle cx="60" cy="19" r="6" fill="{BLUE}"/>'
        # window title
        f'<text x="{w//2}" y="24" text-anchor="middle" class="d" font-size="12">'
        f'{escape(title)}</text>'
    )


def _prompt(x: float, y: float, cmd: str, accent: str = BLUE,
            delay: float = 0.0) -> str:
    """Render one terminal prompt line:  user@host ~ $ cmd"""
    cls = "" if STATIC else f' class="tl" style="animation-delay:{delay:.2f}s"'
    return (
        f'<text x="{x}" y="{y}"{cls} font-size="13">'
        f'<tspan fill="{accent}" font-weight="500">aryan</tspan>'
        f'<tspan fill="{TEXT_DIM}">@github</tspan>'
        f'<tspan fill="{TEXT_DIM}"> ~ </tspan>'
        f'<tspan fill="{TEXT_MUT}">$ </tspan>'
        f'<tspan fill="{TEXT}">{escape(cmd)}</tspan>'
        f'</text>'
    )


def _output_line(x: float, y: float, text: str, color: str = TEXT_DIM,
                 delay: float = 0.0, font_size: int = 12) -> str:
    cls = "" if STATIC else f' class="tl" style="animation-delay:{delay:.2f}s"'
    return (
        f'<text x="{x}" y="{y}"{cls} font-size="{font_size}" fill="{color}">'
        f'{escape(text)}</text>'
    )


def _cursor(x: float, y: float, delay: float = 0.0) -> str:
    if STATIC:
        return ""
    return (
        f'<rect x="{x}" y="{y-13}" width="8" height="15" fill="{TEXT_DIM}" opacity=".7"'
        f' class="cursor" style="animation-delay:{delay:.2f}s"/>'
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

# ── 1. Hero — terminal window with Instrument Serif name + neofetch panel ─────

def hero_card() -> None:
    """
    900 × 300  terminal window
    ──────────────────────────
    [header bar: traffic-light dots + "aryan@github: ~"]
    left column (px 20–460):  Instrument Serif name, typewriter prompt + intro
    right column (px 480–880): neofetch-style info panel
    optional: portrait (embedded) overlaid in right column
    """
    W, H = 900, 300
    s = _svg_open(W, H, f"{NAME} — {ROLE}")
    s += _term_header(W, f"{USERNAME}@github: ~", BLUE)

    # left column ─────────────────────────────────────────────────────────────
    s += _enter(0.0)

    # Serif name (editorial)
    s += (
        f'<text x="28" y="92" class="serif t" font-size="46" font-weight="400">'
        f'{escape(NAME)}</text>'
    )
    # thin rule under name
    s += (
        f'<rect x="28" y="100" width="300" height="1.5" fill="{BLUE}" opacity=".6"/>'
    )

    # typewriter role line
    role_delay = 0.15
    s += _prompt(28, 136, "./whoami.sh", BLUE, role_delay)

    # output lines (typewriter stagger)
    out_lines = [
        (ROLE, AMBER),
        (INTRO[:58] + ("…" if len(INTRO) > 58 else ""), TEXT_DIM),
        (META, TEXT_MUT),
    ]
    for i, (line, col) in enumerate(out_lines):
        s += _output_line(28, 158 + i * 22, line, col, role_delay + 0.25 + i * 0.18)

    # second prompt (ready cursor)
    prompt2_y = 236
    s += _prompt(28, prompt2_y, "", BLUE, role_delay + 0.9)
    s += _cursor(100, prompt2_y, role_delay + 0.9)

    # SMIL blinking accent dot (top-right status indicator)
    s += (
        f'<circle cx="872" cy="20" r="4" fill="{BLUE}" opacity=".8">'
        + ("" if STATIC else
           '<animate attributeName="opacity" values=".2;1;.2" dur="2.4s" '
           'repeatCount="indefinite"/>')
        + "</circle>"
    )

    s += "</g>"

    # right column — neofetch panel ──────────────────────────────────────────
    rx, ry0 = 490, 55
    s += (
        f'<rect x="{rx}" y="{ry0}" width="385" height="{H - ry0 - 16}" '
        f'rx="8" fill="{BG2}" stroke="{BORDER}" stroke-width="1"/>'
    )
    # neofetch header
    s += _enter(0.3)
    s += (
        f'<text x="{rx+16}" y="{ry0+24}" font-size="12" fill="{BLUE}" font-weight="500">'
        f'{USERNAME}@github</text>'
        f'<rect x="{rx+16}" y="{ry0+30}" width="120" height="1" fill="{BORDER}"/>'
    )
    # neofetch fields
    for j, (key, val) in enumerate(NEOFETCH_LINES):
        fy = ry0 + 52 + j * 26
        d  = 0.35 + j * 0.12
        cls = "" if STATIC else f' class="tl" style="animation-delay:{d:.2f}s"'
        s += (
            f'<text x="{rx+16}" y="{fy}"{cls} font-size="12">'
            f'<tspan fill="{BLUE}" font-weight="500">{escape(key):<10}</tspan>'
            f'<tspan fill="{TEXT_DIM}"> {escape(val)}</tspan>'
            f'</text>'
        )
    # colour palette swatches at the bottom of neofetch panel
    swatch_y = ry0 + H - ry0 - 24
    for k, col in enumerate([RED, AMBER, BLUE, "#a855f7", TEXT_MUT, TEXT_DIM]):
        s += f'<rect x="{rx+16+k*22}" y="{swatch_y}" width="14" height="10" rx="2" fill="{col}"/>'
    s += "</g>"

    # optional portrait (top-right corner of neofetch panel) ─────────────────
    portrait = next((p for p in PORTRAIT_CANDIDATES if p.exists()), None)
    if portrait:
        mime = "image/png" if portrait.suffix.lower() == ".png" else "image/jpeg"
        data = base64.b64encode(portrait.read_bytes()).decode()
        # small circular portrait top-right
        s += (
            f'<defs><clipPath id="pc"><circle cx="854" cy="80" r="30"/></clipPath></defs>'
            f'<image href="data:{mime};base64,{data}" '
            f'x="824" y="50" width="60" height="60" '
            f'preserveAspectRatio="xMidYMid slice" clip-path="url(#pc)"/>'
            f'<circle cx="854" cy="80" r="31" fill="none" stroke="{BLUE}" stroke-width="1.5"/>'
        )

    _save("hero.svg", s)


# ── 2. Tiles ─────────────────────────────────────────────────────────────────

def tile_card(i: int, tile: tuple) -> None:
    """
    300 × 140 terminal mini-card per tile.
    Header bar + accent-coloured eyebrow + big title + prompt detail line.
    """
    file, eyebrow, title, detail, _href, _alt, accent = tile
    W, H = 300, 140
    s  = _svg_open(W, H, title)
    s += _term_header(W, eyebrow, accent)
    s += _enter(0.35 + i * 0.14)

    # big title (Instrument Serif)
    s += (
        f'<text x="20" y="90" class="serif t" font-size="32" font-weight="400">'
        f'{escape(title)}</text>'
        f'<rect x="20" y="98" width="40" height="1.5" fill="{accent}" opacity=".8"/>'
        f'<text x="20" y="122" class="d" font-size="12">{escape(detail)}</text>'
    )
    # ↗ corner arrow
    ax, ay = W - 28, 20
    s += (
        f'<text x="{ax}" y="{ay}" font-size="16" fill="{accent}" '
        f'text-anchor="middle">↗</text>'
    )
    s += "</g>"
    _save(file, s)


# ── 3. Contributions chart ────────────────────────────────────────────────────

def contribution_card(st: dict) -> None:
    """
    900 × 310  terminal window with:
      header bar   "aryan@github: ~/contributions"
      3 stat blocks (streak / active_days / busiest)
      12-month bar chart with SMIL grow animation
      footer note
    """
    W, H = 900, 310
    s = _svg_open(W, H, "Contribution analytics — last 12 months")
    s += _term_header(W, f"{USERNAME}@github: ~/contributions", BLUE)
    s += _enter(0.75)

    # prompt line
    s += _prompt(28, 70, "./contributions.sh", BLUE, 0.0)

    # stat blocks
    badges = [
        (str(st["streak"]),      "DAY STREAK",      BLUE),
        (str(st["active_days"]), "ACTIVE DAYS",      AMBER),
        (st["busiest"],          "BUSIEST WEEKDAY",  RED),
    ]
    for j, (val, lab, acc) in enumerate(badges):
        bx = 490 + j * 134
        s += (
            f'<rect x="{bx}" y="50" width="128" height="52" rx="8" '
            f'fill="{BG2}" stroke="{acc}" stroke-width="1" opacity=".9"/>'
            f'<text x="{bx+12}" y="76" font-size="20" fill="{acc}" font-weight="500">'
            f'{escape(val)}</text>'
            f'<text x="{bx+12}" y="94" font-size="9" fill="{TEXT_MUT}">'
            f'{lab}</text>'
        )

    # bar chart
    cx, cy, cw, ch, gap = 28, 112, 840, 140, 10
    months = st["months"]
    bw     = (cw - gap * (len(months) - 1)) / len(months)

    # grid lines (subtle)
    for pct in [0.25, 0.5, 0.75, 1.0]:
        gy = cy + ch - ch * pct
        s += (
            f'<line x1="{cx}" y1="{gy:.1f}" x2="{cx+cw}" y2="{gy:.1f}" '
            f'stroke="{BORDER}" stroke-width=".5" stroke-dasharray="3,3"/>'
        )

    for k, (m, v) in enumerate(months):
        bar_h = max(3.0, ch * v / st["max_month"]) if v else 3.0
        bx    = cx + k * (bw + gap)
        by    = cy + ch - bar_h
        fill  = BLUE if v else EMPTY

        # static base rect (always visible)
        s += (
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bar_h:.1f}" '
            f'rx="4" fill="{fill}" opacity=".85"/>'
        )

        if not STATIC:
            begin = f"{1.0 + k * 0.07:.2f}s"
            s += (
                f'<rect x="{bx:.1f}" y="{cy+ch}" width="{bw:.1f}" height="0" '
                f'rx="4" fill="{fill}" opacity=".85">'
                f'<animate attributeName="height" from="0" to="{bar_h:.1f}" '
                f'dur=".7s" begin="{begin}" fill="freeze"/>'
                f'<animate attributeName="y" from="{cy+ch}" to="{by:.1f}" '
                f'dur=".7s" begin="{begin}" fill="freeze"/>'
                f'</rect>'
            )

        if v:
            s += (
                f'<text x="{bx+bw/2:.1f}" y="{by-5:.1f}" text-anchor="middle" '
                f'font-size="9" fill="{TEXT_DIM}">{v}</text>'
            )
        s += (
            f'<text x="{bx+bw/2:.1f}" y="{cy+ch+16}" text-anchor="middle" '
            f'font-size="10" fill="{TEXT_MUT}">{m}</text>'
        )

    # footer
    note = (
        f'{st["total"]} contributions  ·  {st["range"]}'
        if st["total"] else
        "No contribution data yet — the next scheduled refresh will fill this in."
    )
    s += (
        f'<text x="28" y="{H-12}" font-size="11" fill="{TEXT_MUT}">'
        f'{escape(note)}</text>'
        f'</g>'
    )
    _save("contributions.svg", s)


# ── 4. Repo cards ─────────────────────────────────────────────────────────────

def repo_card(i: int, repo: tuple) -> None:
    """
    900 × 160  terminal card per featured repo.
    Header bar  "FEATURED REPOSITORY / 0N"
    Serif repo name + horizontal rule + description + stack line
    """
    name, desc, stack, _url, accent = repo
    W, H = 900, 160
    s  = _svg_open(W, H, f"{name} — featured repository")
    s += _term_header(W, f"FEATURED REPOSITORY / 0{i}", accent)
    s += _enter(1.5 + i * 0.22)

    s += (
        f'<text x="28" y="85" class="serif t" font-size="32" font-weight="400">'
        f'{escape(name)}</text>'
        f'<rect x="28" y="93" width="60" height="1.5" fill="{accent}" opacity=".8"/>'
        f'<text x="28" y="116" font-size="13" fill="{TEXT_DIM}">{escape(desc)}</text>'
        f'<text x="28" y="140" font-size="11" fill="{accent}">{escape(stack)}</text>'
    )
    # ↗ arrow
    s += (
        f'<text x="862" y="88" font-size="20" fill="{accent}" text-anchor="middle">↗</text>'
    )
    s += "</g>"
    _save(f"repo-{i}-{_slug(name)}.svg", s)


# ── 5. Contribution graph ─────────────────────────────────────────────────────

def graph_card(days: list[tuple[dt.date, int]]) -> None:
    """
    900 × 240  terminal heat-map — 52-week GitHub-style grid in LEVELS palette.
    """
    today  = dt.datetime.now(dt.timezone.utc).date()
    counts = dict(days)
    start  = today - dt.timedelta(weeks=52)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)
    total  = 53 * 7
    mx     = max([counts.get(start + dt.timedelta(days=k), 0) for k in range(total)] + [1])

    W, H = 900, 240
    s  = _svg_open(W, H, "GitHub contribution graph — last 52 weeks")
    s += _term_header(W, f"{USERNAME}@github: ~/graph", BLUE)
    s += _enter(2.3)

    # subtitle
    s += (
        f'<text x="28" y="68" font-size="13" fill="{TEXT_DIM}">'
        f'$ git log --since=52wk --format="%ad" --date=short | uniq | wc -l</text>'
    )

    pitch, x0, y0 = 15, 28, 90
    last_month = None
    cells: list[tuple] = []

    for k in range(total):
        d   = start + dt.timedelta(days=k)
        col, row = divmod(k, 7)
        if row == 0 and d.month != last_month and d <= today:
            last_month = d.month
            s += (
                f'<text x="{x0+col*pitch}" y="82" font-size="9" fill="{TEXT_MUT}">'
                f'{calendar.month_abbr[d.month].upper()}</text>'
            )
        if d > today:
            continue
        c   = counts.get(d, 0)
        lvl = 0 if c == 0 else min(4, 1 + int(3.999 * c / mx))
        cells.append((x0 + col*pitch, y0 + row*pitch, LEVELS[lvl], d, c, col))

    for cx2, cy2, color, d, c, col_idx in cells:
        s += (
            f'<rect x="{cx2}" y="{cy2}" width="12" height="12" rx="2" fill="{color}">'
            f'<title>{d.isoformat()}: {c} contribution{"s" if c!=1 else ""}</title>'
        )
        if not STATIC and c > 0:
            begin = f"{2.4 + col_idx * 0.014:.3f}s"
            s += (
                f'<animate attributeName="opacity" values="0;1" '
                f'dur=".3s" begin="{begin}" fill="freeze"/>'
            )
        s += "</rect>"

    # legend
    s += f'<text x="{x0}" y="216" font-size="9" fill="{TEXT_MUT}" letter-spacing="1">LESS</text>'
    for k, col in enumerate(LEVELS):
        s += f'<rect x="{x0+42+k*18}" y="206" width="12" height="12" rx="2" fill="{col}"/>'
    s += (
        f'<text x="{x0+42+len(LEVELS)*18+6}" y="216" font-size="9" '
        f'fill="{TEXT_MUT}" letter-spacing="1">MORE</text>'
        f'</g>'
    )
    _save("contribution-graph.svg", s)

# ═══════════════════════════════════════════════════════════════════ README

def _readme() -> str:
    tiles = "\n".join(
        f'<a href="{t[4]}"><img src="cards/{t[0]}" width="32.5%" alt="{escape(t[5])}" /></a>'
        for t in TILES
    )
    repos = "\n".join(
        f'<a href="{r[3]}"><img src="cards/repo-{i}-{_slug(r[0])}.svg" '
        f'width="100%" alt="{escape(r[0])} — {escape(r[2])}" /></a>'
        for i, r in enumerate(FEATURED, 1)
    )
    return (
        f'<div align="center">\n\n'
        f'<img src="cards/hero.svg" width="100%" alt="{escape(NAME)}, {escape(ROLE)}" />\n\n'
        f'{tiles}\n\n'
        f'<img src="cards/contributions.svg" width="100%" '
        f'alt="Monthly contributions, streak, active days and busiest weekday" />\n\n'
        f'</div>\n\n'
        f'## Selected work\n\n'
        f'{repos}\n\n'
        f'<div align="center">\n\n'
        f'<img src="cards/contribution-graph.svg" width="100%" '
        f'alt="Contribution graph — last 52 weeks" />\n\n'
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
        f'body{{background:{BG};margin:0;padding:24px}}'
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
                    help="Skip font subsetting (fast iteration, system fonts).")
    args = ap.parse_args()

    if args.refresh_contributions:
        refresh_contributions()

    if not args.skip_fonts:
        print("Subsetting fonts (Instrument Serif + JetBrains Mono)…")
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
