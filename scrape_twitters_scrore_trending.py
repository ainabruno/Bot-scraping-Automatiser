from playwright.sync_api import sync_playwright
import pandas as pd
import time
import re
from datetime import datetime

def extract_score_number(score_text):
    """Extrait uniquement le chiffre du score (sans les flèches et changements)"""
    if not score_text:
        return ""
    # Cherche le premier nombre dans le texte
    match = re.search(r'(\d+(?:\s?\d+)*)', score_text.strip())
    if match:
        # Supprime les espaces dans le nombre (ex: "37 766" -> "37766")
        return match.group(1).replace(' ', '')
    return ""

def is_excellent_score(score):
    """Vérifie si le score est considéré comme excellent (≥ 131)"""
    try:
        score_num = int(score.replace(' ', '')) if score else 0
        return score_num >= 131
    except:
        return False

def scrape_current_page(page):
    """Scrape les données de la page actuelle"""
    data = []
    
    try:
        # Attendre que le contenu soit chargé
        page.wait_for_load_state('domcontentloaded')
        time.sleep(2)
        
        # Chercher le tableau avec différentes approches
        table_found = False
        
        # Essayer de trouver les lignes du tableau
        try:
            rows = page.locator('#topScoredProjectsDiffTable tbody tr').all()
            if rows:
                table_found = True
                print(f"  ✓ Trouvé {len(rows)} lignes dans le tableau")
            else:
                print("  Aucune ligne trouvée avec le sélecteur principal")
        except Exception as e:
            print(f"  Erreur avec le sélecteur principal: {e}")
            
        # Si pas trouvé, essayer d'autres sélecteurs
        if not table_found:
            selectors = [
                'tbody tr.odd, tbody tr.even',
                'table tbody tr',
                'tr.odd, tr.even',
                '.trending-projects-table tbody tr'
            ]
            
            for selector in selectors:
                try:
                    rows = page.locator(selector).all()
                    if rows:
                        table_found = True
                        print(f"  ✓ Trouvé {len(rows)} lignes avec: {selector}")
                        break
                except:
                    continue
        
        if not table_found:
            print("  ❌ Aucune ligne de tableau trouvée")
            return data
            
        # Extraire les données de chaque ligne
        for i, row in enumerate(rows):
            try:
                # Extraire toutes les cellules
                cells = row.locator('td').all()
                if len(cells) < 5:
                    continue
                
                # Rang (1ère colonne)
                rank = cells[0].inner_text().strip()
                
                # Informations du profil (2ème colonne)
                profile_cell = cells[1]
                
                # Nom
                name_links = profile_cell.locator('h6 a').all()
                if len(name_links) >= 2:
                    name = name_links[0].inner_text().strip()
                    profile_link = name_links[0].get_attribute('href')
                    
                    username = name_links[1].inner_text().strip()
                    twitter_link = name_links[1].get_attribute('href')
                else:
                    continue
                
                # Followers (3ème colonne)
                followers_cell = cells[2]
                followers_spans = followers_cell.locator('.table-score-wrapper p span').all()
                followers = ""
                if followers_spans:
                    followers_text = followers_spans[0].inner_text()
                    followers = extract_score_number(followers_text)
                
                # Twitter Score (4ème colonne)
                score_cell = cells[3]
                score_spans = score_cell.locator('.table-score-wrapper p span').all()
                twitter_score = ""
                if score_spans:
                    score_text = score_spans[0].inner_text()
                    twitter_score = extract_score_number(score_text)
                
                # Description (5ème colonne)
                desc_cell = cells[4]
                description = desc_cell.inner_text().strip()
                
                # Créer l'enregistrement
                record = {
                    'Rank': rank,
                    'Name': name,
                    'Username': username,
                    'Profile_Link': f"https://twitterscore.io{profile_link}" if profile_link else "",
                    'Twitter_Link': twitter_link,
                    'Followers': followers,
                    'Twitter_Score': twitter_score,
                    'Description': description,
                    'Is_Excellent': is_excellent_score(twitter_score)
                }
                
                data.append(record)
                print(f"    Ligne {i+1}: {name} ({username}) - Score: {twitter_score}")
                
            except Exception as e:
                print(f"    Erreur ligne {i+1}: {e}")
                continue
                
    except Exception as e:
        print(f"  Erreur générale de scraping: {e}")
    
    return data

