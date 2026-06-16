import asyncio
import pandas as pd
import random
import re
import sys
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────
INPUT_FILE  = "Feuille de calcul sans titre (1).xlsx"
OUTPUT_FILE = "Feuille de calcul sans titre (1)_enrichi1.xlsx"
HEADLESS    = True
WORKERS     = 2
PAUSE_MIN   = 0.8
PAUSE_MAX   = 1.6
NAV_TIMEOUT = 18000   # ms navigation
WAIT_JS     = 2500    # ms attente rendu JS après goto
EL_TIMEOUT  = 3000    # ms locators
# ─────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
]


def clean(v: str) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()


# ═════════════════════════════════════════════════════════════════════════════
# GOTO avec attente JS réelle
# ═════════════════════════════════════════════════════════════════════════════

async def goto_wait(page, url: str) -> bool:
    """
    Navigue vers url et attend que le rendu JS soit stable.
    Retourne False si timeout.
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        # Pappers est une SPA Vue.js — attendre que le contenu soit injecté
        # On attend qu'un élément de contenu soit visible ou le délai max
        try:
            await page.wait_for_load_state("networkidle", timeout=WAIT_JS)
        except PWTimeout:
            pass  # networkidle pas obligatoire, on continue
        await asyncio.sleep(random.uniform(0.4, 0.8))
        return True
    except PWTimeout:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# EXTRACTION — calquée sur la v4 qui fonctionnait
# ═════════════════════════════════════════════════════════════════════════════

async def _best_link(page, words: list) -> tuple:
    """Parcourt tous les a[href*='/entreprise/'] et score par mots."""
    best_url   = None
    best_score = -1
    try:
        links = await page.locator("a[href*='/entreprise/']").all()
        for link in links:
            try:
                href = (await link.get_attribute("href", timeout=600)) or ""
                text = clean(await link.inner_text(timeout=600)).upper()
            except Exception:
                continue
            combined = href.upper() + " " + text
            score = sum(1 for w in words if w in combined)
            if score > best_score:
                best_score = score
                best_url   = href
    except Exception:
        pass
    if best_url and not best_url.startswith("http"):
        best_url = "https://www.pappers.fr" + best_url
    return best_url, best_score


async def _extract_siren_url(url: str) -> str:
    m = re.search(r"-(\d{9})(?:/|$)", url)
    return m.group(1) if m else ""


async def _extract_siren_page(page) -> str:
    """Cherche le SIREN dans le texte brut de la page."""
    try:
        body = await page.inner_text("body", timeout=EL_TIMEOUT)
        # Format Pappers : "SIREN : 123 456 789" ou "SIREN123456789"
        m = re.search(r"SIREN\s*[:\s]*(\d[\d\s]{6,10}\d)", body)
        if m:
            return re.sub(r"\s", "", m.group(1))
    except Exception:
        pass
    return ""


async def _extract_dirigeant_and_fonction(page) -> tuple:
    """
    Stratégie multi-niveaux pour extraire dirigeant + fonction.
    Calquée sur ce qui fonctionnait en v4 (sync).
    """
    dirigeant = ""
    fonction  = ""

    # ── Niveau 1 : sélecteurs directs CSS ────────────────────────────────────
    # td.info-dirigeant a  ← fonctionnait en v4
    sels_dir = [
        "td.info-dirigeant a",
        "td.info-dirigeant",
        ".dirigeant-nom a",
        ".dirigeant-nom",
        ".personne-physique .nom",
        ".nom-complet",
        "tr.dirigeant td:first-child",
        ".section-dirigeants .nom",
        ".bloc-dirigeant .nom",
    ]
    for sel in sels_dir:
        try:
            els = await page.locator(sel).all()
            for el in els:
                t = clean(await el.inner_text(timeout=EL_TIMEOUT))
                if t and len(t) > 3 and "VOIR PLUS" not in t.upper():
                    dirigeant = t
                    break
        except Exception:
            pass
        if dirigeant:
            break

    # ── Niveau 2 : table générique th "Dirigeant" ────────────────────────────
    if not dirigeant:
        try:
            rows = await page.locator("table tr").all()
            for row in rows:
                try:
                    th = clean(await row.locator("th").first.inner_text(timeout=400))
                    if "dirigeant" in th.lower():
                        td = clean(await row.locator("td").first.inner_text(timeout=400))
                        if td:
                            dirigeant = td
                        break
                except Exception:
                    pass
        except Exception:
            pass

    # ── Niveau 3 : regex dans le corps de la page ────────────────────────────
    if not dirigeant:
        try:
            body = await page.inner_text("body", timeout=EL_TIMEOUT)
            # Pattern Pappers : "Gérant : DUPONT Jean" ou "Président MARTIN Paul"
            m = re.search(
                r"(G[ée]rant(?:e)?|Pr[ée]sident(?:e)?|"
                r"Directeur(?:rice)?\s*[Gg][ée]n[ée]ral(?:e)?|"
                r"PDG|CEO|Administrateur(?:rice)?|Associ[ée]e?[- ]?G[ée]rant(?:e)?)"
                r"[^:]{0,5}:?\s*([A-ZÀ-Ÿ][A-ZÀ-Ÿa-zà-ÿ\-' ]{3,40})",
                body,
            )
            if m:
                fonction  = clean(m.group(1))
                dirigeant = clean(m.group(2))
        except Exception:
            pass

    # ── Fonction (si dirigeant trouvé via niveaux 1/2) ────────────────────────
    if dirigeant and not fonction:
        sels_fct = [
            ".dirigeant-qualite", ".qualite-dirigeant", ".fonction-dirigeant",
            ".poste-dirigeant", "td.qualite", ".role",
            ".fiche-identite .qualite", ".bloc-dirigeant .qualite",
        ]
        for sel in sels_fct:
            try:
                t = clean(await page.locator(sel).first.inner_text(timeout=EL_TIMEOUT))
                if t:
                    fonction = t
                    break
            except Exception:
                pass

        # Fallback fonction via regex
        if not fonction:
            try:
                body = await page.inner_text("body", timeout=EL_TIMEOUT)
                pattern = (
                    r"(G[ée]rant(?:e)?|Pr[ée]sident(?:e)?|"
                    r"Directeur(?:rice)?\s*[Gg][ée]n[ée]ral(?:e)?|"
                    r"PDG|CEO|Administrateur(?:rice)?|Associ[ée]e?[- ]?G[ée]rant(?:e)?)"
                )
                m = re.search(pattern, body, re.IGNORECASE)
                if m:
                    fonction = clean(m.group(1))
            except Exception:
                pass

    return dirigeant, fonction


# ═════════════════════════════════════════════════════════════════════════════
# SCRAPING PRINCIPAL
# ═════════════════════════════════════════════════════════════════════════════

async def search_pappers(page, company: str) -> dict:
    result = {"siren": "", "dirigeant": "", "fonction": "", "url": ""}
    words  = [w for w in company.upper().split() if len(w) > 2]

    # ── 1. Recherche entreprise ──────────────────────────────────────────────
    query = company.replace(" ", "+")
    ok = await goto_wait(page, f"https://www.pappers.fr/recherche?q={query}")
    if not ok:
        return result

    best_url, best_score = await _best_link(page, words)

    # ── 1b. Fallback recherche dirigeants ────────────────────────────────────
    if best_score < 1:
        ok2 = await goto_wait(
            page,
            f"https://www.pappers.fr/recherche-dirigeants?q={query}&en_poste=true"
        )
        if ok2:
            best_url2, best_score2 = await _best_link(page, words)
            if best_score2 > best_score:
                best_url, best_score = best_url2, best_score2

    if not best_url:
        return result

    result["url"] = best_url

    # ── 2. Fiche entreprise ──────────────────────────────────────────────────
    ok = await goto_wait(page, best_url)
    if not ok:
        return result

    # SIREN
    result["siren"] = await _extract_siren_url(best_url)
    if not result["siren"]:
        result["siren"] = await _extract_siren_page(page)

    # Dirigeant + Fonction
    result["dirigeant"], result["fonction"] = \
        await _extract_dirigeant_and_fonction(page)

    return result


# ═════════════════════════════════════════════════════════════════════════════
# WORKER
# ═════════════════════════════════════════════════════════════════════════════

async def worker(wid: int, queue: asyncio.Queue, results: dict,
                 context, total: int, counter: list, lock: asyncio.Lock):
    page = await context.new_page()

    while True:
        try:
            idx, company = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        async with lock:
            counter[0] += 1
            n = counter[0]
        print(f"\n[W{wid}] [{n}/{total}] 🔍 {company}")

        result = await search_pappers(page, company)
        results[idx] = result

        siren = result["siren"] or "?"
        dir_  = result["dirigeant"] or "?"
        fct   = result["fonction"] or "?"
        print(f"   [W{wid}] 📋 SIREN={siren} | Dirigeant={dir_} | Fonction={fct}")

        await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

    await page.close()


# ═════════════════════════════════════════════════════════════════════════════
# ENRICHISSEMENT
# ═════════════════════════════════════════════════════════════════════════════

async def enrich_sheet(df: pd.DataFrame, browser) -> pd.DataFrame:
    for col in ["SIREN", "Dirigeant légal (Pappers)", "Source 2 (Pappers)"]:
        if col not in df.columns:
            df[col] = ""

    queue: asyncio.Queue = asyncio.Queue()
    for idx, row in df.iterrows():
        company = str(row.get("company", "")).strip()
        if not company or company == "nan":
            continue
        existing = str(row.get("SIREN", "")).strip()
        if existing and existing != "nan":
            print(f"   ⏭  Déjà enrichi : {company}")
            continue
        queue.put_nowait((idx, company))

    total = queue.qsize()
    if total == 0:
        return df

    n_workers = min(WORKERS, total)
    print(f"   📌 {total} entreprises — {n_workers} workers parallèles")

    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        locale="fr-FR",
        timezone_id="Europe/Paris",
        viewport={"width": 1440, "height": 900},
        extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"},
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR','fr'] });
    """)

    results = {}
    counter = [0]
    lock    = asyncio.Lock()

    await asyncio.gather(*[
        asyncio.create_task(
            worker(i + 1, queue, results, context, total, counter, lock)
        )
        for i in range(n_workers)
    ])
    await context.close()

    for idx, res in results.items():
        df.at[idx, "SIREN"] = res["siren"]
        df.at[idx, "Dirigeant légal (Pappers)"] = (
            f"{res['dirigeant']} – {res['fonction']}"
            if res["dirigeant"] and res["fonction"]
            else res["dirigeant"]
        )
        df.at[idx, "Source 2 (Pappers)"] = res["url"]

    return df


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print(f"  SCRAPER PAPPERS — v7 async ({WORKERS} workers)")
    print("=" * 60)

    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {INPUT_FILE}")
        sys.exit(1)

    all_sheets = pd.read_excel(INPUT_FILE, sheet_name=None)
    print(f"\n✅ Onglets trouvés : {list(all_sheets.keys())}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--lang=fr-FR,fr",
            ],
        )

        for sheet_name, df in all_sheets.items():
            print(f"\n{'='*40}\n  Onglet : {sheet_name}\n{'='*40}")
            all_sheets[sheet_name] = await enrich_sheet(df, browser)

            temp = OUTPUT_FILE.replace(".xlsx", "_temp.xlsx")
            with pd.ExcelWriter(temp, engine="openpyxl") as writer:
                for name, d in all_sheets.items():
                    d.to_excel(writer, sheet_name=name, index=False)
            print(f"   💾 Sauvegarde intermédiaire : {temp}")

        await browser.close()

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
    asyncio.run(main())