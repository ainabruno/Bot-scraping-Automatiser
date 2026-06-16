#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de génération de leads CEE - Mission 2
Génère automatiquement les URLs de recherche LinkedIn pour chaque entreprise
"""

import pandas as pd
import urllib.parse
from datetime import datetime
import re

# Templates de recherche par profil
PROFILS_RECHERCHE = {
    "TECHNIQUE": [
        "Directeur technique",
        "Responsable technique",
        "Directeur travaux",
        "Responsable maintenance",
        "Head of Engineering",
        "Ingénieur patrimoine",
        "Responsable infrastructures"
    ],
    "BUDGET": [
        "Directeur immobilier",
        "Directeur patrimoine",
        "Directeur exploitation",
        "Asset Manager",
        "Directeur des opérations",
        "COO",
        "Responsable immobilier"
    ],
    "VALIDATION": [
        "Directeur général",
        "CEO",
        "Président",
        "DG"
    ]
}

# Mapping des industries vers les thématiques
MAPPING_THEMATIQUE = {
    "real estate": "Tertiaire - Bureaux",
    "facilities services": "Tertiaire - Bureaux",
    "hospitality": "Hôtels",
    "hospitals": "Santé",
    "healthcare": "Médico-social",
    "residential": "Résidentiel institutionnel"
}

def nettoyer_nom_entreprise(nom):
    """Nettoie le nom de l'entreprise pour la recherche LinkedIn"""
    # Supprimer les caractères spéciaux
    nom = re.sub(r'[^\w\s-]', '', nom)
    # Supprimer les espaces multiples
    nom = re.sub(r'\s+', ' ', nom).strip()
    return nom

def generer_url_recherche_linkedin(entreprise, profils_list):
    """
    Génère une URL de recherche LinkedIn pour une entreprise et une liste de profils
    """
    entreprise_clean = nettoyer_nom_entreprise(entreprise)
    
    # Construire la requête de recherche
    profils_str = " OR ".join([f'"{p}"' for p in profils_list])
    query = f'{entreprise_clean} AND ({profils_str})'
    
    # Encoder l'URL
    query_encoded = urllib.parse.quote(query)
    
    # URL de recherche LinkedIn (recherche de personnes)
    linkedin_url = f"https://www.linkedin.com/search/results/people/?keywords={query_encoded}"
    
    return linkedin_url

def determiner_thematique(industry, specialties):
    """Détermine la thématique basée sur l'industrie et les spécialités"""
    industry_lower = str(industry).lower() if pd.notna(industry) else ""
    specialties_lower = str(specialties).lower() if pd.notna(specialties) else ""
    
    combined = industry_lower + " " + specialties_lower
    
    if any(word in combined for word in ["hotel", "hospitality", "hébergement"]):
        return "Hôtels"
    elif any(word in combined for word in ["hospital", "clinic", "santé", "health"]):
        return "Santé"
    elif any(word in combined for word in ["ehpad", "médico", "social care"]):
        return "Médico-social"
    elif any(word in combined for word in ["residential", "logement", "housing"]):
        return "Résidentiel institutionnel"
    elif any(word in combined for word in ["syndic", "copropriété"]):
        return "Syndics / Copropriétés"
    else:
        return "Tertiaire - Bureaux"

def estimer_surface(company_size):
    """Estime la surface basée sur la taille de l'entreprise"""
    try:
        if pd.isna(company_size):
            return "≥ 3000"
        
        size_str = str(company_size)
        
        if "10000+" in size_str:
            return "≥ 10000"
        elif "5001-10000" in size_str:
            return "≥ 8000"
        elif "1001-5000" in size_str:
            return "≥ 5000"
        elif "501-1000" in size_str:
            return "≥ 3000"
        else:
            return "≥ 3000"
    except:
        return "≥ 3000"

def determiner_zone_climatique(ville):
    """Détermine la zone climatique H1/H2/H3 basée sur la ville"""
    ville_lower = str(ville).lower() if pd.notna(ville) else ""
    
    # Zone H1 (nord et est de la France)
    villes_h1 = ["lille", "amiens", "reims", "metz", "nancy", "strasbourg", "besançon", "dijon"]
    
    # Zone H2 (centre et ouest)
    villes_h2 = ["paris", "nantes", "rennes", "brest", "orléans", "tours", "poitiers", "limoges", "lyon", "bordeaux"]
    
    # Zone H3 (sud)
    villes_h3 = ["marseille", "nice", "toulon", "montpellier", "toulouse", "perpignan", "ajaccio"]
    
    for ville_h1 in villes_h1:
        if ville_h1 in ville_lower:
            return "H1"
    
    for ville_h2 in villes_h2:
        if ville_h2 in ville_lower:
            return "H2"
    
    for ville_h3 in villes_h3:
        if ville_h3 in ville_lower:
            return "H3"
    
    # Par défaut H2 (zone la plus commune)
    return "H2"

