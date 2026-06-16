import pandas as pd
import time
import random
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────────
# CONFIGURATION — MODIFIEZ CES CHEMINS
# ─────────────────────────────────────────────
INPUT_FILE  = "Familian.xlsx"
OUTPUT_FILE = "Familia_Contacts.xlsx"
HEADLESS    = False
PAUSE_MIN   = 1.0
PAUSE_MAX   = 2.0
# ─────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]


# ═════════════════════════════════════════════════════════════════════════════
# EXTRACTION DU DOMAINE
# ═════════════════════════════════════════════════════════════════════════════

def extract_domain(url: str) -> str:
    """
    Extrait le nom de domaine brut depuis une URL.
    Ex: "https://www.montclair-hostel.com/EN/" → "montclair-hostel.com"
    Ex: "montclair-hostel.com" → "montclair-hostel.com"
    """
    if not url or str(url).strip().lower() in ("nan", ""):
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        # Supprimer le "www."
        domain = re.sub(r"^www\.", "", domain)
        # Supprimer le port si présent
        domain = domain.split(":")[0]
        # Nettoyer les slashs résiduels
        domain = domain.strip("/")
        return domain
    except Exception:
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# PATTERNS D'EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

# Emails : pattern standard
EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE
)

# Téléphones : formats internationaux et français
PHONE_PATTERN = re.compile(
    r"(?:"
    r"\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?[\s.\-]?\d{1,4}[\s.\-]?\d{1,4}[\s.\-]?\d{0,4}"  # +33 1 46 06 46 07
    r"|(?:\(?\d{2,4}\)?[\s.\-]?){4,6}"                                                   # 01 46 06 46 07
    r")",
    re.IGNORECASE
)

# Domaines à ignorer dans les emails (faux positifs courants)
EMAIL_BLACKLIST_DOMAINS = {
    "google.com", "google.fr", "example.com", "example.fr",
    "gmail.com", "yahoo.com", "hotmail.com",
    "sentry.io", "w3.org", "schema.org",
    "facebook.com", "twitter.com", "instagram.com", "linkedin.com",
    "cloudflare.com", "amazonaws.com", "cdn.com",
}

# Numéros à ignorer (trop courts ou génériques)
PHONE_BLACKLIST = {
    "0000000000", "1234567890", "0123456789",
}


def clean_phone(raw: str) -> str:
    """
    Nettoie et formate un numéro de téléphone.
    Retourne une chaîne vide si invalide.
    """
    if not raw:
        return ""
    # Garder uniquement chiffres, +, espace, point, tiret, parenthèses
    cleaned = re.sub(r"[^\d\+\s.\-()]", "", raw).strip()
    # Compter les chiffres
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) < 7 or len(digits) > 15:
        return ""
    if digits in PHONE_BLACKLIST:
        return ""
    return cleaned


def is_valid_email(email: str) -> bool:
    """Vérifie qu'un email n'est pas un faux positif."""
    if not email:
        return False
    domain = email.split("@")[-1].lower()
    if domain in EMAIL_BLACKLIST_DOMAINS:
        return False
    # Doit avoir au moins un point dans le domaine
    if "." not in domain:
        return False
    return True


def extract_emails_from_text(text: str) -> list:
    """Extrait tous les emails valides d'un texte."""
    found = EMAIL_PATTERN.findall(text)
    return [e for e in found if is_valid_email(e)]


def extract_phones_from_text(text: str) -> list:
    """Extrait tous les téléphones valides d'un texte."""
    found = PHONE_PATTERN.findall(text)
    result = []
    for raw in found:
        cleaned = clean_phone(raw)
        if cleaned:
            result.append(cleaned)
    return result


def prioritize_email(emails: list, domain: str) -> str:
    """
    Choisit le meilleur email parmi une liste.
    Priorité : email du même domaine > autres.
    """
    if not emails:
        return ""
    domain_base = domain.lower().split(":")[0]
    # Email du même domaine
    for e in emails:
        if domain_base in e.lower():
            return e
    # Sinon le premier
    return emails[0]


def prioritize_phone(phones: list) -> str:
    """
    Choisit le meilleur numéro : préfère format international (+XX).
    """
    if not phones:
        return ""
    for p in phones:
        if p.startswith("+"):
            return p
    return phones[0]


# ═════════════════════════════════════════════════════════════════════════════
# PLAYWRIGHT — UTILITAIRES
# ═════════════════════════════════════════════════════════════════════════════

def human_delay(min_s=0.5, max_s=1.5):
    time.sleep(random.uniform(min_s, max_s))


