# -*- coding: utf-8 -*-
"""
scraper_lesfurets_v2.py
========================
Script complet LesFurets mutuelle sante
- Remplit le formulaire etape par etape (vrais selecteurs)
- Atteint la page de resultats #pps/RESULT
- Extrait toutes les offres (assureur, prix, garanties, CTA)
- Export JSON + affichage console

Usage : python scraper_lesfurets_v2.py
"""

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ============================================================
#  CONFIG — modifiez ces valeurs selon votre profil de test
# ============================================================
PROFIL = {
    # Situation : "vous" | "vous_enfants" | "vous_conjoint" | "vous_conjoint_enfants"
    "situation":    "vous",
    "naissance":    "15/03/1958",   # format JJ/MM/AAAA -> age ~66 ans
    "code_postal":  "75012",
    "regime":       "salarie",      # salarie | tns | retraite
}

URL_DEPART = "https://www.lesfurets.com/mutuelle-sante/sante-devis#pps/RESULT"
URL_RESULTATS = "https://www.lesfurets.com/mutuelle-sante/sante-devis#pps/RESULT"
OUTPUT_JSON = "lesfurets_offres.json"
SCREENSHOTS_DIR = Path("lf_screens")

# ============================================================
#  UTILITAIRES
# ============================================================
def log(msg, niv="INFO"):
    sym = {"INFO": "·", "OK": "OK", "WARN": "!!", "ERR": "XX", "STEP": ">>"}
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{sym.get(niv,'·')}] {msg}")

async def pause(mi=0.8, ma=2.0):
    await asyncio.sleep(random.uniform(mi, ma))

async def shot(page, nom):
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    await page.screenshot(path=str(SCREENSHOTS_DIR / f"{nom}.png"), full_page=True)
    log(f"Screenshot: {nom}.png", "OK")

