import re
import sys
import json
import random
import asyncio
import hashlib
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ─── CONFIG ───────────────────────────────────────────────────────────────────
N_WORKERS      = 3
DELAY_MIN_MS   = 1200
DELAY_MAX_MS   = 2800
CHECKPOINT_DIR = Path(".scraper_checkpoints")
PROXIES: list[str] = []   # Ex: ["http://user:pass@host:port"]
# ──────────────────────────────────────────────────────────────────────────────

# ─── MAPPING COLONNES FLEXIBLES ───────────────────────────────────────────────
# Le script détecte ces variantes de noms de colonnes automatiquement
COL_ALIASES = {
    "Company":       ["company", "entreprise", "société", "societe", "nom_entreprise",
                      "company name", "account name", "organization"],
    "City":          ["city", "ville", "location", "localisation", "région", "region"],
    "Nom_Dirigeant": ["nom_dirigeant", "dirigeant", "contact", "name", "full name",
                      "first name", "nom", "prénom nom", "person name", "lead name"],
    "Fonction":      ["fonction", "poste", "title", "job title", "intitulé de poste",
                      "intitule", "role"],
}
# ──────────────────────────────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

SEL_TITLE    = "h1.DUwDvf"
SEL_PHONE    = "button[data-item-id^='phone:tel:']"
SEL_ADDRESS  = "button[data-item-id='address'] .Io6YTe"
SEL_WEBSITE  = "a[data-item-id='authority'] .Io6YTe"
SEL_CATEGORY = [
    "span.mgr77e span span span",
    "button.CsEnBe[jslog*='category'] .Io6YTe",
    "span.YkuOqf",
    ".DkEaL",
]
SEL_FIRST_RESULT = ["a.hfpxzc", "div[role='feed'] > div > div a", "div.Nv2PK a"]

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
Object.defineProperty(navigator, 'languages', { get: () => ['fr-FR','fr','en-US','en'] });
window.chrome = { runtime: {} };
const _origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) =>
    p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : _origQuery(p);
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  DÉTECTION AUTOMATIQUE DES COLONNES LINKEDIN
# ═══════════════════════════════════════════════════════════════════════════════

def detect_columns(df: pd.DataFrame) -> dict:
    """
    Détecte automatiquement les colonnes du CSV LinkedIn
    en cherchant des correspondances avec COL_ALIASES.
    Retourne un dict: {nom_standard: nom_colonne_réelle}
    """
    cols_lower = {c.lower().strip(): c for c in df.columns}
    mapping = {}

    for standard, aliases in COL_ALIASES.items():
        for alias in aliases:
            if alias.lower() in cols_lower:
                mapping[standard] = cols_lower[alias.lower()]
                break

    # Résumé
    print("\n📋 Colonnes détectées dans ton CSV :")
    for std, real in mapping.items():
        print(f"   {std:20s} ← '{real}'")

    missing = [s for s in COL_ALIASES if s not in mapping]
    if missing:
        print(f"\n⚠️  Colonnes non trouvées (seront vides) : {missing}")
        print(f"   Colonnes disponibles dans le CSV : {list(df.columns)}")

    return mapping


def get_val(row, mapping: dict, field: str) -> str:
    col = mapping.get(field)
    if col and col in row:
        v = row[col]
        return str(v).strip() if pd.notna(v) else ""
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILS
# ═══════════════════════════════════════════════════════════════════════════════

def rand_delay(mn=DELAY_MIN_MS, mx=DELAY_MAX_MS):
    return random.randint(mn, mx)

def extract_city(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    c = re.sub(r"Greater\s+(\w+)\s+Area", r"\1", raw.strip())
    c = re.sub(r"\s+(et périphérie|area|region|métropole).*", "", c, flags=re.IGNORECASE)
    return c.split(",")[0].strip()

def strip_legal(name: str) -> str:
    if not isinstance(name, str):
        return ""
    return re.sub(
        r"\b(SAS|SARL|SA|EURL|SE|SNC|SCP|SASU|GIE|GMBH|LTD|LLC|INC|BV|AG)\b\.?",
        "", name.strip(), flags=re.IGNORECASE
    ).strip(" ,.")

def make_key(company: str, city: str) -> str:
    return hashlib.md5(f"{company.lower().strip()}|{city.lower().strip()}".encode()).hexdigest()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ═══════════════════════════════════════════════════════════════════════════════
#  CHECKPOINT
# ═══════════════════════════════════════════════════════════════════════════════

class Checkpoint:
    def __init__(self, output_file: str):
        CHECKPOINT_DIR.mkdir(exist_ok=True)
        self.path = CHECKPOINT_DIR / f"{Path(output_file).stem}.jsonl"
        self.done: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line.strip())
                        if "_key" in row:
                            self.done[row["_key"]] = row
                    except Exception:
                        pass
            if self.done:
                print(f"📂 Checkpoint : {len(self.done)} lignes déjà traitées — reprise automatique")

    def save(self, key: str, data: dict):
        data["_key"] = key
        self.done[key] = data
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def is_done(self, key: str) -> bool:
        return key in self.done

    def get(self, key: str) -> dict:
        return self.done.get(key, {})

    def clear(self):
        if self.path.exists():
            self.path.unlink()
        self.done = {}
        print("🗑️  Checkpoint effacé.")


