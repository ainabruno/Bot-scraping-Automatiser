#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SerpAPI Scraper AUTOMATIQUE pour enrichissement de leads LinkedIn
Version: Détection auto des colonnes + Mode batch sans interaction
"""

import time
import pandas as pd
import requests
from urllib.parse import quote, unquote
import re
import sys
import os
from pathlib import Path
import argparse
import json

# ==================== CONFIGURATION ====================

# Clés API (mettre dans variables d'environnement ou ici)
SERP_API_KEY = os.getenv("SERP_API_KEY", "votre_cle_ici")
SIRENE_API_KEY = os.getenv("SIRENE_API_KEY", None)  # Optionnel pour API Sirene

# Paramètres globaux
DEFAULT_DELAY = 1.5
MAX_RETRIES = 3
BATCH_SIZE = 5  # Sauvegarde intermédiaire tous les X résultats

# Mapping intelligent des colonnes
COMPANY_KEYWORDS = ['company', 'société', 'entreprise', 'societe', 'locataire', 
                     'organization', 'firme', 'business', 'enseigne', 'nom']
LOCATION_KEYWORDS = ['location', 'ville', 'adresse', 'city', 'adress', 'place', 
                      'region', 'localisation', 'geo', 'area']
PHONE_KEYWORDS = ['phone', 'telephone', 'tel', 'mobile', 'portable', 'fixe']
EMAIL_KEYWORDS = ['email', 'mail', 'courriel', 'e-mail']


# ==================== FONCTIONS DE NETTOYAGE ====================

def clean_company_name(company):
    """Nettoie le nom de l'entreprise pour la recherche"""
    if pd.isna(company):
        return ""
    
    company = str(company).strip()
    # Supprimer suffixes juridiques
    suffixes = [' SAS', ' SARL', ' SA', ' EURL', ' SE', ' SCP', ' SNC', 
                ' GMBH', ' LTD', ' LLC', ' Inc', ' Corp', ' SASU', ' SCOP']
    for suffix in suffixes:
        company = re.sub(f'{suffix}$', '', company, flags=re.IGNORECASE)
        company = re.sub(f'{suffix} ', ' ', company, flags=re.IGNORECASE)
    
    # Nettoyer caractères spéciaux sauf espaces
    company = re.sub(r'[^\w\s\-]', '', company)
    return company.strip()

def clean_location(location):
    """Extrait la ville de la location LinkedIn"""
    if pd.isna(location):
        return ""
    
    location = str(location).strip()
    # Enlever "Greater ... Area"
    location = re.sub(r'Greater\s+(\w+)\s+Area', r'\1', location, flags=re.IGNORECASE)
    # Prendre première partie avant virgule
    ville = location.split(',')[0].strip()
    return ville

def normalize_column_name(col_name):
    """Normalise le nom de colonne pour comparaison"""
    return str(col_name).lower().strip().replace(' ', '').replace('_', '').replace('-', '')


# ==================== DÉTECTION AUTO DES COLONNES ====================

def detect_columns(df):
    """
    Détecte automatiquement les colonnes pertinentes avec scoring
    Retourne: dict avec company_col, location_col, etc.
    """
    detected = {
        'company': None,
        'location': None,
        'phone': None,
        'email': None,
        'website': None
    }
    
    scores = {key: {} for key in detected.keys()}
    
    for col in df.columns:
        col_norm = normalize_column_name(col)
        col_lower = str(col).lower()
        
        # Scoring Company
        for keyword in COMPANY_KEYWORDS:
            if keyword in col_lower:
                scores['company'][col] = scores['company'].get(col, 0) + 10
            if keyword in col_norm:
                scores['company'][col] = scores['company'].get(col, 0) + 5
        
        # Scoring Location
        for keyword in LOCATION_KEYWORDS:
            if keyword in col_lower:
                scores['location'][col] = scores['location'].get(col, 0) + 10
            if keyword in col_norm:
                scores['location'][col] = scores['location'].get(col, 0) + 5
        
        # Scoring Phone (pour colonnes déjà existantes)
        for keyword in PHONE_KEYWORDS:
            if keyword in col_lower:
                scores['phone'][col] = scores['phone'].get(col, 0) + 10
        
        # Scoring Email
        for keyword in EMAIL_KEYWORDS:
            if keyword in col_lower:
                scores['email'][col] = scores['email'].get(col, 0) + 10
    
    # Sélectionner les meilleurs scores
    for key in detected.keys():
        if scores[key]:
            best_col = max(scores[key], key=scores[key].get)
            if scores[key][best_col] >= 5:  # Seuil minimum
                detected[key] = best_col
    
    return detected

