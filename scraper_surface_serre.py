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
INPUT_FILE   = "Feuille de calcul sans titre (1).xlsx"
OUTPUT_FILE  = "Feuille de calcul sans titre (1)_final.xlsx"
ALL_SHEETS   = True
HEADLESS     = False
PAUSE_MIN    = 1.5
PAUSE_MAX    = 3.0
# ─────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# ── Patterns pour détecter les surfaces ──────────────────────────────────────
SURFACE_PATTERNS = [
    r"(\d[\d\s]{0,6}\d)\s*(?:m²|m2|mètres?\s*carrés?)",
    r"(\d+[,.]?\d*)\s*(?:ha|hectare?s?)\s*(?:de\s+)?(?:serres?|serre|surfaces?|production|maraîchage|horticult)",
    r"(\d+[,.]?\d*)\s*(?:ha|hectare?s?)",
    r"(\d[\d\s]{0,6}\d)\s*(?:plants?|pieds?|tonnes?|tomates?)\s*(?:par\s+an|\/\s*an)?",
]

SURFACE_QUERY_SUFFIXES = [
    "surface serres hectares",
    "m² serre production",
    "hectares de serres",
    "production maraîchage surface",
]


# ═════════════════════════════════════════════════════════════════════════════
# UTILITAIRES
# ═════════════════════════════════════════════════════════════════════════════

def safe(v) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat", "") else s


def human_delay(a=0.5, b=1.5):
    time.sleep(random.uniform(a, b))


def parse_surface_m2(text: str) -> tuple:
    for pat in SURFACE_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            raw = m.group(1).replace(" ", "").replace("\u202f", "").replace(",", ".")
            try:
                val = float(raw)
            except Exception:
                continue

            matched_text = m.group(0)
            is_ha = any(x in matched_text.lower() for x in ["ha", "hectare"])

            if is_ha:
                surface = int(val * 10000)
            else:
                surface = int(val)

            if 100 <= surface <= 5_000_000:
                context_start = max(0, m.start() - 60)
                context_end   = min(len(text), m.end() + 60)
                context = text[context_start:context_end].replace("\n", " ").strip()
                return surface, f'"{context}"'

    return 0, ""


def estimate_from_indicators(employees: float, revenue: float, type_act: str) -> tuple:
    is_serre = any(x in type_act.lower() for x in ["serre", "horticult", "maraîch"])
    if not is_serre:
        return 0, ""

    if employees > 0:
        est = int(employees * 600)
        est = min(est, 500_000)
        est = max(est, 1_000)
        return est, f"Estimation via effectif ({int(employees)} ETP × ~600 m²/ETP)"

    if revenue > 0:
        est = int(revenue / 150)
        est = min(est, 500_000)
        est = max(est, 1_000)
        return est, f"Estimation via CA ({revenue:,.0f}€ ÷ 150 €/m²)"

    return 0, ""


def format_surface(m2: int) -> str:
    if m2 <= 0:
        return ""
    if m2 >= 10_000:
        return f"{m2:,} m² ({m2/10000:.2f} ha)".replace(",", " ")
    return f"{m2:,} m²".replace(",", " ")


