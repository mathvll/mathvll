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
TOKEN = os.environ.get("METRICS_TOKEN")


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
    organizations(first: 20) {
      totalCount
      nodes {
        login
        name
      }
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


def build_lang_bar(top_languages: list[tuple[str, int]], colors: dict[str, str], total_size: int) -> str:
    x = 32
    y = 126
    width = 640
    segments = [f'  <rect x="{x}" y="{y}" width="{width}" height="16" rx="8" fill="#111827" />']

    used_width = 0
    for index, (language, size) in enumerate(top_languages):
        if total_size == 0:
            segment_width = 0
        elif index == len(top_languages) - 1:
            segment_width = max(0, width - used_width)
        else:
            segment_width = max(8, round((size / total_size) * width))
        if segment_width:
            segments.append(
                f'  <rect x="{x + used_width}" y="{y}" width="{segment_width}" height="16" rx="8" fill="{colors.get(language, "#94a3b8")}" />'
            )
        used_width += segment_width

    return "\n".join(segments)


def build_langs_svg(profile: dict) -> str:
    languages, colors = language_totals(profile)
    top_languages = languages[:6]
    total_size = sum(size for _, size in top_languages)

    legend = []
    start_y = 178
    for index, (language, size) in enumerate(top_languages):
        col = index % 2
        row = index // 2
        x = 32 + (col * 320)
        y = start_y + (row * 58)
        percentage = 0 if total_size == 0 else (size / total_size) * 100
        legend.append(
            f"""  <g transform="translate({x},{y})">
    <circle cx="10" cy="10" r="10" fill="{colors.get(language, '#94a3b8')}" />
    <text x="30" y="14" fill="#f8fafc" font-size="18" font-weight="600" font-family="Segoe UI, Arial, sans-serif">{escape(language)}</text>
    <text x="30" y="38" fill="#94a3b8" font-size="14" font-family="Segoe UI, Arial, sans-serif">{percentage:.1f}% do codigo analisado</text>
  </g>"""
        )

    if not legend:
        legend.append('  <text x="32" y="190" fill="#94a3b8" font-size="16" font-family="Segoe UI, Arial, sans-serif">Nenhuma linguagem detectada nos repositorios analisados.</text>')

    body = f"""  <text x="32" y="56" fill="#f8fafc" font-size="30" font-weight="700" font-family="Segoe UI, Arial, sans-serif">Linguagens mais usadas</text>
  <text x="32" y="88" fill="#94a3b8" font-size="16" font-family="Segoe UI, Arial, sans-serif">Distribuicao agregada por tamanho de linguagem nos repositorios.</text>
{build_lang_bar(top_languages, colors, total_size)}
{chr(10).join(legend)}"""
    return svg_shell(704, 376, "langsTitle", "langsDesc", "Top Langs", f"Linguagens mais usadas no perfil de {profile['login']}.", body)


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
    org_text = ", ".join(org_names) if org_names else "Sem organizacoes visiveis pela API"
    latest_repo = max(repository_nodes(profile), key=lambda repo: repo.get("updatedAt") or "", default={})

    stat_items = [
        ("Conta criada em", format_date(profile.get("createdAt"))),
        ("Repositorios", format_number(profile["repositories"]["totalCount"])),
        ("Organizacoes visiveis", format_number(organizations["totalCount"])),
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
    OUTPUT_STATS.write_text(build_stats_svg(profile), encoding="utf-8")
    OUTPUT_LANGS.write_text(build_langs_svg(profile), encoding="utf-8")
    OUTPUT_METRICS.write_text(build_metrics_svg(profile), encoding="utf-8")


if __name__ == "__main__":
    main()
