import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import asyncio
import json
import os
import re
import random
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

INPUT_FILE       = "paris.xlsx"
OUTPUT_FILE      = "paris_avec_emails1.xlsx"
CHECKPOINT_FILE  = "checkpoint_email1.json"

CDP_URL          = "http://127.0.0.1:9222"
NB_WORKERS       = 2
PAUSE_MIN        = 1.5
PAUSE_MAX        = 3.5
PAUSE_CAPTCHA    = 60
CHECKPOINT_EVERY = 10
TIMEOUT_MS       = 20_000

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
]
CHROME_USER_DATA = r"C:\ChromeBot"

# ─────────────────────────────────────────────────────────────────────────────
# COLONNES DU FICHIER (noms exacts)
# ─────────────────────────────────────────────────────────────────────────────

COL_NOM     = "Nom d'opérateur"
COL_SITE    = "Site web"
COL_EMAIL   = "Email(s) site web"     # colonne à remplir
COL_EMAILS2 = "Tous les emails"       # colonne bonus (on y écrit aussi)
COL_URL_OP  = "URL d'opérateur"

# ─────────────────────────────────────────────────────────────────────────────
# REGEX & BLACKLIST
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

EMAIL_BLACKLIST = {
    "google.com","google.fr","example.com","example.fr",
    "sentry.io","w3.org","schema.org","facebook.com","twitter.com",
    "instagram.com","linkedin.com","cloudflare.com","amazonaws.com",
    "wixpress.com","wordpress.org","jquery.com","bootstrapcdn.com",
    "gstatic.com","googleapis.com","getyourguide.com","reply.getyourguide.com",
    "wix.com","squarespace.com","shopify.com","webflow.io",
}

# Préfixes email prioritaires (professionnel > générique)
EMAIL_PRIORITY = [
    "contact", "info", "hello", "bonjour", "reservation",
    "booking", "accueil", "office", "studio", "team",
]

CONTACT_PATHS = [
    "/contact", "/nous-contacter", "/contactez-nous", "/contact-us",
    "/a-propos", "/about", "/informations", "/coordonnees", "/nous",
]

# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────────────────

def cellval(x) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    s = str(x).strip()
    return "" if s.lower() in ("nan", "none", "null", "<na>") else s

def extract_domain(url: str) -> str:
    url = (url or "").strip()
    if not url or url.lower() in ("nan", "none", ""):
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        netloc = urlparse(url).netloc
        return re.sub(r"^www\.", "", netloc).split(":")[0].strip("/")
    except Exception:
        return ""

def is_valid_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].lower()
    return (
        domain not in EMAIL_BLACKLIST
        and "." in domain
        and len(domain) > 3
        and not domain.endswith(".png")
        and not domain.endswith(".jpg")
    )

def extract_emails(text: str) -> list[str]:
    seen, out = set(), []
    for e in EMAIL_RE.findall(text or ""):
        e = e.lower().strip(".")
        if is_valid_email(e) and e not in seen:
            seen.add(e)
            out.append(e)
    return out

def best_email(emails: list[str], domain: str = "") -> str:
    """Choisit le meilleur email : domaine correspondant > préfixe pro > premier."""
    if not emails:
        return ""
    # 1. Email dont le domaine correspond au site
    if domain:
        for e in emails:
            if domain.lower() in e.split("@")[-1].lower():
                return e
    # 2. Préfixe professionnel connu
    for prefix in EMAIL_PRIORITY:
        for e in emails:
            if e.split("@")[0].lower().startswith(prefix):
                return e
    # 3. Premier trouvé
    return emails[0]

# ─────────────────────────────────────────────────────────────────────────────
# CHROME CDP
# ─────────────────────────────────────────────────────────────────────────────

def cdp_available() -> bool:
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
        return True
    except Exception:
        return False

def find_chrome() -> str:
    for p in CHROME_PATHS:
        if p and Path(p).exists():
            return p
    return ""

