import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

ANIIMO_URL = "https://www.aniimo.com/fr/newslist"
STATE_FILE = Path("aniimo_seen.json")

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
ROLE_ID = os.environ.get("ANIIMO_ROLE_ID", "")

KEYWORDS = (
    "patch", "update", "maintenance", "hotfix",
    "bugfix", "bug fix", "fixes", "version",
    "mise à jour", "correctif", "correction",
    "équilibrage", "notes de version"
)


def get_articles():
    articles = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        page = browser.new_page(
            locale="fr-FR",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
            )
        )

        page.goto(
            ANIIMO_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(8000)

        print("Titre de la page :", page.title())
        print("URL actuelle :", page.url)

        links = page.locator("a[href]").evaluate_all(
            """elements => elements.map(element => ({
                href: element.href,
                title: element.innerText.trim()
            }))"""
        )

        print("Nombre de liens trouvés :", len(links))

        for link in links:
            url = urljoin(ANIIMO_URL, link["href"])
            parsed = urlparse(url)

            if parsed.netloc not in ("aniimo.com", "www.aniimo.com"):
                continue

            match = re.search(
                r"/newslist/detail/(\d+)",
                parsed.path
            )

            if not match:
                continue

            article_id = match.group(1)
            raw_title = link["title"].strip()

            lines = [
                line.strip()
                for line in raw_title.splitlines()
                if line.strip()
            ]

            title = lines[0] if lines else ""

            if article_id not in articles:
                articles[article_id] = {
                    "title": title or f"Actualité Aniimo #{article_id}",
                    "url": url
                }

        browser.close()

    return articles


def is_update(title):
    return any(
        keyword in title.lower()
        for keyword in KEYWORDS
    )


def send_discord(article):
    if not WEBHOOK_URL:
        raise RuntimeError("Webhook Discord manquant")

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
                    "Une nouvelle publication officielle "
                    "est disponible !\n\n"
                    f"📋 [Lire l'article officiel]({article['url']})"
                ),
                "color": 16757570,
                "footer": {
                    "text": "Aniimo • Actualités officielles"
                },
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat()
            }
        ]
    }

    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        timeout=30
    )

    response.raise_for_status()


def main():
    articles = get_articles()

    print(f"Articles détectés : {len(articles)}")

    for article in articles.values():
        print(
            f"Article : {article['title']} | "
            f"{article['url']}"
        )

    if not articles:
        raise RuntimeError(
            "Aucun article détecté avec Playwright."
        )

    if not STATE_FILE.exists():
        STATE_FILE.write_text(
            json.dumps(
                sorted(articles.keys()),
                indent=2
            ),
            encoding="utf-8"
        )

        print(
            "Première exécution : "
            "articles existants mémorisés."
        )
        return

    seen = set(
        json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    )

    for article_id, article in articles.items():
        if article_id in seen:
            continue

        if is_update(article["title"]):
            send_discord(article)
            print(
                f"Annonce envoyée : {article['title']}"
            )
        else:
            print(
                f"Actualité ignorée : {article['title']}"
            )

        seen.add(article_id)

    STATE_FILE.write_text(
        json.dumps(sorted(seen), indent=2),
        encoding="utf-8"
    )


if __name__ == "__main__":
    if os.environ.get("RESEND_ARTICLE_ID"):
        article_id = os.environ["RESEND_ARTICLE_ID"].strip()

        if not re.fullmatch(r"\d+", article_id):
            raise ValueError("Identifiant d'article invalide")

        articles = get_articles()

        if article_id not in articles:
            raise RuntimeError(
                f"Article {article_id} introuvable sur Aniimo."
            )

        article = articles[article_id]

        print(f"Renvoi manuel : {article['title']}")
        send_discord(article)
        print("Notification envoyée avec succès !")

    elif os.environ.get("TEST_DISCORD") == "true":
        print("Envoi d'une notification de test Discord...")

        send_discord({
            "title": "TEST — Mise à jour Aniimo",
            "url": "https://www.aniimo.com/fr/newslist/detail/100277"
        })

        print("Notification de test envoyée avec succès !")

    else:
        main()
