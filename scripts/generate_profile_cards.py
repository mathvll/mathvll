import json
import math
import os
import textwrap
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape


API_URL = "https://api.github.com/graphql"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_STATS = REPO_ROOT / "github-stats.svg"
OUTPUT_LANGS = REPO_ROOT / "top-langs.svg"
USERNAME = os.environ.get("GITHUB_USERNAME", "mathvll")
TOKEN = os.environ.get("METRICS_TOKEN")


GRAPHQL_QUERY = """
query ProfileData($login: String!) {
  user(login: $login) {
    name
    login
    followers {
      totalCount
    }
    following {
      totalCount
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
      }
    }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      orderBy: {field: UPDATED_AT, direction: DESC}
      isFork: false
    ) {
      totalCount
      nodes {
        name
        stargazerCount
        forkCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
  }
}
""".strip()


def post_graphql(query: str, variables: dict) -> dict:
    if not TOKEN:
        raise RuntimeError("METRICS_TOKEN nao configurado.")

    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"{USERNAME}-profile-cards",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Falha ao consultar a API do GitHub: {exc.code} {details}") from exc

    if data.get("errors"):
        raise RuntimeError(f"GraphQL retornou erro: {data['errors']}")

    return data["data"]["user"]


def format_number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def wrap_text(text: str, width: int) -> str:
    return "<br/>".join(escape(line) for line in textwrap.wrap(text, width=width))


def build_stats_svg(profile: dict) -> str:
    repo_total = profile["repositories"]["totalCount"]
    stars = sum(repo["stargazerCount"] for repo in profile["repositories"]["nodes"])
    forks = sum(repo["forkCount"] for repo in profile["repositories"]["nodes"])
    contributions = profile["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    followers = profile["followers"]["totalCount"]
    following = profile["following"]["totalCount"]

    stat_items = [
        ("Repositorios", format_number(repo_total)),
        ("Stars", format_number(stars)),
        ("Forks", format_number(forks)),
        ("Contribuicoes/ano", format_number(contributions)),
        ("Seguidores", format_number(followers)),
        ("Seguindo", format_number(following)),
    ]

    cards = []
    positions = [(32, 132), (256, 132), (480, 132), (32, 256), (256, 256), (480, 256)]
    for (label, value), (x, y) in zip(stat_items, positions):
        cards.append(
            f"""
      <g transform="translate({x},{y})">
        <rect width="192" height="96" rx="18" fill="#111827" stroke="#25324a" />
        <text x="20" y="34" fill="#93c5fd" font-size="15" font-family="Segoe UI, Arial, sans-serif">{escape(label)}</text>
        <text x="20" y="70" fill="#f8fafc" font-size="28" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{escape(value)}</text>
      </g>"""
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="704" height="392" viewBox="0 0 704 392" role="img" aria-labelledby="statsTitle statsDesc">
  <title id="statsTitle">GitHub Stats</title>
  <desc id="statsDesc">Resumo tecnico do perfil do GitHub de {escape(profile["login"])}.</desc>
  <defs>
    <linearGradient id="statsBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#172554" />
    </linearGradient>
  </defs>
  <rect width="704" height="392" rx="24" fill="url(#statsBg)" />
  <rect x="16" y="16" width="672" height="360" rx="22" fill="#0b1220" stroke="#1e293b" />
  <text x="32" y="56" fill="#f8fafc" font-size="30" font-weight="700" font-family="Segoe UI, Arial, sans-serif">GitHub Stats</text>
  <text x="32" y="88" fill="#94a3b8" font-size="16" font-family="Segoe UI, Arial, sans-serif">Resumo local gerado por GitHub Actions para evitar dependencia de cards externos.</text>
  {''.join(cards)}
</svg>
"""


def build_langs_svg(profile: dict) -> str:
    totals = defaultdict(int)
    colors = {}

    for repo in profile["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            totals[name] += edge["size"]
            colors[name] = edge["node"]["color"] or "#94a3b8"

    total_size = sum(totals.values())
    top_languages = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:6]

    rows = []
    bar_y = 132
    current_x = 32
    bar_width = 640
    for language, size in top_languages:
        width = 0 if total_size == 0 else max(8, round((size / total_size) * bar_width))
        rows.append(f'<rect x="{current_x}" y="{bar_y}" width="{width}" height="14" rx="7" fill="{colors.get(language, "#94a3b8")}" />')
        current_x += width

    legend = []
    start_y = 184
    for index, (language, size) in enumerate(top_languages):
        col = index % 2
        row = index // 2
        x = 32 + (col * 320)
        y = start_y + (row * 58)
        percentage = 0 if total_size == 0 else (size / total_size) * 100
        legend.append(
            f"""
      <g transform="translate({x},{y})">
        <circle cx="10" cy="10" r="10" fill="{colors.get(language, '#94a3b8')}" />
        <text x="30" y="14" fill="#f8fafc" font-size="18" font-weight="600" font-family="Segoe UI, Arial, sans-serif">{escape(language)}</text>
        <text x="30" y="38" fill="#94a3b8" font-size="14" font-family="Segoe UI, Arial, sans-serif">{percentage:.1f}% do codigo analisado</text>
      </g>"""
        )

    note = "Baseado no tamanho agregado das linguagens nos repositorios do perfil."

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="704" height="392" viewBox="0 0 704 392" role="img" aria-labelledby="langsTitle langsDesc">
  <title id="langsTitle">Top Langs</title>
  <desc id="langsDesc">Distribuicao de linguagens mais usadas no perfil de {escape(profile["login"])}.</desc>
  <defs>
    <linearGradient id="langsBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1f2937" />
    </linearGradient>
  </defs>
  <rect width="704" height="392" rx="24" fill="url(#langsBg)" />
  <rect x="16" y="16" width="672" height="360" rx="22" fill="#0b1220" stroke="#1e293b" />
  <text x="32" y="56" fill="#f8fafc" font-size="30" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Top Langs</text>
  <text x="32" y="88" fill="#94a3b8" font-size="16" font-family="Segoe UI, Arial, sans-serif">{escape(note)}</text>
  <rect x="32" y="{bar_y}" width="{bar_width}" height="14" rx="7" fill="#111827" />
  {''.join(rows)}
  {''.join(legend)}
</svg>
"""


def main() -> None:
    profile = post_graphql(GRAPHQL_QUERY, {"login": USERNAME})
    OUTPUT_STATS.write_text(build_stats_svg(profile), encoding="utf-8")
    OUTPUT_LANGS.write_text(build_langs_svg(profile), encoding="utf-8")


if __name__ == "__main__":
    main()