def creer_lignes_decideurs(row):
    """Crée 3 lignes pour chaque entreprise (1 par type de décideur)"""
    lignes = []
    
    nom_entreprise = row['company_name']
    thematique = determiner_thematique(row.get('company_industry_1'), row.get('company_specialties'))
    ville = row.get('company_city_1', 'Paris')
    zone = determiner_zone_climatique(ville)
    surface = estimer_surface(row.get('company_size_category'))
    date_extraction = datetime.now().strftime("%Y-%m-%d")
    
    # Ligne pour chaque type de décideur
    for niveau, profils in PROFILS_RECHERCHE.items():
        url_recherche = generer_url_recherche_linkedin(nom_entreprise, profils)
        
        ligne = {
            'Nom_Entité': nom_entreprise,
            'Type_Bâtiment': thematique,
            'Ville': ville,
            'Zone_Climatique': zone,
            'Surface_Estimée_m²': surface,
            'Nom_Décideur': f"[À RECHERCHER - {niveau}]",
            'Fonction_Exacte': f"Voir profils: {', '.join(profils[:2])}...",
            'Niveau_Décision': niveau,
            'Téléphone_Direct': "",
            'Téléphone_Bureau': row.get('company_phone', ''),
            'Email_Professionnel': row.get('company_email', ''),
            'LinkedIn_URL': "",
            'URL_Recherche_LinkedIn': url_recherche,
            'Source': "À compléter manuellement",
            'Date_Extraction': date_extraction,
            'Commentaire': f"Utiliser cette URL pour rechercher: {url_recherche}"
        }
        lignes.append(ligne)
    
    return lignes

def generer_fichier_excel(csv_path, output_path):
    """Génère le fichier Excel final selon le cahier des charges"""
    
    print("📥 Lecture du fichier CSV...")
    df = pd.read_csv(csv_path)
    print(f"✅ {len(df)} entreprises chargées")
    
    print("\n🔄 Génération des lignes de décideurs...")
    toutes_lignes = []
    for idx, row in df.iterrows():
        lignes_entreprise = creer_lignes_decideurs(row)
        toutes_lignes.extend(lignes_entreprise)
        if (idx + 1) % 20 == 0:
            print(f"   → {idx + 1}/{len(df)} entreprises traitées")
    
    print(f"✅ {len(toutes_lignes)} lignes de décideurs générées")
    
    # Créer le DataFrame final
    df_final = pd.DataFrame(toutes_lignes)
    
    # Créer le fichier Excel avec onglets par thématique
    print("\n📊 Création du fichier Excel...")
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        
        # Grouper par thématique
        thematiques = df_final['Type_Bâtiment'].unique()
        
        for thematique in sorted(thematiques):
            df_thematique = df_final[df_final['Type_Bâtiment'] == thematique].copy()
            
            # Nom de l'onglet (limité à 31 caractères, sans caractères invalides)
            nom_onglet = thematique.replace('/', '-').replace('\\', '-').replace('*', '').replace('[', '').replace(']', '').replace(':', '').replace('?', '')[:31]
            
            df_thematique.to_excel(writer, sheet_name=nom_onglet, index=False)
            print(f"   ✓ Onglet '{nom_onglet}': {len(df_thematique)} lignes")
        
        # Onglet récapitulatif
        df_final.to_excel(writer, sheet_name='TOUS', index=False)
        print(f"   ✓ Onglet 'TOUS': {len(df_final)} lignes")
    
    print(f"\n✅ Fichier Excel créé: {output_path}")
    
    # Statistiques
    print("\n" + "="*60)
    print("📊 STATISTIQUES")
    print("="*60)
    print(f"Total entreprises:        {len(df)}")
    print(f"Total lignes générées:    {len(df_final)}")
    print(f"Lignes par entreprise:    3 (TECHNIQUE, BUDGET, VALIDATION)")
    print("\nRépartition par thématique:")
    for thematique in sorted(thematiques):
        count = len(df_final[df_final['Type_Bâtiment'] == thematique])
        print(f"  • {thematique}: {count} lignes")
    
    return df_final

