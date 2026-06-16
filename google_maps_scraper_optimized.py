#!/usr/bin/env python3
"""
Script OPTIMISÉ d'extraction depuis Google Maps
Extrait: Téléphone + Type de site + Taille estimée (m²)
"""

import csv
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def clean_phone_number(phone_text):
    """Nettoie et formate le numéro de téléphone"""
    if not phone_text:
        return None
    return phone_text.strip()


def extract_surface_from_text(text):
    """
    Extrait la surface en m² depuis le texte
    Cherche des patterns comme "3500 m²", "3 500 m2", etc.
    """
    if not text:
        return None
    
    # Patterns pour détecter les surfaces
    patterns = [
        r'(\d[\d\s]*)\s*m[²2]',  # "3500 m²" ou "3 500 m2"
        r'(\d[\d\s]*)\s*mètres?\s*carrés?',  # "3500 mètres carrés"
        r'surface[:\s]+(\d[\d\s]*)\s*m',  # "Surface: 3500 m"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Extraire les chiffres et enlever les espaces
            surface_str = match.group(1).replace(' ', '').replace(',', '')
            try:
                surface = int(surface_str)
                if surface >= 100:  # Filtre minimal pour éviter faux positifs
                    return surface
            except:
                continue
    
    return None


def determine_type_site(societe, description, reviews_text, secteur):
    """
    Détermine le type de site basé sur les informations collectées
    
    Retourne un type de site descriptif selon le secteur
    """
    societe_lower = societe.lower()
    desc_lower = description.lower() if description else ""
    reviews_lower = reviews_text.lower() if reviews_text else ""
    
    combined_text = f"{societe_lower} {desc_lower} {reviews_lower}"
    
    # HÔTELLERIE
    if secteur == "Hôtellerie":
        # Détecter le type d'hôtel
        if any(word in combined_text for word in ['palace', '5 étoiles', 'five star', 'luxury', 'luxe']):
            return "Hôtel de luxe/Palace (surfaces étendues)"
        elif any(word in combined_text for word in ['resort', 'complexe', 'résidence', 'spa']):
            return "Complexe hôtelier multi-services"
        elif any(word in combined_text for word in ['groupe', 'chain', 'collection']):
            return "Groupe hôtelier multi-sites"
        elif re.search(r'(\d+)\s*(chambres?|rooms?)', combined_text):
            # Extraire le nombre de chambres
            match = re.search(r'(\d+)\s*(chambres?|rooms?)', combined_text)
            if match:
                nb_chambres = int(match.group(1))
                if nb_chambres >= 200:
                    return f"Hôtel grande capacité ({nb_chambres}+ chambres)"
                elif nb_chambres >= 100:
                    return f"Hôtel moyenne capacité ({nb_chambres} chambres)"
                else:
                    return f"Hôtel ({nb_chambres} chambres) - À vérifier"
        else:
            return "Hôtel - Type à préciser"
    
    # HÔPITAUX/CLINIQUES
    elif secteur in ["Hôpital/Clinique", "Hôpital", "Clinique"]:
        if any(word in combined_text for word in ['chu', 'centre hospitalier universitaire']):
            return "CHU (Centre Hospitalier Universitaire)"
        elif any(word in combined_text for word in ['chr', 'centre hospitalier régional']):
            return "CHR (Centre Hospitalier Régional)"
        elif 'ap-hp' in combined_text or 'aphp' in combined_text:
            return "AP-HP - Hôpital multi-sites"
        elif any(word in combined_text for word in ['groupe hospitalier', 'ght']):
            return "Groupe Hospitalier multi-sites"
        elif 'clinique' in combined_text:
            # Détecter le nombre de lits
            match = re.search(r'(\d+)\s*(lits?|beds?)', combined_text)
            if match:
                nb_lits = int(match.group(1))
                if nb_lits >= 150:
                    return f"Clinique grande capacité ({nb_lits}+ lits)"
                elif nb_lits >= 50:
                    return f"Clinique moyenne capacité ({nb_lits} lits)"
                else:
                    return f"Clinique ({nb_lits} lits) - À vérifier"
            else:
                return "Clinique - Capacité à vérifier"
        else:
            return "Établissement de santé - Type à préciser"
    
    # EHPAD
    elif secteur == "EHPAD":
        match = re.search(r'(\d+)\s*(résidents?|places?)', combined_text)
        if match:
            nb_residents = int(match.group(1))
            if nb_residents >= 100:
                return f"EHPAD grande capacité ({nb_residents}+ résidents)"
            elif nb_residents >= 60:
                return f"EHPAD moyenne capacité ({nb_residents} résidents)"
            else:
                return f"EHPAD ({nb_residents} résidents) - À vérifier"
        else:
            return "EHPAD - Capacité à vérifier"
    
    # Par défaut
    return "Type à préciser manuellement"


def estimate_surface_from_type(type_site, company_size):
    """
    Estime la surface en m² basée sur le type de site et la taille de l'entreprise
    Uniquement si >= 3000 m² (critère du cahier des charges)
    """
    
    # Extraction depuis le type de site si des chiffres sont présents
    if type_site:
        surface = extract_surface_from_text(type_site)
        if surface and surface >= 3000:
            return surface
    
    # Estimation basée sur les keywords
    type_lower = type_site.lower() if type_site else ""
    
    # Palaces et grands hôtels
    if any(word in type_lower for word in ['palace', 'luxe', 'luxury', 'grande capacité', '200+', '300+', '400+']):
        return 5000
    
    # Complexes
    if any(word in type_lower for word in ['complexe', 'resort', 'multi-sites', 'groupe']):
        return 8000
    
    # CHU/CHR
    if any(word in type_lower for word in ['chu', 'chr', 'universitaire', 'régional']):
        return 15000
    
    # AP-HP
    if 'ap-hp' in type_lower or 'aphp' in type_lower:
        return 20000
    
    # Hôpitaux/Cliniques grande capacité
    if '150+' in type_lower or '200+' in type_lower or '100+ lits' in type_lower:
        return 8000
    
    # Hôtels moyenne capacité
    if '100' in type_lower and 'chambres' in type_lower:
        return 3500
    
    # EHPAD grande capacité
    if 'ehpad' in type_lower and ('100+' in type_lower or 'grande' in type_lower):
        return 4000
    
    # Estimation par Company Size
    if company_size:
        size_str = str(company_size).lower()
        if '10001+' in size_str or '5001-10000' in size_str:
            return 10000
        elif '1001-5000' in size_str:
            return 5000
        elif '501-1000' in size_str:
            return 3500
    
    # Si pas assez d'infos ou < 3000 m²
    return None


def extract_info_from_google_maps(page, societe, ville, secteur, company_size, index, total):
    """
    VERSION COMPLÈTE: Extrait téléphone + description + type de site + taille
    """
    try:
        search_query = f"{societe}+{ville}".replace(" ", "+")
        
        print(f"[{index}/{total}] 🔍 {societe[:35]:35} | {ville[:20]:20}", end=" | ")
        
        # Attendre que le champ de recherche soit visible
        try:
            search_input = page.wait_for_selector('input#UGojuc', timeout=5000)
        except:
            print("⚠ Champ recherche introuvable")
            return {'phone': None, 'type_site': None, 'taille': None}
        
        # Effacer et remplir
        search_input.click()
        page.keyboard.press('Control+A')
        page.keyboard.press('Backspace')
        time.sleep(0.3)
        search_input.type(search_query, delay=30)
        time.sleep(0.5)
        search_input.press('Enter')
        
        # Attendre le chargement
        start_wait = time.time()
        try:
            page.wait_for_selector('div[role="main"]', timeout=6000)
            try:
                page.wait_for_selector('div.DKPXOb.OyjIsf', state='hidden', timeout=3000)
            except:
                pass
            time.sleep(2)
        except PlaywrightTimeout:
            elapsed = time.time() - start_wait
            print(f"⏱ Timeout | {elapsed:.1f}s")
            return {'phone': None, 'type_site': None, 'taille': None}
        
        # EXTRACTION DU TÉLÉPHONE (stratégies multiples)
        phone_number = None
        
        # Stratégie 1: Bouton téléphone
        try:
            phone_button = page.wait_for_selector('button[data-item-id*="phone:tel:"]', timeout=2000)
            if phone_button:
                phone_div = phone_button.query_selector('div.Io6YTe.fontBodyMedium')
                if phone_div:
                    phone_number = clean_phone_number(phone_div.inner_text())
                
                if not phone_number:
                    data_item = phone_button.get_attribute('data-item-id')
                    if data_item and 'phone:tel:' in data_item:
                        tel_match = re.search(r'phone:tel:(\+?\d+)', data_item)
                        if tel_match:
                            phone_number = clean_phone_number(tel_match.group(1))
        except:
            pass
        
        # Stratégie 2: aria-label
        if not phone_number:
            try:
                phone_elements = page.query_selector_all('button[aria-label*="téléphone"]')
                for elem in phone_elements:
                    aria_label = elem.get_attribute('aria-label')
                    if aria_label:
                        phone_match = re.search(r'(\+?\d[\d\s\.\-]+\d)', aria_label)
                        if phone_match:
                            phone_number = clean_phone_number(phone_match.group(1))
                            break
            except:
                pass
        
        # Stratégie 3: liens tel:
        if not phone_number:
            try:
                tel_links = page.query_selector_all('a[href^="tel:"]')
                for link in tel_links:
                    href = link.get_attribute('href')
                    if href:
                        phone_temp = href.replace('tel:', '').strip()
                        if len(re.sub(r'\D', '', phone_temp)) >= 9:
                            phone_number = clean_phone_number(phone_temp)
                            break
            except:
                pass
        
        # EXTRACTION DE LA DESCRIPTION ET INFOS COMPLÉMENTAIRES
        description = ""
        reviews_text = ""
        surface_m2 = None
        
        try:
            # Récupérer tout le texte du panneau principal
            panel = page.query_selector('div[role="main"]')
            if panel:
                full_text = panel.inner_text()
                
                # Chercher la surface directement dans le texte
                surface_m2 = extract_surface_from_text(full_text)
                
                # Extraire la description (souvent dans certains divs)
                try:
                    desc_elements = panel.query_selector_all('div.PYvSYb, div.WeS02d, div.fontBodyMedium')
                    for elem in desc_elements[:5]:  # Limiter aux 5 premiers
                        text = elem.inner_text()
                        if text and len(text) > 20:
                            description += " " + text
                except:
                    pass
                
                # Extraire des avis (pour infos supplémentaires)
                try:
                    review_elements = panel.query_selector_all('span.wiI7pd')
                    for elem in review_elements[:3]:  # Limiter aux 3 premiers avis
                        text = elem.inner_text()
                        if text:
                            reviews_text += " " + text
                except:
                    pass
        except:
            pass
        
        # DÉTERMINER LE TYPE DE SITE
        type_site = determine_type_site(societe, description, reviews_text, secteur)
        
        # ESTIMER LA TAILLE si pas trouvée directement
        if not surface_m2 or surface_m2 < 3000:
            surface_m2 = estimate_surface_from_type(type_site, company_size)
        
        # Formater la taille pour affichage
        taille_display = f"{surface_m2} m²" if surface_m2 and surface_m2 >= 3000 else None
        
        elapsed = time.time() - start_wait
        
        # Affichage du résultat
        phone_display = phone_number if phone_number else "Pas de tél"
        type_display = type_site[:30] if type_site else "Type?"
        taille_display_short = taille_display if taille_display else "< 3000m²"
        
        print(f"📞 {phone_display:15} | 🏢 {type_display:30} | 📏 {taille_display_short:12} | {elapsed:.1f}s")
        
        return {
            'phone': phone_number,
            'type_site': type_site,
            'taille': taille_display
        }
        
    except Exception as e:
        print(f"⚠ Erreur: {str(e)[:40]}")
        return {'phone': None, 'type_site': None, 'taille': None}


def scrape_google_maps_complete(input_file, output_file, headless=False):
    """
    VERSION COMPLÈTE avec extraction de tous les champs
    """
    start_time = time.time()
    
    print(f"📂 Lecture du fichier: {input_file}")
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames)
    
    # Détecter les colonnes
    column_mapping = {}
    
    # Société/Établissement
    for col in ['Société', 'Societe', 'Nom établissement', 'Company', 'companyName']:
        if col in fieldnames:
            column_mapping['Société'] = col
            break
    
    # Ville
    for col in ['Ville', 'ville', 'City']:
        if col in fieldnames:
            column_mapping['Ville'] = col
            break
    
    # Secteur
    for col in ['Secteur', 'secteur', 'Industry']:
        if col in fieldnames:
            column_mapping['Secteur'] = col
            break
    
    # Taille entreprise
    for col in ['Taille estimée', 'Company Size', 'Taille']:
        if col in fieldnames:
            column_mapping['CompanySize'] = col
            break
    
    if 'Société' not in column_mapping or 'Ville' not in column_mapping:
        print(f"❌ Colonnes introuvables")
        print(f"   Colonnes disponibles: {', '.join(fieldnames)}")
        return
    
    print(f"ℹ️  Colonne Société: '{column_mapping['Société']}'")
    print(f"ℹ️  Colonne Ville: '{column_mapping['Ville']}'")
    
    # Ajouter les colonnes manquantes
    if 'Téléphone standard' not in fieldnames:
        fieldnames.append('Téléphone standard')
    if 'Type de site' not in fieldnames:
        fieldnames.append('Type de site')
    if 'Taille estimée' not in fieldnames:
        fieldnames.append('Taille estimée')
    
    # Filtrer les lignes à traiter
    rows_to_process = []
    for i, row in enumerate(rows):
        societe = row.get(column_mapping['Société'], '').strip()
        ville = row.get(column_mapping['Ville'], '').strip()
        
        # Traiter si au moins un champ est vide
        needs_processing = (
            not row.get('Téléphone standard', '').strip() or
            not row.get('Type de site', '').strip() or
            row.get('Type de site', '').strip() == 'À compléter' or
            not row.get('Taille estimée', '').strip() or
            row.get('Taille estimée', '').strip() in ['À vérifier', 'À compléter']
        )
        
        if needs_processing and societe and ville:
            rows_to_process.append((i, row))
    
    print(f"📊 Total de lignes: {len(rows)}")
    print(f"🎯 À traiter: {len(rows_to_process)}")
    print(f"✓ Déjà complétées: {len(rows) - len(rows_to_process)}\n")
    
    if not rows_to_process:
        print("✅ Tout est déjà complété!")
        return
    
    # Lancer Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            locale='fr-FR',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        print("🌐 Ouverture de Google Maps...")
        page.goto('https://www.google.com/maps', wait_until='domcontentloaded')
        time.sleep(3)
        
        # Statistiques
        found_phone = 0
        found_type = 0
        found_taille = 0
        
        print("\n" + "="*120)
        print(f"{'Index':^6} | {'Société':^35} | {'Ville':^20} | {'Téléphone':^15} | {'Type de site':^30} | {'Taille':^12} | Temps")
        print("="*120)
        
        for idx, (original_idx, row) in enumerate(rows_to_process, 1):
            societe = row.get(column_mapping['Société'], '').strip()
            ville = row.get(column_mapping['Ville'], '').strip()
            secteur = row.get(column_mapping.get('Secteur', 'Secteur'), '').strip()
            company_size = row.get(column_mapping.get('CompanySize', ''), '').strip()
            
            # Extraire les infos
            info = extract_info_from_google_maps(page, societe, ville, secteur, company_size, idx, len(rows_to_process))
            
            # Mettre à jour uniquement les champs vides
            if info['phone'] and not row.get('Téléphone standard', '').strip():
                rows[original_idx]['Téléphone standard'] = info['phone']
                found_phone += 1
            
            if info['type_site'] and (not row.get('Type de site', '').strip() or row.get('Type de site', '').strip() == 'À compléter'):
                rows[original_idx]['Type de site'] = info['type_site']
                found_type += 1
            
            if info['taille'] and (not row.get('Taille estimée', '').strip() or row.get('Taille estimée', '').strip() in ['À vérifier', 'À compléter']):
                rows[original_idx]['Taille estimée'] = info['taille']
                found_taille += 1
            
            # Sauvegarder tous les 10 résultats
            if idx % 10 == 0:
                with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"\n💾 Sauvegarde: {idx}/{len(rows_to_process)} | Tél:{found_phone} | Type:{found_type} | Taille:{found_taille}\n")
            
            time.sleep(1.2)
        
        browser.close()
    
    # Sauvegarder final
    print(f"\n💾 Sauvegarde finale...")
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    # Statistiques
    elapsed_time = time.time() - start_time
    
    print(f"\n" + "="*80)
    print(f"✅ TERMINÉ!")
    print(f"="*80)
    print(f"   Durée totale              : {elapsed_time/60:.1f} minutes")
    print(f"   Lignes traitées           : {len(rows_to_process)}")
    print(f"   Téléphones trouvés        : {found_phone}")
    print(f"   Types de site définis     : {found_type}")
    print(f"   Tailles estimées (≥3000m²): {found_taille}")
    print(f"   Fichier mis à jour        : {output_file}")
    print(f"="*80)


if __name__ == "__main__":
    # PARAMÈTRES À MODIFIER
    input_file = r"lien\Leads_Generation_H1_Hotellerie_Hopitaux.csv"
    output_file = r"lien\Leads_Generation_H1_Hotellerie_Hopitaux 1.csv"
    
    # Mode headless (False = visible, True = invisible)
    HEADLESS = False
    
    print("⚡ Script COMPLET Google Maps - Extraction Téléphone + Type + Taille")
    print(f"   Fichier source: {input_file}")
    print(f"   Fichier destination: {output_file}")
    print(f"   Mode: {'Headless (invisible)' if HEADLESS else 'Visible'}\n")
    
    scrape_google_maps_complete(input_file, output_file, headless=HEADLESS)