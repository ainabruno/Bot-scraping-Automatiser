#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║   SCRAPER COORDONNÉES — Silvereco  (v2)                                 ║
║   Utilise un vrai Chrome via CDP (port 9222)                            ║
║                                                                          ║
║   ÉTAPE 1 — Lancer Chrome en mode debug :                               ║
║     Windows :                                                            ║
║       "C:\Program Files\Google\Chrome\Application\chrome.exe"           ║
║         --remote-debugging-port=9222 --user-data-dir=C:\ChromeDebug     ║
║     Ou utiliser lancer_chrome.bat (voir ci-dessous)                     ║
║                                                                          ║
║   ÉTAPE 2 — python scrape_silvereco_v2.py                               ║
╚══════════════════════════════════════════════════════════════════════════╝

── lancer_chrome.bat ──────────────────────────────────────────────────────
@echo off
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%TEMP%\ChromeDebug"
echo Chrome lancé sur le port 9222
pause
───────────────────────────────────────────────────────────────────────────
"""

import asyncio
import re
import time
import urllib.request
import sys
from pathlib import Path
from bs4 import BeautifulSoup

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────
INPUT_FILE  = "silvereco.xlsx"
OUTPUT_FILE = "silvereco_coordonneesUP.xlsx"
CDP_URL     = "http://127.0.0.1:9222"

SAVE_EVERY  = 5      # sauvegarde intermédiaire toutes les N lignes
PAUSE_SEC   = 1.5    # délai entre chaque page

# Colonnes du fichier d'entrée
COL_URL  = "URL"
COL_NOM  = "Nom"
# ─────────────────────────────────────────────────────────────────

# ── Regex ─────────────────────────────────────────────────────────
PHONE_RE = re.compile(
    r"""
    (?:
        (?:\+33\s?|0033\s?)[1-9](?:[\s.\-]?\d{2}){4}   # France +33
      | (?:\+596\s?|0596\s?)[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}  # DOM +596
      | (?:\+269|0269)[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}  # Comores
      | \+\d{1,3}[\s.\-]?\(?\d{1,4}\)?[\s.\-]?\d{2,4}[\s.\-]?\d{2,4}[\s.\-]?\d{0,4}  # International
      | 0[1-9](?:[\s.\-]?\d{2}){4}                      # France 0X
    )
    """,
    re.VERBOSE,
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

SOCIAL_DOMAINS = {
    "facebook.com":  "Facebook",
    "linkedin.com":  "LinkedIn",
    "twitter.com":   "Twitter",
    "x.com":         "Twitter",
    "instagram.com": "Instagram",
    "youtube.com":   "YouTube",
}


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def extract_phone(text: str) -> str:
    m = PHONE_RE.search(text)
    return m.group(0).strip() if m else ""


def extract_emails(text: str) -> list[str]:
    hits = EMAIL_RE.findall(text)
    return list({e for e in hits
                 if not any(x in e.lower() for x in [".png", ".jpg", ".svg", "example"])})


def classify_links(html: str, base_url: str) -> dict:
    """
    Retourne un dict :
      {
        'Site Web': 'https://...',
        'Facebook': 'https://facebook.com/...',
        'LinkedIn': ...,
        ...
      }
    """
    soup = BeautifulSoup(html, "html.parser")
    found = {"Site Web": ""}
    for key in SOCIAL_DOMAINS.values():
        found[key] = ""

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        matched_social = False
        for domain, label in SOCIAL_DOMAINS.items():
            if domain in href:
                if not found[label]:
                    found[label] = href
                matched_social = True
                break
        # Site web externe (ni silvereco.fr ni réseau social)
        if not matched_social and not found["Site Web"]:
            if "silvereco.fr" not in href and len(href) < 120:
                found["Site Web"] = href

    return found


def parse_address_from_html(html: str) -> str:
    """
    Cherche les blocs <p> ou <address> contenant une adresse
    dans les onglets uagb (WordPress).
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1) Chercher dans les panneaux d'onglets uagb
    for panel in soup.select(".uagb-tabs__body-container, [role='tabpanel']"):
        text = panel.get_text(" | ", strip=True)
        if any(kw in text.lower() for kw in
               ["rue ", "avenue ", " av.", "bd ", "boulevard ", "allée ",
                "impasse ", "chemin ", "cedex", "boîte", "martinique",
                "guadeloupe", "réunion", "france", "paris", "lyon"]):
            # Prendre la partie avant "Tel"
            lines = [l.strip() for l in panel.get_text("\n", strip=True).split("\n") if l.strip()]
            addr_lines = []
            for line in lines:
                if re.search(r"tel\s*:", line, re.I) or re.search(r"web\s*:", line, re.I):
                    break
                if len(line) > 3 and not line.startswith("http"):
                    addr_lines.append(line)
            if addr_lines:
                return ", ".join(addr_lines)

    # 2) Fallback: paragraphes avec codes postaux
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if re.search(r"\d{5}", t) and len(t) < 300:
            return t.replace("\n", ", ").replace("  ", " ")

    return ""