def validate_detection(detected, df):
    """
    Valide la détection et retourne les colonnes finales
    """
    print("\n🔍 DÉTECTION AUTOMATIQUE DES COLONNES:")
    print("-" * 50)
    
    # Company
    company_col = detected['company']
    if company_col:
        print(f"✅ Entreprise: '{company_col}' (score: {detected.get('company_score', 'auto')})")
        # Afficher un échantillon
        sample = df[company_col].dropna().head(3).tolist()
        print(f"   Échantillon: {sample}")
    else:
        print("❌ Colonne entreprise non détectée")
        print(f"   Colonnes disponibles: {list(df.columns)}")
        sys.exit(1)
    
    # Location
    location_col = detected['location']
    if location_col:
        print(f"✅ Localisation: '{location_col}'")
        sample = df[location_col].dropna().head(3).tolist()
        print(f"   Échantillon: {sample}")
    else:
        print("⚠️  Colonne location non détectée - utilisation valeur par défaut")
        location_col = None
    
    print("-" * 50)
    
    return company_col, location_col


# ==================== API SIRENE (FRANCE) ====================

def search_sirene_api(company_name, ville=None):
    """
    Recherche via API Sirene (INSEE) - Gratuit
    Retourne les données légales de l'entreprise
    """
    try:
        base_url = "https://api.insee.fr/entreprises/sirene/V3.11/siret"
        
        # Construire la requête
        params = {
            'q': f'denominationUniteLegale:"{company_name}"~',
            'nombre': 5
        }
        
        if ville:
            params['q'] += f' AND libelleCommuneEtablissement:"{ville}"~'
        
        headers = {
            'Accept': 'application/json',
            'X-INSEE-Api-Key-Integration': SIRENE_API_KEY or 'demo'
        }
        
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            etablissements = data.get('etablissements', [])
            
            if etablissements:
                etab = etablissements[0]
                unite = etab.get('uniteLegale', {})
                adresse = etab.get('adresseEtablissement', {})
                
                return {
                    'siret': etab.get('siret', ''),
                    'siren': etab.get('siren', ''),
                    'nom_sirene': unite.get('denominationUniteLegale', ''),
                    'adresse_sirene': f"{adresse.get('numeroVoieEtablissement', '')} {adresse.get('libelleVoieEtablissement', '')}, {adresse.get('codePostalEtablissement', '')} {adresse.get('libelleCommuneEtablissement', '')}",
                    'code_naf': etab.get('activitePrincipaleEtablissement', ''),
                    'tranche_effectif': unite.get('trancheEffectifsUniteLegale', ''),
                    'date_creation': unite.get('dateCreationUniteLegale', ''),
                    'categorie_entreprise': unite.get('categorieEntreprise', ''),
                    'source_sirene': 'TROUVE'
                }
        
        return None
        
    except Exception as e:
        return {'source_sirene': f'ERREUR: {str(e)[:50]}'}


# ==================== API SERPAPI ====================

