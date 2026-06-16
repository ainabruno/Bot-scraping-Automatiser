import re
import time
import random
import pandas as pd
from datetime import datetime
import asyncio
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import sys
import json
import os

# Configuration Windows pour Playwright
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class TwitterProfileScraper:
    def __init__(self, cookie_file="playwright_state.json"):
        self.profiles_data = []
        self.playwright = sync_playwright().start()
        
        # Configuration optimisée pour la vitesse
        self.browser = self.playwright.chromium.launch(
            headless=False,  # Mode headless pour plus de vitesse
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
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-features=VizDisplayCompositor'
            ]
        )
        
        self.context = self.browser.new_context(
            storage_state=cookie_file if os.path.exists(cookie_file) else None,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Upgrade-Insecure-Requests': '1',
            }
        )
        
        self.page = self.context.new_page()
        
        # Scripts anti-détection optimisés
        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        """)

    def random_delay(self, min_ms=500, max_ms=1500):
        """Délai aléatoire optimisé pour la vitesse"""
        delay = random.randint(min_ms, max_ms)
        time.sleep(delay / 1000)

    def bypass_verification_check(self):
        """Bypass optimisé des vérifications"""
        try:
            self.random_delay(2000, 3000)
            
            # Vérification rapide des indicateurs de vérification
            verification_indicators = [
                "Verifying you are human",
                "This may take a few seconds",
                "Challenge",
                "security check"
            ]
            
            page_text = self.page.text_content("body") or ""
            
            if any(indicator in page_text for indicator in verification_indicators):
                print("⚠️ Vérification détectée - Bypass en cours...")
                
                # Attente plus courte
                for i in range(3):
                    print(f"⏳ Attente {i*3+3}s... ({i+1}/3)")
                    self.random_delay(3000, 4000)
                
                return True
                
            return True
            
        except Exception as e:
            print(f"Bypass: {e}")
            return True

    def extract_profile_info(self, profile_url):
        """Extraction des informations de profil optimisée"""
        profile_data = {
            'Nom': '',
            'Username': '',
            'Lien': profile_url,
            'Bio': '',
            'Followers': 0,
            'Following': 0,
            'Date_extraction': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            print(f"🔍 Extraction du profil: {profile_url}")
            
            # Navigation vers le profil avec timeout réduit
            self.page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
            print("✅ Profil chargé!")
            
            # Bypass et attente réduite
            self.bypass_verification_check()
            self.random_delay(3000, 5000)
            
            # Extraction du nom d'affichage
            try:
                name_element = self.page.query_selector('div[data-testid="User-Name"] a[role="link"] div[dir="ltr"] span')
                if name_element:
                    name_text = name_element.inner_text().strip()
                    if name_text and len(name_text) > 1:
                        profile_data['Nom'] = name_text
                        print(f"📝 Nom: {name_text}")
            except Exception as e:
                print(f"Erreur nom: {e}")

            # Extraction du username
            try:
                username_element = self.page.query_selector('div[data-testid="User-Name"] a[href^="/"] div[dir="ltr"] span')
                if username_element:
                    username_text = username_element.inner_text().strip()
                    if username_text:
                        if not username_text.startswith('@'):
                            username_text = '@' + username_text
                        profile_data['Username'] = username_text
                        print(f"👤 Username: {username_text}")
            except Exception as e:
                print(f"Erreur username: {e}")

            # Extraction de la bio
            try:
                bio_element = self.page.query_selector('div[data-testid="UserDescription"]')
                if not bio_element:
                    bio_element = self.page.query_selector('div[data-testid="tweetText"]')
                
                if bio_element:
                    bio_text = bio_element.inner_text().strip()
                    if bio_text and len(bio_text) > 5:
                        profile_data['Bio'] = bio_text[:500]
                        print(f"📄 Bio: {bio_text[:100]}...")
            except Exception as e:
                print(f"Erreur bio: {e}")
            
            # Extraction du nombre de followers/following
            try:
                # Sélecteurs optimisés pour les stats
                stats_elements = self.page.query_selector_all('a[href*="/followers"], a[href*="/following"]')
                
                for element in stats_elements:
                    try:
                        href = element.get_attribute('href') or ''
                        text = element.inner_text().strip()
                        
                        if text and any(char.isdigit() for char in text):
                            clean_number = self.parse_number(text)
                            
                            if '/following' in href:
                                profile_data['Following'] = clean_number
                                print(f"👥 Following: {clean_number}")
                            elif 'followers' in href:
                                profile_data['Followers'] = clean_number
                                print(f"👥 Followers: {clean_number}")
                    except:
                        continue
            except Exception as e:
                print(f"Erreur stats: {e}")
            
        except Exception as e:
            print(f"Erreur extraction profil: {e}")
        
        return profile_data

    def parse_number(self, text):
        """Parse les nombres avec K, M, B suffixes"""
        try:
            clean_text = re.sub(r'[^\d.,KMBkmb]', '', text)
            
            if 'K' in clean_text.upper():
                number = float(clean_text.upper().replace('K', ''))
                return int(number * 1000)
            elif 'M' in clean_text.upper():
                number = float(clean_text.upper().replace('M', ''))
                return int(number * 1000000)
            elif 'B' in clean_text.upper():
                number = float(clean_text.upper().replace('B', ''))
                return int(number * 1000000000)
            else:
                clean_number = clean_text.replace(',', '').replace('.', '')
                if clean_number.isdigit():
                    return int(clean_number)
        except:
            pass
        
        return 0

    def scrape_profile_posts(self, profile_url, max_posts=100):
        """Scraper les posts d'un profil pour récupérer plus de données"""
        posts_data = []
        
        try:
            print(f"📝 Extraction des posts de: {profile_url}")
            
            # Aller à la page du profil
            self.page.goto(profile_url, wait_until="domcontentloaded", timeout=10000)
            self.random_delay(3000, 5000)
            
            # Scroller pour charger plus de posts
            scroll_attempts = 0
            max_scrolls = 20  # Nombre de scrolls pour charger plus de contenu
            
            while scroll_attempts < max_scrolls and len(posts_data) < max_posts:
                # Extraire les posts visibles
                tweet_elements = self.page.query_selector_all('article[data-testid="tweet"]')
                
                for tweet in tweet_elements:
                    try:
                        post_data = self.extract_post_data(tweet)
                        if post_data and post_data not in posts_data:
                            posts_data.append(post_data)
                            if len(posts_data) >= max_posts:
                                break
                    except:
                        continue
                
                # Scroll down
                self.page.evaluate("window.scrollBy(0, 2000)")
                self.random_delay(1000, 2000)
                scroll_attempts += 1
                
                print(f"📊 Posts collectés: {len(posts_data)}/{max_posts}")
                
            return posts_data
            
        except Exception as e:
            print(f"Erreur lors de l'extraction des posts: {e}")
            return posts_data

    def extract_post_data(self, tweet_element):
        """Extraire les données d'un post/tweet"""
        try:
            # Texte du tweet
            text_element = tweet_element.query_selector('div[data-testid="tweetText"]')
            text = text_element.inner_text().strip() if text_element else ""
            
            # Date du tweet
            time_element = tweet_element.query_selector('time')
            date = time_element.get_attribute('datetime') if time_element else ""
            
            # Métriques (likes, retweets, replies)
            metrics = {
                'likes': 0,
                'retweets': 0,
                'replies': 0
            }
            
            # Sélecteurs pour les métriques
            metric_selectors = [
                ('button[data-testid="like"]', 'likes'),
                ('button[data-testid="retweet"]', 'retweets'),
                ('button[data-testid="reply"]', 'replies')
            ]
            
            for selector, metric in metric_selectors:
                element = tweet_element.query_selector(selector)
                if element:
                    metric_text = element.inner_text().strip()
                    metrics[metric] = self.parse_number(metric_text)
            
            return {
                'text': text[:500],  # Limiter la longueur du texte
                'date': date,
                'likes': metrics['likes'],
                'retweets': metrics['retweets'],
                'replies': metrics['replies']
            }
            
        except Exception as e:
            print(f"Erreur extraction post: {e}")
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
    profile_url = "https://x.com/OurCryptoNation"
    
    print("🚀 Démarrage de l'extraction de données Twitter...")
    
    # Initialiser le scraper
    scraper = TwitterProfileScraper()
    
    try:
        # Extraire les informations du profil
        print("📋 Extraction des informations du profil...")
        profile_data = scraper.extract_profile_info(profile_url)
        
        # Extraire les posts du profil
        print("📝 Extraction des posts du profil...")
        posts_data = scraper.scrape_profile_posts(profile_url, max_posts=50)
        
        # Créer un DataFrame avec les données
        profile_df = pd.DataFrame([profile_data])
        
        # Sauvegarder les résultats
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Sauvegarder les informations du profil
        profile_df.to_csv(f"twitter_profile_{timestamp}.csv", index=False)
        print(f"✅ Informations du profil sauvegardées: twitter_profile_{timestamp}.csv")
        
        # Sauvegarder les posts si disponibles
        if posts_data:
            posts_df = pd.DataFrame(posts_data)
            posts_df.to_csv(f"twitter_posts_{timestamp}.csv", index=False)
            print(f"✅ Posts sauvegardés: twitter_posts_{timestamp}.csv")
            
            # Afficher un résumé
            print("\n📊 RÉSUMÉ DE L'EXTRACTION:")
            print(f"• Profil: {profile_data['Nom']} ({profile_data['Username']})")
            print(f"• Followers: {profile_data['Followers']:,}")
            print(f"• Following: {profile_data['Following']:,}")
            print(f"• Posts extraits: {len(posts_data)}")
            print(f"• Total likes: {sum(post['likes'] for post in posts_data):,}")
            print(f"• Total retweets: {sum(post['retweets'] for post in posts_data):,}")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'exécution: {e}")
    
    finally:
        scraper.close()
        print("🎉 Extraction terminée!")

if __name__ == "__main__":
    main()