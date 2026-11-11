#!/usr/bin/env python3
"""Render self-contained animated SVG cards + README for Aryan's GitHub profile.

Usage:
  python scripts/render_cards.py --refresh-contributions   # fetch real data, then render
  python scripts/render_cards.py                           # render from contribution-data.json
  STATIC=1 python scripts/render_cards.py                  # final frame, no motion -> cards-static/ + preview.html

Design notes
  * Cards are embedded as <img>, so no JavaScript, no external requests, no <a> links inside the SVGs
    (links live in README.md). Motion is CSS keyframes only, so `prefers-reduced-motion` disables all of it
    and the un-animated state is always the complete, final frame.
  * Fonts (Jost, Syne Mono) are subset with fontTools (pyftsubset) and embedded as base64 data URIs.
    Source order: Google Fonts download -> local files in assets/fonts/ -> system fallback stack.
  * Contribution data comes from the GitHub GraphQL API (GH_TOKEN / GITHUB_TOKEN), never hardcoded.
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
import urllib.request
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

# --------------------------------------------------------------------------- configuration
ROOT = Path(__file__).resolve().parents[1]
STATIC = os.getenv("STATIC", "0") == "1"
OUT = ROOT / ("cards-static" if STATIC else "cards")       # STATIC never overwrites the published cards
DATA_FILE = ROOT / "contribution-data.json"
PORTRAIT_CANDIDATES = [ROOT / "assets" / "profile.png", ROOT / "assets" / "profile.jpg"]

USERNAME = "aryan99dev"
NAME = "Aryan Sharma"
ROLE = "Full-stack developer  ·  BCA student"
INTRO = "I build modern web apps, learn new technologies and create useful digital experiences."
META = "SHOOLINI UNIVERSITY  ·  INDIA"
EMAIL = "aryan99dev00@gmail.com"

# Palette (matches the portfolio site: near-black, indigo, cyan, refined purple)
BG, INDIGO, PURPLE, CYAN = "#09090b", "#312e81", "#8b7cff", "#06b6d4"
TEXT, MUTED, BORDER, EMPTY = "#f4f4ff", "#a1a1b5", "#25234a", "#18181d"
LEVELS = [EMPTY, INDIGO, "#5b4fd1", PURPLE, CYAN]          # contribution graph shades, low -> high

FEATURED = [  # only technologies you have actually listed for each repo
    ("Portfolio", "Personal site built with Next.js and React, with modern UI and animation techniques.",
     "Next.js · React · TypeScript", f"https://github.com/{USERNAME}/Portfolio"),
    ("Prism", "Modern social platform: authentication, profiles, posts, real-time updates, interactive UI.",
     "React · TypeScript · Vite · Tailwind CSS · Appwrite", f"https://github.com/{USERNAME}/Prism"),
    ("Movie-App", "Movie app built with React and Vite.",
     "React · Vite", f"https://github.com/{USERNAME}/Movie-App"),
]
TILES = [  # (file, eyebrow, title, detail, href, alt text)
    ("tile-build.svg", "01 / MAKE", "BUILD", "Portfolio & projects", f"https://github.com/{USERNAME}/Portfolio", "Build: view the portfolio repository"),
    ("tile-explore.svg", "02 / LEARN", "EXPLORE", "All repositories", f"https://github.com/{USERNAME}?tab=repositories", "Explore: all repositories"),
    ("tile-connect.svg", "03 / SAY HI", "CONNECT", "Let's make something", f"mailto:{EMAIL}", "Connect: send an email"),
]
FONTS = {  # family -> (Google Fonts css2 spec, weights)
    "Jost": ("Jost:wght@400;700", [400, 700]),
    "Syne Mono": ("Syne+Mono", [400]),
}
UNICODES = "U+0020-007E,U+00B7,U+2014,U+2019"
CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FONT_CSS = ""

# --------------------------------------------------------------------------- contribution data
def refresh_contributions() -> None:
    """Fetch the contribution calendar via GraphQL. Failure keeps the existing data file."""
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        print("::warning::No GH_TOKEN/GITHUB_TOKEN; keeping existing contribution data.", file=sys.stderr)
        return
    end = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    query = """query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
      contributionsCollection(from:$from,to:$to){contributionCalendar{totalContributions
      weeks{contributionDays{date contributionCount}}}}}}"""
    body = json.dumps({"query": query, "variables": {
        "login": USERNAME, "from": (end - dt.timedelta(days=365)).isoformat(), "to": end.isoformat()}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": USERNAME})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read().decode())
        cal = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    except Exception as exc:  # network, auth, schema: never crash the whole render
        print(f"::warning::Contribution refresh failed ({exc}); keeping existing data.", file=sys.stderr)
        return
    days = [d for week in cal["weeks"] for d in week["contributionDays"]]
    old = load_json()
    if old.get("days") == days:
        print("Contribution data unchanged.")      # keeps updated_at stable -> no pointless daily commit
        return
    DATA_FILE.write_text(json.dumps({"username": USERNAME, "updated_at": end.isoformat(),
                                     "total_contributions": cal["totalContributions"], "days": days}, indent=2) + "\n")
    print(f"Updated {DATA_FILE.name}: {len(days)} days, {cal['totalContributions']} contributions")


def load_json() -> dict:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def clean_days(raw) -> list[tuple[dt.date, int]]:
    """Normalise to sorted (date, count); silently drop malformed rows."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append((dt.date.fromisoformat(item["date"]), max(0, int(item["contributionCount"]))))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out)


