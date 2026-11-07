import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ANIIMO_URL = "https://www.aniimo.com/fr/newslist"
STATE_FILE = Path("aniimo_seen.json")

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
ROLE_ID = os.environ.get("ANIIMO_ROLE_ID", "")

KEYWORDS = (
    "patch", "update", "maintenance", "hotfix",
    "bug fix", "bugfix", "fixes", "version",
    "mise à jour", "correctif", "correction",
    "maintenance", "équilibrage"
)


def get_articles():
    response = requests.get(
        ANIIMO_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    articles = {}

    for link in soup.find_all("a", href=True):
        url = urljoin(ANIIMO_URL, link["href"])
        parsed = urlparse(url)

        if parsed.netloc not in ("aniimo.com", "www.aniimo.com"):
            continue

        if not re.search(r"/newslist/detail/\d+", parsed.path):
            continue

        title = link.get_text(" ", strip=True)

        if not title:
            parent = link.parent
            title = parent.get_text(" ", strip=True) if parent else ""

        article_id = re.search(r"/detail/(\d+)", parsed.path).group(1)

        if article_id not in articles:
            articles[article_id] = {
                "title": title or f"Actualité Aniimo #{article_id}",
                "url": url
            }

    return articles


def is_update(title):
    return any(word in title.lower() for word in KEYWORDS)


def send_discord(article):
    if not WEBHOOK_URL:
        raise RuntimeError("Secret DISCORD_WEBHOOK_URL manquant")

    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""

    payload = {
        "content": mention,
        "allowed_mentions": {
            "parse": [],
            "roles": [ROLE_ID] if ROLE_ID else []
        },
        "embeds": [
            {
                "title": "🥚 ANIIMO | Nouvelle mise à jour",
                "description": (
                    f"**{article['title']}**\n\n"
                    "Une nouvelle publication officielle est disponible !\n\n"
                    f"📋 [Consulter l'article]({article['url']})"
                ),
                "color": 16757570,
                "footer": {
                    "text": "Aniimo • Actualités officielles"
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        ]
    }

    response = requests.post(WEBHOOK_URL, json=payload, timeout=30)
    response.raise_for_status()


def main():
    articles = get_articles()
    print(f"Articles détectés : {len(articles)}")

    if not articles:
        raise RuntimeError(
            "Aucun article trouvé. Vérifier la structure du site Aniimo."
        )

    if not STATE_FILE.exists():
        STATE_FILE.write_text(
            json.dumps(list(articles.keys()), indent=2),
            encoding="utf-8"
        )
        print("Première exécution : articles existants mémorisés.")
        return

    seen = set(json.loads(STATE_FILE.read_text(encoding="utf-8")))

    for article_id, article in articles.items():
        if article_id in seen:
            continue

        if is_update(article["title"]):
            send_discord(article)
            print(f"Annonce envoyée : {article['title']}")
        else:
            print(f"Actualité ignorée : {article['title']}")

        seen.add(article_id)

    STATE_FILE.write_text(
        json.dumps(sorted(seen), indent=2),
        encoding="utf-8"
    )


if __name__ == "__main__":
    main()