def accept_cookies(page):
    for sel in ["button:has-text('Tout accepter')", "button:has-text('Accept all')",
                "#L2AGLb", "button:has-text('Accepter')"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                human_delay(0.5, 1.0)
                return True
        except Exception:
            continue
    return False


def detect_company_column(df: pd.DataFrame) -> str:
    """
    Détecte automatiquement la colonne contenant le nom de l'entreprise.
    """
    candidates = [
        "Nom de l'entreprise", "Nom", "Entreprise", "Société", "Company", 
        "Raison sociale", "Dénomination", "Nom entreprise", "Client"
    ]
    for col in df.columns:
        if str(col).strip() in candidates:
            return str(col).strip()
    # Fuzzy match
    for col in df.columns:
        col_lower = str(col).lower()
        for cand in ["nom", "entreprise", "société", "company", "raison", "client"]:
            if cand in col_lower:
                return str(col).strip()
    return None


def detect_column(df: pd.DataFrame, keywords: list) -> str:
    """Trouve une colonne correspondant aux mots-clés."""
    for col in df.columns:
        col_lower = str(col).lower()
        for kw in keywords:
            if kw.lower() in col_lower:
                return str(col).strip()
    return None


# ═════════════════════════════════════════════════════════════════════════════
# SCRAPING
# ═════════════════════════════════════════════════════════════════════════════

def scrape_site_officiel(page, website: str) -> tuple:
    if not website:
        return 0, ""

    pages_to_check = [
        website,
        website.rstrip("/") + "/qui-sommes-nous",
        website.rstrip("/") + "/about",
        website.rstrip("/") + "/chiffres-cles",
        website.rstrip("/") + "/presentation",
        website.rstrip("/") + "/notre-histoire",
        website.rstrip("/") + "/productions",
    ]

    for url in pages_to_check:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            human_delay(0.8, 1.5)
            text = page.inner_text("body")
            surface, preuve = parse_surface_m2(text)
            if surface:
                return surface, f"Site officiel ({url}): {preuve}"
        except Exception:
            continue

    return 0, ""


_cookies_done = [False]

def scrape_google(page, company: str, location: str) -> tuple:
    for suffix in SURFACE_QUERY_SUFFIXES:
        query = f'"{company} {location}" {suffix}'
        try:
            page.goto("https://www.google.fr", wait_until="domcontentloaded", timeout=15000)
            human_delay(0.5, 1.0)
            if not _cookies_done[0]:
                if accept_cookies(page):
                    _cookies_done[0] = True

            for sel in ["textarea#APjFqb", "textarea[name='q']", "input[name='q']"]:
                try:
                    loc = page.locator(sel)
                    loc.wait_for(state="visible", timeout=5000)
                    loc.fill(query)
                    loc.press("Enter")
                    break
                except Exception:
                    continue

            page.wait_for_selector("#search, #rso, .g", timeout=10000)
            human_delay(1.0, 1.8)

            snippets = []
            for sel in [".BNeawe.s3v9rd.AP7Wnd", ".IsZvec", ".VwiC3b",
                        ".MUxGbd", ".yDYNvb", "span.hgKElc", ".n6owBd"]:
                try:
                    for el in page.locator(sel).all():
                        t = el.inner_text(timeout=500).strip()
                        if t and len(t) > 20:
                            snippets.append(t)
                except Exception:
                    pass

            combined = "\n".join(snippets)
            surface, preuve = parse_surface_m2(combined)
            if surface:
                return surface, f"Google ({query}): {preuve}"

        except Exception as e:
            print(f"   ⚠️  Erreur Google: {e}")

    return 0, ""


def find_surface(page, company: str, location: str, website: str,
                 employees: float, revenue: float, type_act: str) -> tuple:
    print(f"   🌱 Recherche surface : {company}")

    surface, preuve = scrape_site_officiel(page, website)
    if surface:
        print(f"   ✅ Site officiel → {format_surface(surface)}")
        return surface, preuve

    surface, preuve = scrape_google(page, company, location)
    if surface:
        print(f"   ✅ Google → {format_surface(surface)}")
        return surface, preuve

    surface, preuve = estimate_from_indicators(employees, revenue, type_act)
    if surface:
        print(f"   ⚡ Estimation → {format_surface(surface)} ({preuve})")
        return surface, f"[ESTIMÉ] {preuve}"

    print(f"   ❓ Surface non trouvée")
    return 0, "À vérifier par appel"


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def enrich_sheet(df: pd.DataFrame, page) -> pd.DataFrame:
    # ── DEBUG : Afficher la structure ──
    print(f"   📊 Colonnes détectées : {list(df.columns)}")
    print(f"   📊 Nombre de lignes : {len(df)}")
    if len(df) > 0:
        print(f"   📊 3 premières lignes :\n{df.head(3).to_string()}")

    # ── Détection automatique des colonnes ──
    col_company = detect_company_column(df)
    col_location = detect_column(df, ["location", "ville", "adresse", "city", "localisation"])
    col_website = detect_column(df, ["site internet", "website", "web", "url", "site"])
    col_type = detect_column(df, ["type d'activité", "activité", "secteur", "type"])
    col_employees = detect_column(df, ["nb employés", "employés", "effectif", "salariés", "employees"])
    col_revenue = detect_column(df, ["ca estimé", "chiffre d'affaires", "ca ", "revenue", "turnover"])

    print(f"   🔍 Colonne entreprise : {col_company}")
    print(f"   🔍 Colonne localisation : {col_location}")
    print(f"   🔍 Colonne site web : {col_website}")

    if not col_company:
        print("   ❌ ERREUR : Aucune colonne 'Nom de l'entreprise' détectée !")
        print("   💡 Vérifie les noms de colonnes dans ton Excel.")
        return df

    # S'assurer que les colonnes de sortie existent
    if "Surface estimée serres (m²)" not in df.columns:
        df["Surface estimée serres (m²)"] = ""
    if "Preuve / indice surface" not in df.columns:
        df["Preuve / indice surface"] = ""

    total = len(df)
    skipped_empty = 0
    skipped_filled = 0

    for idx, row in df.iterrows():
        company = safe(row.get(col_company, ""))
        
        if not company:
            skipped_empty += 1
            print(f"   ⚠️  Ligne {idx+1} sautée : nom d'entreprise vide")
            continue

        # Ne pas ré-enrichir si déjà rempli
        existing = safe(row.get("Surface estimée serres (m²)", ""))
        if existing and existing not in ("À vérifier par appel", "0", ""):
            skipped_filled += 1
            print(f"[{idx+1}/{total}] ⏭  Déjà rempli : {company} → {existing}")
            continue

        location = safe(row.get(col_location, "")) if col_location else ""
        website = safe(row.get(col_website, "")) if col_website else ""
        type_act = safe(row.get(col_type, "")) if col_type else ""

        try:
            emp = float(row.get(col_employees, 0) or 0) if col_employees else 0
        except Exception:
            emp = 0
        try:
            rev = float(row.get(col_revenue, 0) or 0) if col_revenue else 0
        except Exception:
            rev = 0

        print(f"\n[{idx+1}/{total}] {company}")
        surface, preuve = find_surface(page, company, location, website, emp, rev, type_act)

        df.at[idx, "Surface estimée serres (m²)"] = format_surface(surface) if surface else "À vérifier par appel"
        df.at[idx, "Preuve / indice surface"] = preuve

        # Sauvegarde intermédiaire tous les 5
        if (idx + 1) % 5 == 0:
            temp_file = OUTPUT_FILE.replace(".xlsx", "_temp.xlsx")
            df.to_excel(temp_file, index=False)
            print(f"   💾 Sauvegarde intermédiaire ({temp_file})")

        pause = random.uniform(PAUSE_MIN, PAUSE_MAX)
        print(f"   ⏳ Pause {pause:.1f}s…")
        time.sleep(pause)

    print(f"\n   📈 Résumé : {total} lignes, {skipped_empty} vides, {skipped_filled} déjà remplies, {total - skipped_empty - skipped_filled} traitées")
    return df


def main():
    print("=" * 60)
    print("  SCRAPER SURFACE DE SERRES  (v2.1 - DEBUG)")
    print("=" * 60)

    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {INPUT_FILE}")
        sys.exit(1)

    all_sheets = pd.read_excel(INPUT_FILE, sheet_name=None)
    print(f"\n✅ Onglets trouvés : {list(all_sheets.keys())}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage", "--lang=fr-FR,fr"],
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1440, "height": 900},
        )
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = context.new_page()

        sheets_to_process = list(all_sheets.keys()) if ALL_SHEETS else ["🏆 Leads Priorité A"]

        for sheet_name in sheets_to_process:
            if sheet_name not in all_sheets:
                continue
            print(f"\n{'='*40}\n  Onglet : {sheet_name}\n{'='*40}")
            all_sheets[sheet_name] = enrich_sheet(all_sheets[sheet_name], page)

        browser.close()

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        for name, df in all_sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    found = sum(
        ((df.get("Surface estimée serres (m²)", pd.Series(dtype=str)) != "")
         & (df.get("Surface estimée serres (m²)", pd.Series(dtype=str)) != "À vérifier par appel")
        ).sum()
        for df in all_sheets.values()
    )
    print(f"\n{'='*60}")
    print(f"  ✅ TERMINÉ — {found} surfaces trouvées/estimées")
    print(f"  💾 Fichier : {OUTPUT_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()