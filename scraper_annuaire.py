"""
╔══════════════════════════════════════════════════════════════╗
║   SCRAPER ANNUAIRE EXPERTS-COMPTABLES — Playwright headless  ║
║   Usage : python scraper_annuaire.py                         ║
║   Prérequis :                                                 ║
║     pip install playwright openpyxl pandas                   ║
║     python -m playwright install chromium                    ║
╚══════════════════════════════════════════════════════════════╝
"""

import pandas as pd
from playwright.sync_api import sync_playwright
import time
import os
from datetime import datetime

# ─── CONFIG ────────────────────────────────────────────────────
INPUT_FILE  = "annuaire.xlsx"          # Fichier source
OUTPUT_FILE = "annuaire_resultat.xlsx" # Fichier de sortie
CHECKPOINT  = "checkpoint.xlsx"        # Sauvegarde progressive
HEADLESS    = True                     # False = voir le navigateur
DELAY       = 1.2                      # Délai entre chaque page (secondes)
TIMEOUT     = 20000                    # Timeout par page (ms)
# ───────────────────────────────────────────────────────────────


def scrape_page(page, url: str) -> dict:
    """Scrape une page et retourne les données extraites."""
    result = {"Url": url, "Nom": "", "Adresse": "", "Telephone": ""}

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        page.wait_for_timeout(800)

        # ── Nom : <div class="info"> <span>NOM</span><br><span>Prénom</span>
        try:
            spans = page.query_selector_all(".info span")
            if spans:
                parts = [s.inner_text().strip() for s in spans if s.inner_text().strip()]
                result["Nom"] = " ".join(parts)
        except Exception:
            pass

        # ── Adresse : <div class="panel-addr"> <strong>...</strong>
        try:
            addr_el = page.query_selector(".panel-addr strong")
            if addr_el:
                result["Adresse"] = addr_el.inner_text().strip().replace("\n", " ").replace("  ", " ")
        except Exception:
            pass

        # ── Téléphone : clic sur bouton .firm-phone → modal .phone-link
        try:
            btn = page.query_selector(".firm-phone")
            if btn:
                btn.click()
                page.wait_for_selector(".phone-link", timeout=5000)
                tel_el = page.query_selector(".phone-link")
                if tel_el:
                    result["Telephone"] = tel_el.inner_text().strip()
                # Fermer la modale
                close_btn = page.query_selector("#modal-close")
                if close_btn:
                    close_btn.click()
                    page.wait_for_timeout(300)
        except Exception:
            pass

    except Exception as e:
        print(f"    ⚠️  Erreur sur {url}: {e}")

    return result


def load_checkpoint(checkpoint_file: str) -> set:
    """Charge les URLs déjà traitées depuis le checkpoint."""
    if os.path.exists(checkpoint_file):
        try:
            df = pd.read_excel(checkpoint_file)
            return set(df["Url"].tolist())
        except Exception:
            pass
    return set()


def save_checkpoint(results: list, checkpoint_file: str):
    """Sauvegarde progressive des résultats."""
    if results:
        pd.DataFrame(results).to_excel(checkpoint_file, index=False)


def main():
    print("=" * 60)
    print("  SCRAPER ANNUAIRE EXPERTS-COMPTABLES")
    print(f"  Démarrage : {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)

    # Charger le fichier source
    df = pd.read_excel(INPUT_FILE)
    urls = df["Url"].dropna().tolist()
    total = len(urls)
    print(f"\n📋 {total} URLs à traiter\n")

    # Charger checkpoint si existant (reprise en cas d'interruption)
    done_urls = load_checkpoint(CHECKPOINT)
    if done_urls:
        print(f"♻️  Reprise depuis checkpoint : {len(done_urls)} URLs déjà traitées\n")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Bloquer images/fonts pour aller plus vite
        page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot}",
            lambda route: route.abort()
        )

        for idx, url in enumerate(urls, 1):
            if url in done_urls:
                print(f"  [{idx:>3}/{total}] ⏭️  Déjà traité : {url[:60]}...")
                continue

            print(f"  [{idx:>3}/{total}] 🔍 {url[:70]}...", end=" ", flush=True)

            data = scrape_page(page, url)
            results.append(data)
            done_urls.add(url)

            nom = data['Nom'] or "—"
            tel = data['Telephone'] or "—"
            print(f"→ {nom} | {tel}")

            # Sauvegarde checkpoint toutes les 10 URLs
            if idx % 10 == 0:
                save_checkpoint(results, CHECKPOINT)
                print(f"\n  💾 Checkpoint sauvegardé ({len(results)} lignes)\n")

            time.sleep(DELAY)

        browser.close()

    # ── Sauvegarder le fichier final
    if results:
        df_out = pd.DataFrame(results)[["Url", "Nom", "Adresse", "Telephone"]]
        df_out.to_excel(OUTPUT_FILE, index=False)

        # Nettoyage checkpoint
        if os.path.exists(CHECKPOINT):
            os.remove(CHECKPOINT)

        print("\n" + "=" * 60)
        print(f"  ✅ TERMINÉ — {len(results)} leads extraits")
        print(f"  📁 Fichier : {OUTPUT_FILE}")
        print(f"  🕐 Fin     : {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 60)

        # Résumé rapide
        df_stats = df_out.copy()
        with_tel = df_stats[df_stats["Telephone"] != ""].shape[0]
        without_tel = df_stats[df_stats["Telephone"] == ""].shape[0]
        print(f"\n  📊 Avec téléphone    : {with_tel}")
        print(f"  📊 Sans téléphone    : {without_tel}")
    else:
        print("\n  ⚠️  Aucun résultat — vérifier les URLs ou la connexion")


if __name__ == "__main__":
    main()