def today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def month_shift(d: dt.date, delta: int) -> tuple[int, int]:
    idx = d.year * 12 + d.month - 1 + delta
    return idx // 12, idx % 12 + 1


def contribution_stats(days: list[tuple[dt.date, int]], today: dt.date | None = None) -> dict:
    """All figures derive from the stored data over the same window: the last 12 calendar months."""
    today = today or today_utc()
    months_keys = [month_shift(today, -i) for i in range(11, -1, -1)]
    start = dt.date(*months_keys[0], 1)
    window = [(d, c) for d, c in days if start <= d <= today]
    per_month = Counter()
    weekday, weekday_days = Counter(), Counter()
    for d, c in window:
        per_month[(d.year, d.month)] += c
        if c:
            weekday[calendar.day_name[d.weekday()]] += c
            weekday_days[calendar.day_name[d.weekday()]] += 1
    active = {d for d, c in window if c}
    cursor = today if today in active else today - dt.timedelta(days=1)   # a quiet "today" doesn't break a streak
    streak = 0
    while cursor in active:
        streak += 1
        cursor -= dt.timedelta(days=1)
    months = [(calendar.month_abbr[m], per_month.get((y, m), 0)) for y, m in months_keys]
    return {"months": months, "streak": streak, "active_days": len(active),
            "busiest": max(weekday, key=lambda k: (weekday[k], weekday_days[k])) if weekday else "None yet",  # ties: more active days wins
            "total": sum(c for _, c in window), "max_month": max(v for _, v in months) or 1,
            "range": f"{calendar.month_abbr[months_keys[0][1]]} {months_keys[0][0]} – "
                     f"{calendar.month_abbr[months_keys[-1][1]]} {months_keys[-1][0]}"}

