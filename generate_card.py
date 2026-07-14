"""
generate_card.py
=================
WHAT THIS DOES (plain English):
This script talks to the GitHub API, pulls your real stats (repo count,
commit count, stars, followers, lines of code added/removed), then
draws them into a dark "terminal card" SVG image next to your ASCII
art. The GitHub Action in .github/workflows/update-card.yml runs this
automatically on a schedule so the image always shows fresh numbers.

WHAT YOU CAN SAFELY EDIT:
- The STATIC_INFO dictionary below (OS, IDE, languages, hobbies, email,
  LinkedIn). This is plain text you type once.
- ascii_art.txt (swap in a new piece of art any time; layout auto-adjusts
  to however many lines it has).

WHAT YOU SHOULDN'T NEED TO TOUCH:
- Everything under "GitHub API calls" and "SVG drawing" further down.
"""

import os
import json
import time
import datetime
import requests

# ------------------------------------------------------------------
# 1. EDIT THIS BLOCK WITH YOUR OWN INFO
# ------------------------------------------------------------------
GITHUB_USERNAME = "RebEmnacin"

STATIC_INFO = {
    "os": "Windows 11",
    "ide": "VS Code",
    "languages_programming": "JavaScript, TypeScript, Python, Java",
    "languages_frameworks": "React, Node.js",
    "languages_real": "English, Filipino/Tagalog",
    "hobbies": "Minecraft, Photography",
    "email": "rebqemnacin@gmail.com",
    "linkedin": "linkedin.com/in/reb-emnacin",
}

# Colors (kept here so you can restyle without hunting through SVG code)
COLORS = {
    "background": "#0b0e14",
    "border": "#1f2430",
    "ascii_art": "#c8ccd4",
    "greeting": "#e5c07b",
    "divider": "#3b4048",
    "label": "#56b6c2",
    "value": "#d4d7dd",
    "header": "#61afef",
    "additions": "#98c379",
    "deletions": "#e06c75",
}

# ------------------------------------------------------------------
# 2. GitHub API calls (reads your token from the GH_TOKEN secret)
# ------------------------------------------------------------------
TOKEN = os.environ.get("GH_TOKEN")
if not TOKEN:
    raise SystemExit(
        "No GH_TOKEN environment variable found. "
        "In GitHub Actions this comes from secrets.ACCESS_TOKEN — "
        "see the setup note in update-card.yml."
    )

HEADERS_REST = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json"}
HEADERS_GQL = {"Authorization": f"bearer {TOKEN}"}

CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "cache.json")
os.makedirs(CACHE_DIR, exist_ok=True)
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        cache = json.load(f)
else:
    cache = {}