# ══════════════════════════════════════════════════════════════════
# CONNEXION CDP
# ══════════════════════════════════════════════════════════════════

def wait_for_chrome(max_attempts: int = 10) -> bool:
    print(f"🔍 Connexion à Chrome sur {CDP_URL}...")
    for i in range(1, max_attempts + 1):
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
            print("✅ Chrome détecté !\n")
            return True
        except Exception:
            print(f"   ⏳ Tentative {i}/{max_attempts}...")
            time.sleep(2)
    return False


async def connect_chrome(playwright):
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = (browser.contexts[0] if browser.contexts
               else await browser.new_context(viewport={"width": 1400, "height": 900}))
    print(f"✅ Connecté — Chrome {browser.version}\n")
    return browser, context


# ══════════════════════════════════════════════════════════════════
# SCRAPE D'UNE PAGE
# ══════════════════════════════════════════════════════════════════

async def scrape_page(page, url: str, nom: str) -> dict:
    result = {
        "Nom":       nom,
        "URL":       url,
        "Adresse":   "",
        "Téléphone": "",
        "Email":     "",
        "Site Web":  "",
        "Facebook":  "",
        "LinkedIn":  "",
        "Twitter":   "",
        "Instagram": "",
        "YouTube":   "",
        "Statut":    "OK",
    }

    try:
        # ── Chargement de la page ─────────────────────────────────
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1.5)

        # ── Cliquer sur l'onglet "Coordonnées" si présent ─────────
        tab_selectors = [
            ".uagb-tabs__tab",            # onglets uagb (WordPress)
            "[role='tab']",
            ".nav-tab",
            ".tab-link",
        ]
        for sel in tab_selectors:
            tabs = await page.query_selector_all(sel)
            for tab in tabs:
                try:
                    label = (await tab.inner_text()).strip().lower()
                    if any(kw in label for kw in
                           ["coordonnée", "contact", "adresse", "infos"]):
                        await tab.click()
                        await asyncio.sleep(1.0)
                        print(f"      🖱️  Onglet cliqué : '{label}'")
                        break
                except Exception:
                    pass

        # ── Attendre que le panneau actif soit visible ────────────
        try:
            await page.wait_for_selector(
                ".uagb-tabs-body__active, [role='tabpanel'][aria-hidden='false']",
                timeout=5_000
            )
        except PWTimeout:
            pass  # Pas d'onglets, on continue

        # ── Récupération HTML + texte ─────────────────────────────
        html = await page.content()
        text = await page.inner_text("body")

        # ── Extraction ────────────────────────────────────────────
        result["Adresse"]   = parse_address_from_html(html)
        result["Téléphone"] = extract_phone(text)
        result["Email"]     = " | ".join(extract_emails(text))

        links = classify_links(html, url)
        result["Site Web"]  = links.get("Site Web",  "")
        result["Facebook"]  = links.get("Facebook",  "")
        result["LinkedIn"]  = links.get("LinkedIn",  "")
        result["Twitter"]   = links.get("Twitter",   "")
        result["Instagram"] = links.get("Instagram", "")
        result["YouTube"]   = links.get("YouTube",   "")

    except PWTimeout:
        result["Statut"] = "Timeout"
    except Exception as e:
        result["Statut"] = f"Erreur: {str(e)[:80]}"

    return result


# ══════════════════════════════════════════════════════════════════
# SAUVEGARDE INTERMÉDIAIRE
# ══════════════════════════════════════════════════════════════════

