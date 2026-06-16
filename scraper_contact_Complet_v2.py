import sys
if sys.platform == "win32":
    # ProactorEventLoop = seul event loop Windows qui supporte
    # asyncio.create_subprocess_exec (nécessaire pour Playwright)
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
from playwright.async_api import async_playwright, Page

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

INPUT_FILE       = "Familian.xlsx"
OUTPUT_FILE      = "Familian_Contacts_v3.xlsx"
CHECKPOINT_FILE  = "checkpoint_v3.json"

CDP_URL          = "http://127.0.0.1:9222"
NB_WORKERS       = 2          # Onglets en parallèle
PAUSE_MIN        = 2.5        # secondes min entre requêtes Google
PAUSE_MAX        = 5.0        # secondes max
PAUSE_CAPTCHA    = 60         # pause si CAPTCHA détecté (s)
CHECKPOINT_EVERY = 10         # sauvegarde toutes les N lignes
TIMEOUT_MS       = 25_000     # timeout Playwright (ms)

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
# REGEX
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
PHONE_FR_RE = re.compile(
    r"(?:(?:\+33|0033)[\s.\-]?[1-9](?:[\s.\-]?\d{2}){4}"
    r"|0[1-9](?:[\s.\-]?\d{2}){4})"
)
PHONE_INTL_RE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s.\-]?)(?:\(?\d{1,4}\)?[\s.\-]?)?(?:\d[\s.\-]?){6,11}\d"
)

EMAIL_BLACKLIST = {
    "google.com","google.fr","example.com","example.fr","gmail.com",
    "yahoo.com","hotmail.com","sentry.io","w3.org","schema.org",
    "facebook.com","twitter.com","instagram.com","linkedin.com",
    "cloudflare.com","amazonaws.com","wixpress.com","wordpress.org",
    "jquery.com","bootstrapcdn.com","gstatic.com","googleapis.com",
}
# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────────────────

def extract_domain(url: str) -> str:
    if not url or str(url).strip().lower() in ("nan", "", "none"):
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        domain = urlparse(url).netloc or urlparse(url).path
        domain = re.sub(r"^www\.", "", domain).split(":")[0].strip("/")
        return domain
    except Exception:
        return ""


def clean_phone(raw: str) -> str:
    cleaned = re.sub(r"[^\d\+\s.\-()]", "", (raw or "")).strip()
    digits  = re.sub(r"\D", "", cleaned)
    return cleaned if 7 <= len(digits) <= 15 else ""


def is_valid_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].lower()
    return domain not in EMAIL_BLACKLIST and "." in domain and len(domain) > 3


def extract_emails(text: str) -> list:
    seen, out = set(), []
    for e in EMAIL_RE.findall(text or ""):
        e = e.lower()
        if is_valid_email(e) and e not in seen:
            seen.add(e)
            out.append(e)
    return out


def extract_phones(text: str) -> list:
    seen, out = set(), []
    for pat in [PHONE_FR_RE, PHONE_INTL_RE]:
        for m in pat.finditer(text or ""):
            p = clean_phone(m.group(0))
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def best_email(emails: list, domain: str) -> str:
    if not emails:
        return ""
    for e in emails:
        if domain.lower() in e.lower():
            return e
    for prefix in ("contact", "info", "hello", "reservation", "accueil", "bonjour"):
        for e in emails:
            if e.startswith(prefix):
                return e
    return emails[0]


def best_phone(phones: list) -> str:
    if not phones:
        return ""
    for p in phones:
        if p.startswith("+"):
            return p
    return phones[0]


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

# ─────────────────────────────────────────────────────────────────────────────
# CHROME CDP
# ─────────────────────────────────────────────────────────────────────────────

def find_chrome() -> str:
    for p in CHROME_PATHS:
        if p and Path(p).exists():
            return p
    return ""


def cdp_available() -> bool:
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2)
        return True
    except Exception:
        return False


def launch_chrome_sync():
    """Lance Chrome en mode debug (appel synchrone, avant asyncio)."""
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
    print("   En attente que Chrome soit prêt", end="", flush=True)
    for _ in range(20):
        if cdp_available():
            print(" ✅")
            return
        print(".", end="", flush=True)
        time.sleep(1)
    print(" ⚠️  port 9222 toujours injoignable")

# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE — collecte du texte de résultats
# ─────────────────────────────────────────────────────────────────────────────

_cookies_done = False

async def accept_cookies(page: Page):
    global _cookies_done
    if _cookies_done:
        return
    for sel in [
        "button:has-text('Tout accepter')",
        "button:has-text('Accept all')",
        "#L2AGLb",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await asyncio.sleep(1)
                _cookies_done = True
                print("   🍪 Cookies acceptés")
                return
        except Exception:
            pass
    _cookies_done = True


async def is_captcha(page: Page) -> bool:
    try:
        if "sorry" in page.url or "captcha" in page.url.lower():
            return True
        return await page.locator("form#captcha-form, iframe[src*='recaptcha']").count() > 0
    except Exception:
        return False


async def google_text(page: Page, query: str, wid: int) -> str:
    """Recherche Google → retourne tout le texte utile."""
    url = "https://www.google.fr/search?q=" + urllib.parse.quote(query) + "&hl=fr&gl=fr&num=10"

    for attempt in range(3):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            await accept_cookies(page)
            await asyncio.sleep(random.uniform(1.0, 2.0))

            if await is_captcha(page):
                w = PAUSE_CAPTCHA + random.randint(0, 20)
                print(f"   ⚠️  [W{wid}] CAPTCHA ! Pause {w}s…")
                await asyncio.sleep(w)
                await page.goto("https://www.google.fr",
                                wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                await asyncio.sleep(random.uniform(4, 8))
                continue

            parts = []
            # Bloc IA
            for sel in [".n6owBd",".IZ6rdc",".hgKElc",".yDYNvb",
                        ".T286Pc","div[jsname='yEVEwb']",
                        ".kp-blk .LGOjhe",".Z0LcW",".ayRjaf",
                        "[data-attrid='wa:/description']"]:
                try:
                    for el in await page.locator(sel).all():
                        t = (await el.inner_text(timeout=400)).strip()
                        if t:
                            parts.append(t)
                except Exception:
                    pass
            # Snippets
            for sel in [".BNeawe",".IsZvec",".VwiC3b",".lEBKkf",
                        ".MUxGbd",".yXK7lf",".r0bn4c","h3","cite",".tjvcx"]:
                try:
                    for el in await page.locator(sel).all():
                        t = (await el.inner_text(timeout=400)).strip()
                        if t and len(t) > 4:
                            parts.append(t)
                except Exception:
                    pass
            # Liens mailto / tel
            for el in await page.locator("a[href^='mailto:']").all():
                try:
                    h = (await el.get_attribute("href", timeout=400)) or ""
                    parts.append(h.replace("mailto:", "").split("?")[0])
                except Exception:
                    pass
            for el in await page.locator("a[href^='tel:']").all():
                try:
                    h = (await el.get_attribute("href", timeout=400)) or ""
                    parts.append(h.replace("tel:", ""))
                except Exception:
                    pass

            return "\n".join(parts)

        except Exception as e:
            print(f"   ⚠️  [W{wid}] tentative {attempt+1}/3 : {e}")
            await asyncio.sleep(random.uniform(3, 7))

    return ""

# ─────────────────────────────────────────────────────────────────────────────
# SCRAPING DIRECT DU SITE (fallback)
# ─────────────────────────────────────────────────────────────────────────────

CONTACT_PATHS = [
    "/contact", "/nous-contacter", "/contactez-nous", "/contact-us",
    "/a-propos", "/about", "/informations",
]

async def scrape_site(page: Page, domain: str) -> dict:
    base   = f"https://{domain}"
    result = {"email": "", "phone": ""}

    async def _fetch(url: str) -> dict:
        out = {"email": "", "phone": ""}
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            await asyncio.sleep(random.uniform(0.8, 1.5))

            # Liens mailto (les plus fiables)
            for el in await page.locator("a[href^='mailto:']").all():
                try:
                    h = (await el.get_attribute("href", timeout=400)) or ""
                    e = h.replace("mailto:", "").split("?")[0].strip().lower()
                    if is_valid_email(e):
                        out["email"] = e
                        break
                except Exception:
                    pass

            # Liens tel:
            for el in await page.locator("a[href^='tel:']").all():
                try:
                    h = (await el.get_attribute("href", timeout=400)) or ""
                    p = clean_phone(h.replace("tel:", "").strip())
                    if p:
                        out["phone"] = p
                        break
                except Exception:
                    pass

            # Fallback texte complet
            if not out["email"] or not out["phone"]:
                try:
                    text = await page.locator("body").inner_text(timeout=3000)
                    if not out["email"]:
                        out["email"] = best_email(extract_emails(text), domain)
                    if not out["phone"]:
                        out["phone"] = best_phone(extract_phones(text))
                except Exception:
                    pass
        except Exception:
            pass
        return out

    r = await _fetch(base)
    result["email"] = r["email"]
    result["phone"] = r["phone"]

    if not result["email"] or not result["phone"]:
        for path in CONTACT_PATHS:
            if result["email"] and result["phone"]:
                break
            r2 = await _fetch(base + path)
            if r2["email"] and not result["email"]:
                result["email"] = r2["email"]
            if r2["phone"] and not result["phone"]:
                result["phone"] = r2["phone"]
            await asyncio.sleep(0.5)

    return result

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
        site_web = cellval(row.get("Site web", ""))
        societe  = cellval(row.get("Societe", "")) or cellval(row.get("Nom", ""))
        domain   = extract_domain(site_web)

        print(f"\n[{idx+1}/{total}] W{wid} ▶ {societe[:45]}")
        print(f"   🌐 {domain or '(aucun domaine)'}")

        if not domain:
            return idx, {"email": "", "telephone": ""}

        email = cellval(row.get("Email", ""))
        phone = cellval(row.get("Telephone", ""))

        if email and phone:
            print(f"   ⏭  Déjà complet")
            return idx, {"email": email, "telephone": phone}

        # ── Couche 1 : Google "<domain> email" ──────────────────────────────
        if not email:
            txt    = await google_text(page, f"{domain} email", wid)
            email  = best_email(extract_emails(txt), domain)
            print(f"   📧 Google  : {'✔  ' + email if email else '✖  non trouvé'}")
            await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

        # ── Couche 2 : Google "<domain> tel" ────────────────────────────────
        if not phone:
            txt    = await google_text(page, f"{domain} tel", wid)
            phone  = best_phone(extract_phones(txt))
            print(f"   📞 Google  : {'✔  ' + phone if phone else '✖  non trouvé'}")
            await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

        # ── Couche 3 : Scraping direct du site (fallback) ───────────────────
        if not email or not phone:
            print(f"   🔍 Scraping direct : {domain}")
            sc = await scrape_site(page, domain)
            if sc["email"] and not email:
                email = sc["email"]
                print(f"   📧 Site    : ✔  {email}")
            if sc["phone"] and not phone:
                phone = sc["phone"]
                print(f"   📞 Site    : ✔  {phone}")

        ok = "✅" if (email and phone) else ("⚠️" if (email or phone) else "❌")
        print(f"   {ok} email={email or '—'} | tel={phone or '—'}")

        return idx, {"email": email, "telephone": phone}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ASYNC
# ─────────────────────────────────────────────────────────────────────────────

async def main_async():
    print("\n" + "=" * 65)
    print("  SCRAPER CONTACT v3 — asyncio + Playwright")
    print(f"  {NB_WORKERS} onglets parallèles — Anti-CAPTCHA CDP")
    print("=" * 65)

    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {INPUT_FILE}")
        sys.exit(1)

    # ── Excel ────────────────────────────────────────────────────────────────
    df = pd.read_excel(INPUT_FILE)
    print(f"\n✅ {len(df)} lignes — colonnes : {list(df.columns)}")

    rename = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl in ("nom","titre","name","societe","société"):   rename[c] = "Societe"
        elif cl in ("site web","site_web","website","url site"): rename[c] = "Site web"
        elif cl in ("telephone","téléphone","tel","tél","phone"): rename[c] = "Telephone"
        elif cl == "email":                                     rename[c] = "Email"
    df = df.rename(columns=rename)

    for col in ["Email", "Telephone"]:
        if col not in df.columns:
            df[col] = pd.Series([""] * len(df), dtype="object")
        else:
            df[col] = df[col].astype("object")

    # ── Checkpoint ───────────────────────────────────────────────────────────
    checkpoint = {}
    if Path(CHECKPOINT_FILE).exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            print(f"✅ Checkpoint : {len(checkpoint)} lignes déjà traitées")
        except Exception:
            pass

    total = len(df)

    # ── Connexion Chrome ─────────────────────────────────────────────────────
    # IMPORTANT : launch_chrome_sync() est appelé AVANT async_playwright()
    # pour éviter les conflits de subprocess sous Windows.
    if not cdp_available():
        launch_chrome_sync()

    async with async_playwright() as p:

        if cdp_available():
            print(f"✅ Connexion vrai Chrome : {CDP_URL}")
            browser  = await p.chromium.connect_over_cdp(CDP_URL)
            via_cdp  = True
        else:
            print("⚠️  CDP indisponible → Chromium headless de secours")
            browser  = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox",
                      "--disable-blink-features=AutomationControlled",
                      "--window-size=1400,900"],
            )
            via_cdp = False

        ANTI_DETECT = """
            Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
            Object.defineProperty(navigator,'plugins',{get:()=>{
                const a=[1,2,3,4,5];a.item=i=>a[i];return a;}});
            Object.defineProperty(navigator,'languages',{get:()=>['fr-FR','fr','en']});
            window.chrome={runtime:{},loadTimes:()=>{},csi:()=>{}};
        """

        # Contexte
        if via_cdp and browser.contexts:
            ctx = browser.contexts[0]
        else:
            ctx = await browser.new_context(
                locale="fr-FR",
                viewport={"width": 1400, "height": 900},
            )

        # Créer NB_WORKERS onglets
        pages = []
        for _ in range(NB_WORKERS):
            pg = await ctx.new_page()
            await pg.add_init_script(ANTI_DETECT)
            pages.append(pg)

        print(f"🪟  {NB_WORKERS} onglets ouverts\n")

        # ── Répartition des tâches ───────────────────────────────────────────
        tasks_to_do = []
        for idx, row in df.iterrows():
            key = str(idx)
            if key in checkpoint:
                res = checkpoint[key]
                df.at[idx, "Email"]     = res.get("email", "")
                df.at[idx, "Telephone"] = res.get("telephone", "")
            else:
                tasks_to_do.append((idx, row.to_dict()))

        print(f"📋 {len(tasks_to_do)} lignes à traiter / {total} total\n")

        sem       = asyncio.Semaphore(NB_WORKERS)
        completed = 0

        # Chaque tâche reçoit un onglet dédié en round-robin
        coros = [
            process_row(idx, row, pages[i % NB_WORKERS], (i % NB_WORKERS) + 1, total, sem)
            for i, (idx, row) in enumerate(tasks_to_do)
        ]

        for coro in asyncio.as_completed(coros):
            idx_done, res = await coro
            df.at[idx_done, "Email"]     = res["email"]
            df.at[idx_done, "Telephone"] = res["telephone"]
            checkpoint[str(idx_done)]    = res
            completed += 1

            if completed % CHECKPOINT_EVERY == 0:
                with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                    json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                tmp = OUTPUT_FILE.replace(".xlsx", "_temp.xlsx")
                df.to_excel(tmp, index=False)
                ne = sum(1 for r in checkpoint.values() if r.get("email"))
                np_ = sum(1 for r in checkpoint.values() if r.get("telephone"))
                print(f"\n💾 #{completed} sauvegardé — email:{ne} | tel:{np_} → {tmp}\n")

        # Fermeture propre
        for pg in pages:
            try:
                await pg.close()
            except Exception:
                pass
        if not via_cdp:
            await browser.close()

    # ── Sauvegarde finale ─────────────────────────────────────────────────────
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    df.to_excel(OUTPUT_FILE, index=False)

    def count_col(col):
        return df[col].apply(
            lambda x: bool(str(x).strip()) and str(x).strip().lower() not in ("nan","")
        ).sum() if col in df.columns else 0

    print("\n" + "=" * 65)
    print("  ✅ TERMINÉ")
    print(f"  📧 Emails      : {count_col('Email')} / {total}")
    print(f"  📞 Téléphones  : {count_col('Telephone')} / {total}")
    print(f"  💾 Fichier     : {OUTPUT_FILE}")
    print("=" * 65)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(main_async())