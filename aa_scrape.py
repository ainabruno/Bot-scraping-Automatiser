import re
import time
import random
import pandas as pd
from datetime import datetime
import sys
import asyncio
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Configuration Windows pour Playwright subprocess
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class TwitterProfileScraper:
    def __init__(self, cookie_file="playwright_state.json"):
        self.posts_data = []
        self.playwright = sync_playwright().start()
        
        # Configuration stealth optimisée
        self.browser = self.playwright.chromium.launch(
            headless=False,  # Mode headless pour plus de discrétion
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--disable-dev-shm-usage',
                '--disable-extensions',
                '--no-first-run',
                '--disable-default-apps',
                '--disable-infobars',
                '--window-size=1920,1080',
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
        )
        
        self.context = self.browser.new_context(
            storage_state=cookie_file,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
            }
        )
        
        self.page = self.context.new_page()
        
        # Scripts anti-détection
        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'fr'],
            });
        """)

    def random_delay(self, min_ms=1000, max_ms=4000):
        """Délai aléatoire optimisé"""
        delay = random.randint(min_ms, max_ms)
        time.sleep(delay / 1000)

    def simulate_human_behavior(self):
        """Comportement humain minimal mais efficace"""
        try:
            x = random.randint(200, 800)
            y = random.randint(200, 600)
            self.page.mouse.move(x, y)
            self.random_delay(500, 1000)
        except:
            pass

    def bypass_verification_check(self):
        """Bypass optimisé des vérifications"""
        try:
            self.random_delay(3000, 5000)
            
            verification_indicators = [
                "Verifying you are human",
                "This may take a few seconds",
                "Challenge",
                "security check"
            ]
            
            page_text = self.page.text_content("body") or ""
            
            if any(indicator in page_text for indicator in verification_indicators):
                print("⚠️ Vérification détectée - Bypass en cours...")
                
                # Attente intelligente avec feedback
                for i in range(6):
                    print(f"⏳ Attente {i*5+5}s... ({i+1}/6)")
                    self.random_delay(5000, 7000)
                    self.simulate_human_behavior()
                
                # Vérifier le succès
                self.page.reload(wait_until="load", timeout=120000)
                self.random_delay(5000, 8000)
                
                return True
                
            return True
            
        except Exception as e:
            print(f"Bypass: {e}")
            return True

    def extract_post_data(self, post_element):
        """Extrait les données d'un post spécifique"""
        post_data = {
            'name': '',
            'profile_link': '',
            'username': '',
            'tweet_content': '',
            'extracted_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            # Extraction du nom d'utilisateur (ex: Michael Saylor)
            name_selectors = [
                'div[data-testid="User-Name"] span[class*="css-1jxf684"]:not([class*="r-16dba41"])',
                'a[href*="/"] div[dir="ltr"] span span',
                'div[class*="r-1awozwy"] span span'
            ]
            
            for selector in name_selectors:
                try:
                    name_element = post_element.query_selector(selector)
                    if name_element:
                        name_text = name_element.inner_text().strip()
                        if name_text and not name_text.startswith('@') and len(name_text) > 2:
                            post_data['name'] = name_text
                            break
                except:
                    continue
            
            # Extraction du lien de profil (href="/saylor" -> "https://x.com/saylor")
            profile_selectors = [
                'a[href^="/"][href*="/status"]:not([href*="/status/"])',
                'div[data-testid="User-Name"] a[href^="/"]',
                'a[href^="/"][role="link"]:not([href*="/status/"])'
            ]
            
            for selector in profile_selectors:
                try:
                    link_elements = post_element.query_selector_all(selector)
                    for link_element in link_elements:
                        href = link_element.get_attribute('href')
                        if href and not '/status/' in href and len(href.split('/')) == 2:
                            post_data['profile_link'] = f"https://x.com{href}"
                            break
                    if post_data['profile_link']:
                        break
                except:
                    continue
            
            # Extraction du nom d'utilisateur (@saylor)
            username_selectors = [
                'div[style*="color: rgb(83, 100, 113)"] span[class*="css-1jxf684"]',
                'a[href^="/"] div[class*="r-1wvb978"] span',
                'span[class*="css-1jxf684"]:not([class*="r-b88u0q"])'
            ]
            
            for selector in username_selectors:
                try:
                    username_elements = post_element.query_selector_all(selector)
                    for element in username_elements:
                        username_text = element.inner_text().strip()
                        if username_text.startswith('@') and len(username_text) > 1:
                            post_data['username'] = username_text
                            break
                    if post_data['username']:
                        break
                except:
                    continue
            
            # Extraction du contenu du tweet
            tweet_selectors = [
                'div[data-testid="tweetText"]',
                'div[lang] span[class*="css-1jxf684"]',
                'div[dir="auto"] span[class*="css-1jxf684"]'
            ]
            
            for selector in tweet_selectors:
                try:
                    tweet_element = post_element.query_selector(selector)
                    if tweet_element:
                        tweet_text = tweet_element.inner_text().strip()
                        if tweet_text and len(tweet_text) > 3:
                            post_data['tweet_content'] = tweet_text
                            break
                except:
                    continue
            
            # Vérifier que nous avons au moins quelques données
            if post_data['name'] or post_data['username'] or post_data['tweet_content']:
                return post_data
                
        except Exception as e:
            print(f"Erreur extraction post: {e}")
            
        return None

    def scrape_profile(self, profile_url, max_scrolls=10):
        """Scrape tous les posts d'un profil"""
        print(f"🔍 Connexion au profil: {profile_url}")
        
        try:
            # Navigation vers le profil
            for attempt in range(2):
                try:
                    self.page.goto(profile_url, wait_until="load", timeout=120000)
                    print("✅ Profil chargé!")
                    break
                except PlaywrightTimeoutError:
                    if attempt == 0:
                        print("⏱️ Retry...")
                        self.random_delay(5000, 8000)
                    else:
                        raise
            
            # Bypass et attente initiale
            self.bypass_verification_check()
            self.random_delay(8000, 12000)
            
            # Scroll et extraction
            unique_posts = set()
            
            for scroll in range(max_scrolls):
                print(f"📜 Scroll {scroll+1}/{max_scrolls}")
                
                # Recherche des articles/posts
                post_selectors = [
                    'article[data-testid="tweet"]',
                    'div[data-testid="cellInnerDiv"] article',
                    'article[role="article"]'
                ]
                
                posts_found = 0
                for selector in post_selectors:
                    try:
                        posts = self.page.query_selector_all(selector)
                        print(f"🔍 Sélecteur '{selector}': {len(posts)} posts trouvés")
                        
                        for post in posts:
                            try:
                                # Créer un identifiant unique pour éviter les doublons
                                post_html = post.inner_html()[:200]  # Premiers 200 caractères
                                post_hash = hash(post_html)
                                
                                if post_hash not in unique_posts:
                                    post_data = self.extract_post_data(post)
                                    if post_data:
                                        self.posts_data.append(post_data)
                                        unique_posts.add(post_hash)
                                        posts_found += 1
                                        print(f"✅ Post extrait: {post_data['name']} - {post_data['tweet_content'][:50]}...")
                                        
                            except Exception as e:
                                print(f"Erreur post individuel: {e}")
                                continue
                                
                    except Exception as e:
                        print(f"Erreur sélecteur {selector}: {e}")
                        continue
                
                print(f"📊 Scroll {scroll+1}: +{posts_found} nouveaux posts | Total: {len(self.posts_data)}")
                
                # Scroll vers le bas
                self.page.evaluate(f"window.scrollBy(0, {600 + scroll*100})")
                self.random_delay(3000, 6000)
                
                # Pause intelligente entre les scrolls
                self.simulate_human_behavior()
                
        except Exception as e:
            print(f"❌ Erreur scraping profil: {e}")
            
        return self.posts_data

    def save_to_excel(self, filename=None):
        """Sauvegarde les données dans un fichier Excel"""
        if not self.posts_data:
            print("❌ Aucune donnée à sauvegarder")
            return None
            
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"Resultat/twitter posts {timestamp}.xlsx"
        
        try:
            # Créer DataFrame
            df = pd.DataFrame(self.posts_data)
            
            # Nettoyer et optimiser les données
            df = df.drop_duplicates(subset=['name', 'username', 'tweet_content'], keep='first')
            df = df[df['tweet_content'].str.len() > 0]  # Supprimer les tweets vides
            
            # Réorganiser les colonnes
            columns_order = ['name', 'username', 'profile_link', 'tweet_content', 'extracted_at']
            df = df.reindex(columns=columns_order)
            
            # Sauvegarder en Excel
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Twitter_Posts', index=False)
                
                # Ajuster la largeur des colonnes
                worksheet = writer.sheets['Twitter_Posts']
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            print(f"✅ Données sauvegardées: {filename}")
            print(f"📊 {len(df)} posts uniques extraits")
            
            return filename
            
        except Exception as e:
            print(f"❌ Erreur sauvegarde Excel: {e}")
            return None

    def close(self):
        """Fermeture propre"""
        try:
            self.page.close()
            self.context.close()
            self.browser.close()
            self.playwright.stop()
        except:
            pass


def main():
    """Fonction principale"""
    profile_url = "https://x.com/cryptogems555"
    max_scrolls = 15  # Nombre de scrolls pour récupérer plus de posts
    
    print("🚀 Démarrage du scraper Twitter Profile")
    print(f"🎯 URL cible: {profile_url}")
    print(f"📜 Scrolls maximum: {max_scrolls}")
    
    # Initialiser le scraper
    scraper = TwitterProfileScraper("playwright_state.json")
    
    try:
        # Scraper le profil
        posts_data = scraper.scrape_profile(profile_url, max_scrolls)
        
        if posts_data:
            print(f"\n🎉 {len(posts_data)} posts extraits avec succès!")
            
            # Afficher un aperçu des données
            print("\n📋 Aperçu des données extraites:")
            for i, post in enumerate(posts_data[:3]):  # Afficher les 3 premiers
                print(f"\n--- Post {i+1} ---")
                print(f"Nom: {post['name']}")
                print(f"Username: {post['username']}")
                print(f"Profil: {post['profile_link']}")
                print(f"Tweet: {post['tweet_content'][:100]}...")
            
            if len(posts_data) > 3:
                print(f"\n... et {len(posts_data)-3} autres posts")
            
            # Sauvegarder en Excel
            excel_file = scraper.save_to_excel()
            if excel_file:
                print(f"\n✅ Fichier Excel créé: {excel_file}")
            
        else:
            print("\n❌ Aucun post extrait")
            print("💡 Suggestions:")
            print("• Vérifiez l'URL du profil")
            print("• Augmentez le nombre de scrolls")
            print("• Vérifiez vos cookies de session")
            
    except Exception as e:
        print(f"\n❌ Erreur générale: {e}")
        
    finally:
        print("\n🔚 Fermeture du scraper...")
        scraper.close()
        print("✅ Terminé!")


if __name__ == "__main__":
    main()