#!/usr/bin/env python3
"""Render self-contained animated SVG cards for Aryan's GitHub profile.

Usage:
  python scripts/render_cards.py --refresh-contributions
  STATIC=1 python scripts/render_cards.py
  python scripts/render_cards.py

The contribution refresh uses the GitHub GraphQL API and GH_TOKEN (or GITHUB_TOKEN).
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
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "cards"
DATA_FILE = ROOT / "contribution-data.json"
USERNAME = "aryan99dev"
NAME = "Aryan Sharma"
TAGLINE = "BCA student · Full-stack developer · Building thoughtful web experiences"
BRAND = "#8b7cff"
CYAN = "#06b6d4"
BG = "#08090d"
PANEL = "#10121b"
MUTED = "#a3a6b8"
WHITE = "#f5f6ff"
FEATURED = [
    ("Portfolio", "A personal portfolio built with Next.js, React and motion-led UI.", "Next.js · React · TypeScript", "https://github.com/aryan99dev/Portfolio"),
    ("Prism", "A real-time social platform with profiles, feeds and Appwrite-powered auth.", "React · TypeScript · Appwrite", "https://github.com/aryan99dev/Prism"),
    ("Movie-App", "A movie discovery experience built with React and Vite.", "React · Vite · JavaScript", "https://github.com/aryan99dev/Movie-App"),
]
STATIC = os.getenv("STATIC", "0") == "1"
FONT_CSS = ""


def request_json(url: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode())


def refresh_contributions() -> None:
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Set GH_TOKEN or GITHUB_TOKEN to refresh contribution data.")
    end = dt.datetime.now(dt.timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    start = end - dt.timedelta(days=365)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    result = request_json(
        "https://api.github.com/graphql",
        {"query": query, "variables": {"login": USERNAME, "from": start.isoformat(), "to": end.isoformat()}},
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": USERNAME},
    )
    if result.get("errors"):
        raise SystemExit("GitHub GraphQL error: " + json.dumps(result["errors"]))
    calendar_data = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = [day for week in calendar_data["weeks"] for day in week["contributionDays"]]
    DATA_FILE.write_text(json.dumps({
        "username": USERNAME,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_contributions": calendar_data["totalContributions"],
        "days": days,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {DATA_FILE.name}: {len(days)} contribution days")


def load_data() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8")).get("days", [])
    except (json.JSONDecodeError, OSError):
        return []


def contribution_stats(days: list[dict]) -> dict:
    normalized = []
    for item in days:
        try:
            normalized.append((dt.date.fromisoformat(item["date"]), int(item["contributionCount"])))
        except (KeyError, ValueError, TypeError):
            continue
    normalized.sort()
    today = dt.datetime.now(dt.timezone.utc).date()
    by_month: dict[str, int] = defaultdict(int)
    weekday_counts: Counter = Counter()
    active_dates = []
    for date, count in normalized:
        if date >= today - dt.timedelta(days=364):
            by_month[date.strftime("%b")] += count
            if count:
                active_dates.append(date)
                weekday_counts[date.strftime("%A")] += count
    # Current streak ends today, or yesterday if there was no contribution today.
    active = set(active_dates)
    cursor = today if today in active else today - dt.timedelta(days=1)
    streak = 0
    while cursor in active:
        streak += 1
        cursor -= dt.timedelta(days=1)
    months = []
    for offset in range(11, -1, -1):
        month_date = (today.replace(day=1) - dt.timedelta(days=offset * 28)).replace(day=1)
        key = month_date.strftime("%b")
        months.append((key, by_month.get(key, 0)))
    # Correct month labels when year boundaries produce duplicate abbreviations.
    months = []
    for offset in range(11, -1, -1):
        month_index = today.month - offset
        year = today.year + (month_index - 1) // 12
        month = (month_index - 1) % 12 + 1
        key = calendar.month_abbr[month]
        total = sum(c for d, c in normalized if d.year == year and d.month == month)
        months.append((key, total))
    busiest = weekday_counts.most_common(1)[0][0] if weekday_counts else "—"
    return {
        "months": months,
        "streak": streak,
        "active_days": len(active_dates),
        "busiest": busiest,
        "total": sum(c for d, c in normalized),
        "max_month": max((v for _, v in months), default=1) or 1,
    }


def subset_font(family: str, text: str) -> str:
    """Download a Latin font, subset it with pyftsubset, return an embedded WOFF2 face."""
    try:
        css_url = "https://fonts.googleapis.com/css2?family=" + urllib.parse.quote(family.replace(" ", "+")) + "&display=swap"
        css_req = urllib.request.Request(css_url, headers={"User-Agent": "Mozilla/5.0"})
        css = urllib.request.urlopen(css_req, timeout=20).read().decode()
        blocks = re.split(r"/\* latin \*/", css)
        latin = blocks[-1] if len(blocks) > 1 else css
        match = re.search(r"url\((https://[^)]+\.woff2)\)", latin)
        if not match:
            return ""
        font_bytes = urllib.request.urlopen(match.group(1), timeout=20).read()
        source = CARDS / (re.sub(r"\W+", "-", family.lower()) + "-source.woff2")
        target = CARDS / (re.sub(r"\W+", "-", family.lower()) + "-subset.woff2")
        source.write_bytes(font_bytes)
        subprocess.run([
            sys.executable, "-m", "fontTools.subset", str(source),
            f"--text={text}", f"--output-file={target}", "--flavor=woff2",
            "--layout-features=*", "--name-IDs=0,1,2,4,6",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        encoded = base64.b64encode(target.read_bytes()).decode()
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        return f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{encoded}) format('woff2');font-weight:100 900;font-display:swap}}"
    except Exception as exc:
        print(f"Font subset skipped for {family}: {exc}", file=sys.stderr)
        return ""


def svg_start(width: int, height: int, delay: float, label: str) -> str:
    animation = "" if STATIC else f"""
    @keyframes rise{{from{{opacity:0;transform:translateY(22px)}}to{{opacity:1;transform:translateY(0)}}}}
    @keyframes glow{{0%,100%{{opacity:.35}}50%{{opacity:.9}}}}
    .enter{{opacity:1;animation:rise .85s cubic-bezier(.2,.75,.25,1) {delay:.2f}s both}}
    .glow{{animation:glow 4s ease-in-out {delay + .7:.2f}s infinite}}
    @media(prefers-reduced-motion:reduce){{*,*::before,*::after{{animation:none!important;transition:none!important}} animate{{display:none}}}}
    """
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">
    <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#11131d"/><stop offset="1" stop-color="#08090d"/></linearGradient>
    <linearGradient id="accent"><stop stop-color="{BRAND}"/><stop offset="1" stop-color="{CYAN}"/></linearGradient>
    <filter id="blur"><feGaussianBlur stdDeviation="35"/></filter></defs>
    <style>{FONT_CSS}
    text{{font-family:'Jost',Arial,sans-serif}} .mono{{font-family:'Syne Mono',monospace}}
    .muted{{fill:{MUTED}}} .white{{fill:{WHITE}}} .accent{{fill:{BRAND}}}
    {animation}
    </style>
    <rect x="1" y="1" width="{width-2}" height="{height-2}" rx="24" fill="url(#bg)" stroke="#292b3b"/>
    <circle class="glow" cx="{width-50}" cy="20" r="90" fill="{BRAND}" opacity=".13" filter="url(#blur)"/>
    '''


def svg_end() -> str:
    return "</svg>\n"


def write_card(name: str, svg: str) -> None:
    CARDS.mkdir(parents=True, exist_ok=True)
    (CARDS / name).write_text(svg + svg_end(), encoding="utf-8")


def hero_card() -> None:
    portrait = ROOT / "assets" / "profile.png"
    if not portrait.exists():
        portrait = ROOT / "profile.png"
    portrait_markup = ""
    if portrait.exists():
        data = base64.b64encode(portrait.read_bytes()).decode()
        mime = "image/png"
        portrait_markup = f'<clipPath id="portraitClip"><circle cx="710" cy="118" r="62"/></clipPath><image href="data:{mime};base64,{data}" x="648" y="56" width="124" height="124" preserveAspectRatio="xMidYMid slice" clip-path="url(#portraitClip)"/><circle cx="710" cy="118" r="65" fill="none" stroke="url(#accent)" stroke-width="2"/>'
    svg = svg_start(900, 240, 0, "Aryan Sharma hero card")
    svg += f'''<g class="enter"><text x="48" y="56" class="mono accent" font-size="13" letter-spacing="3">HELLO, WORLD / I'M</text>
    <text x="44" y="128" class="white" font-size="58" font-weight="700">{NAME}</text>
    <text x="48" y="166" class="muted" font-size="18">{escape(TAGLINE)}</text>
    <text x="48" y="205" class="mono" fill="{CYAN}" font-size="12">INDIA  ·  OPEN TO BUILDING COOL THINGS</text>
    {portrait_markup}</g>'''
    if not STATIC:
        svg += '<circle cx="820" cy="54" r="3" fill="#06b6d4"><animate attributeName="opacity" values=".2;1;.2" dur="2.8s" repeatCount="indefinite"/></circle>'
    write_card("hero.svg", svg)


def tile_card(filename: str, eyebrow: str, title: str, detail: str, href: str, delay: float, index: str) -> None:
    svg = svg_start(300, 132, delay, title)
    svg += f'''<a href="{escape(href)}"><g class="enter">
    <text x="22" y="32" class="mono accent" font-size="11" letter-spacing="2">{escape(eyebrow)}</text>
    <text x="22" y="73" class="white" font-size="25" font-weight="700">{escape(title)}</text>
    <text x="22" y="101" class="muted" font-size="12">{escape(detail)}</text>
    <text x="270" y="34" class="mono" fill="{CYAN}" font-size="12">{index} ↗</text>
    </g></a>'''
    write_card(filename, svg)


def contribution_card(stats: dict, delay: float) -> None:
    svg = svg_start(900, 290, delay, "Contribution activity by month")
    svg += '<g class="enter"><text x="34" y="43" class="white" font-size="23" font-weight="700">CONTRIBUTION PULSE</text>'
    svg += f'<text x="34" y="67" class="muted" font-size="12">A year of showing up, one commit at a time.</text>'
    metrics = [(f"{stats["streak"]}", "DAY STREAK"), (f"{stats["active_days"]}", "ACTIVE DAYS"), (stats["busiest"].upper(), "BUSIEST DAY")]
    for i, (value, label) in enumerate(metrics):
        x = 500 + i * 125
        svg += f'<text x="{x}" y="42" class="accent" font-size="24" font-weight="700">{escape(value)}</text><text x="{x}" y="62" class="muted mono" font-size="9">{label}</text>'
    chart_x, chart_y, chart_w, chart_h = 42, 105, 816, 125
    svg += f'<line x1="{chart_x}" y1="{chart_y+chart_h}" x2="{chart_x+chart_w}" y2="{chart_y+chart_h}" stroke="#303247"/>'
    months = stats["months"]
    gap = 17
    bar_w = (chart_w - gap * (len(months)-1)) / len(months)
    for i, (month, value) in enumerate(months):
        height = max(3, chart_h * value / stats["max_month"])
        x = chart_x + i * (bar_w + gap)
        y = chart_y + chart_h - height
        svg += f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{height:.1f}" rx="5" fill="url(#accent)" opacity=".9"/>'
        if not STATIC:
            svg += f'<rect x="{x:.1f}" y="{chart_y+chart_h}" width="{bar_w:.1f}" height="0" rx="5" fill="url(#accent)"><animate attributeName="height" from="0" to="{height:.1f}" dur=".8s" begin="{delay + .25 + i*.055:.2f}s" fill="freeze"/><animate attributeName="y" from="{chart_y+chart_h}" to="{y:.1f}" dur=".8s" begin="{delay + .25 + i*.055:.2f}s" fill="freeze"/></rect>'
        svg += f'<text x="{x+bar_w/2:.1f}" y="250" text-anchor="middle" class="muted mono" font-size="10">{month}</text>'
    svg += f'<text x="42" y="273" class="muted mono" font-size="10">{stats["total"]} contributions in the last 12 months</text></g>'
    write_card("contributions.svg", svg)


def repo_card(index: int, repo: tuple[str, str, str, str], delay: float) -> None:
    name, description, stack, href = repo
    svg = svg_start(900, 150, delay, f"{name} featured repository")
    svg += f'''<a href="{escape(href)}"><g class="enter">
    <text x="32" y="38" class="mono accent" font-size="11" letter-spacing="2">FEATURED REPOSITORY / 0{index}</text>
    <text x="32" y="79" class="white" font-size="28" font-weight="700">{escape(name)}</text>
    <text x="32" y="105" class="muted" font-size="14">{escape(description)}</text>
    <text x="32" y="130" fill="{CYAN}" class="mono" font-size="11">{escape(stack)}</text>
    <text x="850" y="82" text-anchor="middle" class="accent" font-size="24">↗</text>
    </g></a>'''
    write_card(f"repo-{index}-{re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')}.svg", svg)


def graph_card(days: list[dict], delay: float) -> None:
    svg = svg_start(900, 190, delay, "GitHub contribution graph")
    svg += '<g class="enter"><text x="32" y="39" class="white" font-size="22" font-weight="700">THE CONSISTENCY MAP</text><text x="32" y="62" class="muted" font-size="12">Daily contribution activity · last 52 weeks</text>'
    counts = {d.get("date"): int(d.get("contributionCount", 0)) for d in days}
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=363)
    start -= dt.timedelta(days=(start.weekday()+1) % 7)
    cell, gap = 10, 4
    for i in range(364):
        date = start + dt.timedelta(days=i)
        if date > today:
            continue
        count = counts.get(date.isoformat(), 0)
        color = "#1a1c29" if count == 0 else (("#37305f" if count < 3 else "#5545a5") if count < 6 else (BRAND if count < 10 else CYAN))
        col, row = i // 7, i % 7
        x, y = 34 + col * (cell + gap), 82 + row * (cell + gap)
        svg += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}"><title>{date.isoformat()}: {count} contributions</title></rect>'
    svg += f'<text x="34" y="174" class="mono muted" font-size="10">LESS</text>'
    for i, color in enumerate(["#1a1c29","#37305f","#5545a5",BRAND,CYAN]):
        svg += f'<rect x="{80+i*18}" y="165" width="11" height="11" rx="2" fill="{color}"/>'
    svg += '<text x="184" y="174" class="mono muted" font-size="10">MORE</text></g>'
    write_card("contribution-graph.svg", svg)


def readme() -> str:
    repo_imgs = []
    for i, repo in enumerate(FEATURED, 1):
        slug = re.sub(r"[^a-z0-9]+", "-", repo[0].lower()).strip("-")
        repo_imgs.append(f'<a href="{repo[3]}"><img src="cards/repo-{i}-{slug}.svg" width="100%" alt="{repo[0]} featured project card" /></a>')
    return f'''<div align="center">

<img src="cards/hero.svg" width="100%" alt="Aryan Sharma — full-stack developer" />

<a href="https://github.com/aryan99dev/Portfolio"><img src="cards/tile-build.svg" width="32.5%" alt="Explore portfolio" /></a>
<a href="https://github.com/aryan99dev/Prism"><img src="cards/tile-explore.svg" width="32.5%" alt="Explore projects" /></a>
<a href="mailto:aryan99dev00@gmail.com"><img src="cards/tile-connect.svg" width="32.5%" alt="Contact Aryan" /></a>

<img src="cards/contributions.svg" width="100%" alt="Monthly GitHub contributions, streak, active days and busiest day" />

</div>

## Selected work

{chr(10).join(repo_imgs)}

<div align="center">
<img src="cards/contribution-graph.svg" width="100%" alt="GitHub contribution graph in Aryan's brand colour" />

[GitHub](https://github.com/{USERNAME}) · [Portfolio repository](https://github.com/{USERNAME}/Portfolio) · [Business email](mailto:aryan99dev00@gmail.com)

</div>

<!-- Cards are generated by scripts/render_cards.py. Edit FEATURED and visual settings there. -->
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-contributions", action="store_true")
    parser.add_argument("--skip-fonts", action="store_true")
    args = parser.parse_args()
    CARDS.mkdir(parents=True, exist_ok=True)
    if args.refresh_contributions:
        refresh_contributions()
    global FONT_CSS
    if not args.skip_fonts:
        FONT_CSS = subset_font("Jost", NAME + TAGLINE + "CONTRIBUTION PULSE FEATURED REPOSITORY THE CONSISTENCY MAP BUILD EXPLORE CONNECT " + "0123456789")
        FONT_CSS += subset_font("Syne Mono", "HELLO WORLD INDIA OPEN TO BUILDING COOL THINGS CONTRIBUTION PULSE DAY STREAK ACTIVE DAYS BUSIEST DAY LESS MORE")
    days = load_data()
    stats = contribution_stats(days)
    hero_card()
    tile_card("tile-build.svg", "01 / MAKE", "BUILD", "Portfolio & experiments", "https://github.com/aryan99dev/Portfolio", .35, "01")
    tile_card("tile-explore.svg", "02 / LEARN", "EXPLORE", "Projects & open source", "https://github.com/aryan99dev?tab=repositories", .35, "02")
    tile_card("tile-connect.svg", "03 / SAY HI", "CONNECT", "Let's make something", "mailto:aryan99dev00@gmail.com", .35, "03")
    contribution_card(stats, .85)
    for index, repo in enumerate(FEATURED, 1):
        repo_card(index, repo, 1.45 + index * .25)
    graph_card(days, 2.5)
    (ROOT / "README.md").write_text(readme(), encoding="utf-8")
    print(f"Rendered {len(list(CARDS.glob('*.svg')))} SVG cards in {CARDS.relative_to(ROOT)}/")
    print("STATIC=1 disables all motion and renders the final frame.")


if __name__ == "__main__":
    main()