# --------------------------------------------------------------------------- fonts
def google_font_files(family: str) -> list[tuple[int, bytes]]:
    spec, _ = FONTS[family]
    req = urllib.request.Request(f"https://fonts.googleapis.com/css2?family={spec}&display=swap",
                                 headers={"User-Agent": CHROME_UA})
    css = urllib.request.urlopen(req, timeout=20).read().decode()
    files = []
    for subset, block in re.findall(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", css, re.S):
        if subset != "latin":
            continue
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url = re.search(r"url\((https://[^)]+)\)", block)
        if url:
            files.append((int(weight.group(1)) if weight else 400, urllib.request.urlopen(url.group(1), timeout=20).read()))
    return files


def local_font_files(family: str) -> list[tuple[int, bytes]]:
    stem = family.replace(" ", "").lower()
    found = []
    for p in sorted((ROOT / "assets" / "fonts").glob("*")):
        if p.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"} and p.name.lower().replace("-", "").startswith(stem):
            found.append((700 if "bold" in p.name.lower() else 400, p.read_bytes()))
    return found


def subset_font(family: str) -> str:
    """Return @font-face CSS with subsetted base64 fonts (pyftsubset), or '' if no source is available."""
    try:
        sources = google_font_files(family)
    except Exception as exc:
        print(f"Google Fonts unavailable for {family} ({exc}); trying assets/fonts/", file=sys.stderr)
        sources = []
    sources = sources or local_font_files(family)
    if not sources:
        print(f"::warning::No font source for {family}; cards fall back to system fonts.", file=sys.stderr)
        return ""
    try:
        import brotli  # noqa: F401
        flavor, mime = "woff2", "font/woff2"
    except ImportError:
        flavor, mime = "woff", "font/woff"
    css = ""
    with tempfile.TemporaryDirectory() as tmp:
        for i, (weight, data) in enumerate(sources):
            src, dst = Path(tmp, f"src{i}"), Path(tmp, f"out{i}.{flavor}")
            src.write_bytes(data)
            proc = subprocess.run([sys.executable, "-m", "fontTools.subset", str(src), f"--unicodes={UNICODES}",
                                   f"--output-file={dst}", f"--flavor={flavor}", "--layout-features=*",
                                   "--name-IDs=0,1,2,4,6"], capture_output=True, text=True)
            if proc.returncode or not dst.exists():
                print(f"::warning::pyftsubset failed for {family} {weight}: {proc.stderr.strip()[:300]}", file=sys.stderr)
                continue
            b64 = base64.b64encode(dst.read_bytes()).decode()
            css += (f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;"
                    f"src:url(data:{mime};base64,{b64}) format('{flavor}')}}")
    return css

# --------------------------------------------------------------------------- SVG building blocks
def svg_open(w: int, h: int, label: str, glow_x: int | None = None) -> str:
    anim = "" if STATIC else (
        "@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}"
        "@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}"
        "@keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}"
        ".enter{animation:rise .8s cubic-bezier(.2,.75,.25,1) both}"
        ".bar{transform-box:fill-box;transform-origin:50% 100%;animation:grow .9s cubic-bezier(.2,.75,.25,1) both}"
        ".pulse{animation:pulse 3.2s ease-in-out infinite}"
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    gx = glow_x if glow_x is not None else w - 60
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">'
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#13112b"/><stop offset="1" stop-color="{BG}"/></linearGradient>'
            f'<linearGradient id="ac" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{PURPLE}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient>'
            f'<linearGradient id="bar" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="{INDIGO}"/><stop offset=".55" stop-color="{PURPLE}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient>'
            f'<filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="30"/></filter>'
            f'<clipPath id="card"><rect width="{w}" height="{h}" rx="22"/></clipPath></defs>'
            f'<style>{FONT_CSS}text{{font-family:Jost,"Segoe UI",Arial,sans-serif}}.mono{{font-family:"Syne Mono","SFMono-Regular",Consolas,monospace}}'
            f'.t{{fill:{TEXT}}}.m{{fill:{MUTED}}}.p{{fill:{PURPLE}}}.c{{fill:{CYAN}}}{anim}</style>'
            f'<g clip-path="url(#card)"><rect width="{w}" height="{h}" fill="url(#bg)"/>'
            f'<circle class="{"" if STATIC else "pulse"}" cx="{gx}" cy="10" r="90" fill="{INDIGO}" opacity=".55" filter="url(#blur)"/>'
            f'<circle cx="40" cy="{h}" r="70" fill="{CYAN}" opacity=".08" filter="url(#blur)"/></g>'
            f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="22" fill="none" stroke="{BORDER}"/>')


def enter(delay: float) -> str:
    return "<g>" if STATIC else f'<g class="enter" style="animation-delay:{delay:.2f}s">'


def arrow(x: float, y: float, color: str = PURPLE) -> str:
    return (f'<path d="M{x} {y+10} L{x+10} {y} M{x+1} {y} H{x+10} V{y+9}" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>')


def save(name: str, svg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(svg + "</svg>\n", encoding="utf-8")

# --------------------------------------------------------------------------- cards
def hero_card() -> None:
    portrait = next((p for p in PORTRAIT_CANDIDATES if p.exists()), None)   # optional
    img = ""
    if portrait:
        mime = "image/png" if portrait.suffix.lower() == ".png" else "image/jpeg"
        data = base64.b64encode(portrait.read_bytes()).decode()
        img = (f'<clipPath id="pc"><circle cx="760" cy="125" r="64"/></clipPath>'
               f'<image href="data:{mime};base64,{data}" x="696" y="61" width="128" height="128" preserveAspectRatio="xMidYMid slice" clip-path="url(#pc)"/>'
               f'<circle cx="760" cy="125" r="67" fill="none" stroke="url(#ac)" stroke-width="2"/>')
    s = svg_open(900, 250, f"{NAME} — {ROLE}")
    s += (enter(0) + f'<text x="48" y="54" class="mono p" font-size="13" letter-spacing="3">HELLO, WORLD / I\'M</text>'
          f'<text x="46" y="126" class="t" font-size="60" font-weight="700">{escape(NAME)}</text>'
          f'<rect x="48" y="142" width="64" height="3" rx="1.5" fill="url(#ac)"/>'
          f'<text x="48" y="178" class="m" font-size="21">{escape(ROLE)}</text>'
          f'<text x="48" y="204" class="m" font-size="15">{escape(INTRO)}</text>'
          f'<text x="48" y="232" class="mono c" font-size="11" letter-spacing="2">{escape(META)}</text>{img}</g>')
    save("hero.svg", s)


def tile_card(i: int, tile: tuple) -> None:
    file, eyebrow, title, detail, _, _ = tile
    s = svg_open(300, 132, title, glow_x=250) + enter(0.35 + i * 0.12)
    s += (f'<text x="22" y="32" class="mono p" font-size="11" letter-spacing="2">{escape(eyebrow)}</text>'
          f'<text x="22" y="76" class="t" font-size="28" font-weight="700">{escape(title)}</text>'
          f'<text x="22" y="104" class="m" font-size="14">{escape(detail)}</text>{arrow(266, 22, CYAN)}</g>')
    save(file, s)


def contribution_card(st: dict) -> None:
    s = svg_open(900, 290, "Contribution analytics") + enter(0.8)
    s += (f'<text x="34" y="44" class="t" font-size="23" font-weight="700" letter-spacing="1">CONTRIBUTION PULSE</text>'
          f'<text x="34" y="68" class="m" font-size="13">Real GitHub activity, last 12 months.</text>')
    for i, (val, lab) in enumerate([(str(st["streak"]), "DAY STREAK"), (str(st["active_days"]), "ACTIVE DAYS"),
                                    (st["busiest"], "BUSIEST WEEKDAY")]):
        x = 470 + i * 140
        s += (f'<text x="{x}" y="44" class="p" font-size="22" font-weight="700">{escape(val)}</text>'
              f'<text x="{x}" y="64" class="mono m" font-size="9" letter-spacing="1">{lab}</text>')
    cx, cy, cw, ch, gap = 42, 100, 816, 130, 14
    months = st["months"]
    bw = (cw - gap * (len(months) - 1)) / len(months)
    s += f'<line x1="{cx}" y1="{cy+ch}" x2="{cx+cw}" y2="{cy+ch}" stroke="{BORDER}"/>'
    for i, (m, v) in enumerate(months):
        h = max(3.0, ch * v / st["max_month"]) if v else 3.0
        x = cx + i * (bw + gap)
        delay = f' style="animation-delay:{1.0 + i * 0.06:.2f}s"' if not STATIC else ""
        s += (f'<rect class="{"" if STATIC else "bar"}" x="{x:.1f}" y="{cy+ch-h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="5" '
              f'fill="{"url(#bar)" if v else EMPTY}"{delay}/>')
        if v:
            s += f'<text x="{x+bw/2:.1f}" y="{cy+ch-h-6:.1f}" text-anchor="middle" class="mono t" font-size="10">{v}</text>'
        s += f'<text x="{x+bw/2:.1f}" y="{cy+ch+18}" text-anchor="middle" class="mono m" font-size="10">{m}</text>'
    note = f'{st["total"]} contributions  ·  {st["range"]}' if st["total"] else "No contribution data yet. The next scheduled refresh will fill this in."
    s += f'<text x="42" y="274" class="mono m" font-size="11">{escape(note)}</text></g>'
    save("contributions.svg", s)


def repo_card(i: int, repo: tuple) -> None:
    name, desc, stack, _ = repo
    s = svg_open(900, 150, f"{name} featured repository") + enter(1.5 + i * 0.25)
    s += (f'<text x="32" y="38" class="mono p" font-size="11" letter-spacing="2">FEATURED REPOSITORY / 0{i}</text>'
          f'<text x="32" y="78" class="t" font-size="28" font-weight="700">{escape(name)}</text>'
          f'<text x="32" y="104" class="m" font-size="14">{escape(desc)}</text>'
          f'<text x="32" y="130" class="mono c" font-size="11" letter-spacing="1">{escape(stack)}</text>{arrow(846, 66)}</g>')
    save(f"repo-{i}-{slug(name)}.svg", s)


def graph_card(days: list[tuple[dt.date, int]]) -> None:
    today = today_utc()
    counts = dict(days)
    start = today - dt.timedelta(weeks=52)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)            # back to Sunday, like GitHub
    mx = max([counts.get(start + dt.timedelta(days=i), 0) for i in range(371)] + [1])
    s = svg_open(900, 232, "GitHub contribution graph") + enter(2.6)
    s += (f'<text x="34" y="40" class="t" font-size="22" font-weight="700" letter-spacing="1">THE CONSISTENCY MAP</text>'
          f'<text x="34" y="62" class="m" font-size="13">Daily contribution activity, last 52 weeks</text>')
    pitch, x0, y0, last_month = 15, 34, 92, None
    for i in range(53 * 7):
        d = start + dt.timedelta(days=i)
        col, row = divmod(i, 7)
        if row == 0 and d.month != last_month and d <= today:
            last_month = d.month
            s += f'<text x="{x0+col*pitch}" y="82" class="mono m" font-size="9">{calendar.month_abbr[d.month].upper()}</text>'
        if d > today:
            continue
        c = counts.get(d, 0)
        lvl = 0 if c == 0 else min(4, 1 + int(3.999 * c / mx))
        s += (f'<rect x="{x0+col*pitch}" y="{y0+row*pitch}" width="12" height="12" rx="3" fill="{LEVELS[lvl]}">'
              f'<title>{d.isoformat()}: {c} contributions</title></rect>')
    s += f'<text x="34" y="216" class="mono m" font-size="10" letter-spacing="1">LESS</text>'
    for i, col in enumerate(LEVELS):
        s += f'<rect x="{80+i*18}" y="206" width="12" height="12" rx="3" fill="{col}"/>'
    s += '<text x="184" y="216" class="mono m" font-size="10" letter-spacing="1">MORE</text></g>'
    save("contribution-graph.svg", s)

# --------------------------------------------------------------------------- README / preview
def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def readme() -> str:
    tiles = "\n".join(f'<a href="{t[4]}"><img src="cards/{t[0]}" width="32.5%" alt="{escape(t[5])}" /></a>' for t in TILES)
    repos = "\n".join(f'<a href="{r[3]}"><img src="cards/repo-{i}-{slug(r[0])}.svg" width="100%" alt="{escape(r[0])} repository: {escape(r[2])}" /></a>'
                      for i, r in enumerate(FEATURED, 1))
    return f'''<div align="center">

<img src="cards/hero.svg" width="100%" alt="{NAME}, {ROLE}" />

{tiles}

<img src="cards/contributions.svg" width="100%" alt="Monthly contributions, current streak, active days and busiest weekday" />

{repos}

<img src="cards/contribution-graph.svg" width="100%" alt="Contribution graph for the last 52 weeks" />

</div>

<div align="center">

[GitHub](https://github.com/{USERNAME}) · [Portfolio](https://github.com/{USERNAME}/Portfolio) · [Email](mailto:{EMAIL})

</div>

<!-- Generated by scripts/render_cards.py. Edit the config at the top of that file, not the SVGs. -->
'''


def preview_html() -> str:
    names = ["hero.svg"] + [t[0] for t in TILES] + ["contributions.svg"] + \
            [f"repo-{i}-{slug(r[0])}.svg" for i, r in enumerate(FEATURED, 1)] + ["contribution-graph.svg"]
    imgs = "".join(f'<img src="cards-static/{n}" alt="{n}">' for n in names)
    return (f'<!doctype html><meta charset="utf-8"><title>Static preview</title><style>body{{background:#0d1117;margin:0;padding:24px}}'
            f'.w{{max-width:900px;margin:auto;display:flex;flex-wrap:wrap;gap:10px}}img{{width:100%}}img[src*="tile-"]{{width:calc(33.33% - 7px)}}</style>'
            f'<div class="w">{imgs}</div>')


def main() -> None:
    global FONT_CSS
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-contributions", action="store_true")
    ap.add_argument("--skip-fonts", action="store_true")
    args = ap.parse_args()
    if args.refresh_contributions:
        refresh_contributions()
    if not args.skip_fonts:
        FONT_CSS = "".join(subset_font(f) for f in FONTS)
    days = clean_days(load_json().get("days"))
    stats = contribution_stats(days)
    hero_card()
    for i, tile in enumerate(TILES):
        tile_card(i, tile)
    contribution_card(stats)
    for i, repo in enumerate(FEATURED, 1):
        repo_card(i, repo)
    graph_card(days)
    if STATIC:
        (ROOT / "preview.html").write_text(preview_html(), encoding="utf-8")
        print(f"STATIC=1: wrote {len(list(OUT.glob('*.svg')))} cards to {OUT.name}/ and preview.html (README untouched)")
    else:
        (ROOT / "README.md").write_text(readme(), encoding="utf-8")
        print(f"Wrote {len(list(OUT.glob('*.svg')))} cards to {OUT.name}/ and README.md")
    print(f"Embedded fonts: {sorted(set(re.findall(r'font-family:.([A-Za-z ]+).;font-weight', FONT_CSS))) or 'none (system fallback)'}")
    print(f"Stats: {json.dumps({k: v for k, v in stats.items() if k != 'months'})}")


if __name__ == "__main__":
    main()
