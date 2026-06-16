#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║     SCRAPER LINKEDIN URL — Résolution URLs obfusquées (v2)              ║
║                                                                          ║
║  ✅ Injection cookies LinkedIn — pas besoin d'être connecté dans Chrome ║
║                                                                          ║
║  ÉTAPE 1 — Lancer Chrome debug (lancer_chrome.bat)                      ║
║  ÉTAPE 2 — python scraper_linkedin_url_v2.py                            ║
║                                                                          ║
║  Avant : https://www.linkedin.com/in/ACwAACeZAXEBPl6SLT4...            ║
║  Après : https://www.linkedin.com/in/anthony-esteve-3a959b166/          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import re
import random
import time
import urllib.request
import sys
import json
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
INPUT_FILE   = "Leads Serre dg Res_resolved_temp.xlsx"
OUTPUT_FILE  = "Leads Serre dg Res_resolved.xlsx"
CDP_URL      = "http://127.0.0.1:9222"

COL_LINKEDIN = "linkedin_url"       # colonne source (URLs obfusquées)
COL_RESOLVED = "linkedin_url_real"  # colonne résultat (vraies URLs)

MAX_WORKERS  = 2      # 2 onglets max en parallèle (ne pas dépasser)
SAVE_EVERY   = 5      # sauvegarde intermédiaire toutes les N lignes
PAUSE_MIN    = 2.5    # délai entre requêtes (secondes)
PAUSE_MAX    = 5.0
# ─────────────────────────────────────────────