def save_temp(records: list, output_file: str):
    tmp_path = output_file.replace(".xlsx", "_temp.xlsx")
    pd.DataFrame(records).to_excel(tmp_path, index=False)
    nb_tel = sum(1 for r in records if r.get("Téléphone"))
    print(f"   💾 Sauvegarde temp → {tmp_path}  ({nb_tel} tél. trouvés)")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

async def main():
    print("=" * 65)
    print("  SCRAPER COORDONNÉES — Silvereco  (v2) — Chrome CDP")
    print("=" * 65)

    # ── Chargement Excel ──────────────────────────────────────────
    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {Path(INPUT_FILE).absolute()}")
        print("   Place silvereco.xlsx dans le même dossier que ce script.")
        sys.exit(1)

    df = pd.read_excel(INPUT_FILE)
    if COL_URL not in df.columns or COL_NOM not in df.columns:
        print(f"❌ Colonnes requises : '{COL_URL}' et '{COL_NOM}'")
        print(f"   Colonnes trouvées : {list(df.columns)}")
        sys.exit(1)

    print(f"\n✅ {len(df)} URLs chargées\n")

    # ── Connexion Chrome ──────────────────────────────────────────
    if not wait_for_chrome():
        print("\n❌ Chrome non disponible sur le port 9222.")
        print("   Lance lancer_chrome.bat d'abord, puis relance ce script.")
        sys.exit(1)

    t_start  = time.time()
    records  = []

    async with async_playwright() as playwright:
        browser, context = await connect_chrome(playwright)
        page = await context.new_page()

        for i, row in df.iterrows():
            url = str(row[COL_URL]).strip()
            nom = str(row[COL_NOM]).strip()
            print(f"\n[{i+1}/{len(df)}] {nom}")
            print(f"  → {url}")

            result = await scrape_page(page, url, nom)
            records.append(result)

            # Affichage résumé ligne
            print(f"  📍 Adresse   : {result['Adresse']   or '–'}")
            print(f"  📞 Téléphone : {result['Téléphone'] or '–'}")
            print(f"  📧 Email     : {result['Email']     or '–'}")
            print(f"  🌐 Site Web  : {result['Site Web']  or '–'}")
            print(f"  👤 Facebook  : {result['Facebook']  or '–'}")

            # Sauvegarde intermédiaire
            if (i + 1) % SAVE_EVERY == 0:
                save_temp(records, OUTPUT_FILE)

            await asyncio.sleep(PAUSE_SEC)

        await page.close()

    # ── Export final ──────────────────────────────────────────────
    out_df = pd.DataFrame(records)
    out_df.to_excel(OUTPUT_FILE, index=False)

    elapsed = int(time.time() - t_start)
    nb_tel  = sum(1 for r in records if r.get("Téléphone"))
    nb_web  = sum(1 for r in records if r.get("Site Web"))
    nb_fb   = sum(1 for r in records if r.get("Facebook"))

    print("\n" + "=" * 65)
    print(f"  ✅ TERMINÉ en {elapsed // 60}m{elapsed % 60:02d}s")
    print(f"  📞 {nb_tel} téléphone(s)  |  🌐 {nb_web} sites web  |  👤 {nb_fb} Facebook")
    print(f"  💾 Résultats → {Path(OUTPUT_FILE).absolute()}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())

# """
# Script Playwright pour extraire les coordonnées (adresse, téléphone, email, site web)
# depuis chaque URL listée dans le fichier silvereco.xlsx
# """

# import asyncio
# import re
# import pandas as pd
# from playwright.async_api import async_playwright

# EXCEL_PATH = "silvereco.xlsx"
# OUTPUT_PATH = "silvereco_coordonnees.xlsx"

# # Patterns regex pour extraire les coordonnées
# PHONE_PATTERNS = [
#     r'(?:\+33|0033|0)[1-9](?:[\s.\-]?\d{2}){4}',  # France
#     r'(?:\+596|0596)\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{2}',  # Martinique
#     r'(?:\+\d{1,3}[\s.\-]?)?\(?\d{1,4}\)?[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}[\s.\-]?\d{0,4}',
# ]
# EMAIL_PATTERN = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'


# def extract_phones(text):
#     phones = set()
#     for pattern in PHONE_PATTERNS:
#         matches = re.findall(pattern, text)
#         for m in matches:
#             cleaned = re.sub(r'[\s.\-]', '', m).strip()
#             if len(cleaned) >= 10:
#                 phones.add(m.strip())
#     return list(phones)[:3]  # Max 3 numéros


# def extract_emails(text):
#     emails = re.findall(EMAIL_PATTERN, text)
#     # Filtrer les emails génériques (images, sprites, etc.)
#     filtered = [e for e in emails if not any(x in e.lower() for x in ['@2x', '.png', '.jpg', '.svg', 'example'])]
#     return list(set(filtered))[:3]


# def extract_website(text, current_url):
#     urls = re.findall(r'https?://[^\s<>"\']+', text)
#     external = [u for u in urls if 'silvereco.fr' not in u and len(u) < 100]
#     # Enlever les URLs de réseaux sociaux connues
#     social = ['facebook', 'twitter', 'linkedin', 'instagram', 'youtube', 'x.com']
#     websites = [u for u in external if not any(s in u.lower() for s in social)]
#     return websites[0] if websites else ""


# async def scrape_url(page, url, nom):
#     result = {
#         "Nom": nom,
#         "URL": url,
#         "Adresse": "",
#         "Téléphone": "",
#         "Email": "",
#         "Site Web": "",
#         "Statut": "OK"
#     }
#     try:
#         await page.goto(url, wait_until="domcontentloaded", timeout=30000)
#         await page.wait_for_timeout(2000)

#         # Récupérer tout le texte visible de la page
#         text = await page.inner_text("body")

#         # Téléphones
#         phones = extract_phones(text)
#         result["Téléphone"] = " | ".join(phones)

#         # Emails
#         emails = extract_emails(text)
#         result["Email"] = " | ".join(emails)

#         # Site web externe
#         html = await page.content()
#         result["Site Web"] = extract_website(html, url)

#         # Adresse : chercher des blocs contenant des mots-clés d'adresse
#         address_keywords = ['rue ', 'avenue ', 'av. ', 'bd ', 'boulevard ', 'allée ', 'impasse ',
#                             'chemin ', 'place ', 'route ', 'cedex', 'bp ', 'boîte postale',
#                             'france', 'martinique', 'guadeloupe', 'réunion']
#         lines = [l.strip() for l in text.split('\n') if l.strip()]
#         address_lines = []
#         for i, line in enumerate(lines):
#             if any(kw in line.lower() for kw in address_keywords):
#                 # Prendre quelques lignes autour pour reconstituer l'adresse
#                 start = max(0, i - 1)
#                 end = min(len(lines), i + 3)
#                 block = " | ".join(lines[start:end])
#                 if len(block) < 300:
#                     address_lines.append(block)
#                 if len(address_lines) >= 2:
#                     break
#         result["Adresse"] = address_lines[0] if address_lines else ""

#     except Exception as e:
#         result["Statut"] = f"Erreur: {str(e)[:80]}"

#     return result


# async def main():
#     df = pd.read_excel(EXCEL_PATH)
#     print(f"📋 {len(df)} URLs à traiter...")

#     results = []

#     async with async_playwright() as p:
#         browser = await p.chromium.launch(headless=True)
#         context = await browser.new_context(
#             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
#         )
#         page = await context.new_page()

#         for i, row in df.iterrows():
#             url = str(row["URL"]).strip()
#             nom = str(row["Nom"]).strip()
#             print(f"[{i+1}/{len(df)}] {nom} — {url}")
#             result = await scrape_url(page, url, nom)
#             results.append(result)
#             print(f"  ✓ Tél: {result['Téléphone'] or '-'} | Email: {result['Email'] or '-'}")

#         await browser.close()

#     # Sauvegarder dans Excel
#     out_df = pd.DataFrame(results)
#     out_df.to_excel(OUTPUT_PATH, index=False)
#     print(f"\n✅ Résultats sauvegardés dans : {OUTPUT_PATH}")
#     print(f"   {len([r for r in results if r['Statut'] == 'OK'])} OK / {len(results)} total")


# if __name__ == "__main__":
#     asyncio.run(main())