# ═══════════════════════════════════════════════════════════════════════════════
#  PLAYWRIGHT — contexte stealth
# ═══════════════════════════════════════════════════════════════════════════════

async def new_context(browser, proxy=None):
    kw = dict(
        viewport={"width": random.randint(1240, 1400), "height": random.randint(780, 920)},
        locale="fr-FR",
        timezone_id="Europe/Paris",
        user_agent=random.choice(USER_AGENTS),
        extra_http_headers={
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    if proxy:
        kw["proxy"] = {"server": proxy}
    ctx = await browser.new_context(**kw)
    await ctx.add_init_script(STEALTH_JS)
    return ctx

async def accept_cookies(page):
    for sel in [
        "button[aria-label*='Accept']", "button[aria-label*='Tout accept']",
        "button[aria-label*='Accepter']", "button#L2AGLb",
        "form[action*='consent'] button",
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(600)
                return
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  SCRAPING FICHE GOOGLE MAPS
# ═══════════════════════════════════════════════════════════════════════════════

async def scrape_place(page) -> dict:
    """Extrait les données d'une fiche établissement Google Maps ouverte."""
    data = {"gm_nom": "", "gm_produit": "", "gm_tel_entreprise": "",
            "gm_adresse": "", "gm_site_internet": "", "gm_note": "",
            "gm_nb_avis": "", "gm_lien": page.url}
    try:
        el = await page.query_selector(SEL_TITLE)
        if el:
            data["gm_nom"] = (await el.inner_text()).strip()

        for sel in SEL_CATEGORY:
            el = await page.query_selector(sel)
            if el:
                txt = (await el.inner_text()).strip()
                if len(txt) > 2:
                    data["gm_produit"] = txt
                    break

        el = await page.query_selector(SEL_PHONE)
        if el:
            item_id = await el.get_attribute("data-item-id") or ""
            if "tel:" in item_id:
                data["gm_tel_entreprise"] = item_id.split("tel:")[-1]
            else:
                inner = await el.query_selector(".Io6YTe")
                if inner:
                    data["gm_tel_entreprise"] = (await inner.inner_text()).strip()

        el = await page.query_selector(SEL_ADDRESS)
        if el:
            data["gm_adresse"] = (await el.inner_text()).strip()

        el = await page.query_selector(SEL_WEBSITE)
        if el:
            data["gm_site_internet"] = (await el.inner_text()).strip()

        for sel in ["div.fontDisplayLarge", "span[aria-hidden='true'].MW4etd"]:
            el = await page.query_selector(sel)
            if el:
                data["gm_note"] = (await el.inner_text()).strip()
                break

        el = await page.query_selector("span[aria-hidden='true'].UY7F9")
        if el:
            data["gm_nb_avis"] = (await el.inner_text()).strip().strip("()")

    except Exception as e:
        print(f"     ⚠️ Erreur scrape: {e}")
    return data


async def search_maps(page, query: str) -> dict | None:
    """Recherche une query sur Google Maps et scrape la fiche trouvée."""
    url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(rand_delay(800, 1400))
        await accept_cookies(page)
        await page.wait_for_timeout(rand_delay(900, 1600))

        if await page.query_selector(SEL_TITLE):
            return await scrape_place(page)

        for sel in SEL_FIRST_RESULT:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(rand_delay(DELAY_MIN_MS, DELAY_MAX_MS))
                if await page.query_selector(SEL_TITLE):
                    return await scrape_place(page)
                break

        return None
    except PWTimeout:
        print(f"   ⏰ Timeout: {query}")
        return None
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        return None


async def enrich_company(page, company: str, city: str) -> dict:
    """
    Stratégie 2 étapes :
      1) "Nom entreprise + Ville"  → si téléphone + catégorie → OK
      2) "Nom entreprise" seul     → fusion avec étape 1
    """
    company_q  = strip_legal(company) or company
    city_clean = extract_city(city)

    r1 = None
    if company_q and city_clean:
        r1 = await search_maps(page, f"{company_q} {city_clean}")

    if r1 and r1.get("gm_tel_entreprise") and r1.get("gm_produit"):
        return r1

    r2 = await search_maps(page, company_q)

    if r2:
        if r1:
            for f in r1:
                r2[f] = r2.get(f) or r1.get(f, "")
        return r2

    return r1 or {}


# ═══════════════════════════════════════════════════════════════════════════════
#  WORKER PARALLÈLE
# ═══════════════════════════════════════════════════════════════════════════════

async def worker(worker_id: int, queue: asyncio.Queue, results: list,
                 checkpoint: Checkpoint, browser, proxy, col_mapping: dict):

    ctx  = await new_context(browser, proxy)
    page = await ctx.new_page()
    print(f"🚀 Worker {worker_id} prêt")

    try:
        while True:
            try:
                i, total, row = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            company = get_val(row, col_mapping, "Company")
            city    = get_val(row, col_mapping, "City")
            dirigeant = get_val(row, col_mapping, "Nom_Dirigeant")
            fonction  = get_val(row, col_mapping, "Fonction")
            key = make_key(company, city)

            print(f"\n[W{worker_id}] [{i+1}/{total}] {company} — {city}")

            if checkpoint.is_done(key):
                gm = checkpoint.get(key)
                print(f"   ⏭️  Déjà traité (checkpoint) — status: {gm.get('gm_status','?')}")
            else:
                gm = await enrich_company(page, company, city)
                gm["gm_status"] = "TROUVE" if gm.get("gm_tel_entreprise") else ("PARTIEL" if gm else "NON_TROUVE")
                checkpoint.save(key, gm)

            # ── Construction de la ligne finale (colonnes PDF) ──
            final_row = {
                "Entreprise":          gm.get("gm_nom")          or company,
                "Ville":               city,
                "Produit":             gm.get("gm_produit",       ""),
                "Nom_Dirigeant":       dirigeant,
                "Fonction":            fonction,
                "Tel_Mobile_Direct":   "",   # ← à remplir via Apollo
                "Tel_Entreprise":      gm.get("gm_tel_entreprise",""),
                "Site_Internet":       gm.get("gm_site_internet", ""),
                "Source":              "LinkedIn + Google Maps",
                # Colonnes bonus utiles
                "Adresse":             gm.get("gm_adresse",       ""),
                "Note_Google":         gm.get("gm_note",          ""),
                "Nb_Avis":             gm.get("gm_nb_avis",       ""),
                "Lien_Maps":           gm.get("gm_lien",          ""),
                "Status":              gm.get("gm_status",        ""),
                "Traité_le":           now_iso(),
            }

            results.append(final_row)
            queue.task_done()

            # Log
            tel   = final_row["Tel_Entreprise"]
            site  = final_row["Site_Internet"]
            produit = final_row["Produit"]
            icon  = "✅" if tel else "⚠️ "
            print(f"   {icon} {final_row['Entreprise']} | {produit} | {tel or 'pas de tél'} | {site or 'pas de site'}")

    finally:
        await ctx.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  SAUVEGARDE EXCEL
# ═══════════════════════════════════════════════════════════════════════════════

FINAL_COLUMNS = [
    "Entreprise", "Ville", "Produit", "Nom_Dirigeant", "Fonction",
    "Tel_Mobile_Direct", "Tel_Entreprise", "Site_Internet", "Source",
    "Adresse", "Note_Google", "Nb_Avis", "Lien_Maps", "Status", "Traité_le",
]

def save_excel(rows: list, output_file: str):
    if not rows:
        print("⚠️  Aucun résultat.")
        return
    df = pd.DataFrame(rows)
    # Ordre des colonnes : colonnes PDF en premier, le reste après
    ordered = [c for c in FINAL_COLUMNS if c in df.columns]
    extra   = [c for c in df.columns if c not in ordered and c != "_key"]
    df      = df[ordered + extra]

    # Mise en forme Excel basique
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
        ws = writer.sheets["Leads"]
        # Largeurs colonnes
        col_widths = {
            "Entreprise": 30, "Ville": 18, "Produit": 22,
            "Nom_Dirigeant": 22, "Fonction": 22,
            "Tel_Mobile_Direct": 20, "Tel_Entreprise": 18,
            "Site_Internet": 30, "Source": 22,
            "Adresse": 35, "Note_Google": 12, "Nb_Avis": 10,
            "Lien_Maps": 40, "Status": 12, "Traité_le": 20,
        }
        for col_idx, col_name in enumerate(df.columns, 1):
            width = col_widths.get(col_name, 18)
            ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = width

    print(f"💾 Fichier sauvegardé : {output_file}  ({len(df)} lignes)")


def print_stats(rows: list):
    if not rows:
        return
    df     = pd.DataFrame(rows)
    total  = len(df)
    tel    = df["Tel_Entreprise"].astype(str).str.strip().ne("").sum()
    site   = df["Site_Internet"].astype(str).str.strip().ne("").sum()
    produit= df["Produit"].astype(str).str.strip().ne("").sum()
    dirig  = df["Nom_Dirigeant"].astype(str).str.strip().ne("").sum()
    both   = ((df["Tel_Entreprise"].astype(str).str.strip().ne("")) &
              (df["Site_Internet"].astype(str).str.strip().ne(""))).sum()

    print(f"\n{'='*55}")
    print(f"📈 RÉSULTATS FINAUX")
    print(f"{'='*55}")
    print(f"  Total leads             : {total}")
    print(f"  Avec téléphone          : {tel}  ({tel/total*100:.1f}%)")
    print(f"  Avec site internet      : {site} ({site/total*100:.1f}%)")
    print(f"  Avec produit/catégorie  : {produit} ({produit/total*100:.1f}%)")
    print(f"  Avec dirigeant (LinkedIn): {dirig} ({dirig/total*100:.1f}%)")
    print(f"  ✅ Tél + Site           : {both} ({both/total*100:.1f}%)")
    print(f"\n  ⚡ Il reste à remplir 'Tel_Mobile_Direct' via Apollo")
    print(f"{'='*55}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main(args):
    global N_WORKERS
    N_WORKERS = args.workers

    # ── Lecture CSV ──
    try:
        df = pd.read_csv(args.input, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(args.input, encoding="latin-1")

    if args.limit:
        df = df.head(args.limit)

    print(f"\n📊 {len(df)} leads chargés depuis '{args.input}'")
    print(f"   Colonnes brutes : {list(df.columns)}")

    col_mapping = detect_columns(df)

    if "Company" not in col_mapping:
        print("\n❌ ERREUR : colonne 'Company/Entreprise' introuvable dans le CSV.")
        print("   Renomme la colonne dans ton CSV et relance.")
        sys.exit(1)

    # ── Checkpoint ──
    cp = Checkpoint(args.output)
    if args.reset_checkpoint:
        cp.clear()

    # ── Queue ──
    queue   = asyncio.Queue()
    results = []
    for i, row in df.iterrows():
        queue.put_nowait((i, len(df), row))

    proxies_cycle = PROXIES if PROXIES else [None]

    # ── Playwright ──
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage"],
        )

        # Sauvegarde automatique toutes les 60s
        async def auto_save():
            while True:
                await asyncio.sleep(60)
                if results:
                    save_excel(results, args.output)
                    print(f"   💾 Auto-save ({len(results)} lignes)")

        saver   = asyncio.create_task(auto_save())
        workers = [
            worker(
                worker_id=w,
                queue=queue,
                results=results,
                checkpoint=cp,
                browser=browser,
                proxy=proxies_cycle[w % len(proxies_cycle)],
                col_mapping=col_mapping,
            )
            for w in range(min(N_WORKERS, len(df)))
        ]

        await asyncio.gather(*workers)
        saver.cancel()
        await browser.close()

    save_excel(results, args.output)
    print_stats(results)
    print(f"\n✅ Terminé ! Ouvre '{args.output}' et complète 'Tel_Mobile_Direct' via Apollo.")


def parse_args():
    p = argparse.ArgumentParser(
        description="Enrichit un export LinkedIn avec Google Maps → Excel final complet"
    )
    p.add_argument("--input",   required=True,  help="CSV exporté depuis LinkedIn Sales Navigator")
    p.add_argument("--output",  required=True,  help="Fichier Excel en sortie (.xlsx)")
    p.add_argument("--workers", type=int, default=3, help="Nombre de pages parallèles (défaut: 3)")
    p.add_argument("--limit",   type=int,       help="Tester sur N premières lignes")
    p.add_argument("--reset-checkpoint", action="store_true",
                   help="Ignorer le checkpoint et tout re-scraper")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