# ── Cookies LinkedIn (session exportée) ──────────────────────────────────────
# Ces cookies permettent de contourner l'authwall LinkedIn
LINKEDIN_COOKIES = [
    {"name": "lms_ads",           "value": "AQGzOPCmolCstwAAAZ46OnTmvyb4p76P-5PRBAUJ4253Ue6v55VMODU7dNGZ6RvB6cSx3tC3InZV6XWYzcxF0JlT5LZV5OnZ", "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "AMP_5919ff8c0c",    "value": "JTdCJTIyZGV2aWNlSWQlMjIlM0ElMjIyZGIwYmJkMy00OWZjLTQyYTItYmIwYS1lYTdmYjBmZmMxOGMlMjIlMkMlMjJzZXNzaW9uSWQlMjIlM0ExNzcxNDA2OTQzMDY0JTJDJTIyb3B0T3V0JTIyJTNBZmFsc2UlMkMlMjJsYXN0RXZlbnRUaW1lJTIyJTNBMTc3MTQwNjk0MzI1MyUyQyUyMmxhc3RFdmVudElkJTIyJTNBMSU3RA==", "domain": ".linkedin.com", "path": "/", "secure": False, "httpOnly": False, "sameSite": "Lax"},
    {"name": "bcookie",           "value": '"v=2&f53a5eb9-b230-45ec-8c8e-9440f05386a9"', "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "li_at",             "value": "AQEDAT5JROYAzZLPAAABnknCQGYAAAGebc7EZk0AuZiVNANEl1TOGDdRpZAE2rsg-rL5j3aiQsDap6CRO5jvoyjLlJRcwFfGPw7bGSFdbRO36udLD678Z-z1QQMA14WDMrIHKFAuXv62nJmh3AXmazjC", "domain": ".www.linkedin.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
    {"name": "JSESSIONID",        "value": '"ajax:0370149689736612121"', "domain": ".www.linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "bscookie",          "value": '"v=1&20251203111325cea47735-ef44-48b9-8593-9171db41b87fAQGBI4H3OMYA8PY_p1q4yFhikOCoLsFk"', "domain": ".www.linkedin.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
    {"name": "li_rm",             "value": "AQHSG1AfsqPB2QAAAZrj6sdGhV4hh1qnBdw4zPQLqwRCYQYNhUHmiTwJa5oDjfwF_GWIqq7jsHGMyRn7N_MYZ-KdmXNUaoWnHe6CPWNwmLsEl0tzYwKqEc-t", "domain": ".www.linkedin.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
    {"name": "liap",              "value": "true", "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "lms_analytics",     "value": "AQGzOPCmolCstwAAAZ46OnTmvyb4p76P-5PRBAUJ4253Ue6v55VMODU7dNGZ6RvB6cSx3tC3InZV6XWYzcxF0JlT5LZV5OnZ", "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "lidc",              "value": '"b=VB58:s=V:r=V:a=V:p=V:g=3601:u=225:x=1:i=1779351714:t=1779431477:v=2:sig=AQHvirrqtzYooZSglEZYyKKH-dqIurOa"', "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "li_sugr",           "value": "5d4b6545-4fe7-4075-9a6a-929d0561c979", "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "lang",              "value": "v=2&lang=fr-fr", "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "AnalyticsSyncHistory", "value": "AQK376_-eZT3RQAAAZ46OnIQFL97rYxL9KzMrYfc6Xm_s4bzuWxF6jf8zCc4ND7cCAf9bw3694PlT1As4jE3Tg", "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "UserMatchHistory",  "value": "AQKJvrle9Icl8gAAAZ46OnIQAgx0xkJT_tU0X923XPplKqt4iEJf2wG7cX9Xkeh_uJe9odzSqamvJg", "domain": ".linkedin.com", "path": "/", "secure": True, "httpOnly": False, "sameSite": "None"},
    {"name": "li_ep_auth_context","value": "AHVhcHA9c2FsZXNOYXZpZ2F0b3IsYWlkPTI4MTY4MDQwMixpaWQ9NTM2OTczNDU3LHBpZD0yODMwMTg5MDEsZXhwPTE3NzM5ODc0ODkyMTcsY3VyPXRydWUsaWQ9MTU3MzAxMjA4NixjaWQ9MjAyMTkyNzY4OQENLgIC0NvvVR7B7IhH8+EAj2A4yA==", "domain": ".www.linkedin.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
    {"name": "g_state",           "value": '{"i_l":0}', "domain": "www.linkedin.com", "path": "/", "secure": False, "httpOnly": False, "sameSite": "Lax"},
]

# ── Regex ─────────────────────────────────────────────────────────────────────
REAL_URL_REGEX = re.compile(
    r"linkedin\.com/in/([a-zA-Z0-9][a-zA-Z0-9\-]+(?:-[a-zA-Z0-9]+)*/?)"
)

def is_obfuscated(url: str) -> bool:
    if not url or str(url).lower() in ("nan", ""):
        return False
    return bool(re.search(r"linkedin\.com/in/ACw", str(url)))

def is_real_url(url: str) -> bool:
    if not url or str(url).lower() in ("nan", ""):
        return False
    if is_obfuscated(url):
        return False
    return bool(REAL_URL_REGEX.search(str(url)))


# ══════════════════════════════════════════════════════════════════════════════
# CONNEXION CDP
# ══════════════════════════════════════════════════════════════════════════════

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
    """Se connecte au Chrome réel via CDP + injecte les cookies LinkedIn."""
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)

    # Créer un NOUVEAU contexte isolé avec les cookies injectés
    # (ne pas réutiliser browser.contexts[0] qui pourrait ne pas être connecté)
    context = await browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )

    # ── Injection des cookies de session LinkedIn ─────────────────────────────
    await context.add_cookies(LINKEDIN_COOKIES)
    print(f"✅ Connecté à Chrome {browser.version}")
    print(f"🍪 {len(LINKEDIN_COOKIES)} cookies LinkedIn injectés")

    return browser, context


# ══════════════════════════════════════════════════════════════════════════════
# VÉRIFICATION SESSION LINKEDIN
# ══════════════════════════════════════════════════════════════════════════════

async def check_session(context) -> bool:
    """
    Ouvre un onglet de test pour vérifier que les cookies fonctionnent
    et qu'on est bien connecté à LinkedIn.
    """
    page = await context.new_page()
    try:
        await page.goto("https://www.linkedin.com/feed/",
                        wait_until="domcontentloaded", timeout=20_000)
        await asyncio.sleep(2)
        url = page.url
        if "authwall" in url or "login" in url or "checkpoint" in url:
            print("❌ Session LinkedIn invalide — les cookies sont expirés ou incorrects.")
            print("   → Exporte à nouveau les cookies depuis ton navigateur connecté.")
            return False
        title = await page.title()
        print(f"✅ Session LinkedIn valide ! Page : {title[:60]}")
        return True
    except Exception as e:
        print(f"⚠️  Erreur vérification session : {e}")
        return False
    finally:
        await page.close()


# ══════════════════════════════════════════════════════════════════════════════
# RÉSOLUTION URL LINKEDIN
# ══════════════════════════════════════════════════════════════════════════════

async def resolve_linkedin_url(page, obfuscated_url: str) -> str:
    """
    Navigue vers l'URL obfusquée et récupère l'URL finale résolue.
    LinkedIn redirige vers le vrai slug du profil si on est connecté.
    """
    print(f"   🔗 {obfuscated_url[:70]}...")

    try:
        await page.goto(
            obfuscated_url,
            wait_until="domcontentloaded",
            timeout=20_000
        )
        await asyncio.sleep(random.uniform(1.5, 2.5))

        final_url = page.url
        print(f"   📍 URL finale : {final_url[:80]}")

        # ── Méthode 1 : URL après redirection ────────────────────────────────
        if is_real_url(final_url):
            clean = final_url.split("?")[0].split("#")[0].rstrip("/") + "/"
            print(f"   ✔ Résolu (redirect) : {clean}")
            return clean

        # ── Authwall / checkpoint ─────────────────────────────────────────────
        if "authwall" in final_url or "login" in final_url or "checkpoint" in final_url:
            print("   ⚠️  Authwall — tentative de ré-injection cookies...")
            # Re-injecter les cookies et réessayer une fois
            await page.context.add_cookies(LINKEDIN_COOKIES)
            await page.goto(obfuscated_url,
                            wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            final_url = page.url
            if is_real_url(final_url):
                clean = final_url.split("?")[0].rstrip("/") + "/"
                print(f"   ✔ Résolu (retry) : {clean}")
                return clean
            print("   ❌ Authwall persistant")
            return "AUTHWALL"

        # ── Méthode 2 : canonical link ───────────────────────────────────────
        try:
            canonical = await page.get_attribute("link[rel='canonical']", "href")
            if canonical and is_real_url(canonical):
                clean = canonical.split("?")[0].rstrip("/") + "/"
                print(f"   ✔ Canonical : {clean}")
                return clean
        except Exception:
            pass

        # ── Méthode 3 : og:url meta tag ──────────────────────────────────────
        try:
            og_url = await page.get_attribute("meta[property='og:url']", "content")
            if og_url and is_real_url(og_url):
                clean = og_url.split("?")[0].rstrip("/") + "/"
                print(f"   ✔ og:url : {clean}")
                return clean
        except Exception:
            pass

        # ── Méthode 4 : regex dans le HTML ───────────────────────────────────
        try:
            content = await page.content()
            matches = REAL_URL_REGEX.findall(content)
            for slug in matches:
                candidate = f"https://www.linkedin.com/in/{slug.rstrip('/')}/"
                if not is_obfuscated(candidate):
                    print(f"   ✔ HTML match : {candidate}")
                    return candidate
        except Exception:
            pass

        # ── Profil introuvable ────────────────────────────────────────────────
        if "unavailable" in final_url:
            print("   ⚠️  Profil introuvable (supprimé ou privé)")
            return "INTROUVABLE"

        print(f"   ⚠️  Non résolu — URL finale : {final_url[:80]}")
        return ""

    except PWTimeout:
        print("   ⚠️  Timeout page")
        return ""
    except Exception as e:
        print(f"   ⚠️  Erreur : {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# WORKER CONCURRENT avec reconnexion automatique
# ══════════════════════════════════════════════════════════════════════════════

async def worker(
    sem: asyncio.Semaphore,
    playwright,
    browser_ctx: list,
    idx: int,
    total: int,
    nom: str,
    obfuscated_url: str,
    results: list,
    lock: asyncio.Lock,
) -> None:
    async with sem:
        page = None
        try:
            context = browser_ctx[1]
            page = await context.new_page()
        except Exception as e:
            print(f"\n   🔄 Contexte fermé ({e.__class__.__name__}), reconnexion...")
            try:
                browser, context = await connect_chrome(playwright)
                async with lock:
                    browser_ctx[0] = browser
                    browser_ctx[1] = context
                page = await context.new_page()
            except Exception as e2:
                print(f"   ❌ Reconnexion impossible : {e2}")
                async with lock:
                    results[idx] = ""
                return

        try:
            print(f"\n[{idx+1}/{total}] {nom}")
            resolved = await resolve_linkedin_url(page, obfuscated_url)
            await asyncio.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))
            async with lock:
                results[idx] = resolved
        except Exception as e:
            print(f"   ⚠️  Worker erreur : {e}")
            async with lock:
                results[idx] = ""
        finally:
            try:
                await page.close()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# SAUVEGARDE INTERMÉDIAIRE
# ══════════════════════════════════════════════════════════════════════════════

def save_intermediate(df: pd.DataFrame, results: list, output_file: str):
    tmp = df.copy()
    for i, v in enumerate(results):
        if i < len(tmp) and v:
            tmp.at[i, COL_RESOLVED] = v
    path = output_file.replace(".xlsx", "_1temp.xlsx")
    tmp.to_excel(path, index=False)
    nb = sum(1 for r in results if r and r not in ("AUTHWALL", "INTROUVABLE", ""))
    print(f"   💾 temp → {path}  ({nb} URLs résolues)")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 65)
    print("  SCRAPER LINKEDIN URL — Résolution obfusquées → vraies (v2)")
    print(f"  Workers : {MAX_WORKERS}  |  Pause : {PAUSE_MIN}–{PAUSE_MAX}s")
    print("=" * 65)

    # ── Chargement Excel ──────────────────────────────────────────────────────
    if not Path(INPUT_FILE).exists():
        print(f"\n❌ Fichier introuvable : {Path(INPUT_FILE).absolute()}")
        sys.exit(1)

    df = pd.read_excel(INPUT_FILE)
    print(f"\n✅ {len(df)} lignes chargées")
    print(f"   Colonnes : {list(df.columns)}\n")

    if COL_LINKEDIN not in df.columns:
        print(f"❌ Colonne manquante : '{COL_LINKEDIN}'")
        sys.exit(1)

    if COL_RESOLVED not in df.columns:
        df[COL_RESOLVED] = ""

    # ── Connexion Chrome ──────────────────────────────────────────────────────
    if not wait_for_chrome():
        print("\n❌ Chrome non disponible sur le port 9222.")
        print("   Lance lancer_chrome.bat d'abord !")
        sys.exit(1)

    t_start = time.time()

    async with async_playwright() as playwright:
        browser, context = await connect_chrome(playwright)
        browser_ctx = [browser, context]

        # ── Vérification session avant de commencer ───────────────────────────
        print("\n🔐 Vérification session LinkedIn...")
        session_ok = await check_session(context)
        if not session_ok:
            print("\n⚠️  Session invalide. Le script va quand même tenter.")
            print("   (Les cookies ont peut-être expiré — mets-les à jour)\n")
        print()

        total   = len(df)
        results = [""] * total
        sem     = asyncio.Semaphore(MAX_WORKERS)
        lock    = asyncio.Lock()

        # ── Pré-remplir les valeurs existantes ───────────────────────────────
        already_real = 0
        for i, row in df.iterrows():
            existing_resolved = str(row.get(COL_RESOLVED, "")).strip()
            if existing_resolved and existing_resolved.lower() not in ("nan", ""):
                results[i] = existing_resolved
                continue
            original = str(row.get(COL_LINKEDIN, "")).strip()
            if is_real_url(original):
                results[i] = original
                already_real += 1

        # ── Lignes à traiter ─────────────────────────────────────────────────
        rows_todo = []
        for i, row in df.iterrows():
            if results[i]:
                continue
            url = str(row.get(COL_LINKEDIN, "")).strip()
            nom = str(row.get("Nom", f"Ligne {i+1}")).strip()
            if is_obfuscated(url):
                rows_todo.append((i, nom, url))

        already_done = total - len(rows_todo) - already_real
        print(f"📊 Total : {total}")
        print(f"   Déjà résolues (colonne résultat) : {already_done}")
        print(f"   Déjà vraies URLs (source)        : {already_real}")
        print(f"   À résoudre (obfusquées)          : {len(rows_todo)}\n")

        if not rows_todo:
            print("✅ Tout est déjà traité !")
        else:
            for batch_start in range(0, len(rows_todo), SAVE_EVERY):
                batch = rows_todo[batch_start: batch_start + SAVE_EVERY]

                tasks = [
                    worker(sem, playwright, browser_ctx,
                           idx, total, nom, url,
                           results, lock)
                    for idx, nom, url in batch
                ]
                await asyncio.gather(*tasks)

                save_intermediate(df, results, OUTPUT_FILE)

                done    = batch_start + len(batch)
                elapsed = time.time() - t_start
                rate    = done / elapsed if elapsed > 0 else 0
                left    = len(rows_todo) - done
                eta     = int(left / rate) if rate > 0 else 0
                print(f"\n⏱️  {done}/{len(rows_todo)} traités | "
                      f"{rate:.2f}/s | ETA {eta//60}m{eta%60:02d}s\n")

    # ── Écriture finale ───────────────────────────────────────────────────────
    for i, v in enumerate(results):
        if i < len(df) and v and v not in ("AUTHWALL",):
            df.at[i, COL_RESOLVED] = v

    df.to_excel(OUTPUT_FILE, index=False)

    elapsed_total = int(time.time() - t_start)
    nb_ok    = sum(1 for r in results if r and r not in ("AUTHWALL", "INTROUVABLE", ""))
    nb_auth  = sum(1 for r in results if r == "AUTHWALL")
    nb_nf    = sum(1 for r in results if r == "INTROUVABLE")
    nb_empty = sum(1 for r in results if not r)

    print("\n" + "=" * 65)
    print(f"  ✅ TERMINÉ en {elapsed_total // 60}m{elapsed_total % 60:02d}s")
    print(f"  🔗 {nb_ok} URL(s) résolue(s) / {len(rows_todo)} traitée(s)")
    if nb_auth:  print(f"  🔒 {nb_auth} authwall (cookies expirés)")
    if nb_nf:    print(f"  ❓ {nb_nf} profil(s) introuvable(s)")
    if nb_empty: print(f"  ⬜ {nb_empty} non résolu(s) (timeout)")
    print(f"  💾 {OUTPUT_FILE}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())