async def accepter_cookies(page):
    selectors = [
        "#didomi-notice-agree-button",
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter tout')",
        "button:has-text('Accepter')",
        ".didomi-continue-without-agreeing",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                log("Cookies acceptes", "OK")
                await pause(1, 2)
                return True
        except Exception:
            pass
    log("Pas de bandeau cookies detecte", "WARN")
    return False

# ============================================================
#  EXTRACTION DES OFFRES (depuis HTML confirme)
# ============================================================
async def extraire_offres(page):
    """
    Extrait toutes les offres depuis la page de resultats.
    Selecteurs confirmes via le HTML fourni par l'utilisateur.
    """
    log("Extraction des offres...", "STEP")

    # Attendre que les offres soient chargees
    try:
        await page.wait_for_selector('[data-testid="SanteOffersList"]', timeout=15000)
        log("Liste des offres detectee", "OK")
    except Exception:
        log("SanteOffersList non trouvee - tentative alternative", "WARN")
        try:
            await page.wait_for_selector('.DesktopOffer', timeout=10000)
        except Exception:
            log("Aucune offre trouvee", "ERR")
            return []

    offres = await page.evaluate("""
        () => {
            var result = [];
            var cards = document.querySelectorAll('.DesktopOffer');

            for (var i = 0; i < cards.length; i++) {
                var card = cards[i];
                var offre = {};

                // ID de l'offre depuis data-testid
                var tid = card.getAttribute('data-testid') || '';
                offre['id'] = tid.replace('offer-', '');

                // Nom de l'assureur depuis le alt de l'image logo
                var img = card.querySelector('.Logo img');
                if (img) {
                    var alt = img.getAttribute('alt') || '';
                    offre['formule'] = alt.replace('Formule ', '');
                    offre['logo_url'] = img.getAttribute('src') || '';
                }

                // Prix mensuel
                var prixEl = card.querySelector('.SantePrice-montant strong');
                if (prixEl) {
                    offre['prix_mois'] = prixEl.innerText.trim().replace(/[^0-9]/g, '') + ' EUR/mois';
                }

                // Budget annuel
                var budgetEl = card.querySelector('.SantePrice-infos');
                if (budgetEl) {
                    offre['budget_annuel'] = budgetEl.innerText.trim();
                }

                // Promo
                var promoEl = card.closest('.Box') ? card.closest('.Box').querySelector('.CardTag') : null;
                if (!promoEl) {
                    var parent = card.parentElement;
                    if (parent) promoEl = parent.querySelector('.CardTag');
                }
                offre['promo'] = promoEl ? promoEl.innerText.trim() : null;

                // Contrat responsable
                var crEl = card.querySelector('.TagContratResponsable');
                offre['contrat_responsable'] = crEl ? true : false;

                // Label excellence
                var labelEl = card.querySelector('.TagLabelDistinction');
                offre['label'] = labelEl ? labelEl.innerText.trim() : null;

                // Note / avis
                var ratingEl = card.querySelector('.Rating strong');
                var avisEl = card.querySelector('.Rating span');
                offre['note'] = ratingEl ? ratingEl.innerText.trim() : null;
                offre['avis'] = avisEl ? avisEl.innerText.trim().replace(/\s+/g, ' ') : null;

                // Garanties avec niveau (nombre de barres actives sur 4)
                var garanties = {};
                var niveaux = card.querySelectorAll('.NiveauGarantie');
                for (var j = 0; j < niveaux.length; j++) {
                    var labelNiv = niveaux[j].querySelector('.LabelNiveau');
                    var barres = niveaux[j].querySelectorAll('.Graduation.active');
                    if (labelNiv) {
                        garanties[labelNiv.innerText.trim()] = barres.length + '/4';
                    }
                }
                offre['garanties'] = garanties;

                // Boutons CTA disponibles
                var ctas = [];
                var btns = card.querySelectorAll('button.PpsButton');
                for (var k = 0; k < btns.length; k++) {
                    var txt = btns[k].innerText ? btns[k].innerText.trim() : '';
                    var dtid = btns[k].getAttribute('data-testid') || '';
                    if (txt) ctas.push({label: txt, testid: dtid});
                }
                offre['ctas'] = ctas;

                // Note rappel (texte PhonePressure)
                var ppEl = card.querySelector('.PhonePressure');
                offre['note_rappel'] = ppEl ? ppEl.innerText.trim() : null;

                result.push(offre);
            }
            return result;
        }
    """)

    # Extraire aussi les filtres disponibles (Mini/Moyen/Fort/Maxi)
    filtres = await page.evaluate("""
        () => {
            var cats = ['Soins courants', 'Hospitalisation', 'Dentaire', 'Optique'];
            var result = {};
            var headers = document.querySelectorAll('h3, .filter-title, [class*="FilterHeader"]');
            return cats;
        }
    """)

    log(f"{len(offres)} offres extraites", "OK")
    return offres


# ============================================================
#  PARCOURS FORMULAIRE LESFURETS (confirme par tests manuels)
# ============================================================
async def remplir_formulaire(page):
    """
    Reproduit exactement le parcours manuel confirme.
    Sélecteurs confirmes : data-testid="DEM_CIBLE_ASSURANCE_vous" etc.
    """
    journal = []

    # ── ETAPE 1 : Situation familiale ─────────────────────────
    log("Etape 1 - Situation familiale", "STEP")
    await shot(page, "01_avant_situation")

    # Sélecteur exact confirme via HTML fourni
    sel_situation = f'[data-testid="DEM_CIBLE_ASSURANCE_{PROFIL["situation"]}"]'

    # Essai 1: clic direct sur le span radio
    clique = False
    try:
        el = page.locator(sel_situation).first
        await el.wait_for(state="visible", timeout=8000)
        await el.click()
        clique = True
        log(f"Situation '{PROFIL['situation']}' cliquee (direct)", "OK")
        journal.append({"etape": "situation", "valeur": PROFIL["situation"], "methode": "testid_direct"})
    except Exception as e:
        log(f"Echec direct: {e}", "WARN")

    # Essai 2: clic sur le label parent si le radio est hidden
    if not clique:
        try:
            # Le radio input est cache, on clique le label .MuiFormControlLabel-root
            label = page.locator(f'label:has([data-testid="{PROFIL["situation"]}"])').first
            if not await label.is_visible(timeout=3000):
                # Clic sur le conteneur .optionHasIcon
                label = page.locator(f'.optionHasIcon:has([data-testid="{PROFIL["situation"]}"])').first
            await label.click()
            clique = True
            log(f"Situation cliquee via label parent", "OK")
            journal.append({"etape": "situation", "valeur": PROFIL["situation"], "methode": "label_parent"})
        except Exception as e:
            log(f"Echec label parent: {e}", "WARN")

    # Essai 3: clic via JavaScript sur l'input radio directement
    if not clique:
        try:
            await page.evaluate(f"""
                () => {{
                    var el = document.querySelector('[data-testid="{PROFIL["situation"]}"]');
                    if (el) {{
                        var input = el.querySelector('input[type=radio]');
                        if (!input) input = el.closest('label') ? el.closest('label').querySelector('input') : null;
                        if (!input && el.tagName === 'INPUT') input = el;
                        if (input) {{
                            input.checked = true;
                            input.dispatchEvent(new Event('change', {{bubbles: true}}));
                            input.dispatchEvent(new Event('click', {{bubbles: true}}));
                        }}
                        el.click();
                    }}
                }}
            """)
            clique = True
            log("Situation cliquee via JS", "OK")
            journal.append({"etape": "situation", "valeur": PROFIL["situation"], "methode": "js_force"})
        except Exception as e:
            log(f"Echec JS: {e}", "ERR")

    await pause(1, 2)
    await shot(page, "02_apres_situation")

    # ── ETAPE 2 : Clic "Comparer en 2 minutes" ─────────────────
    log("Etape 2 - Bouton Comparer", "STEP")
    bouton_comparer = [
        "button:has-text('Comparer en 2 minutes')",
        "button:has-text('Comparer')",
        ".btn-primary:has-text('Comparer')",
    ]
    for sel in bouton_comparer:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=4000):
                await btn.click()
                log("Bouton Comparer clique", "OK")
                journal.append({"etape": "comparer", "statut": "ok"})
                await pause(2, 4)
                break
        except Exception:
            continue

    await shot(page, "03_apres_comparer")

    # ── ETAPE 3 : Formulaire - champs variables selon profil ────
    log("Etape 3 - Champs formulaire", "STEP")

    # Lire les champs disponibles (noms des inputs MUI)
    inputs_disponibles = await page.evaluate("""
        () => {
            var els = document.querySelectorAll('input:not([type=radio]):not([type=checkbox]), select');
            var r = [];
            for (var i = 0; i < els.length; i++) {
                var el = els[i];
                if (el.offsetParent !== null) {
                    r.push({
                        name: el.name || '',
                        id: el.id || '',
                        type: el.type || el.tagName,
                        placeholder: el.placeholder || '',
                        visible: true
                    });
                }
            }
            return r;
        }
    """)
    log(f"Inputs visibles: {inputs_disponibles}", "INFO")
    journal.append({"etape": "lecture_inputs", "inputs": inputs_disponibles})

    # Date de naissance - essai avec plusieurs noms MUI possibles
    naissance_selectors = [
        'input[name="DEM_DATE_NAISSANCE_ASSURE_0"]',
        'input[name*="NAISSANCE"]',
        'input[name*="naissance"]',
        'input[placeholder*="JJ/MM/AAAA"]',
        'input[placeholder*="naissance"]',
        'input[placeholder*="01/01"]',
        'input[type="text"]:visible',
    ]
    for sel in naissance_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.triple_click()
                await el.fill(PROFIL["naissance"])
                await page.keyboard.press("Tab")
                log(f"Date naissance saisie: {PROFIL['naissance']}", "OK")
                journal.append({"etape": "naissance", "selecteur": sel, "statut": "ok"})
                await pause(0.5, 1)
                break
        except Exception:
            continue

    # Code postal
    postal_selectors = [
        'input[name="DEM_CODE_POSTAL"]',
        'input[name*="POSTAL"]',
        'input[name*="postal"]',
        'input[placeholder*="Code postal"]',
        'input[placeholder*="75"]',
    ]
    for sel in postal_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.triple_click()
                await el.fill(PROFIL["code_postal"])
                await page.keyboard.press("Tab")
                log(f"Code postal saisi: {PROFIL['code_postal']}", "OK")
                journal.append({"etape": "code_postal", "selecteur": sel, "statut": "ok"})
                await pause(0.5, 1)
                break
        except Exception:
            continue

    await shot(page, "04_champs_remplis")

    # ── ETAPE 4 : Bouton suivant / valider ─────────────────────
    log("Etape 4 - Validation et suite des etapes", "STEP")

    # Sur LesFurets le formulaire a plusieurs etapes - on clique "Suivant" jusqu'aux resultats
    for tentative in range(6):
        # Verifier si on est sur la page resultats
        url_actuelle = page.url
        if "RESULT" in url_actuelle or "pps" in url_actuelle:
            log("Page de resultats atteinte !", "OK")
            journal.append({"etape": "resultats_atteints", "url": url_actuelle})
            break

        # Chercher et cliquer le bouton suivant
        btns_suivant = [
            "button:has-text('Suivant')",
            "button:has-text('Valider')",
            "button:has-text('Continuer')",
            "button:has-text('Voir les offres')",
            "button:has-text('Comparer')",
            "button[type='submit']",
            ".btn-next",
            ".next-step",
        ]

        clique_suivant = False
        for sel in btns_suivant:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    txt = await btn.inner_text()
                    await btn.click()
                    log(f"Bouton suivant clique: '{txt}'", "OK")
                    journal.append({"etape": f"suivant_{tentative}", "bouton": txt})
                    clique_suivant = True
                    await pause(2, 3)
                    break
            except Exception:
                continue

        if not clique_suivant:
            log(f"Aucun bouton suivant trouve (tentative {tentative+1})", "WARN")
            await shot(page, f"0{5+tentative}_etape_bloquee_{tentative}")
            break

        await shot(page, f"0{5+tentative}_apres_suivant_{tentative}")

    return journal


