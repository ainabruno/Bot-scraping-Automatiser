#!/usr/bin/env python3
"""
Script pour extraire les numéros de téléphone des sites web des entreprises
et les ajouter au fichier CSV leads.csv
"""

import csv
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import urljoin, urlparse


def clean_phone_number(phone):
    """Nettoie et formate le numéro de téléphone"""
    if not phone:
        return ""
    # Supprime les espaces, points, tirets
    phone = re.sub(r'[\s\.\-\(\)]', '', phone)
    return phone


def extract_phone_from_text(text):
    """
    Extrait les numéros de téléphone du texte
    Patterns pour numéros français et internationaux
    """
    if not text:
        return None
    
    # Patterns pour différents formats de téléphone
    patterns = [
        # Format français avec +33
        r'\+33\s*[1-9](?:[\s\.\-]?\d{2}){4}',
        # Format français 0X XX XX XX XX
        r'0[1-9](?:[\s\.\-]?\d{2}){4}',
        # Format international général
        r'\+\d{1,3}[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}',
        # Format avec parenthèses
        r'\(\+?\d{1,3}\)[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            # Retourne le premier numéro trouvé
            return matches[0].strip()
    
    return None


def find_phone_on_page(page, url):
    """
    Cherche un numéro de téléphone sur la page web
    """
    try:
        # Attendre que la page soit chargée
        page.wait_for_load_state('networkidle', timeout=10000)
        
        # Récupérer tout le texte de la page
        page_text = page.inner_text('body')
        
        # Chercher dans le texte général
        phone = extract_phone_from_text(page_text)
        if phone:
            return phone
        
        # Chercher spécifiquement dans les sections de contact
        contact_selectors = [
            'a[href^="tel:"]',
            '[class*="phone"]',
            '[class*="telephone"]',
            '[class*="contact"]',
            '[id*="phone"]',
            '[id*="telephone"]',
            '[id*="contact"]',
            'footer',
            'header',
        ]
        
        for selector in contact_selectors:
            try:
                elements = page.query_selector_all(selector)
                for element in elements:
                    text = element.inner_text()
                    phone = extract_phone_from_text(text)
                    if phone:
                        return phone
                    
                    # Vérifier l'attribut href pour les liens tel:
                    href = element.get_attribute('href')
                    if href and href.startswith('tel:'):
                        return href.replace('tel:', '').strip()
            except:
                continue
        
        # Essayer de trouver une page contact
        contact_links = page.query_selector_all('a[href*="contact"], a[href*="Contact"]')
        for link in contact_links[:3]:  # Limiter à 3 liens pour ne pas perdre trop de temps
            try:
                href = link.get_attribute('href')
                if href:
                    contact_url = urljoin(url, href)
                    page.goto(contact_url, wait_until='networkidle', timeout=10000)
                    page_text = page.inner_text('body')
                    phone = extract_phone_from_text(page_text)
                    if phone:
                        return phone
            except:
                continue
                
    except Exception as e:
        print(f"Erreur lors de l'extraction du téléphone: {e}")
    
    return None


def scrape_phones_from_csv(input_file, output_file):
    """
    Lit le fichier CSV, extrait les numéros de téléphone et met à jour le fichier
    """
    # Lire le fichier CSV
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    
    print(f"Total de {len(rows)} lignes à traiter")
    
    # Initialiser Playwright
    with sync_playwright() as p:
        # Lancer le navigateur
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        # Traiter chaque ligne
        for i, row in enumerate(rows, start=1):
            website = row.get('companyWebsite', '').strip()
            existing_phone = row.get('Téléphone', '').strip()
            company_name = row.get('Nom établissement / société', 'Unknown')
            
            print(f"\n[{i}/{len(rows)}] Traitement de: {company_name}")
            
            # Si le téléphone existe déjà, passer
            if existing_phone:
                print(f"  ✓ Téléphone déjà présent: {existing_phone}")
                continue
            
            # Si pas de site web, passer
            if not website or website == 'N/A':
                print(f"  ⚠ Pas de site web disponible")
                continue
            
            print(f"  → Visite de: {website}")
            
            try:
                # Visiter le site
                page.goto(website, wait_until='domcontentloaded', timeout=15000)
                
                # Chercher le téléphone
                phone = find_phone_on_page(page, website)
                
                if phone:
                    row['Téléphone'] = phone
                    print(f"  ✓ Téléphone trouvé: {phone}")
                else:
                    print(f"  ✗ Aucun téléphone trouvé")
                
                # Pause pour éviter de surcharger les serveurs
                time.sleep(1)
                
            except PlaywrightTimeout:
                print(f"  ✗ Timeout lors du chargement de la page")
            except Exception as e:
                print(f"  ✗ Erreur: {str(e)}")
            
            # Sauvegarder tous les 10 sites pour ne pas perdre les données
            if i % 10 == 0:
                print(f"\n💾 Sauvegarde intermédiaire après {i} lignes...")
                with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
        
        browser.close()
    
    # Sauvegarder le fichier final
    print(f"\n💾 Sauvegarde finale dans {output_file}...")
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    # Statistiques
    phones_found = sum(1 for row in rows if row.get('Téléphone', '').strip())
    print(f"\n✅ Terminé!")
    print(f"   Total de lignes: {len(rows)}")
    print(f"   Téléphones trouvés: {phones_found}")
    print(f"   Fichier mis à jour: {output_file}")


if __name__ == "__main__":
    input_file = r"lien\leads.csv"
    output_file = r"lien\leads_updated1.csv"
    
    print("🚀 Démarrage du script d'extraction de numéros de téléphone...")
    print(f"   Fichier source: {input_file}")
    print(f"   Fichier destination: {output_file}")
    
    scrape_phones_from_csv(input_file, output_file)