def generer_guide_utilisation(output_path):
    """Génère un guide d'utilisation"""
    guide = """
╔══════════════════════════════════════════════════════════════════════════╗
║                     GUIDE D'UTILISATION - MISSION 2                      ║
╚══════════════════════════════════════════════════════════════════════════╝

🎯 OBJECTIF:
   Remplir le fichier Excel généré avec les informations des décideurs

📋 MÉTHODE (100% GRATUITE):

1️⃣  OUVRIR LE FICHIER EXCEL
   → Vous avez 1 onglet par thématique
   → Chaque ligne = 1 décideur à rechercher
   → 3 décideurs par entreprise (TECHNIQUE, BUDGET, VALIDATION)

2️⃣  POUR CHAQUE LIGNE:
   
   a) Cliquez sur l'URL dans la colonne "URL_Recherche_LinkedIn"
      → Cela ouvre LinkedIn avec la recherche pré-remplie
      
   b) Sur LinkedIn (gratuit):
      → Consultez les profils qui apparaissent
      → Identifiez le décideur correspondant au niveau recherché
      → Notez son nom, fonction exacte
      
   c) Cherchez le téléphone:
      → Site web de l'entreprise (section "Contact" ou "Équipe")
      → Google: "[Nom décideur] téléphone"
      → Societe.com / Verif.com (informations publiques)
      → Standard de l'entreprise + demander extension
      
   d) Remplissez les colonnes:
      ✓ Nom_Décideur: Prénom NOM
      ✓ Fonction_Exacte: Titre exact du poste
      ✓ Téléphone_Direct: PRIORITÉ ABSOLUE
      ✓ Téléphone_Bureau: Si pas de direct
      ✓ LinkedIn_URL: URL du profil LinkedIn
      ✓ Email_Professionnel: Optionnel
      ✓ Source: "LinkedIn + Site web" ou autre

3️⃣  OUTILS GRATUITS RECOMMANDÉS:

   🔍 Recherche LinkedIn:
      → Compte LinkedIn gratuit suffit
      → Recherche de personnes (limite 100/mois gratuit)
      → Utiliser les URLs pré-générées
      
   📞 Trouver les téléphones:
      → Site web entreprise (section Contact/Équipe)
      → Pages Jaunes: pagesjaunes.fr
      → Societe.com: informations publiques
      → Google: "[entreprise] + [fonction] + téléphone"
      → Appeler le standard et demander
      
   📧 Trouver les emails (optionnel):
      → Hunter.io (version gratuite: 25 recherches/mois)
      → Format email sur le site entreprise
      → Profil LinkedIn (parfois visible)

4️⃣  ORDRE DE PRIORITÉ:

   🥇 Téléphone direct
   🥈 Téléphone bureau + fonction exacte
   🥉 Standard + poste/extension
   
   ⚠️  Sans téléphone = lead faible (à faire en dernier)

5️⃣  VALIDATION:

   ✓ 2-3 décideurs MAXIMUM par entreprise
   ✓ Au moins 1 décideur TECHNIQUE obligatoire
   ✓ Téléphone renseigné pour chaque lead prioritaire
   ✓ Fonction exacte (pas approximative)
   ✓ Pas de doublon avec Mission 1

6️⃣  ASTUCES:

   💡 Commencez par les grandes entreprises (plus d'infos disponibles)
   💡 Groupez les recherches par secteur (gain de temps)
   💡 Vérifiez le site web de l'entreprise en premier
   💡 LinkedIn mobile app = plus de résultats visibles gratuitement
   💡 Contactez le standard en vous présentant comme partenaire CEE

═══════════════════════════════════════════════════════════════════════════

📞 SCRIPT TÉLÉPHONIQUE (appel au standard):

   "Bonjour, je souhaiterais parler avec le responsable technique 
    [ou maintenance] pour un projet de travaux d'efficacité énergétique.
    Pourriez-vous me donner ses coordonnées directes SVP?"
    
═══════════════════════════════════════════════════════════════════════════

⏱️  TEMPS ESTIMÉ:
   → 5-10 minutes par décideur avec téléphone
   → 125 entreprises × 3 décideurs = 375 lignes à remplir
   → Temps total: 30-60 heures de travail (réparti sur plusieurs jours)

═══════════════════════════════════════════════════════════════════════════

✅ CRITÈRES DE QUALITÉ:
   • Téléphone direct pour 80%+ des leads
   • Fonction exacte (pas "Manager" mais "Directeur technique")
   • Niveau de décision correct
   • Source vérifiée et fiable

═══════════════════════════════════════════════════════════════════════════

🚀 BONNE CHANCE !
"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(guide)
    
    print(guide)

if __name__ == "__main__":
    print("="*70)
    print("🎯 GÉNÉRATEUR DE LEADS CEE - MISSION 2")
    print("="*70)
    print()
    
    # Chemins des fichiers
    csv_input = r"lien\34200157_export_2026-01-29_09-38-44.csv"
    excel_output = f"lien\CEE_MISSION2_{datetime.now().strftime('%Y%m%d')}.xlsx"
    guide_output = "GUIDE_UTILISATION.txt"
    
    # Générer le fichier Excel
    df_final = generer_fichier_excel(csv_input, excel_output)
    
    # Générer le guide
    print("\n" + "="*70)
    print("📖 GÉNÉRATION DU GUIDE D'UTILISATION")
    print("="*70)
    generer_guide_utilisation(guide_output)
    
    print("\n" + "="*70)
    print("✅ GÉNÉRATION TERMINÉE !")
    print("="*70)
    print(f"\n📁 Fichiers créés:")
    print(f"   1. {excel_output}")
    print(f"   2. {guide_output}")
    print("\n👉 Suivez le guide pour remplir le fichier Excel avec les infos des décideurs")
    print()