# ============================================================
#  POINT D'ENTREE PRINCIPAL
# ============================================================
async def main():
    log("=" * 60)
    log("  SCRAPER LESFURETS v2 - EXTRACTION COMPLETE DES OFFRES")
    log("=" * 60)

    resultat = {
        "site": "LesFurets",
        "url": URL_DEPART,
        "profil": PROFIL,
        "timestamp": datetime.now().isoformat(),
        "statut": "echec",
        "journal": [],
        "offres": [],
        "nb_offres": 0,
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,          # False = voir le navigateur, True = invisible
            slow_mo=200,             # Ralentit pour mieux voir les actions
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
            timezone_id="Europe/Paris",
        )

        page = await context.new_page()

        try:
            # Chargement page accueil
            log(f"Chargement: {URL_DEPART}")
            await page.goto(URL_DEPART, wait_until="networkidle", timeout=30000)
            await pause(2, 3)
            await shot(page, "00_page_accueil")

            # Cookies
            await accepter_cookies(page)

            # Remplissage formulaire
            resultat["journal"] = await remplir_formulaire(page)

            # Attendre la page de resultats (max 20s)
            log("Attente page resultats...", "STEP")
            try:
                await page.wait_for_url("**/RESULT**", timeout=20000)
                log(f"URL resultats: {page.url}", "OK")
            except Exception:
                # Essai navigation directe si le formulaire est bloque
                log("Navigation directe vers les resultats...", "WARN")
                await page.goto(URL_RESULTATS, wait_until="networkidle", timeout=20000)
                await pause(3, 5)

            await shot(page, "10_page_resultats")

            # Extraction des offres
            resultat["offres"] = await extraire_offres(page)
            resultat["nb_offres"] = len(resultat["offres"])
            resultat["url_resultats"] = page.url
            resultat["statut"] = "succes"

            await shot(page, "11_extraction_terminee")

        except PWTimeout:
            resultat["statut"] = "timeout"
            log("Timeout", "ERR")
        except Exception as e:
            resultat["statut"] = f"erreur: {str(e)[:100]}"
            log(f"Erreur: {e}", "ERR")
        finally:
            await context.close()
            await browser.close()

    # Sauvegarde JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=2)
    log(f"JSON sauvegarde: {OUTPUT_JSON}", "OK")

    # Affichage console des offres
    print()
    print("=" * 65)
    print(f"  {resultat['nb_offres']} OFFRES EXTRAITES — LesFurets Mutuelle Sante")
    print("=" * 65)
    print(f"{'#':<3} {'Formule':<35} {'Prix/mois':<12} {'Note':<8} {'Promo'}")
    print("-" * 65)
    for i, o in enumerate(resultat["offres"], 1):
        formule = o.get("formule", "?")[:34]
        prix = o.get("prix_mois", "?")
        note = o.get("note") or "-"
        promo = "OUI" if o.get("promo") else "-"
        print(f"{i:<3} {formule:<35} {prix:<12} {note:<8} {promo}")

    print()
    print("Garanties par offre :")
    print("-" * 65)
    for i, o in enumerate(resultat["offres"], 1):
        g = o.get("garanties", {})
        g_str = " | ".join([f"{k}: {v}" for k, v in g.items()])
        print(f"{i}. {o.get('formule','?')[:30]}")
        print(f"   Garanties: {g_str}")
        ctas = [c["label"] for c in o.get("ctas", [])]
        print(f"   CTA: {' / '.join(ctas)}")
        print()

    print(f"Statut final: {resultat['statut']}")
    print(f"Screenshots: {len(list(SCREENSHOTS_DIR.glob('*.png')))} captures")
    print(f"JSON: {OUTPUT_JSON}")


if __name__ == "__main__":
    asyncio.run(main())