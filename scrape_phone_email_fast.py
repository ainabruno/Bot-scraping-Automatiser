#!/usr/bin/env python3
"""
Script ULTRA-RAPIDE - Extraction téléphones + emails (Sans navigateur)
Utilise requests + BeautifulSoup pour une vitesse maximale
"""

import csv
import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
import time


def extract_phone_from_text(text):
    """Extrait les numéros de téléphone du texte"""
    if not text:
        return None
    
    patterns = [
        r'\+33\s*[1-9](?:[\s\.\-]?\d{2}){4}',
        r'0[1-9](?:[\s\.\-]?\d{2}){4}',
        r'\+\d{1,3}[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}[\s\.\-]?\d{1,4}',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            return matches[0].strip()
    
    return None


def extract_email_from_text(text, domain_hint=None):
    """Extrait les emails professionnels du texte"""
    if not text:
        return None
    
    # Pattern pour emails
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    
    if not emails:
        return None
    
    # Filtrer les emails spam/génériques
    spam_patterns = [
        'example.com', 'test.com', 'email.com', 'domain.com',
        'noreply', 'no-reply', 'donotreply', 'mailer-daemon',
        'postmaster', 'abuse', 'spam', 'image', 'icon', 'jpg', 'png'
    ]
    
    valid_emails = []
    for email in emails:
        email_lower = email.lower()
        if any(spam in email_lower for spam in spam_patterns):
            continue
        if len(email) < 6 or email.count('@') != 1:
            continue
        valid_emails.append(email)
    
    if not valid_emails:
        return None
    
    # Prioriser emails du domaine de l'entreprise
    if domain_hint:
        domain_hint_clean = domain_hint.lower().replace('www.', '').split('/')[0]
        for email in valid_emails:
            if domain_hint_clean in email.lower():
                return email
    
    # Prioriser emails contact/info
    priority_prefixes = ['contact', 'info', 'hello', 'bonjour', 'commercial']
    for prefix in priority_prefixes:
        for email in valid_emails:
            if email.lower().startswith(prefix):
                return email
    
    return valid_emails[0]


def find_contact_info_on_page(url, session):
    """
    Cherche téléphone ET email - VERSION ULTRA RAPIDE
    Retourne: (phone, email)
    """
    phone = None
    email = None
    domain = urlparse(url).netloc
    
    try:
        # Timeout court
        response = session.get(url, timeout=5)
        response.raise_for_status()
        
        # Parser le HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Chercher les liens tel: et mailto: (plus rapide et fiable)
        tel_links = soup.find_all('a', href=re.compile(r'^tel:'))
        for link in tel_links:
            if not phone:
                phone_candidate = link['href'].replace('tel:', '').strip()
                if len(re.sub(r'\D', '', phone_candidate)) >= 9:
                    phone = phone_candidate
                    break
        
        mailto_links = soup.find_all('a', href=re.compile(r'^mailto:'))
        for link in mailto_links:
            if not email:
                email_candidate = link['href'].replace('mailto:', '').strip().split('?')[0]
                if '@' in email_candidate and len(email_candidate) > 5:
                    email = email_candidate
                    break
        
        # Si on a trouvé les deux, retourner
        if phone and email:
            return phone, email
        
        # 2. Chercher dans les éléments avec classes/ids spécifiques
        contact_elements = soup.find_all(
            ['div', 'span', 'p', 'a', 'footer', 'header'], 
            class_=re.compile(r'phone|telephone|contact|tel|email|mail|coordonnees|footer', re.I)
        )
        
        for elem in contact_elements[:10]:  # Limiter à 10 éléments
            text = elem.get_text()
            
            if not phone:
                phone = extract_phone_from_text(text)
            
            if not email:
                email = extract_email_from_text(text, domain)
            
            if phone and email:
                return phone, email
        
        # 3. Chercher dans le footer
        footer = soup.find('footer')
        if footer:
            footer_text = footer.get_text()
            
            if not phone:
                phone = extract_phone_from_text(footer_text)
            
            if not email:
                email = extract_email_from_text(footer_text, domain)
        
        # 4. Chercher dans tout le texte (dernier recours)
        if not phone or not email:
            text = soup.get_text()
            
            if not phone:
                phone = extract_phone_from_text(text)
            
            if not email:
                email = extract_email_from_text(text, domain)
        
        # 5. Si toujours pas trouvé, essayer la page contact
        if not phone or not email:
            contact_links = soup.find_all('a', href=re.compile(r'contact', re.I))
            if contact_links:
                contact_url = urljoin(url, contact_links[0]['href'])
                
                # Éviter liens externes
                if urlparse(contact_url).netloc == urlparse(url).netloc:
                    try:
                        contact_response = session.get(contact_url, timeout=3)
                        contact_soup = BeautifulSoup(contact_response.text, 'html.parser')
                        contact_text = contact_soup.get_text()
                        
                        if not phone:
                            phone = extract_phone_from_text(contact_text)
                        
                        if not email:
                            email = extract_email_from_text(contact_text, domain)
                    except:
                        pass
        
        return phone, email
        
    except Exception as e:
        return None, None


def process_row(row, index, total, session):
    """Traite une ligne du CSV"""
    website = row.get('companyWebsite', '').strip()
    existing_phone = row.get('Téléphone', '').strip()
    existing_email = row.get('Email professionnel', '').strip()
    company_name = row.get('Nom établissement / société', 'Unknown')
    
    # Vérifier si on a déjà tout
    has_phone = bool(existing_phone)
    has_email = bool(existing_email)
    
    # Si on a déjà les deux, skip
    if has_phone and has_email:
        return row, f"[{index}/{total}] {company_name[:35]:35} | ✓ Complet"
    
    # Si pas de site, skip
    if not website or website == 'N/A':
        status = []
        if not has_phone:
            status.append("⚠ Tel")
        if not has_email:
            status.append("⚠ Email")
        return row, f"[{index}/{total}] {company_name[:35]:35} | {' '.join(status)} | Pas de site"
    
    # Chercher les infos
    phone, email = find_contact_info_on_page(website, session)
    
    # Mettre à jour seulement ce qui manque
    if phone and not has_phone:
        row['Téléphone'] = phone
    
    if email and not has_email:
        row['Email professionnel'] = email
    
    # Construire le message de statut
    status_parts = []
    if phone and not has_phone:
        status_parts.append(f"✓ Tel: {phone[:15]}")
    elif has_phone:
        status_parts.append("✓ Tel exist")
    else:
        status_parts.append("✗ Tel")
    
    if email and not has_email:
        status_parts.append(f"✓ Email: {email[:20]}")
    elif has_email:
        status_parts.append("✓ Email exist")
    else:
        status_parts.append("✗ Email")
    
    return row, f"[{index}/{total}] {company_name[:35]:35} | {' | '.join(status_parts)}"


def scrape_contact_info_ultrafast(input_file, output_file, max_workers=30):
    """
    Version ULTRA-RAPIDE avec requests (pas de navigateur)
    max_workers = nombre de threads (30-50 recommandé)
    """
    start_time = time.time()
    
    # Lire le fichier CSV
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    
    # Vérifier que les colonnes existent
    if 'Téléphone' not in fieldnames:
        fieldnames = list(fieldnames) + ['Téléphone']
    if 'Email professionnel' not in fieldnames:
        fieldnames = list(fieldnames) + ['Email professionnel']
    
    print(f"📊 Total de {len(rows)} lignes à traiter")
    print(f"⚡ Mode ULTRA-RAPIDE : {max_workers} threads")
    print(f"🎯 Extraction : Téléphones + Emails")
    print(f"⏱️  Temps estimé : 1-3 minutes\n")
    
    # Session HTTP avec pool de connexions
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    
    results = [None] * len(rows)
    
    # Traitement parallèle avec ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Soumettre toutes les tâches
        future_to_index = {
            executor.submit(process_row, row, i+1, len(rows), session): i 
            for i, row in enumerate(rows)
        }
        
        # Récupérer les résultats au fur et à mesure
        completed = 0
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                updated_row, message = future.result()
                results[index] = updated_row
                print(message)
                
                completed += 1
                
                # Sauvegarder tous les 100 sites
                if completed % 100 == 0:
                    print(f"\n💾 Sauvegarde ({completed}/{len(rows)})...")
                    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows([r for r in results if r is not None])
                    print()
                    
            except Exception as e:
                print(f"Erreur sur la ligne {index}: {e}")
    
    # Sauvegarder le fichier final
    print(f"\n💾 Sauvegarde finale...")
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    # Statistiques
    elapsed_time = time.time() - start_time
    phones_found = sum(1 for row in results if row.get('Téléphone', '').strip())
    emails_found = sum(1 for row in results if row.get('Email professionnel', '').strip())
    both_found = sum(1 for row in results if row.get('Téléphone', '').strip() and row.get('Email professionnel', '').strip())
    
    print(f"\n" + "="*70)
    print(f"✅ TERMINÉ!")
    print(f"="*70)
    print(f"   Durée totale          : {elapsed_time/60:.1f} minutes ({elapsed_time:.0f} secondes)")
    print(f"   Total de lignes       : {len(results)}")
    print(f"   Téléphones trouvés    : {phones_found} ({phones_found/len(results)*100:.1f}%)")
    print(f"   Emails trouvés        : {emails_found} ({emails_found/len(results)*100:.1f}%)")
    print(f"   Contacts complets     : {both_found} ({both_found/len(results)*100:.1f}%)")
    print(f"   Vitesse moyenne       : {len(results)/elapsed_time:.1f} sites/seconde")
    print(f"   Fichier mis à jour    : {output_file}")
    print(f"="*70)


if __name__ == "__main__":
    input_file = r"lien\leadssans.csv"  # Modifiez selon votre chemin
    output_file = r"lien\leadssansinfo_updated.csv"  # Modifiez selon votre chemin
    
    # PARAMÈTRE : Nombre de threads simultanés
    # Recommandations :
    # - 20 : Connexion lente
    # - 30-40 : Connexion normale (RECOMMANDÉ)
    # - 50-100 : Connexion très rapide
    MAX_WORKERS = 40
    
    print("⚡ Script ULTRA-RAPIDE - Téléphones + Emails (Sans navigateur)")
    print(f"   Fichier source: {input_file}")
    print(f"   Fichier destination: {output_file}")
    print(f"   Threads: {MAX_WORKERS}\n")
    
    scrape_contact_info_ultrafast(input_file, output_file, MAX_WORKERS)