def search_serpapi(company, ville, max_retries=MAX_RETRIES):
    """
    Recherche via SerpAPI Google Maps
    """
    company_clean = clean_company_name(company)
    ville_clean = clean_location(ville) if ville else ""
    
    if not company_clean:
        return None
    
    query = f"{company_clean} {ville_clean}".strip()
    print(f"🔍 SerpAPI: {query}")
    
    for attempt in range(max_retries):
        try:
            params = {
                "engine": "google_maps",
                "q": query,
                "api_key": SERP_API_KEY,
                "hl": "fr",
                "gl": "fr",
                "type": "search",
            }
            
            response = requests.get(
                "https://serpapi.com/search",
                params=params,
                timeout=30
            )
            data = response.json()
            
            if "error" in data:
                error_msg = data['error']
                print(f"⚠️  Erreur API: {error_msg}")
                if "limit" in error_msg.lower() or "quota" in error_msg.lower():
                    print("🚫 Limite API atteinte - arrêt")
                    return {'status': 'API_LIMIT', 'error': error_msg}
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return None
            
            local_results = data.get('local_results', [])
            
            if not local_results:
                print(f"❌ Aucun résultat pour: {query}")
                return {'status': 'NON_TROUVE'}
            
            place = local_results[0]
            
            result = {
                'nom_trouve': place.get('title', ''),
                'adresse_complete': place.get('address', ''),
                'telephone': place.get('phone', ''),
                'site_web': place.get('website', ''),
                'note': place.get('rating', ''),
                'nb_avis': place.get('reviews', ''),
                'categorie': place.get('type', ''),
                'latitude': place.get('gps_coordinates', {}).get('latitude', ''),
                'longitude': place.get('gps_coordinates', {}).get('longitude', ''),
                'horaires': str(place.get('hours', ''))[:100],
                'lien_google': place.get('link', ''),
                'place_id': place.get('place_id', ''),
                'status': 'TROUVE'
            }
            
            print(f"✅ Trouvé: {result['nom_trouve']} | 📞 {result['telephone'] or 'N/A'}")
            return result
            
        except Exception as e:
            print(f"❌ Erreur tentative {attempt+1}: {str(e)[:80]}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return {'status': f'ERREUR: {str(e)[:50]}'}
    
    return None


# ==================== FUSION DES SOURCES ====================

def enrich_company(company, ville, use_sirene=True, use_serpapi=True):
    """
    Enrichit une entreprise avec toutes les sources disponibles
    """
    final_result = {
        'company_input': company,
        'ville_input': ville,
        'status': 'INIT'
    }
    
    # 1. API Sirene (France uniquement)
    if use_sirene and ville and any(c.isalpha() for c in str(ville)):
        sirene_data = search_sirene_api(company, ville)
        if sirene_data:
            final_result.update(sirene_data)
    
    # 2. API SerpAPI (Google Maps)
    if use_serpapi and SERP_API_KEY and SERP_API_KEY != "votre_cle_ici":
        serpapi_data = search_serpapi(company, ville)
        if serpapi_data:
            # Éviter écrasement si Sirene a déjà trouvé
            if serpapi_data.get('status') == 'TROUVE':
                final_result.update(serpapi_data)
                final_result['status'] = 'TROUVE_MULTI'
            elif 'status' in serpapi_data:
                final_result['status_serpapi'] = serpapi_data['status']
    
    # Déterminer statut final
    if final_result.get('status') == 'TROUVE_MULTI':
        final_result['status'] = 'TROUVE'
    elif final_result.get('source_sirene') == 'TROUVE':
        final_result['status'] = 'TROUVE_SIRENE_ONLY'
    elif final_result.get('status') == 'INIT':
        final_result['status'] = 'NON_TROUVE'
    
    return final_result


# ==================== TRAITEMENT PRINCIPAL ====================

def process_csv_auto(input_file, output_file=None, limit=None, 
                    use_sirene=True, use_serpapi=True,
                    skip_existing=True):
    """
    Traitement complet automatique sans interaction
    """
    print(f"\n{'='*70}")
    print(f"🚀 MODE AUTOMATIQUE - Traitement: {input_file}")
    print(f"{'='*70}")
    
    # 1. Lecture fichier
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Fichier introuvable: {input_file}")
        # Chercher dans dossier courant
        csv_files = list(Path('.').glob('*.csv'))
        if csv_files:
            print(f"📁 Fichiers CSV trouvés: {[f.name for f in csv_files]}")
            input_path = csv_files[0]
            print(f"✅ Utilisation auto: {input_path}")
        else:
            sys.exit(1)
    
    # Détection encoding
    for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
        try:
            df = pd.read_csv(input_path, encoding=encoding)
            print(f"✅ Fichier lu (encoding: {encoding})")
            break
        except:
            continue
    else:
        print("❌ Impossible de lire le fichier")
        sys.exit(1)
    
    print(f"📊 Total lignes: {len(df)} | Colonnes: {list(df.columns)}")
    
    # 2. Détection auto colonnes
    detected = detect_columns(df)
    company_col, location_col = validate_detection(detected, df)
    
    # 3. Détection colonnes déjà enrichies (pour reprise)
    existing_cols = [c for c in df.columns if c in ['telephone', 'nom_trouve', 'siret', 'status']]
    if existing_cols and skip_existing:
        print(f"\n⚠️  Colonnes existantes détectées: {existing_cols}")
        print("   Filtrage des lignes déjà traitées...")
        mask = df['status'].isna() | (df['status'] == '') | (df['status'] == 'INIT')
        df_to_process = df[mask].copy()
        print(f"   Reste à traiter: {len(df_to_process)}/{len(df)} lignes")
    else:
        df_to_process = df.copy()
    
    # 4. Limiter si demandé
    if limit:
        df_to_process = df_to_process.head(limit)
        print(f"⚡ Limité aux {limit} premières lignes")
    
    # 5. Traitement
    enriched_rows = []
    api_limit_reached = False
    
    for idx, row in df_to_process.iterrows():
        if api_limit_reached:
            # Copier tel quel si limite API atteinte
            enriched_rows.append(row.to_dict())
            continue
        
        print(f"\n{'='*70}")
        print(f"🔎 [{idx+1}/{len(df_to_process)}] {row[company_col]}")
        
        company = row[company_col]
        ville = row[location_col] if location_col else ""
        
        # Enrichissement
        result = enrich_company(company, ville, use_sirene, use_serpapi)
        
        # Vérifier limite API
        if result.get('status') == 'API_LIMIT':
            api_limit_reached = True
            print("🚫 Arrêt - Limite API atteinte")
        
        # Fusion
        enriched_row = {**row.to_dict(), **result}
        enriched_rows.append(enriched_row)
        
        # Sauvegarde intermédiaire
        if (len(enriched_rows) % BATCH_SIZE == 0) or api_limit_reached:
            temp_save(input_path, enriched_rows, df.columns, detected)
        
        if not api_limit_reached:
            time.sleep(DEFAULT_DELAY)
    
    # 6. Finalisation
    df_final = pd.DataFrame(enriched_rows)
    
    # Réintégrer les lignes non traitées si filtrage
    if skip_existing and len(df_final) < len(df):
        processed_indices = df_to_process.index
        df_not_processed = df.drop(processed_indices)
        df_final = pd.concat([df_final, df_not_processed], ignore_index=True)
    
    # 7. Sauvegarde
    if not output_file:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = input_path.stem + f"_ENRICHIS_{timestamp}.xlsx"
    
    output_path = Path(output_file)
    df_final.to_excel(output_path, index=False, engine='openpyxl')
    
    # 8. Statistiques
    stats = generate_stats(df_final)
    print_stats(stats, output_path)
    
    # Sauvegarde aussi en JSON pour traçabilité
    stats_file = output_path.with_suffix('.stats.json')
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    
    return df_final

def temp_save(input_path, enriched_rows, original_cols, detected):
    """Sauvegarde intermédiaire"""
    try:
        temp_file = input_path.stem + "_TEMP.xlsx"
        df_temp = pd.DataFrame(enriched_rows)
        df_temp.to_excel(temp_file, index=False)
        print(f"💾 Sauvegarde intermédiaire: {len(enriched_rows)} lignes")
    except Exception as e:
        print(f"⚠️  Erreur sauvegarde temp: {e}")

def generate_stats(df):
    """Génère les statistiques finales"""
    total = len(df)
    stats = {
        'total': total,
        'trouves': 0,
        'avec_telephone': 0,
        'avec_site_web': 0,
        'avec_siret': 0,
        'par_status': df['status'].value_counts().to_dict() if 'status' in df.columns else {},
        'taux_succes': 0
    }
    
    if 'status' in df.columns:
        stats['trouves'] = len(df[df['status'].isin(['TROUVE', 'TROUVE_MULTI', 'TROUVE_SIRENE_ONLY'])])
        stats['taux_succes'] = round(stats['trouves'] / total * 100, 1) if total > 0 else 0
    
    if 'telephone' in df.columns:
        stats['avec_telephone'] = len(df[df['telephone'].notna() & (df['telephone'] != '')])
    
    if 'site_web' in df.columns:
        stats['avec_site_web'] = len(df[df['site_web'].notna() & (df['site_web'] != '')])
    
    if 'siret' in df.columns:
        stats['avec_siret'] = len(df[df['siret'].notna() & (df['siret'] != '')])
    
    return stats

def print_stats(stats, output_path):
    """Affiche les statistiques"""
    print(f"\n{'='*70}")
    print(f"📈 STATISTIQUES FINALES")
    print(f"{'='*70}")
    print(f"Total traité:        {stats['total']}")
    print(f"Trouvés:             {stats['trouves']} ({stats['taux_succes']}%)")
    print(f"Avec téléphone:      {stats['avec_telephone']}")
    print(f"Avec site web:       {stats['avec_site_web']}")
    print(f"Avec SIRET:          {stats['avec_siret']}")
    print(f"\nRépartition:")
    for status, count in stats['par_status'].items():
        print(f"  - {status}: {count}")
    print(f"\n✅ Fichier final: {output_path}")
    print(f"{'='*70}")


# ==================== MODE SECTEUR (BULK) ====================

def search_sector_auto(villes, secteur, max_per_city=50):
    """
    Recherche par secteur automatique (équivalent SerpAPI bulk)
    """
    all_results = []
    
    for ville in villes:
        print(f"\n{'='*70}")
        print(f"🏙️  {ville} | {secteur}")
        print(f"{'='*70}")
        
        start = 0
        while start < max_per_city:
            print(f"📦 Récupération {start}-{start+20}...")
            
            params = {
                "engine": "google_maps",
                "q": f"{secteur} {ville}",
                "api_key": SERP_API_KEY,
                "hl": "fr",
                "gl": "fr",
                "start": start,
                "num": 20,
            }
            
            try:
                response = requests.get("https://serpapi.com/search", params=params, timeout=30)
                data = response.json()
                
                if "error" in data:
                    print(f"⚠️  {data['error']}")
                    break
                
                results = data.get('local_results', [])
                if not results:
                    break
                
                for place in results:
                    all_results.append({
                        'nom': place.get('title', ''),
                        'adresse': place.get('address', ''),
                        'telephone': place.get('phone', ''),
                        'site_web': place.get('website', ''),
                        'note': place.get('rating', ''),
                        'nb_avis': place.get('reviews', ''),
                        'categorie': place.get('type', ''),
                        'ville': ville,
                        'secteur': secteur,
                        'place_id': place.get('place_id', '')
                    })
                
                start += len(results)
                if len(results) < 20:
                    break
                
                time.sleep(1.5)
                
            except Exception as e:
                print(f"❌ Erreur: {e}")
                break
        
        print(f"✅ {ville}: {len([r for r in all_results if r['ville'] == ville])} résultats")
    
    # Sauvegarde
    df = pd.DataFrame(all_results)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"secteur_{secteur.replace(' ', '_')}_{timestamp}_{len(df)}_results.xlsx"
    df.to_excel(filename, index=False)
    
    print(f"\n{'='*70}")
    print(f"✅ Total: {len(df)} entreprises → {filename}")
    print(f"{'='*70}")
    
    return df


# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(
        description='Enrichisseur de leads LinkedIn - Mode automatique',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Mode auto (détecte le CSV dans le dossier)
  python scraper_auto.py
  
  # Fichier spécifique
  python scraper_auto.py -f leads.csv
  
  # Limite à 50 lignes, sans API Sirene
  python scraper_auto.py -f leads.csv -l 50 --no-sirene
  
  # Mode secteur bulk
  python scraper_auto.py --mode sector -v "Lyon,Paris" -s "restaurant"
        """
    )
    
    parser.add_argument('-f', '--file', help='Fichier CSV input (auto-détecté si non précisé)')
    parser.add_argument('-o', '--output', help='Fichier output (auto-généré si non précisé)')
    parser.add_argument('-l', '--limit', type=int, help='Limite de lignes à traiter')
    parser.add_argument('--no-sirene', action='store_true', help='Désactiver API Sirene')
    parser.add_argument('--no-serpapi', action='store_true', help='Désactiver SerpAPI')
    parser.add_argument('--mode', choices=['enrich', 'sector'], default='enrich',
                       help='Mode: enrich (défaut) ou sector (recherche par secteur)')
    parser.add_argument('-v', '--villes', help='Villes pour mode sector (séparées par virgule)')
    parser.add_argument('-s', '--secteur', help='Secteur pour mode sector')
    parser.add_argument('--max-per-city', type=int, default=50, help='Max résultats par ville (mode sector)')
    
    args = parser.parse_args()
    
    # Vérifier clés API
    if not args.no_serpapi and SERP_API_KEY == "votre_cle_ici":
        print("⚠️  AVERTISSEMENT: SerpAPI key non configurée!")
        print("   Définissez: export SERP_API_KEY='votre_cle'")
        print("   Ou modifiez la variable SERP_API_KEY dans le script")
        if not args.no_sirene:
            print("   Fallback sur API Sirene uniquement...")
        else:
            print("   Aucune source disponible - arrêt")
            sys.exit(1)
    
    if args.mode == 'sector':
        # Mode secteur bulk
        if not args.villes or not args.secteur:
            print("❌ Mode sector nécessite --villes et --secteur")
            sys.exit(1)
        
        villes = [v.strip() for v in args.villes.split(',')]
        search_sector_auto(villes, args.secteur, args.max_per_city)
        
    else:
        # Mode enrichissement
        input_file = args.file
        if not input_file:
            # Auto-détection
            csv_files = list(Path('.').glob('*.csv'))
            if not csv_files:
                print("❌ Aucun fichier CSV trouvé. Précisez avec -f")
                sys.exit(1)
            input_file = str(csv_files[0])
            print(f"📁 Auto-détection: {input_file}")
        
        process_csv_auto(
            input_file=input_file,
            output_file=args.output,
            limit=args.limit,
            use_sirene=not args.no_sirene,
            use_serpapi=not args.no_serpapi
        )

if __name__ == "__main__":
    main()