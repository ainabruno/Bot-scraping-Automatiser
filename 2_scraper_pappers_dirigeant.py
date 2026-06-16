import pandas as pd
import time
import random
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────
INPUT_FILE  = "A-serres.xlsx"
OUTPUT_FILE = "A-serres_Avec_Dirigeants.xlsx"
ALL_SHEETS  = True
HEADLESS    = False
PAUSE_MIN   = 1.5
PAUSE_MAX   = 3.0
# ─────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


def human_delay(a=0.5, b=1.5):
    time.sleep(random.uniform(a, b))


def clean(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()


# ═════════════════════════════════════════════════════════════════════════════
# PAPPERS — RECHERCHE DIRIGEANTS (URL correcte)
# ═════════════════════════════════════════════════════════════════════════════

def search_pappers_dirigeant(page, company: str) -> dict:
    """
    Stratégie en 2 temps :
      1. Recherche entreprise  →  https://www.pappers.fr/recherche?q=NOM
         → récupère l'URL de la fiche du meilleur résultat
      2. Fiche entreprise      →  pappers.fr/entreprise/nom-SIREN
         → extrait SIREN (URL), Dirigeant (td.info-dirigeant a), Fonction (th + td)
    """
    result = {"siren": "", "dirigeant": "", "fonction": "", "url": ""}

    try:
        # ── 1. Recherche entreprise ──────────────────────────────────────────
        query = company.replace(" ", "+")
        search_url = f"https://www.pappers.fr/recherche?q={query}"
        page.goto(search_url, wait_until="domcontentloaded", timeout=10000)
        human_delay(0.5, 1.2)

        # Récupérer tous les liens de fiches entreprise dans les résultats
        # Pappers : liens sous forme /entreprise/nom-siren
        result_links = page.locator("a[href*='/entreprise/']").all()

        if not result_links:
            print(f"   ⚠️  Aucun résultat Pappers pour : {company}")
            return result

        # Choisir le lien dont le texte ou l'URL ressemble le plus à l'entreprise
        company_upper = company.upper()
        words = [w for w in company_upper.split() if len(w) > 2]

        best_url  = None
        best_score = -1

        for link in result_links:
            try:
                href = link.get_attribute("href", timeout=800) or ""
                text = clean(link.inner_text(timeout=800)).upper()
            except Exception:
                continue

            combined = (href.upper() + " " + text)
            score = sum(1 for w in words if w in combined)

            if score > best_score:
                best_score = score
                best_url   = href

        if not best_url or best_score == 0:
            print(f"   ⚠️  Aucune fiche trouvée pour : {company}")
            return result

        if not best_url.startswith("http"):
            best_url = "https://www.pappers.fr" + best_url
        result["url"] = best_url

        # ── 2. Naviguer sur la fiche entreprise ─────────────────────────────
        page.goto(best_url, wait_until="domcontentloaded", timeout=5000)
        human_delay(0.1, 0.5)

        # ── SIREN depuis l'URL : /entreprise/nom-123456789 ───────────────────
        m = re.search(r"-(\d{9})(?:/|$)", best_url)
        if m:
            result["siren"] = m.group(1)

        # ── Dirigeant : td.info-dirigeant a  (structure réelle Pappers) ──────
        #   <th>Dirigeant :</th>
        #   <td class="info-dirigeant"><a ...>Berge Laurent</a></td>
        try:
            dirigeant_el = page.locator("td.info-dirigeant a").first
            if dirigeant_el.is_visible(timeout=80):
                result["dirigeant"] = clean(dirigeant_el.inner_text(timeout=80))
        except Exception:
            pass

        # Fallback : chercher dans la table-container le th "Dirigeant"
        if not result["dirigeant"]:
            try:
                rows = page.locator("table tr").all()
                for row in rows:
                    th_text = clean(row.locator("th").first.inner_text(timeout=50))
                    if "dirigeant" in th_text.lower():
                        td_text = clean(row.locator("td").first.inner_text(timeout=50))
                        if td_text:
                            result["dirigeant"] = td_text
                        break
            except Exception:
                pass

        # ── Fonction : th précédant le nom du dirigeant dans le résumé ───────
        # Sur la fiche résumé Pappers la fonction n'est pas affichée dans
        # le tableau d'en-tête → on la cherche dans la section dirigeants
        result["fonction"] = _get_fonction_fiche(page)

        print(
            f"   📋 Pappers → SIREN={result['siren']} | "
            f"Dirigeant={result['dirigeant'] or '?'} | "
            f"Fonction={result['fonction'] or '?'}"
        )

    except Exception as e:
        print(f"   ⚠️  Erreur Pappers: {e}")

    return result


def _get_fonction_fiche(page) -> str:
    """
    Cherche la fonction (Gérant, Président, DG…) dans la section dirigeants
    de la fiche entreprise Pappers.

    Pappers affiche typiquement un bloc :
        <div class="dirigeant"> ... Gérant ... NOM ... </div>
    ou un tableau avec une colonne qualité/fonction.
    """
    fonction = ""

    # Sélecteurs directs (section dirigeants de la fiche)
    sels = [
        ".dirigeant-qualite",
        ".qualite-dirigeant",
        ".fonction-dirigeant",
        ".poste-dirigeant",
        "td.qualite",
        ".role",
        # Pappers onglet dirigeants : span/div contenant le rôle
        ".fiche-identite .qualite",
        ".bloc-dirigeant .qualite",
    ]
    for sel in sels:
        try:
            t = clean(page.locator(sel).first.inner_text(timeout=1000))
            if t:
                return t
        except Exception:
            pass

    # Fallback regex dans le texte brut de la page
    try:
        body = page.inner_text("body", timeout=1000)
        pattern = (
            r"(G[ée]rant(?:e)?|Pr[ée]sident(?:e)?|"
            r"Directeur(?:rice)?\s*[Gg][ée]n[ée]ral(?:e)?|"
            r"PDG|CEO|Administrateur(?:rice)?|Associé(?:e)?[- ]?[Gg][ée]rant(?:e)?)"
        )
        m = re.search(pattern, body, re.IGNORECASE)
        if m:
            fonction = clean(m.group(1))
    except Exception:
        pass

    return fonction


# ═════════════════════════════════════════════════════════════════════════════
# ENRICHISSEMENT
# ═════════════════════════════════════════════════════════════════════════════

def enrich_sheet(df: pd.DataFrame, page) -> pd.DataFrame:
    total = len(df)

    # S'assurer que les colonnes cibles existent
    for col in ["SIREN", "Dirigeant légal (Pappers)", "Fonction Dirigeant", "Source 2 (Pappers)"]:
        if col not in df.columns:
            df[col] = ""

    for idx, row in df.iterrows():
        company = str(row.get("Company", "")).strip()
        if not company or company == "nan":
            continue

        existing_siren = str(row.get("SIREN", "")).strip()
        if existing_siren and existing_siren != "nan":
            print(f"[{idx+1}/{total}] ⏭  Déjà enrichi : {company}")
            continue

        print(f"\n[{idx+1}/{total}] 🔍 {company}")

        result = search_pappers_dirigeant(page, company)

        df.at[idx, "SIREN"] = result["siren"]
        df.at[idx, "Dirigeant légal (Pappers)"] = result['dirigeant']
        df.at[idx, "Fonction Dirigeant"] = result['fonction']
        df.at[idx, "Source 2 (Pappers)"] = result["url"]

        # Sauvegarde intermédiaire tous les 50 enregistrements
        if (idx + 1) % 50 == 0:
            df.to_excel(OUTPUT_FILE.replace(".xlsx", "_temp.xlsx"), index=False)
            print("   💾 Sauvegarde intermédiaire")

        pause = random.uniform(PAUSE_MIN, PAUSE_MAX)
        print(f"   ⏳ Pause {pause:.1f}s…")
        time.sleep(pause)

    return df


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  SCRAPER PAPPERS — DIRIGEANT + SIREN  (v4)")
    print("=" * 60)

    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {INPUT_FILE}")
        sys.exit(1)

    all_sheets = pd.read_excel(INPUT_FILE, sheet_name=None)
    print(f"\n✅ Onglets trouvés : {list(all_sheets.keys())}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--lang=fr-FR,fr",
            ],
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"},
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR','fr'] });
        """)
        page = context.new_page()

        for sheet_name, df in all_sheets.items():
            print(f"\n{'='*40}")
            print(f"  Traitement onglet : {sheet_name}")
            print(f"{'='*40}")
            all_sheets[sheet_name] = enrich_sheet(df, page)

        browser.close()

    # Sauvegarde finale — tous les onglets préservés
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        for name, df in all_sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    total_enriched = sum(
        (df.get("SIREN", pd.Series(dtype=str)).astype(str).str.strip() != "").sum()
        for df in all_sheets.values()
    )
    print(f"\n{'='*60}")
    print(f"  ✅ TERMINÉ — {total_enriched} SIREN trouvés")
    print(f"  💾 Fichier : {OUTPUT_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()