def launch_chrome_sync():
    exe = find_chrome()
    if not exe:
        print("⚠️  chrome.exe introuvable — ajoutez le chemin dans CHROME_PATHS")
        return
    Path(CHROME_USER_DATA).mkdir(parents=True, exist_ok=True)
    print(f"🚀 Lancement Chrome : {exe}")
    subprocess.Popen(
        [exe,
         "--remote-debugging-port=9222",
         f"--user-data-dir={CHROME_USER_DATA}",
         "--no-first-run",
         "--no-default-browser-check",
         "--disable-blink-features=AutomationControlled",
         "--window-size=1400,900"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("   En attente Chrome", end="", flush=True)
    for _ in range(20):
        if cdp_available():
            print(" ✅")
            return
        print(".", end="", flush=True)
        time.sleep(1)
    print(" ⚠️  port 9222 injoignable")

# ─────────────────────────────────────────────────────────────────────────────
# SCRAPING DU SITE WEB
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_emails_from_url(page: Page, url: str, domain: str) -> list[str]:
    """Visite une URL et retourne tous les emails valides trouvés."""
    all_emails = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        await asyncio.sleep(random.uniform(0.8, 1.5))

        # 1. Liens mailto: — les plus fiables
        for el in await page.locator("a[href^='mailto:']").all():
            try:
                h = (await el.get_attribute("href", timeout=400) or "")
                e = h.replace("mailto:", "").split("?")[0].strip().lower()
                if is_valid_email(e):
                    all_emails.append(e)
            except Exception:
                pass

        # 2. Texte visible du body
        if not all_emails:
            try:
                text = await page.locator("body").inner_text(timeout=3_000)
                all_emails.extend(extract_emails(text))
            except Exception:
                pass

        # 3. HTML brut (emails masqués dans des attributs data-, spans, etc.)
        if not all_emails:
            try:
                html = await page.content()
                all_emails.extend(extract_emails(html))
            except Exception:
                pass

    except Exception:
        pass

    # Dédupliquer
    seen, out = set(), []
    for e in all_emails:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


async def scrape_site_email(page: Page, site_url: str, domain: str) -> str:
    """
    Stratégie 3 couches :
      1. Page d'accueil
      2. Pages /contact (et variantes)
      3. Retourne le meilleur email trouvé
    """
    if not domain:
        return ""

    base = f"https://{domain}"
    all_emails: list[str] = []

    # Couche 1 — Page d'accueil
    emails = await fetch_emails_from_url(page, base, domain)
    all_emails.extend(emails)

    if best_email(all_emails, domain):
        return best_email(all_emails, domain)

    # Couche 2 — Pages contact
    for path in CONTACT_PATHS:
        emails2 = await fetch_emails_from_url(page, base + path, domain)
        all_emails.extend(emails2)
        if best_email(all_emails, domain):
            return best_email(all_emails, domain)
        await asyncio.sleep(0.4)

    return best_email(all_emails, domain)

# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

_cookies_done = False

async def accept_cookies(page: Page):
    global _cookies_done
    if _cookies_done:
        return
    for sel in ["button:has-text('Tout accepter')", "button:has-text('Accept all')", "#L2AGLb"]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1_500):
                await btn.click()
                await asyncio.sleep(1)
                _cookies_done = True
                return
        except Exception:
            pass
    _cookies_done = True

async def is_captcha(page: Page) -> bool:
    try:
        return "sorry" in page.url or "captcha" in page.url.lower() or \
               await page.locator("form#captcha-form").count() > 0
    except Exception:
        return False

async def google_email(page: Page, query: str, domain: str, wid: int) -> str:
    """Cherche sur Google et extrait le meilleur email."""
    url = "https://www.google.fr/search?q=" + urllib.parse.quote(query) + "&hl=fr&gl=fr&num=10"

    for attempt in range(2):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            await accept_cookies(page)
            await asyncio.sleep(random.uniform(1.0, 2.0))

            if await is_captcha(page):
                print(f"   ⚠️  [W{wid}] CAPTCHA ! Pause {PAUSE_CAPTCHA}s…")
                await asyncio.sleep(PAUSE_CAPTCHA)
                continue

            parts = []

            # Snippets Google
            for sel in [".BNeawe", ".IsZvec", ".VwiC3b", ".lEBKkf",
                        ".MUxGbd", ".yXK7lf", ".r0bn4c", ".tjvcx"]:
                try:
                    for el in await page.locator(sel).all():
                        t = (await el.inner_text(timeout=400)).strip()
                        if t:
                            parts.append(t)
                except Exception:
                    pass

            # Liens mailto dans les résultats
            for el in await page.locator("a[href^='mailto:']").all():
                try:
                    h = (await el.get_attribute("href", timeout=400) or "")
                    parts.append(h.replace("mailto:", "").split("?")[0])
                except Exception:
                    pass

            text = "\n".join(parts)
            emails = extract_emails(text)
            return best_email(emails, domain)

        except Exception as e:
            print(f"   ⚠️  [W{wid}] Google tentative {attempt+1}/2 : {e}")
            await asyncio.sleep(random.uniform(3, 6))

    return ""

# ─────────────────────────────────────────────────────────────────────────────
# TRAITEMENT D'UNE LIGNE
# ─────────────────────────────────────────────────────────────────────────────

async def process_row(
    idx: int,
    row: dict,
    page: Page,
    wid: int,
    total: int,
    sem: asyncio.Semaphore,
) -> tuple:
    async with sem:
        nom     = cellval(row.get(COL_NOM, ""))
        site    = cellval(row.get(COL_SITE, ""))
        email   = cellval(row.get(COL_EMAIL, ""))
        domain  = extract_domain(site)

        print(f"\n[{idx+1}/{total}] W{wid} ▶ {nom[:45]}")
        print(f"   🌐 {domain or '(pas de site)'}")

        # Déjà rempli → skip
        if email:
            print(f"   ⏭  Email déjà présent : {email}")
            return idx, email

        if not domain:
            print(f"   ❌ Pas de domaine — skip")
            return idx, ""

        # ── Couche 1 : scraping direct du site ──────────────────────────────
        email = await scrape_site_email(page, site, domain)
        if email:
            print(f"   📧 Site → ✔  {email}")
            return idx, email

        await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

        # ── Couche 2 : Google "{domaine} email contact" ──────────────────────
        query = f'"{domain}" email'
        print(f"   🔎 Google : {query}")
        email = await google_email(page, query, domain, wid)
        if email:
            print(f"   📧 Google → ✔  {email}")
        else:
            print(f"   ❌ Non trouvé")

        await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))
        return idx, email

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main_async():
    print("\n" + "=" * 65)
    print("  Paris — Scraper Email uniquement v1")
    print(f"  Entrée : {INPUT_FILE}  |  Sortie : {OUTPUT_FILE}")
    print("=" * 65)

    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {INPUT_FILE}")
        sys.exit(1)

    df = pd.read_excel(INPUT_FILE)
    total = len(df)
    print(f"\n✅ {total} lignes chargées")
    print(f"   Colonnes : {list(df.columns)}\n")

    # S'assurer que la colonne Email existe
    if COL_EMAIL not in df.columns:
        df[COL_EMAIL] = ""
    df[COL_EMAIL] = df[COL_EMAIL].astype("object")

    # Checkpoint
    checkpoint: dict[str, str] = {}
    if Path(CHECKPOINT_FILE).exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            print(f"✅ Checkpoint : {len(checkpoint)} lignes déjà traitées")
        except Exception:
            pass

    # Chrome
    if not cdp_available():
        launch_chrome_sync()

    async with async_playwright() as p:
        if cdp_available():
            print(f"✅ Chrome CDP connecté : {CDP_URL}")
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            via_cdp = True
        else:
            print("⚠️  CDP indisponible → Chromium headless")
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            via_cdp = False

        ANTI_DETECT = """
            Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
            window.chrome={runtime:{},loadTimes:()=>{},csi:()=>{}};
            Object.defineProperty(navigator,'languages',{get:()=>['fr-FR','fr','en']});
        """

        ctx = (
            browser.contexts[0] if (via_cdp and browser.contexts)
            else await browser.new_context(locale="fr-FR", viewport={"width": 1400, "height": 900})
        )

        pages = []
        for _ in range(NB_WORKERS):
            pg = await ctx.new_page()
            await pg.add_init_script(ANTI_DETECT)
            pages.append(pg)

        print(f"🪟  {NB_WORKERS} onglets ouverts\n")

        # Construire la liste des tâches
        tasks_to_do = []
        for idx, row in df.iterrows():
            key = str(idx)
            if key in checkpoint:
                df.at[idx, COL_EMAIL] = checkpoint[key]
            else:
                tasks_to_do.append((idx, row.to_dict()))

        print(f"📋 {len(tasks_to_do)} lignes à traiter / {total} total\n")

        sem       = asyncio.Semaphore(NB_WORKERS)
        completed = 0

        coros = [
            process_row(idx, row, pages[i % NB_WORKERS], (i % NB_WORKERS) + 1, total, sem)
            for i, (idx, row) in enumerate(tasks_to_do)
        ]

        for coro in asyncio.as_completed(coros):
            idx_done, email = await coro
            df.at[idx_done, COL_EMAIL] = email
            checkpoint[str(idx_done)]  = email
            completed += 1

            if completed % CHECKPOINT_EVERY == 0:
                with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                    json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                tmp = OUTPUT_FILE.replace(".xlsx", "_temp.xlsx")
                df.to_excel(tmp, index=False)
                nb_emails = sum(1 for v in checkpoint.values() if v)
                pct = nb_emails / max(len(checkpoint), 1) * 100
                print(f"\n💾 #{completed} sauvegardé — {nb_emails} emails trouvés ({pct:.0f}%) → {tmp}\n")

        for pg in pages:
            try:
                await pg.close()
            except Exception:
                pass
        if not via_cdp:
            await browser.close()

    # Sauvegarde finale
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    df.to_excel(OUTPUT_FILE, index=False)

    nb_emails = df[COL_EMAIL].apply(
        lambda x: bool(str(x).strip()) and str(x).strip().lower() not in ("nan", "")
    ).sum()

    print("\n" + "=" * 65)
    print("  ✅ TERMINÉ")
    print(f"  📧 Emails trouvés : {nb_emails} / {total}  ({nb_emails/total*100:.0f}%)")
    print(f"  💾 Fichier        : {OUTPUT_FILE}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main_async())