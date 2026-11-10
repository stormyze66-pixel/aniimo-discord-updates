import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

# CONFIGURATION
ANIIMO_URL = "https://www.aniimo.com/fr/newslist"
STATE_FILE = Path("aniimo_seen.json")

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
ROLE_ID = os.environ.get("ANIIMO_ROLE_ID", "").strip()

KEYWORDS = (
    "patch",
    "update",
    "maintenance",
    "hotfix",
    "bugfix",
    "bug fix",
    "fixes",
    "version",
    "mise a jour",
    "correctif",
    "correction",
    "equilibrage",
    "notes de version",
    "problemes connus",
)


def normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(
        char for char in text
        if not unicodedata.combining(char)
    )


def is_update(title):
    normalized = normalize(title)

    return any(
        keyword in normalized
        for keyword in KEYWORDS
    )


def clean_title(raw_title):
    lines = [
        line.strip()
        for line in raw_title.splitlines()
        if line.strip()
    ]

    return lines[0] if lines else ""


def get_articles():
    articles = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        try:
            page = browser.new_page(locale="fr-FR")

            page.goto(
                ANIIMO_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(8000)

            links = page.locator("a[href]").evaluate_all(
                """elements => elements.map(element => ({
                    href: element.href,
                    title: element.innerText.trim()
                }))"""
            )

            print(f"Liens détectés : {len(links)}")

            for link in links:
                url = urljoin(ANIIMO_URL, link["href"])
                parsed = urlparse(url)

                if parsed.netloc not in (
                    "aniimo.com",
                    "www.aniimo.com"
                ):
                    continue

                match = re.search(
                    r"/newslist/detail/(\d+)",
                    parsed.path
                )

                if not match:
                    continue

                article_id = match.group(1)
                title = clean_title(link["title"])

                if article_id not in articles:
                    articles[article_id] = {
                        "title": title or f"Actualité Aniimo #{article_id}",
                        "url": url
                    }

        finally:
            browser.close()

    return articles


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

    for attempt in range(1, 4):
        try:
            response = requests.post(
                WEBHOOK_URL,
                json=payload,
                timeout=30
            )

            response.raise_for_status()

            print(
                f"Discord confirme l'envoi : "
                f"{article['title']}"
            )

            return

        except requests.RequestException as error:
            print(
                f"Erreur Discord "
                f"(tentative {attempt}/3) : {error}"
            )

            if attempt == 3:
                raise

            time.sleep(5)


def load_seen():
    if not STATE_FILE.exists():
        return None

    return set(
        json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    )


def save_seen(seen):
    temporary_file = STATE_FILE.with_suffix(".tmp")

    temporary_file.write_text(
        json.dumps(
            sorted(seen),
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    temporary_file.replace(STATE_FILE)


def main():
    articles = get_articles()

    print(f"Articles détectés : {len(articles)}")

    if not articles:
        raise RuntimeError(
            "Aucun article détecté sur Aniimo."
        )

    seen = load_seen()

    if seen is None:
        save_seen(set(articles.keys()))

        print(
            "Initialisation : "
            "articles existants mémorisés."
        )
        return

    new_articles = {
        article_id: article
        for article_id, article in articles.items()
        if article_id not in seen
    }

    print(
        f"Nouvelles publications : "
        f"{len(new_articles)}"
    )

    for article_id, article in new_articles.items():
        title = article["title"]

        print(f"Analyse : {title}")

        if not is_update(title):
            print(
                f"Publication ignorée par le filtre : "
                f"{title}"
            )

            # On mémorise les articles ignorés
            # pour éviter de les réexaminer indéfiniment.
            seen.add(article_id)
            save_seen(seen)
            continue

        print(
            f"Mise à jour détectée : {title}"
        )

        # On envoie d'abord sur Discord.
        send_discord(article)

        # On mémorise seulement après confirmation.
        seen.add(article_id)
        save_seen(seen)

        print(
            f"Article {article_id} enregistré "
            f"après notification."
        )

    print("Vérification terminée.")


def resend_article(article_id):
    if not re.fullmatch(r"\d+", article_id):
        raise ValueError(
            "Identifiant d'article invalide."
        )

    articles = get_articles()

    if article_id not in articles:
        raise RuntimeError(
            f"Article {article_id} introuvable."
        )

    article = articles[article_id]

    print(
        f"Renvoi manuel : {article['title']}"
    )

    send_discord(article)

    print("Renvoi manuel terminé.")


if __name__ == "__main__":
    resend_id = os.environ.get(
        "RESEND_ARTICLE_ID", ""
    ).strip()

    if resend_id:
        resend_article(resend_id)

    elif os.environ.get("TEST_DISCORD") == "true":
        send_discord({
            "title": "TEST — Mise à jour Aniimo",
            "url": (
                "https://www.aniimo.com/fr/"
                "newslist/detail/100277"
            )
        })

    else:
        main()
