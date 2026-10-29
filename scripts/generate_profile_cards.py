import json
import os
import urllib.error
import urllib.request
from collections import defaultdict
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
query ProfileData($login: String!) {
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

    return data["data"]["user"]


def fetch_organizations(login: str) -> dict:
    try:
        return post_graphql(ORGANIZATIONS_QUERY, {"login": login})["organizations"]
    except RuntimeError as exc:
        if "INSUFFICIENT_SCOPES" in str(exc) or "read:org" in str(exc):
            return {"totalCount": None, "nodes": [], "available": False}
        raise


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

    for repo in repository_nodes(profile):
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
    stars, forks = repo_totals(profile)
    contributions = profile["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    stat_items = [
        ("Repositorios", format_number(profile["repositories"]["totalCount"])),
        ("Contribuicoes", format_number(contributions)),
        ("Stars", format_number(stars)),
        ("Forks", format_number(forks)),
        ("Seguidores", format_number(profile["followers"]["totalCount"])),
        ("Seguindo", format_number(profile["following"]["totalCount"])),
    ]

    cards = []
    positions = [(32, 124), (256, 124), (480, 124), (32, 248), (256, 248), (480, 248)]
    for (label, value), (x, y) in zip(stat_items, positions):
        cards.append(
            f"""  <g transform="translate({x},{y})">
    <rect width="192" height="96" rx="12" fill="#111827" stroke="#25324a" />
    <text x="20" y="34" fill="#93c5fd" font-size="15" font-family="Segoe UI, Arial, sans-serif">{escape(label)}</text>
    <text x="20" y="70" fill="#f8fafc" font-size="28" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{escape(value)}</text>
  </g>"""
        )

    body = f"""  <text x="32" y="56" fill="#f8fafc" font-size="30" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Resumo da atividade</text>
  <text x="32" y="88" fill="#94a3b8" font-size="16" font-family="Segoe UI, Arial, sans-serif">Indicadores gerais do perfil e dos repositorios.</text>
{chr(10).join(cards)}"""
    return svg_shell(704, 376, "statsTitle", "statsDesc", "GitHub Stats", f"Resumo do perfil GitHub de {profile['login']}.", body)


def build_langs_svg(profile: dict) -> str:
    languages, colors = language_totals(profile)
    top_languages = languages[:6]
    total_size = sum(size for _, size in languages)
    language_marks = {
        "TypeScript": "TS", "JavaScript": "JS", "Python": "Py", "HTML": "H5",
        "CSS": "CSS", "Java": "J", "Go": "Go", "Rust": "Rs", "C++": "C++",
        "C#": "C#", "Ruby": "Rb", "PHP": "PHP", "Swift": "Sw", "Kotlin": "Kt",
    }

    marks = []
    column_width = 640 / max(len(top_languages), 1)
    for index, (language, size) in enumerate(top_languages):
        center_x = 32 + column_width * (index + 0.5)
        percentage = 0 if total_size == 0 else (size / total_size) * 100
        mark = language_marks.get(language, language[:2])
        marks.append(
            f'''  <g transform="translate({center_x:.1f},0)">
    <circle cx="0" cy="126" r="27" fill="{colors.get(language, '#94a3b8')}" fill-opacity="0.18" stroke="{colors.get(language, '#94a3b8')}" stroke-width="2" />
    <text x="0" y="132" text-anchor="middle" fill="#f8fafc" font-size="{12 if len(mark) > 2 else 15}" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{escape(mark)}</text>
    <text x="0" y="174" text-anchor="middle" fill="#f8fafc" font-size="18" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{percentage:.1f}%</text>
    <text x="0" y="198" text-anchor="middle" fill="#94a3b8" font-size="13" font-family="Segoe UI, Arial, sans-serif">{escape(language)}</text>
  </g>'''
        )

    if not marks:
        marks.append('  <text x="352" y="148" text-anchor="middle" fill="#94a3b8" font-size="16" font-family="Segoe UI, Arial, sans-serif">Nenhuma linguagem detectada nos repositórios analisados.</text>')

    body = f"""  <text x="352" y="53" text-anchor="middle" fill="#f8fafc" font-size="24" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Distribuição de linguagens</text>
  <text x="352" y="80" text-anchor="middle" fill="#94a3b8" font-size="14" font-family="Segoe UI, Arial, sans-serif">Percentual do código analisado nos repositórios próprios.</text>
{chr(10).join(marks)}"""
    return svg_shell(704, 224, "langsTitle", "langsDesc", "Distribuição de linguagens", f"Distribuição de linguagens detectadas nos repositórios de {profile['login']}.", body)


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
    profile = post_graphql(GRAPHQL_QUERY, {"login": USERNAME})
    profile["organizations"] = fetch_organizations(USERNAME)
    OUTPUT_STATS.write_text(build_stats_svg(profile), encoding="utf-8")
    OUTPUT_LANGS.write_text(build_langs_svg(profile), encoding="utf-8")
    OUTPUT_METRICS.write_text(build_metrics_svg(profile), encoding="utf-8")


if __name__ == "__main__":
    main()
