import json
import os
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


API_URL = "https://api.github.com/graphql"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_STATS = REPO_ROOT / "github-stats.svg"
OUTPUT_LANGS = REPO_ROOT / "top-langs.svg"
OUTPUT_METRICS = REPO_ROOT / "github-metrics.svg"
USERNAME = os.environ.get("GITHUB_USERNAME", "mathvll")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("METRICS_TOKEN")


GRAPHQL_QUERY = """
query ProfileData($login: String!, $yearStart: DateTime!, $monthStart: DateTime!, $now: DateTime!) {
  user(login: $login) {
    name
    login
    createdAt
    followers {
      totalCount
    }
    following {
      totalCount
    }
    yearCommits: contributionsCollection(from: $yearStart, to: $now) {
      totalCommitContributions
    }
    monthCommits: contributionsCollection(from: $monthStart, to: $now) {
      totalCommitContributions
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
        updatedAt
        pushedAt
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


ORGANIZATIONS_QUERY = """
query ProfileOrganizations($login: String!) {
  user(login: $login) {
    organizations(first: 20) {
      totalCount
      nodes {
        login
        name
      }
    }
  }
}
""".strip()


HYPPESOCIAL_REPOSITORIES_QUERY = """
query HyppeSocialRepositories {
  organization(login: "HyppeSocial") {
    repositories(first: 1, isFork: false) {
      totalCount
    }
    languageRepositories: repositories(first: 100, isFork: false) {
      nodes {
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
        raise RuntimeError("GITHUB_TOKEN nao configurado.")

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

    return data["data"]


def fetch_organizations(login: str) -> dict:
    try:
        return post_graphql(ORGANIZATIONS_QUERY, {"login": login})["user"]["organizations"]
    except RuntimeError as exc:
        if "INSUFFICIENT_SCOPES" in str(exc) or "read:org" in str(exc):
            return {"totalCount": None, "nodes": [], "available": False}
        raise


def fetch_hyppesocial_repositories() -> dict:
    data = post_graphql(HYPPESOCIAL_REPOSITORIES_QUERY, {})
    organization = data.get("organization")
    if not organization:
        return {"totalCount": 0, "nodes": []}
    return {
        "totalCount": organization["repositories"]["totalCount"],
        "nodes": organization["languageRepositories"]["nodes"],
    }


def format_number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_date(value: str | None) -> str:
    if not value:
        return "Sem data"
    year, month, day = value[:10].split("-")
    return f"{day}/{month}/{year}"


def repository_nodes(profile: dict) -> list[dict]:
    return profile["repositories"]["nodes"]


def language_totals(profile: dict) -> tuple[list[tuple[str, int]], dict[str, str]]:
    totals = defaultdict(int)
    colors = {}
    repositories = repository_nodes(profile) + profile.get("hyppeSocialRepositoryNodes", [])

    for repo in repositories:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            totals[name] += edge["size"]
            colors[name] = edge["node"]["color"] or "#94a3b8"

    return sorted(totals.items(), key=lambda item: item[1], reverse=True), colors


def repo_totals(profile: dict) -> tuple[int, int]:
    stars = sum(repo["stargazerCount"] for repo in repository_nodes(profile))
    forks = sum(repo["forkCount"] for repo in repository_nodes(profile))
    return stars, forks


def svg_shell(width: int, height: int, title_id: str, desc_id: str, title: str, desc: str, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="{title_id} {desc_id}">
  <title id="{title_id}">{escape(title)}</title>
  <desc id="{desc_id}">{escape(desc)}</desc>
  <defs>
    <linearGradient id="{title_id}Bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="55%" stop-color="#111827" />
      <stop offset="100%" stop-color="#1e3a5f" />
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="18" fill="url(#{title_id}Bg)" />
  <rect x="14" y="14" width="{width - 28}" height="{height - 28}" rx="14" fill="#0b1220" stroke="#24324a" />
{body}
</svg>
"""


def build_stats_svg(profile: dict) -> str:
    stat_items = [
        ("Repos pessoais", format_number(profile["repositories"]["totalCount"])),
        ("HyppeSocial", format_number(profile["hyppeSocialRepositories"])),
        ("Commits no ano", format_number(profile["yearCommits"]["totalCommitContributions"])),
        ("Commits no mês", format_number(profile["monthCommits"]["totalCommitContributions"])),
    ]

    cards = []
    positions = [(32, 98), (196, 98), (360, 98), (524, 98)]
    for (label, value), (x, y) in zip(stat_items, positions):
        cards.append(
            f"""  <g transform="translate({x},{y})">
    <rect width="144" height="72" rx="12" fill="#111827" stroke="#25324a" />
    <rect width="144" height="4" rx="2" fill="#60a5fa" />
    <text x="72" y="29" text-anchor="middle" fill="#93c5fd" font-size="13" font-family="Segoe UI, Arial, sans-serif">{escape(label)}</text>
    <text x="72" y="56" text-anchor="middle" fill="#f8fafc" font-size="24" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{escape(value)}</text>
  </g>"""
        )

    body = f"""  <text x="352" y="48" text-anchor="middle" fill="#f8fafc" font-size="24" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Atividade no GitHub</text>
  <text x="352" y="74" text-anchor="middle" fill="#94a3b8" font-size="14" font-family="Segoe UI, Arial, sans-serif">Commits contabilizados pelo GitHub</text>
{chr(10).join(cards)}"""
    return svg_shell(704, 196, "statsTitle", "statsDesc", "Atividade no GitHub", f"Repositórios e commits contabilizados pelo GitHub para {profile['login']}.", body)


def build_langs_svg(profile: dict) -> str:
    languages, colors = language_totals(profile)
    language_marks = {
        "TypeScript": "TS", "JavaScript": "JS", "Python": "Py", "HTML": "H5",
        "CSS": "CSS", "Java": "J", "Go": "Go", "Rust": "Rs", "C++": "C++",
        "C#": "C#", "Ruby": "Rb", "PHP": "PHP", "Swift": "Sw", "Kotlin": "Kt",
        "PLpgSQL": "SQL", "Shell": "SH", "Less": "Le",
    }
    frontend_names = {
        "TypeScript", "JavaScript", "HTML", "CSS", "Less", "SCSS", "Sass",
        "Vue", "Svelte", "Astro", "Swift", "Kotlin", "Go Template",
    }
    frontend = [(name, size) for name, size in languages if name in frontend_names]
    backend = [(name, size) for name, size in languages if name not in frontend_names]
    backend.sort(key=lambda item: item[1], reverse=True)
    if len(backend) > 5:
        backend = backend[:5] + [("Outros", sum(size for _, size in backend[5:]))]

    marks = []
    groups = [("Backend", backend, 24), ("Frontend", frontend, 360)]
    for title, entries, x in groups:
        group_total = sum(size for _, size in entries)
        max_percentage = max(
            (size / group_total * 100 for _, size in entries),
            default=1,
        )
        panel_width = 320
        marks.append(
            f'''  <g>
    <rect x="{x}" y="92" width="{panel_width}" height="282" rx="14" fill="#111827" stroke="#25324a" />
    <text x="{x + 18}" y="121" fill="#f8fafc" font-size="19" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{title}</text>'''
        )
        for index, (language, size) in enumerate(entries):
            y = 151 + index * 27
            percentage = 0 if group_total == 0 else (size / group_total) * 100
            percentage_label = f"{percentage:.1f}%" if percentage >= 0.05 else "<0.1%"
            bar_width = max(2, 250 * percentage / max_percentage) if group_total else 0
            mark = "+" if language == "Outros" else language_marks.get(language, language[:2])
            label = "Swift (SwiftUI)" if language == "Swift" else language
            color = colors.get(language, "#64748b")
            marks.append(
                f'''    <g>
      <circle cx="{x + 26}" cy="{y}" r="10" fill="{color}" fill-opacity="0.2" stroke="{color}" />
      <text x="{x + 26}" y="{y + 3}" text-anchor="middle" fill="#f8fafc" font-size="8" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{escape(mark)}</text>
      <text x="{x + 44}" y="{y + 4}" fill="#e2e8f0" font-size="12" font-family="Segoe UI, Arial, sans-serif">{escape(label)}</text>
      <text x="{x + 300}" y="{y + 4}" text-anchor="end" fill="#f8fafc" font-size="12" font-weight="600" font-family="Segoe UI, Arial, sans-serif">{percentage_label}</text>
      <rect x="{x + 44}" y="{y + 10}" width="250" height="3" rx="1.5" fill="#25324a" />
      <rect x="{x + 44}" y="{y + 10}" width="{bar_width:.1f}" height="3" rx="1.5" fill="{color}" />
    </g>'''
            )
        marks.append("  </g>")

    body = f"""  <text x="352" y="42" text-anchor="middle" fill="#f8fafc" font-size="22" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Distribuição de linguagens</text>
  <text x="352" y="66" text-anchor="middle" fill="#94a3b8" font-size="13" font-family="Segoe UI, Arial, sans-serif">Repos pessoais + HyppeSocial · % por área · TypeScript/JavaScript no Frontend</text>
{chr(10).join(marks)}"""
    return svg_shell(704, 396, "langsTitle", "langsDesc", "Distribuição de linguagens", f"Distribuição de linguagens de backend e frontend nos repositórios pessoais e HyppeSocial de {profile['login']}.", body)


def build_metrics_svg(profile: dict) -> str:
    languages, colors = language_totals(profile)
    top_languages = languages[:5]
    stars, forks = repo_totals(profile)
    organizations = profile["organizations"]
    org_names = [
        org.get("name") or org.get("login")
        for org in organizations["nodes"][:4]
        if org.get("name") or org.get("login")
    ]
    org_text = ", ".join(org_names) if org_names else "Organizacoes nao disponiveis"
    latest_repo = max(repository_nodes(profile), key=lambda repo: repo.get("updatedAt") or "", default={})
    org_count = organizations["totalCount"]
    org_value = format_number(org_count) if isinstance(org_count, int) else "Nao disponivel"

    stat_items = [
        ("Conta criada em", format_date(profile.get("createdAt"))),
        ("Repositorios", format_number(profile["repositories"]["totalCount"])),
        ("Organizacoes visiveis", org_value),
        ("Contribuicoes no ano", format_number(profile["contributionsCollection"]["contributionCalendar"]["totalContributions"])),
        ("Stars recebidas", format_number(stars)),
        ("Forks recebidos", format_number(forks)),
    ]

    cards = []
    positions = [(40, 118), (322, 118), (604, 118), (40, 240), (322, 240), (604, 240)]
    for (label, value), (x, y) in zip(stat_items, positions):
        cards.append(
            f"""  <g transform="translate({x},{y})">
    <rect width="242" height="88" rx="12" fill="#111827" stroke="#25324a" />
    <text x="18" y="32" fill="#93c5fd" font-size="14" font-family="Segoe UI, Arial, sans-serif">{escape(label)}</text>
    <text x="18" y="62" fill="#f8fafc" font-size="23" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{escape(value)}</text>
  </g>"""
        )

    language_rows = []
    total_size = sum(size for _, size in top_languages)
    for index, (language, size) in enumerate(top_languages):
        y = 420 + index * 42
        percentage = 0 if total_size == 0 else (size / total_size) * 100
        bar_width = max(8, round((percentage / 100) * 260)) if total_size else 0
        language_rows.append(
            f"""  <g transform="translate(40,{y})">
    <text x="0" y="14" fill="#f8fafc" font-size="15" font-weight="600" font-family="Segoe UI, Arial, sans-serif">{escape(language)}</text>
    <rect x="150" y="2" width="260" height="12" rx="6" fill="#111827" />
    <rect x="150" y="2" width="{bar_width}" height="12" rx="6" fill="{colors.get(language, '#94a3b8')}" />
    <text x="430" y="14" fill="#94a3b8" font-size="14" font-family="Segoe UI, Arial, sans-serif">{percentage:.1f}%</text>
  </g>"""
        )

    if not language_rows:
        language_rows.append('  <text x="40" y="434" fill="#94a3b8" font-size="15" font-family="Segoe UI, Arial, sans-serif">Nenhuma linguagem detectada nos repositorios analisados.</text>')

    body = f"""  <text x="40" y="58" fill="#f8fafc" font-size="32" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Detalhamento tecnico</text>
  <text x="40" y="90" fill="#94a3b8" font-size="16" font-family="Segoe UI, Arial, sans-serif">Visao consolidada de repositorios, contribuicoes, linguagens e organizacoes.</text>
{chr(10).join(cards)}
  <text x="40" y="382" fill="#f8fafc" font-size="22" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Linguagens agregadas</text>
  <text x="504" y="382" fill="#f8fafc" font-size="22" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Contexto recente</text>
{chr(10).join(language_rows)}
  <g transform="translate(504,410)">
    <rect width="356" height="170" rx="12" fill="#111827" stroke="#25324a" />
    <text x="20" y="34" fill="#93c5fd" font-size="14" font-family="Segoe UI, Arial, sans-serif">Organizacoes</text>
    <text x="20" y="62" fill="#f8fafc" font-size="16" font-family="Segoe UI, Arial, sans-serif">{escape(org_text[:42])}</text>
    <text x="20" y="106" fill="#93c5fd" font-size="14" font-family="Segoe UI, Arial, sans-serif">Repositorio atualizado recentemente</text>
    <text x="20" y="134" fill="#f8fafc" font-size="16" font-family="Segoe UI, Arial, sans-serif">{escape((latest_repo.get("name") or "Sem repositorios")[:42])}</text>
  </g>"""
    return svg_shell(900, 640, "metricsTitle", "metricsDesc", "Detalhamento tecnico", f"Detalhamento tecnico do perfil GitHub de {profile['login']}.", body)


def main() -> None:
    now = datetime.now(timezone.utc)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    profile = post_graphql(
        GRAPHQL_QUERY,
        {
            "login": USERNAME,
            "yearStart": year_start.isoformat().replace("+00:00", "Z"),
            "monthStart": month_start.isoformat().replace("+00:00", "Z"),
            "now": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
    )["user"]
    profile["organizations"] = fetch_organizations(USERNAME)
    hyppe_social = fetch_hyppesocial_repositories()
    profile["hyppeSocialRepositories"] = hyppe_social["totalCount"]
    profile["hyppeSocialRepositoryNodes"] = hyppe_social["nodes"]
    OUTPUT_STATS.write_text(build_stats_svg(profile), encoding="utf-8")
    OUTPUT_LANGS.write_text(build_langs_svg(profile), encoding="utf-8")
    OUTPUT_METRICS.write_text(build_metrics_svg(profile), encoding="utf-8")


if __name__ == "__main__":
    main()
