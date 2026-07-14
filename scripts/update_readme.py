#!/usr/bin/env python3
"""
Self-updating GitHub profile README generator.

Reads README.template.md, replaces the content between <!--MARKER--> ...
<!--END_MARKER--> pairs with freshly fetched data, and writes README.md.

Each section fails independently: if an API call errors, that section keeps
its previous content (or a fallback) so the README never blanks out.

Env vars:
  GITHUB_TOKEN   required. In Actions the built-in secret works for public data.
                 Use a PAT with `repo` scope if you want private-repo stats.
  GH_USERNAME    optional. Defaults to the authenticated user (the token owner).
  BLOG_RSS_URL   optional. e.g. https://dev.to/feed/yourname — enables the blog section.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "README.template.md"
OUTPUT = ROOT / "README.md"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GH_USERNAME = os.environ.get("GH_USERNAME", "").strip()
BLOG_RSS_URL = os.environ.get("BLOG_RSS_URL", "").strip()

GRAPHQL_URL = "https://api.github.com/graphql"
SESSION = requests.Session()
SESSION.headers.update(
    {
        "Authorization": f"bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "readme-auto-updater",
    }
)


# --------------------------------------------------------------------------- #
# GitHub data                                                                 #
# --------------------------------------------------------------------------- #

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    followers { totalCount }
    following { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name
        url
        description
        pushedAt
        stargazerCount
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      restrictedContributionsCount
    }
  }
}
"""


def fetch_profile(login: str | None) -> dict:
    """Run the profile GraphQL query. If login is falsy, resolve the viewer first."""
    if not login:
        viewer = SESSION.post(
            GRAPHQL_URL, json={"query": "{ viewer { login } }"}, timeout=30
        )
        viewer.raise_for_status()
        login = viewer.json()["data"]["viewer"]["login"]

    resp = SESSION.post(
        GRAPHQL_URL,
        json={"query": PROFILE_QUERY, "variables": {"login": login}},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]["user"]


# --------------------------------------------------------------------------- #
# Section renderers                                                           #
# --------------------------------------------------------------------------- #


def render_recent_repos(user: dict, limit: int = 5) -> str:
    repos = user["repositories"]["nodes"][:limit]
    if not repos:
        return "_No public repositories yet._"

    lines = []
    for r in repos:
        desc = (r.get("description") or "").strip() or "—"
        lang = (r.get("primaryLanguage") or {}).get("name") or ""
        lang_badge = f" · `{lang}`" if lang else ""
        stars = r["stargazerCount"]
        star_badge = f" · ⭐ {stars}" if stars else ""
        lines.append(f"- [**{r['name']}**]({r['url']}){lang_badge}{star_badge}  \n  {desc}")
    return "\n".join(lines)


def render_stats(user: dict) -> str:
    contrib = user["contributionsCollection"]
    total_stars = sum(r["stargazerCount"] for r in user["repositories"]["nodes"])
    commits = contrib["totalCommitContributions"] + contrib["restrictedContributionsCount"]
    rows = [
        ("⭐ Total stars", total_stars),
        ("📦 Public repos", user["repositories"]["totalCount"]),
        ("🧑‍💻 Commits (this year)", commits),
        ("🔀 Pull requests (this year)", contrib["totalPullRequestContributions"]),
        ("👥 Followers", user["followers"]["totalCount"]),
    ]
    return "\n".join(f"| {label} | **{value}** |" for label, value in rows)


def render_top_languages(user: dict, limit: int = 6) -> str:
    totals: dict[str, int] = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            totals[name] = totals.get(name, 0) + edge["size"]

    if not totals:
        return "_No language data yet._"

    grand = sum(totals.values())
    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]

    lines = []
    for name, size in top:
        pct = size / grand * 100
        filled = round(pct / 5)  # 20-cell bar
        bar = "█" * filled + "░" * (20 - filled)
        lines.append(f"`{name:<16}` `{bar}` {pct:5.1f}%")
    return "\n".join(lines)


def render_blog(url: str, limit: int = 4) -> str:
    if not url:
        return "_Set BLOG_RSS_URL to show your latest posts._"
    try:
        import feedparser  # imported lazily so the core works without it
    except ImportError:
        return "_Install `feedparser` to enable the blog section._"

    feed = feedparser.parse(url)
    if not feed.entries:
        return "_No posts found._"

    lines = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "Untitled").strip()
        link = entry.get("link", "")
        lines.append(f"- [{title}]({link})")
    return "\n".join(lines)


def render_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return f"⚙️ Last auto-updated: {now.strftime('%Y-%m-%d %H:%M UTC')}"


# --------------------------------------------------------------------------- #
# Marker replacement                                                          #
# --------------------------------------------------------------------------- #


def replace_marker(text: str, marker: str, content: str) -> str:
    """Replace everything between <!--MARKER--> and <!--END_MARKER-->."""
    pattern = re.compile(
        rf"(<!--{marker}-->)(.*?)(<!--END_{marker}-->)", re.DOTALL
    )
    if not pattern.search(text):
        print(f"  ! marker {marker} not found in template — skipping", file=sys.stderr)
        return text
    return pattern.sub(rf"\1\n{content}\n\3", text)


def safe(section: str, fn, *args):
    """Run a renderer, returning a friendly note on failure instead of crashing."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — sections must fail independently
        print(f"  ! {section} failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN is not set.", file=sys.stderr)
        return 1
    if not TEMPLATE.exists():
        print(f"Template not found: {TEMPLATE}", file=sys.stderr)
        return 1

    print("Fetching GitHub profile data…")
    user = fetch_profile(GH_USERNAME or None)
    print(f"  user: {user['login']}")

    text = TEMPLATE.read_text(encoding="utf-8")

    sections = {
        "RECENT_REPOS": safe("recent_repos", render_recent_repos, user),
        "STATS": safe("stats", render_stats, user),
        "TOP_LANGS": safe("top_languages", render_top_languages, user),
        "BLOG": safe("blog", render_blog, BLOG_RSS_URL),
        "TIMESTAMP": render_timestamp(),
    }

    for marker, content in sections.items():
        if content is not None:
            text = replace_marker(text, marker, content)

    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