def graphql(query, variables=None):
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables or {}},
        headers=HEADERS_GQL,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def get_user_overview():
    query = """
    query($login: String!) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100, privacy: PUBLIC) {
          totalCount
          nodes { name stargazerCount }
        }
      }
    }
    """
    data = graphql(query, {"login": GITHUB_USERNAME})["user"]
    repos = data["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)
    return {
        "created_at": data["createdAt"],
        "followers": data["followers"]["totalCount"],
        "repo_count": data["repositories"]["totalCount"],
        "repo_names": [r["name"] for r in repos],
        "stars": stars,
    }


def get_total_commits(created_at_iso):
    """Loops year-by-year (GraphQL only allows ~1 year per query) and
    sums up commit contributions across your whole account history."""
    start_year = int(created_at_iso[:4])
    current_year = datetime.datetime.utcnow().year
    total = 0
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    for year in range(start_year, current_year + 1):
        from_date = f"{year}-01-01T00:00:00Z"
        to_date = f"{year}-12-31T23:59:59Z"
        data = graphql(query, {"login": GITHUB_USERNAME, "from": from_date, "to": to_date})
        c = data["user"]["contributionsCollection"]
        total += c["totalCommitContributions"] + c["restrictedContributionsCount"]
    return total


def get_lines_of_code(repo_names):
    """Sums additions/deletions credited to GITHUB_USERNAME across all
    owned repos, using the /stats/contributors endpoint. Caches per-repo
    so repos you haven't touched aren't re-downloaded every run."""
    total_add, total_del = 0, 0
    for repo in repo_names:
        cache_key = repo
        url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{repo}/stats/contributors"
        attempts = 0
        data = None
        while attempts < 3:
            resp = requests.get(url, headers=HEADERS_REST, timeout=30)
            if resp.status_code == 202:
                # GitHub is still computing stats for this repo; wait and retry
                time.sleep(3)
                attempts += 1
                continue
            if resp.status_code == 200:
                data = resp.json()
            break

        if not data:
            # fall back to last cached value for this repo, if any
            cached = cache.get(cache_key)
            if cached:
                total_add += cached["add"]
                total_del += cached["del"]
            continue

        repo_add, repo_del = 0, 0
        for contributor in data:
            if contributor.get("author") and contributor["author"].get("login") == GITHUB_USERNAME:
                for week in contributor.get("weeks", []):
                    repo_add += week.get("a", 0)
                    repo_del += week.get("d", 0)

        cache[cache_key] = {"add": repo_add, "del": repo_del}
        total_add += repo_add
        total_del += repo_del

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    return total_add, total_del


def format_uptime(created_at_iso):
    created = datetime.datetime.strptime(created_at_iso, "%Y-%m-%dT%H:%M:%SZ")
    now = datetime.datetime.utcnow()
    delta_days = (now - created).days
    years = delta_days // 365
    months = (delta_days % 365) // 30
    days = (delta_days % 365) % 30
    return f"{years} years, {months} months, {days} days"


def comma(n):
    return f"{n:,}"


# ------------------------------------------------------------------
# 3. Pull everything together
# ------------------------------------------------------------------
overview = get_user_overview()
commits = get_total_commits(overview["created_at"])
loc_add, loc_del = get_lines_of_code(overview["repo_names"])
uptime = format_uptime(overview["created_at"])

STATS = {
    "repos": comma(overview["repo_count"]),
    "commits": comma(commits),
    "stars": comma(overview["stars"]),
    "followers": comma(overview["followers"]),
    "loc_add": comma(loc_add),
    "loc_del": comma(loc_del),
    "uptime": uptime,
}

# ------------------------------------------------------------------
# 4. SVG drawing
# ------------------------------------------------------------------
def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


with open("ascii_art.txt", "r") as f:
    art_lines = [line.rstrip("\n") for line in f.readlines()]

ART_FONT_SIZE = 6
ART_LINE_HEIGHT = 9
ART_X = 30
ART_Y_START = 34

art_tspans = "\n".join(
    f'<tspan x="{ART_X}" dy="{ART_LINE_HEIGHT if i else 0}">{esc(line)}</tspan>'
    for i, line in enumerate(art_lines)
)

art_block_height = ART_Y_START + len(art_lines) * ART_LINE_HEIGHT + 20

STAT_X = 470
STAT_FONT_SIZE = 13
STAT_LINE_HEIGHT = 21
STAT_Y_START = 40

greeting = f"{GITHUB_USERNAME.lower()}@{GITHUB_USERNAME.lower()}"
dash_fill = "-" * max(4, 58 - len(greeting))

# Each entry: (kind, text) OR ("stat_line", label, dots, value, value_color)
lines = [
    ("greeting", f"{greeting} {dash_fill}"),
    ("blank",),
    ("row", "OS:", "......................................", STATIC_INFO["os"]),
    ("row", "Uptime:", "..................................", STATS["uptime"]),
    ("row", "IDE:", "......................................", STATIC_INFO["ide"]),
    ("blank",),
    ("row", "Languages.Programming:", "......", STATIC_INFO["languages_programming"]),
    ("row", "Languages.Frameworks:", ".......", STATIC_INFO["languages_frameworks"]),
    ("row", "Languages.Real:", ".............", STATIC_INFO["languages_real"]),
    ("blank",),
    ("row", "Hobbies:", ".................................", STATIC_INFO["hobbies"]),
    ("blank",),
    ("header", "- Contact -"),
    ("row", "Email.Personal:", ".............", STATIC_INFO["email"]),
    ("row", "LinkedIn:", "................................", STATIC_INFO["linkedin"]),
    ("blank",),
    ("header", "- GitHub Stats -"),
    ("row", "Repos:", "...................................", STATS["repos"]),
    ("row", "Commits:", ".................................", STATS["commits"]),
    ("row", "Stars:", "...................................", STATS["stars"]),
    ("row", "Followers:", "...............................", STATS["followers"]),
    ("loc", "Lines of Code on GitHub:", STATS["loc_add"], STATS["loc_del"]),
]

stat_svg_lines = []
y = STAT_Y_START
for entry in lines:
    kind = entry[0]
    if kind == "blank":
        y += STAT_LINE_HEIGHT
        continue
    if kind == "greeting":
        stat_svg_lines.append(
            f'<text x="{STAT_X}" y="{y}" font-family="Consolas, monospace" '
            f'font-size="{STAT_FONT_SIZE}" fill="{COLORS["greeting"]}">{esc(entry[1])}</text>'
        )
    elif kind == "header":
        stat_svg_lines.append(
            f'<text x="{STAT_X}" y="{y}" font-family="Consolas, monospace" '
            f'font-size="{STAT_FONT_SIZE}" fill="{COLORS["header"]}">{esc(entry[1])}</text>'
        )
    elif kind == "row":
        _, label, dots, value = entry
        stat_svg_lines.append(
            f'<text x="{STAT_X}" y="{y}" font-family="Consolas, monospace" font-size="{STAT_FONT_SIZE}">'
            f'<tspan fill="{COLORS["label"]}">{esc(label)}</tspan>'
            f'<tspan fill="{COLORS["divider"]}"> {esc(dots)} </tspan>'
            f'<tspan fill="{COLORS["value"]}">{esc(value)}</tspan>'
            f"</text>"
        )
    elif kind == "loc":
        _, label, add, deletion = entry
        stat_svg_lines.append(
            f'<text x="{STAT_X}" y="{y}" font-family="Consolas, monospace" font-size="{STAT_FONT_SIZE}">'
            f'<tspan fill="{COLORS["label"]}">{esc(label)}</tspan>'
            f'<tspan fill="{COLORS["divider"]}"> .... </tspan>'
            f'<tspan fill="{COLORS["additions"]}">{esc(add)}++</tspan>'
            f'<tspan fill="{COLORS["value"]}">  </tspan>'
            f'<tspan fill="{COLORS["deletions"]}">{esc(deletion)}--</tspan>'
            f"</text>"
        )
    y += STAT_LINE_HEIGHT

stat_block_height = y + 20
canvas_height = max(art_block_height, stat_block_height)
canvas_width = 1050

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">
  <rect width="{canvas_width}" height="{canvas_height}" rx="10" fill="{COLORS['background']}" stroke="{COLORS['border']}" stroke-width="1"/>
  <text xml:space="preserve" x="{ART_X}" y="{ART_Y_START}" font-family="Consolas, Monaco, monospace" font-size="{ART_FONT_SIZE}" fill="{COLORS['ascii_art']}">
{art_tspans}
  </text>
  {chr(10).join(stat_svg_lines)}
</svg>"""

with open("profile-card.svg", "w") as f:
    f.write(svg)

print("profile-card.svg generated successfully.")
print(STATS)
