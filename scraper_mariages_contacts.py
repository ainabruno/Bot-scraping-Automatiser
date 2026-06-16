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

INPUT_FILE       = "mariages_paris.xlsx"
OUTPUT_FILE      = "mariages_paris_contacts.xlsx"
CHECKPOINT_FILE  = "checkpoint_contacts.json"

CDP_URL          = "http://127.0.0.1:9222"
NB_WORKERS       = 2
PAUSE_MIN        = 2.5
PAUSE_MAX        = 5.0
PAUSE_CAPTCHA    = 60
CHECKPOINT_EVERY = 10
TIMEOUT_MS       = 25_000

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

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
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
    "mariages.net","lafiancee.fr","zankyou.fr",
}

# Sélecteurs pour extraire le photographe sur mariages.net
PHOTOGRAPHER_SELECTORS = [
    ".gallery-box-owner-name",
    ".vendor-name",
    ".pro-name",
    ".supplier-name",
    "a[href*='/photographe']",
    ".realWeddingHero__vendorName",
    ".app-vendor-name",
    "[class*='photographer']",
    "[class*='vendor'] a",
    "[class*='prestataire']",
]

# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────────────────────────────────────

def clean(text) -> str:
    return " ".join(str(text).split()).strip() if text else ""

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

def extract_address(text: str) -> str:
    """Extrait une adresse depuis un texte (numéro + rue + ville)."""
    patterns = [
        r"\d{1,4}[,\s]+(?:rue|avenue|av\.|boulevard|bd\.?|impasse|allée|place|chemin|voie|route)\s+[^\n,]{5,60}",
        r"(?:rue|avenue|av\.|boulevard|bd\.?|impasse|allée|place|chemin)\s+[^\n,]{5,60}",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return clean(m.group(0))
    return ""

def best_email(emails: list, domain: str = "") -> str:
    if not emails:
        return ""
    if domain:
        for e in emails:
            if domain.lower() in e.lower():
                return e
    for prefix in ("contact", "info", "hello", "bonjour", "accueil", "studio", "photo"):
        for e in emails:
            if e.startswith(prefix):
                return e
    return emails[0]

def best_phone(phones: list) -> str:
    if not phones:
        return ""
    for p in phones:
        if p.startswith("+33") or p.startswith("06") or p.startswith("07"):
            return p
    return phones[0]

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
# STEP 1 — Extraire le photographe depuis la page mariages.net
# ─────────────────────────────────────────────────────────────────────────────

async def get_photographer_from_page(page: Page, url: str) -> dict:
    """
    Ouvre la page du reportage mariages.net et récupère :
    - nom du photographe
    - lien vers sa page mariages.net
    - son site web s'il est visible
    """
    result = {"photographer_name": "", "photographer_url": "", "photographer_site": ""}
    if not url or "mariages.net" not in url:
        return result

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # Essaie chaque sélecteur pour trouver le photographe
        for sel in PHOTOGRAPHER_SELECTORS:
            try:
                els = await page.locator(sel).all()
                for el in els:
                    name = clean(await el.inner_text(timeout=500))
                    href = await el.get_attribute("href", timeout=500) or ""
                    if name and len(name) > 3 and not name.isdigit():
                        result["photographer_name"] = name
                        if href:
                            result["photographer_url"] = (
                                href if href.startswith("http")
                                else "https://www.mariages.net" + href
                            )
                        break
                if result["photographer_name"]:
                    break
            except Exception:
                pass

        # Cherche le site web du photographe directement sur la page
        try:
            for el in await page.locator("a[href*='site']:not([href*='mariages.net'])").all():
                href = await el.get_attribute("href", timeout=400) or ""
                if href.startswith("http") and "mariages.net" not in href:
                    result["photographer_site"] = href
                    break
        except Exception:
            pass

    except Exception as e:
        pass

    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Page prestataire sur mariages.net (si on a l'URL)
# ─────────────────────────────────────────────────────────────────────────────

async def get_contacts_from_mariages_profile(page: Page, profile_url: str) -> dict:
    """Visite la page profil du photographe sur mariages.net."""
    result = {"email": "", "phone": "", "address": "", "website": ""}
    if not profile_url:
        return result

    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        await asyncio.sleep(random.uniform(1.5, 2.5))

        text = ""
        try:
            text = await page.locator("body").inner_text(timeout=4000)
        except Exception:
            pass

        # Site web externe
        for el in await page.locator("a[href*='site'], a[href*='www.'], a.vendor-website").all():
            href = await el.get_attribute("href", timeout=400) or ""
            if href.startswith("http") and "mariages.net" not in href:
                result["website"] = href
                break

        # Liens mailto / tel
        for el in await page.locator("a[href^='mailto:']").all():
            h = (await el.get_attribute("href", timeout=400) or "").replace("mailto:", "").split("?")[0].strip()
            if is_valid_email(h):
                result["email"] = h
                break

        for el in await page.locator("a[href^='tel:']").all():
            h = (await el.get_attribute("href", timeout=400) or "").replace("tel:", "").strip()
            p = clean_phone(h)
            if p:
                result["phone"] = p
                break

        # Fallback texte
        if text:
            if not result["email"]:
                result["email"] = best_email(extract_emails(text))
            if not result["phone"]:
                result["phone"] = best_phone(extract_phones(text))
            if not result["address"]:
                result["address"] = extract_address(text)

    except Exception:
        pass

    return result

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Google search
# ─────────────────────────────────────────────────────────────────────────────

_cookies_done = False

async def accept_cookies(page: Page):
    global _cookies_done
    if _cookies_done:
        return
    for sel in ["button:has-text('Tout accepter')", "button:has-text('Accept all')", "#L2AGLb"]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await asyncio.sleep(1)
                _cookies_done = True
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

async def google_search(page: Page, query: str, wid: int) -> str:
    """Retourne le texte brut + URLs des résultats Google."""
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
                continue

            parts = []

            # Blocs de résultats + snippets
            for sel in [".BNeawe", ".IsZvec", ".VwiC3b", ".lEBKkf",
                        ".MUxGbd", ".yXK7lf", ".r0bn4c", "h3", "cite",
                        ".tjvcx", ".n6owBd", ".IZ6rdc", ".hgKElc",
                        ".Z0LcW", "[data-attrid='wa:/description']"]:
                try:
                    for el in await page.locator(sel).all():
                        t = (await el.inner_text(timeout=400)).strip()
                        if t and len(t) > 3:
                            parts.append(t)
                except Exception:
                    pass

            # URLs des résultats (pour trouver le site du photographe)
            for el in await page.locator("a[href^='http']:not([href*='google'])").all():
                try:
                    h = (await el.get_attribute("href", timeout=400)) or ""
                    if h and "mariages.net" not in h and len(h) > 10:
                        parts.append(h)
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

def extract_best_site_url(text: str, exclude_domains: list = None) -> str:
    """Trouve la meilleure URL de site web dans un texte Google."""
    exclude = set(exclude_domains or [])
    exclude.update(["google.com", "google.fr", "mariages.net", "facebook.com",
                    "instagram.com", "twitter.com", "linkedin.com", "youtube.com",
                    "lafiancee.fr", "zankyou.fr", "helloasso.com"])

    # Cherche des URLs http dans le texte
    urls = re.findall(r"https?://[^\s\n\"'<>]{8,}", text)
    for url in urls:
        domain = extract_domain(url)
        if domain and not any(ex in domain for ex in exclude):
            return url.split("?")[0].rstrip("/")
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Scraping direct du site du photographe
# ─────────────────────────────────────────────────────────────────────────────

CONTACT_PATHS = [
    "/contact", "/nous-contacter", "/contactez-nous", "/contact-us",
    "/a-propos", "/about", "/informations", "/coordonnees",
]

async def scrape_photographer_site(page: Page, site_url: str) -> dict:
    """Visite le site du photographe et extrait email, tel, adresse."""
    result = {"email": "", "phone": "", "address": ""}
    if not site_url:
        return result

    domain = extract_domain(site_url)

    async def _fetch(url: str) -> dict:
        out = {"email": "", "phone": "", "address": ""}
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            await asyncio.sleep(random.uniform(0.8, 1.5))

            # Liens mailto
            for el in await page.locator("a[href^='mailto:']").all():
                h = (await el.get_attribute("href", timeout=400) or "").replace("mailto:", "").split("?")[0].strip().lower()
                if is_valid_email(h):
                    out["email"] = h
                    break

            # Liens tel
            for el in await page.locator("a[href^='tel:']").all():
                h = (await el.get_attribute("href", timeout=400) or "").replace("tel:", "").strip()
                p = clean_phone(h)
                if p:
                    out["phone"] = p
                    break

            # Texte complet
            if not out["email"] or not out["phone"] or not out["address"]:
                try:
                    text = await page.locator("body").inner_text(timeout=3000)
                    if not out["email"]:
                        out["email"] = best_email(extract_emails(text), domain)
                    if not out["phone"]:
                        out["phone"] = best_phone(extract_phones(text))
                    if not out["address"]:
                        out["address"] = extract_address(text)
                except Exception:
                    pass
        except Exception:
            pass
        return out

    r = await _fetch(site_url)
    result.update({k: v for k, v in r.items() if v})

    # Visite la page /contact si manque encore des infos
    if not result["email"] or not result["phone"]:
        for path in CONTACT_PATHS:
            if result["email"] and result["phone"]:
                break
            r2 = await _fetch(f"https://{domain}{path}")
            if r2["email"] and not result["email"]:
                result["email"] = r2["email"]
            if r2["phone"] and not result["phone"]:
                result["phone"] = r2["phone"]
            if r2["address"] and not result["address"]:
                result["address"] = r2["address"]
            await asyncio.sleep(0.5)

    return result

# ─────────────────────────────────────────────────────────────────────────────
# TRAITEMENT D'UNE LIGNE — Pipeline complet
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
        noms    = cellval(row.get("Noms", "")) or cellval(row.get("noms", ""))
        ville   = cellval(row.get("Ville", "")) or cellval(row.get("ville", ""))
        url_rep = cellval(row.get("URL", ""))   or cellval(row.get("url", ""))

        # Valeurs déjà présentes
        email   = cellval(row.get("Email", ""))
        phone   = cellval(row.get("Telephone", ""))
        address = cellval(row.get("Adresse", ""))
        website = cellval(row.get("Site web", ""))

        print(f"\n[{idx+1}/{total}] W{wid} ▶ {noms[:40]} ({ville})")

        if email and phone and address and website:
            print(f"   ⏭  Déjà complet")
            return idx, {"email": email, "telephone": phone, "adresse": address, "site_web": website}

        photographer_name = cellval(row.get("photographe", "")) or cellval(row.get("Photographe", ""))
        photographer_site = website

        # ── ÉTAPE 1 : Ouvrir la page du reportage → nom photographe ─────────
        if not photographer_name and url_rep and "mariages.net" in url_rep:
            print(f"   🔍 Lecture page reportage…")
            pg_info = await get_photographer_from_page(page, url_rep)
            photographer_name = pg_info["photographer_name"]
            if not photographer_site:
                photographer_site = pg_info["photographer_site"]

            # Si on a l'URL du profil mariages.net → scraping direct
            if pg_info["photographer_url"] and not (email and phone):
                print(f"   👤 Profil mariages.net : {pg_info['photographer_url'][:60]}")
                contacts = await get_contacts_from_mariages_profile(page, pg_info["photographer_url"])
                if contacts["email"] and not email:
                    email = contacts["email"]
                if contacts["phone"] and not phone:
                    phone = contacts["phone"]
                if contacts["address"] and not address:
                    address = contacts["address"]
                if contacts["website"] and not photographer_site:
                    photographer_site = contacts["website"]
                await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

        if photographer_name:
            print(f"   📸 Photographe : {photographer_name}")

        # ── ÉTAPE 2 : Google "{photographe} {ville} photographe mariage" ────
        if photographer_name and not (email and phone and photographer_site):
            query = f'"{photographer_name}" {ville} photographe mariage contact'
            print(f"   🔎 Google : {query[:70]}")
            gtxt = await google_search(page, query, wid)
            await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

            if not email:
                email = best_email(extract_emails(gtxt))
                if email:
                    print(f"   📧 Google→ {email}")
            if not phone:
                phone = best_phone(extract_phones(gtxt))
                if phone:
                    print(f"   📞 Google→ {phone}")
            if not photographer_site:
                photographer_site = extract_best_site_url(gtxt)
                if photographer_site:
                    print(f"   🌐 Google→ {photographer_site}")

        # ── ÉTAPE 3 : Fallback Google avec noms+ville ────────────────────────
        if (not photographer_name or not (email or phone)) and noms:
            query2 = f'"{noms}" {ville} mariage photographe site'
            print(f"   🔎 Fallback Google : {query2[:70]}")
            gtxt2 = await google_search(page, query2, wid)
            await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

            if not email:
                email = best_email(extract_emails(gtxt2))
                if email:
                    print(f"   📧 Fallback→ {email}")
            if not phone:
                phone = best_phone(extract_phones(gtxt2))
                if phone:
                    print(f"   📞 Fallback→ {phone}")
            if not photographer_site:
                photographer_site = extract_best_site_url(gtxt2)
                if photographer_site:
                    print(f"   🌐 Fallback→ {photographer_site}")

        # ── ÉTAPE 4 : Scraping direct du site du photographe ────────────────
        if photographer_site and not (email and phone):
            print(f"   🌐 Scraping site : {photographer_site[:60]}")
            sc = await scrape_photographer_site(page, photographer_site)
            if sc["email"] and not email:
                email = sc["email"]
                print(f"   📧 Site→ {email}")
            if sc["phone"] and not phone:
                phone = sc["phone"]
                print(f"   📞 Site→ {phone}")
            if sc["address"] and not address:
                address = sc["address"]
                print(f"   📍 Site→ {address}")

        # ── Résumé ────────────────────────────────────────────────────────────
        nb = sum(bool(x) for x in [email, phone, address, photographer_site])
        icon = "✅" if nb == 4 else ("⚠️" if nb > 0 else "❌")
        print(f"   {icon} [{nb}/4] email={email or '—'} | tel={phone or '—'} | adresse={address or '—'}")

        return idx, {
            "email":         email,
            "telephone":     phone,
            "adresse":       address,
            "site_web":      photographer_site,
            "photographe":   photographer_name,
        }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ASYNC
# ─────────────────────────────────────────────────────────────────────────────

async def main_async():
    print("\n" + "=" * 65)
    print("  SCRAPER CONTACTS MARIAGES v4")
    print(f"  Stratégie : reportage → photographe → Google → site")
    print("=" * 65)

    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {INPUT_FILE}")
        sys.exit(1)

    df = pd.read_excel(INPUT_FILE)
    print(f"\n✅ {len(df)} lignes — colonnes : {list(df.columns)}")

    # Normalisation des colonnes
    rename = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl in ("noms", "nom", "name", "mariés"):        rename[c] = "Noms"
        elif cl in ("ville", "city", "localisation"):       rename[c] = "Ville"
        elif cl in ("url", "lien", "link"):                 rename[c] = "URL"
        elif cl in ("photographe", "photographer"):         rename[c] = "Photographe"
        elif cl in ("telephone","téléphone","tel","phone"): rename[c] = "Telephone"
        elif cl == "email":                                 rename[c] = "Email"
        elif cl in ("adresse","address"):                   rename[c] = "Adresse"
        elif cl in ("site web","site_web","website"):       rename[c] = "Site web"
    df = df.rename(columns=rename)

    for col in ["Email", "Telephone", "Adresse", "Site web", "Photographe"]:
        if col not in df.columns:
            df[col] = pd.Series([""] * len(df), dtype="object")
        else:
            df[col] = df[col].astype("object")

    # Checkpoint
    checkpoint = {}
    if Path(CHECKPOINT_FILE).exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            print(f"✅ Checkpoint : {len(checkpoint)} lignes déjà traitées")
        except Exception:
            pass

    total = len(df)

    # Chrome CDP
    if not cdp_available():
        launch_chrome_sync()

    async with async_playwright() as p:
        if cdp_available():
            print(f"✅ Connexion Chrome CDP : {CDP_URL}")
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

        ctx = browser.contexts[0] if (via_cdp and browser.contexts) else \
              await browser.new_context(locale="fr-FR", viewport={"width": 1400, "height": 900})

        pages = []
        for _ in range(NB_WORKERS):
            pg = await ctx.new_page()
            await pg.add_init_script(ANTI_DETECT)
            pages.append(pg)

        print(f"🪟  {NB_WORKERS} onglets ouverts\n")

        tasks_to_do = []
        for idx, row in df.iterrows():
            key = str(idx)
            if key in checkpoint:
                res = checkpoint[key]
                df.at[idx, "Email"]       = res.get("email", "")
                df.at[idx, "Telephone"]   = res.get("telephone", "")
                df.at[idx, "Adresse"]     = res.get("adresse", "")
                df.at[idx, "Site web"]    = res.get("site_web", "")
                df.at[idx, "Photographe"] = res.get("photographe", "")
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
            idx_done, res = await coro
            df.at[idx_done, "Email"]       = res["email"]
            df.at[idx_done, "Telephone"]   = res["telephone"]
            df.at[idx_done, "Adresse"]     = res["adresse"]
            df.at[idx_done, "Site web"]    = res["site_web"]
            df.at[idx_done, "Photographe"] = res["photographe"]
            checkpoint[str(idx_done)]      = res
            completed += 1

            if completed % CHECKPOINT_EVERY == 0:
                with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                    json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                tmp = OUTPUT_FILE.replace(".xlsx", "_temp.xlsx")
                df.to_excel(tmp, index=False)
                ne  = sum(1 for r in checkpoint.values() if r.get("email"))
                nph = sum(1 for r in checkpoint.values() if r.get("telephone"))
                print(f"\n💾 #{completed} sauvegardé — email:{ne} tel:{nph} → {tmp}\n")

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

    def count_col(col):
        return df[col].apply(
            lambda x: bool(str(x).strip()) and str(x).strip().lower() not in ("nan", "")
        ).sum() if col in df.columns else 0

    print("\n" + "=" * 65)
    print("  ✅ TERMINÉ")
    print(f"  📸 Photographes : {count_col('Photographe')} / {total}")
    print(f"  📧 Emails       : {count_col('Email')} / {total}")
    print(f"  📞 Téléphones   : {count_col('Telephone')} / {total}")
    print(f"  📍 Adresses     : {count_col('Adresse')} / {total}")
    print(f"  🌐 Sites web    : {count_col('Site web')} / {total}")
    print(f"  💾 Fichier      : {OUTPUT_FILE}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main_async())