def scrape_twitterscore():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        try:
            # Charger les cookies sauvegardés
            context = browser.new_context(storage_state="twitterscore.json")
            page = context.new_page()
            
            # Augmenter le timeout par défaut
            page.set_default_timeout(60000)
            
            print("Navigation vers la page trending...")
            page.goto("https://twitterscore.io/trending/", wait_until='domcontentloaded')
            
            # Attendre que la page soit complètement chargée
            time.sleep(5)
            
            all_data = []
            current_page = 1
            max_pages = 50  # Limite de sécurité
            
            while current_page <= max_pages:
                print(f"\n=== SCRAPING PAGE {current_page} ===")
                
                # Scraper la page actuelle
                page_data = scrape_current_page(page)
                
                if not page_data:
                    print("Aucune donnée trouvée sur cette page")
                    # Sauvegarder le HTML pour debug si première page
                    if current_page == 1:
                        with open(f'debug_page_{current_page}.html', 'w', encoding='utf-8') as f:
                            f.write(page.content())
                        print("HTML de debug sauvegardé dans debug_page_1.html")
                    break
                
                all_data.extend(page_data)
                print(f"  ✓ {len(page_data)} enregistrements ajoutés (Total: {len(all_data)})")
                
                # Chercher le bouton "suivant"
                try:
                    next_button = page.locator('#topScoredProjectsDiffTable_next')
                    
                    # Vérifier si le bouton est désactivé
                    button_class = next_button.get_attribute('class')
                    if button_class and 'disabled' in button_class:
                        print("  → Dernière page atteinte (bouton suivant désactivé)")
                        break
                    
                    # Cliquer sur suivant
                    print("  → Passage à la page suivante...")
                    next_button.click()
                    current_page += 1
                    
                    # Attendre le chargement
                    time.sleep(3)
                    
                except Exception as e:
                    print(f"  → Impossible de passer à la page suivante: {e}")
                    break
            
            print(f"\n🎉 Scraping terminé! Total: {len(all_data)} enregistrements")
            
            if not all_data:
                print("❌ Aucune donnée collectée")
                return None, None
            
            # Créer les DataFrames
            df_all = pd.DataFrame(all_data)
            df_excellent = df_all[df_all['Is_Excellent'] == True].copy()
            
            # Générer les noms de fichiers avec timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Sauvegarder tous les résultats
            filename_all = f"twitterscore_all_results_{timestamp}.xlsx"
            df_all.to_excel(filename_all, index=False)
            print(f"\n📊 Tous les résultats sauvegardés dans: {filename_all}")
            print(f"   Total d'enregistrements: {len(df_all)}")
            
            # Sauvegarder les excellents scores
            filename_excellent = f"twitterscore_excellent_scores_{timestamp}.xlsx"
            df_excellent.to_excel(filename_excellent, index=False)
            print(f"📊 Scores excellents sauvegardés dans: {filename_excellent}")
            print(f"   Nombre d'excellents scores (≥131): {len(df_excellent)}")
            
            # Afficher les statistiques
            if not df_all.empty:
                scores = df_all['Twitter_Score'].astype(str).apply(lambda x: int(x) if x.isdigit() else 0)
                print(f"\n--- STATISTIQUES ---")
                print(f"Score le plus élevé: {scores.max()}")
                print(f"Score le plus bas: {scores.min()}")
                print(f"Pourcentage de scores excellents: {len(df_excellent)/len(df_all)*100:.1f}%")
                print(f"Pages scrapées: {current_page}")
            
            return df_all, df_excellent
            
        except Exception as e:
            print(f"❌ Erreur générale: {e}")
            return None, None
            
        finally:
            browser.close()

if __name__ == "__main__":
    print("🚀 Démarrage du scraping TwitterScore.io...")
    print("📁 Assurez-vous que le fichier 'twitterscore.json' est présent dans le répertoire")
    
    df_all, df_excellent = scrape_twitterscore()
    
    if df_all is not None:
        print("\n✅ Scraping terminé avec succès!")
    else:
        print("\n❌ Échec du scraping")