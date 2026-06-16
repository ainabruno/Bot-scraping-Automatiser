# serpapi_scraper_full.py - Récupère 200+ résultats avec pagination
import time
import pandas as pd
import requests

SERP_API_KEY = "f77905421b96292fedf81fab00d96982701c9696f6d33e31b5f04c715a4414fd"

def scrape_maps_api_full(query, city, max_results=200):
    """SerpAPI avec pagination complète"""
    
    all_results = []
    next_page_token = None
    page = 0
    
    while len(all_results) < max_results:
        page += 1
        print(f"\nPage {page} - Résultats: {len(all_results)}/{max_results}")
        
        # Paramètres de base
        params = {
            "engine": "google_maps",
            "q": f"{query} {city}",
            "api_key": SERP_API_KEY,
            "hl": "fr",  # Langue française
            "gl": "fr",  # Géolocalisation France
            "ll": "@45.764043,4.835659,14z",  # Coordonnées Lyon (change pour ta ville)
            "type": "search",  # Type de recherche
        }
        
        # Ajouter le token de pagination si disponible
        if next_page_token:
            params["start"] = len(all_results)  # Offset
            # OU params["next_page_token"] = next_page_token (selon la doc SerpAPI)
        
        try:
            response = requests.get(
                "https://serpapi.com/search", 
                params=params,
                timeout=30
            )
            data = response.json()
            
            # Vérifier erreurs
            if "error" in data:
                print(f"❌ Erreur API: {data['error']}")
                break
            
            # Extraire les résultats locaux
            local_results = data.get('local_results', [])
            
            if not local_results:
                print("⚠️ Plus de résultats")
                break
            
            for place in local_results:
                all_results.append({
                    'nom': place.get('title', ''),
                    'adresse': place.get('address', ''),
                    'telephone': place.get('phone', ''),
                    'site_web': place.get('website', ''),
                    'note': place.get('rating', ''),
                    'nb_avis': place.get('reviews', ''),
                    'categorie': place.get('type', ''),
                    'prix': place.get('price', ''),
                    'horaires': place.get('hours', ''),
                    'ville': city,
                    'secteur': query
                })
            
            # Vérifier s'il y a une page suivante
            next_page_token = data.get('serpapi_pagination', {}).get('next_page_token')
            
            # Alternative: vérifier si on a atteint la fin
            if len(local_results) < 20:  # Moins de 20 = dernière page
                print("🏁 Dernière page atteinte")
                break
            
            # Pause entre les requêtes
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            break
    
    print(f"\n✅ Total récupéré: {len(all_results)}")
    return pd.DataFrame(all_results)

# Alternative: Utiliser l'endpoint Google Maps direct avec pagination
def scrape_maps_pagination(query, city, max_results=200):
    """Méthode alternative avec gestion de pagination"""
    
    all_results = []
    start = 0
    
    while start < max_results:
        print(f"\nRécupération {start}-{start+20}...")
        
        params = {
            "engine": "google_maps",
            "q": f"{query} {city}",
            "api_key": SERP_API_KEY,
            "start": start,
            "num": 20,  # 20 résultats par page
        }
        
        response = requests.get("https://serpapi.com/search", params=params)
        data = response.json()
        
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
                'ville': city,
                'secteur': query
            })
        
        # Incrémenter le start pour la page suivante
        start += len(results)
        
        # Vérifier si on a atteint la fin
        if len(results) < 20:
            break
        
        time.sleep(1.5)
    
    return pd.DataFrame(all_results)

# LANCEMENT
if __name__ == "__main__":
    ville = input("Ville (Lyon/Nice/Paris): ").strip() or "Lyon"
    secteur = input("Secteur (restaurant/hotel/etc): ").strip() or "restaurant"
    max_res = int(input("Nombre max (50-500): ") or "200")
    
    print(f"\n{'='*60}")
    print(f"Scraping {max_res} {secteur} à {ville}")
    print(f"{'='*60}")
    
    # Méthode 1: Pagination simple
    df = scrape_maps_pagination(secteur, ville, max_results=max_res)
    
    if len(df) < max_res:
        print(f"\n⚠️ Seulement {len(df)} trouvés, tentative méthode 2...")
        df = scrape_maps_api_full(secteur, ville, max_results=max_res)
    
    # Sauvegarde
    filename = f"{ville.lower()}_{secteur}_{len(df)}.xlsx"
    df.to_excel(filename, index=False)
    
    print(f"\n{'='*60}")
    print(f"✅ {len(df)} leads sauvegardés dans {filename}")
    print(f"{'='*60}")
    print(df[['nom', 'telephone', 'note']].head(10).to_string())

# # maps_api_scraper.py
# # Plus fiable mais payant (100 requêtes gratuites/mois)
# # https://serpapi.com/

# import time

# import pandas as pd
# import requests

# SERP_API_KEY = "f77905421b96292fedf81fab00d96982701c9696f6d33e31b5f04c715a4414fd"

# def scrape_maps_api(query, city, max_results=200):
#     """Utilise SerpAPI (plus stable)"""
    
#     all_results = []
    
#     for i in range(0, max_results, 200):
#         params = {
#             "engine": "google_maps",
#             "q": f"{query} {city}",
#             "api_key": SERP_API_KEY,
#             "start": i
#         }
        
#         response = requests.get("https://serpapi.com/search", params=params)
#         data = response.json()
        
#         for place in data.get('local_results', []):
#             all_results.append({
#                 'nom': place.get('title', ''),
#                 'adresse': place.get('address', ''),
#                 'telephone': place.get('phone', ''),
#                 'site_web': place.get('website', ''),
#                 'note': place.get('rating', ''),
#                 'nb_avis': place.get('reviews', ''),
#                 'categorie': place.get('type', ''),
#                 'ville': city,
#                 'secteur': query
#             })
        
#         time.sleep(1)
    
#     return pd.DataFrame(all_results)

# # Utilisation
# df = scrape_maps_api("Restaurant", "Lyon", max_results=500)
# df.to_excel("maps_api_resultsRestaurant.xlsx", index=False)