def accept_cookies(page):
    for sel in [
        "button:has-text('Tout accepter')",
        "button:has-text('Accept all')",
        "button:has-text('J\\'accepte')",
        "#L2AGLb",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                human_delay(0.8, 1.5)
                print("   🍪 Cookies acceptés")
                return True
        except Exception:
            continue
    return False


def type_in_searchbar(page, query: str):
    for sel in ["textarea#APjFqb", "textarea[name='q']", "input[name='q']"]:
        try:
            loc = page.locator(sel)
            loc.wait_for(state="visible", timeout=6000)
            loc.click()
            human_delay(0.2, 0.4)
            loc.fill(query)
            human_delay(0.3, 0.6)
            loc.press("Enter")
            return
        except Exception:
            continue
    raise Exception("Barre de recherche introuvable")


def collect_all_visible_text(page) -> str:
    """
    Collecte tout le texte visible de la page Google
    (bloc IA + snippets + titres + méta-descriptions).
    """
    selectors = [
        # Bloc IA / AI Overview
        ".n6owBd.awi2gc",
        ".IZ6rdc",
        ".hgKElc",
        ".yDYNvb.lEBKkf",
        "div[jsname='yEVEwb']",
        ".T286Pc",
        # Snippets classiques
        ".BNeawe.s3v9rd.AP7Wnd",
        ".BNeawe.iBp4i.AP7Wnd",
        ".IsZvec",
        ".VwiC3b",
        ".lEBKkf",
        ".MUxGbd",
        ".yXK7lf",
        # Titres
        "h3",
        # Résumés Knowledge Panel
        "[data-attrid='wa:/description']",
        ".kp-blk .LGOjhe",
        ".Z0LcW",
        ".ayRjaf",
        ".aCOpRe",
        # Blocs génériques
        ".r0bn4c.rQMQod",
        ".X5LH0c",
        # Liens (contiennent parfois l'email en clair)
        "cite",
        ".tjvcx",
    ]
    texts = []
    for sel in selectors:
        try:
            for el in page.locator(sel).all():
                try:
                    t = el.inner_text(timeout=800).strip()
                    if t and len(t) > 3:
                        texts.append(t)
                except Exception:
                    pass
        except Exception:
            pass

    # Aussi récupérer les liens <a href="mailto:...">
    try:
        for el in page.locator("a[href^='mailto:']").all():
            try:
                href = el.get_attribute("href", timeout=800) or ""
                email = href.replace("mailto:", "").split("?")[0].strip()
                if email:
                    texts.append(email)
            except Exception:
                pass
    except Exception:
        pass

    # Aussi récupérer les liens <a href="tel:...">
    try:
        for el in page.locator("a[href^='tel:']").all():
            try:
                href = el.get_attribute("href", timeout=800) or ""
                phone = href.replace("tel:", "").strip()
                if phone:
                    texts.append(phone)
            except Exception:
                pass
    except Exception:
        pass

    seen, unique = set(), []
    for t in texts:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return "\n".join(unique)


# ═════════════════════════════════════════════════════════════════════════════
# RECHERCHE EMAIL
# ═════════════════════════════════════════════════════════════════════════════

def search_email(page, domain: str, cookies_accepted: list) -> str:
    """
    Recherche Google : "<domain> email"
    Retourne l'email trouvé ou chaîne vide.
    """
    query = f"{domain} email"
    print(f"   📧 Recherche email : {query}")

    try:
        page.goto("https://www.google.fr", wait_until="domcontentloaded", timeout=20000)

        if not cookies_accepted[0]:
            if accept_cookies(page):
                cookies_accepted[0] = True

        type_in_searchbar(page, query)
        page.wait_for_selector("#search, #rso, .g, .tF2Cxc", timeout=12000)
        human_delay(1.0, 1.8)

        text = collect_all_visible_text(page)
        emails = extract_emails_from_text(text)
        best = prioritize_email(emails, domain)

        if best:
            print(f"   ✔ Email trouvé : {best}")
        else:
            print("   ✖ Email non trouvé")

        return best

    except Exception as e:
        print(f"   ⚠️  Erreur email: {e}")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# RECHERCHE TÉLÉPHONE
# ═════════════════════════════════════════════════════════════════════════════

def search_phone(page, domain: str, cookies_accepted: list) -> str:
    """
    Recherche Google : "<domain> tel"
    Retourne le numéro trouvé ou chaîne vide.
    """
    query = f"{domain} tel"
    print(f"   📞 Recherche tél  : {query}")

    try:
        page.goto("https://www.google.fr", wait_until="domcontentloaded", timeout=20000)

        if not cookies_accepted[0]:
            if accept_cookies(page):
                cookies_accepted[0] = True

        type_in_searchbar(page, query)
        page.wait_for_selector("#search, #rso, .g, .tF2Cxc", timeout=12000)
        human_delay(1.0, 1.8)

        text = collect_all_visible_text(page)
        phones = extract_phones_from_text(text)
        best = prioritize_phone(phones)

        if best:
            print(f"   ✔ Téléphone trouvé : {best}")
        else:
            print("   ✖ Téléphone non trouvé")

        return best

    except Exception as e:
        print(f"   ⚠️  Erreur téléphone: {e}")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  SCRAPER CONTACT — Email & Téléphone  (v5)")
    print("=" * 60)

    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable: {INPUT_FILE}")
        print(f"   Chemin absolu: {Path(INPUT_FILE).absolute()}")
        sys.exit(1)

    df = pd.read_excel(INPUT_FILE)
    print(f"\n✅ {len(df)} lignes chargées — Colonnes: {list(df.columns)}")

    # Création des colonnes si absentes
    for col in ["Email", "Telephone"]:
        if col not in df.columns:
            df[col] = ""

    results = []
    cookies_done = [False]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--lang=fr-FR,fr",
                "--start-maximized",
            ]
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver',  {get: () => undefined});
            Object.defineProperty(navigator, 'plugins',    {get: () => {const a=[1,2,3,4,5]; a.item=i=>a[i]; return a;}});
            Object.defineProperty(navigator, 'languages',  {get: () => ['fr-FR','fr','en-US','en']});
            window.chrome = {runtime:{}, loadTimes:()=>{}, csi:()=>{}};
            const _pq = window.navigator.permissions.query;
            window.navigator.permissions.query = p =>
                p.name==='notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : _pq(p);
        """)

        page  = context.new_page()
        total = len(df)

        for idx, row in df.iterrows():
            societe  = str(row.get("Societe", "")).strip()
            site_web = str(row.get("Site web", "")).strip()  # ← colonne site web

            print(f"\n[{idx+1}/{total}] {societe}")

            # ── Extraire le domaine ──────────────────────────────────────────
            domain = extract_domain(site_web)
            if not domain:
                print("   ⏭ Pas de site web — ligne ignorée")
                results.append({"email": "", "telephone": ""})
                continue

            print(f"   🌐 Domaine : {domain}")

            # ── Vérifier si déjà rempli ─────────────────────────────────────
            existing_email = str(row.get("Email", "")).strip()
            existing_phone = str(row.get("Telephone", "")).strip()

            skip_email = existing_email and existing_email.lower() not in ("nan", "")
            skip_phone = existing_phone and existing_phone.lower() not in ("nan", "")

            if skip_email and skip_phone:
                print("   ⏭ Email et téléphone déjà remplis")
                results.append({"email": existing_email, "telephone": existing_phone})
                continue

            email     = existing_email if skip_email else ""
            telephone = existing_phone if skip_phone else ""

            # ── Recherche Email ──────────────────────────────────────────────
            if not skip_email:
                email = search_email(page, domain, cookies_done)
                human_delay(PAUSE_MIN, PAUSE_MAX)

            # ── Recherche Téléphone ──────────────────────────────────────────
            if not skip_phone:
                telephone = search_phone(page, domain, cookies_done)
                if idx < total - 1:
                    human_delay(PAUSE_MIN, PAUSE_MAX)

            results.append({"email": email, "telephone": telephone})

            # ── Sauvegarde intermédiaire tous les 10 ────────────────────────
            if (idx + 1) % 10 == 0:
                df_tmp = df.copy()
                n = len(results)
                df_tmp.loc[:n-1, "Email"]     = [r["email"]     for r in results]
                df_tmp.loc[:n-1, "Telephone"] = [r["telephone"] for r in results]
                tmp_path = OUTPUT_FILE.replace(".xlsx", "_temp.xlsx")
                df_tmp.to_excel(tmp_path, index=False)
                print(f"   💾 Sauvegarde intermédiaire → {tmp_path}")

        browser.close()

    # ── Écriture finale ──────────────────────────────────────────────────────
    n = len(results)
    df.loc[:n-1, "Email"]     = [r["email"]     for r in results]
    df.loc[:n-1, "Telephone"] = [r["telephone"] for r in results]
    df.to_excel(OUTPUT_FILE, index=False)

    nb_email = sum(1 for r in results if r["email"])
    nb_phone = sum(1 for r in results if r["telephone"])

    print("\n" + "=" * 60)
    print(f"  ✅ TERMINÉ")
    print(f"  📧 Emails trouvés     : {nb_email} / {n}")
    print(f"  📞 Téléphones trouvés : {nb_phone} / {n}")
    print(f"  💾 Fichier            : {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()