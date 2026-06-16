import re
import time
import random
import pandas as pd
from datetime import datetime
import streamlit as st
import sys
import asyncio
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ⚠️ Correction Windows pour Playwright subprocess
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class OptimizedStealthCryptoScraper:
    def __init__(self, cookie_file="playwright_state.json"):
        self.addresses = set()
        self.processed_elements = set()  # Cache pour éviter les doublons
        self.playwright = sync_playwright().start()
        
        # Configuration stealth optimisée
        self.browser = self.playwright.chromium.launch(
            headless=False,
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
                '--disable-images',  # OPTIMISATION: Désactiver les images
                '--disable-javascript-harmony-shipping',
                '--disable-background-networking',
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
        )
        
        # Contexte optimisé
        self.context = self.browser.new_context(
            storage_state=cookie_file,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
            }
        )
        
        self.page = self.context.new_page()
        
        # OPTIMISATION: Bloquer les ressources inutiles
        self.page.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico}", lambda route: route.abort())
        self.page.route("**/*.{css,woff,woff2,ttf}", lambda route: route.abort())
        self.page.route("**/analytics**", lambda route: route.abort())
        self.page.route("**/ads**", lambda route: route.abort())
        
        # Scripts anti-détection optimisés
        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'fr']});
        """)

    def quick_delay(self, min_ms=500, max_ms=1500):
        """Délai réduit pour accélération"""
        delay = random.randint(min_ms, max_ms)
        time.sleep(delay / 1000)

    def fast_scroll(self, pixels=800):
        """Scroll rapide et efficace"""
        self.page.evaluate(f"window.scrollBy(0, {pixels})")
        self.quick_delay(800, 1200)  # Délai réduit

    def extract_crypto_addresses_optimized(self, text):
        """Extraction optimisée avec patterns précis"""
        # Patterns optimisés pour différents types de crypto
        patterns = {
            'solana': r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b',
            'bitcoin': r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b',
            'bitcoin_bech32': r'\bbc1[a-z0-9]{39,59}\b',
            'ethereum': r'\b0x[a-fA-F0-9]{40}\b',
            'other': r'\b[A-Za-z0-9]{25,60}\b'
        }

        found_addresses = set()
        for crypto_type, pattern in patterns.items():
            matches = re.findall(pattern, text)
            for match in matches:
                if self.is_valid_crypto_address_fast(match):
                    found_addresses.add(match)
        return found_addresses

    def is_valid_crypto_address_fast(self, address):
        """Validation rapide et efficace"""
        if not (20 <= len(address) <= 70):
            return False
        
        # Filtres rapides d'exclusion
        invalid_keywords = ['http', 'www', 'com', 'twitter', 'status', 'follow', 'like', 'retweet']
        address_lower = address.lower()
        if any(keyword in address_lower for keyword in invalid_keywords):
            return False
        
        # Vérification de diversité des caractères (rapide)
        if len(set(address)) < 8:
            return False
            
        # Patterns répétitifs
        if any(char * 6 in address for char in '0123456789ABCDEF'):
            return False
            
        return True

    def extract_all_visible_content(self):
        """Extraction massive et rapide de tout le contenu visible"""
        try:
            # Sélecteurs optimisés pour maximum de contenu
            selectors = [
                'div[data-testid="tweetText"]',
                'article[data-testid="tweet"] span',
                'div[lang] span',
                'span[dir="auto"]',
                'div[dir="auto"] span',
                'article span',
                '[data-testid="tweet"] div span'
            ]
            
            all_addresses = set()
            processed_count = 0
            
            for selector in selectors:
                try:
                    elements = self.page.query_selector_all(selector)
                    st.info(f"🔍 Traitement {len(elements)} éléments avec sélecteur: {selector[:30]}...")
                    
                    for element in elements:
                        try:
                            # Créer un hash unique de l'élément pour éviter les doublons
                            element_html = element.inner_html()[:100]  # Premier 100 chars pour hash
                            element_hash = hash(element_html)
                            
                            if element_hash in self.processed_elements:
                                continue
                            
                            self.processed_elements.add(element_hash)
                            
                            text = element.inner_text()
                            if text and len(text.strip()) > 10:  # Texte significatif seulement
                                addresses = self.extract_crypto_addresses_optimized(text)
                                if addresses:
                                    all_addresses.update(addresses)
                                    processed_count += 1
                                    if len(addresses) > 0:
                                        st.success(f"💰 +{len(addresses)} adresses | Total: {len(all_addresses)}")
                        except:
                            continue
                            
                except Exception as e:
                    continue
            
            st.info(f"📊 Éléments traités: {processed_count} | Adresses uniques: {len(all_addresses)}")
            return list(all_addresses)
            
        except Exception as e:
            st.error(f"Erreur extraction: {e}")
            return []

    def scrape_twitter_post_fast(self, url):
        """Scraping rapide du post principal"""
        try:
            st.info(f"🚀 Chargement rapide: {url}")
            
            # Navigation rapide avec timeout réduit
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)  # 1 minute seulement
            st.success("✅ Page chargée!")
            
            # Attente minimale pour le contenu dynamique
            self.quick_delay(3000, 5000)
            
            # Bypass rapide si nécessaire
            self.quick_bypass_check()
            
            # Scroll initial pour déclencher le contenu
            self.fast_scroll(300)
            self.page.evaluate("window.scrollTo(0, 0)")
            self.quick_delay(2000, 3000)
            
            # Extraction rapide
            addresses = self.extract_all_visible_content()
            st.success(f"✅ Post principal: {len(addresses)} adresses extraites")
            
            return addresses
            
        except Exception as e:
            st.error(f"Erreur scraping post: {e}")
            return []

    def scrape_twitter_comments_fast(self, url, max_scroll=20):
        """Scraping rapide des commentaires avec extraction maximisée"""
        try:
            st.info("🌐 Chargement des commentaires...")
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            self.quick_bypass_check()
            self.quick_delay(3000, 5000)
            
            all_addresses = set()
            last_count = 0
            consecutive_no_new = 0
            
            for scroll in range(max_scroll):
                st.info(f"📜 Scroll {scroll+1}/{max_scroll}")
                
                # Scroll rapide et efficace
                scroll_amount = random.randint(800, 1500)  # Scroll plus important
                self.fast_scroll(scroll_amount)
                
                # Attente réduite mais suffisante
                self.quick_delay(2000, 3500)
                
                # Extraction massive à chaque scroll
                new_addresses = self.extract_all_visible_content()
                current_count = len(all_addresses)
                all_addresses.update(new_addresses)
                new_count = len(all_addresses) - current_count
                
                st.info(f"📊 Scroll {scroll+1}: +{new_count} nouvelles | Total: {len(all_addresses)}")
                
                # Optimisation: arrêter si pas de nouvelles adresses
                if new_count == 0:
                    consecutive_no_new += 1
                    if consecutive_no_new >= 3:
                        st.warning("⏭️ Pas de nouvelles adresses depuis 3 scrolls, arrêt anticipé")
                        break
                else:
                    consecutive_no_new = 0
                
                # Pause minimale entre scrolls
                self.quick_delay(1000, 2000)
                
                # Scroll supplémentaire aléatoire pour plus de contenu
                if scroll % 3 == 0:  # Tous les 3 scrolls
                    self.page.evaluate("window.scrollBy(0, 400)")
                    self.quick_delay(1500, 2000)
            
            return list(all_addresses)
            
        except Exception as e:
            st.error(f"Erreur scraping commentaires: {e}")
            return []

    def quick_bypass_check(self):
        """Bypass rapide et efficace"""
        try:
            page_text = self.page.text_content("body")
            verification_keywords = ["Verifying", "Challenge", "security", "human"]
            
            if any(keyword in page_text for keyword in verification_keywords):
                st.warning("⚠️ Vérification détectée - Bypass rapide...")
                
                # Stratégie de bypass accélérée
                for i in range(3):
                    x, y = random.randint(100, 800), random.randint(100, 600)
                    self.page.mouse.move(x, y)
                    self.quick_delay(1000, 2000)
                
                # Attente réduite
                self.quick_delay(8000, 12000)  # 8-12 secondes seulement
                st.info("✅ Bypass terminé")
                
        except Exception as e:
            pass

    def save_to_excel_fast(self, addresses):
        """Sauvegarde optimisée"""
        if not addresses:
            return None
            
        # Tri par type de crypto pour meilleur aperçu
        def sort_key(addr):
            if addr.startswith('0x'):
                return (1, len(addr), addr)  # Ethereum
            elif addr.startswith('bc1'):
                return (2, len(addr), addr)  # Bitcoin Bech32
            elif len(addr) in [26, 27, 34] and addr[0] in '13':
                return (3, len(addr), addr)  # Bitcoin
            elif 32 <= len(addr) <= 44:
                return (4, len(addr), addr)  # Solana probable
            else:
                return (5, len(addr), addr)  # Autres
        
        sorted_addresses = sorted(addresses, key=sort_key)
        
        df = pd.DataFrame({
            'Adresse_Crypto': sorted_addresses,
            'Longueur': [len(addr) for addr in sorted_addresses],
            'Type_Crypto': [self.guess_crypto_type_fast(addr) for addr in sorted_addresses],
            'Validation': ['✅ Valide' for _ in sorted_addresses],
            'Date_Extraction': [datetime.now().strftime("%Y-%m-%d %H:%M:%S")] * len(sorted_addresses)
        })
        
        return df

    def guess_crypto_type_fast(self, address):
        """Classification rapide des crypto"""
        if address.startswith('0x') and len(address) == 42:
            return "🟦 Ethereum/ERC20"
        elif address.startswith('bc1'):
            return "🟨 Bitcoin (Bech32)"
        elif len(address) in [26, 27, 34] and address[0] in '13':
            return "🟨 Bitcoin (Legacy)"
        elif 32 <= len(address) <= 44 and not address.startswith('0x'):
            return "🟣 Solana"
        elif len(address) >= 25:
            return "⚪ Autre Crypto"
        else:
            return "❓ Inconnu"

    def close(self):
        try:
            self.page.close()
            self.context.close()
            self.browser.close()
            self.playwright.stop()
        except:
            pass


# ===================== Interface Streamlit Optimisée =====================
st.title("🚀 Scraper Crypto Ultra-Rapide - Version Optimisée")
st.markdown("### ⚡ Extraction maximisée avec vitesse optimisée")

# Configuration simplifiée mais efficace
with st.expander("⚙️ Configuration Rapide"):
    cookie_file = st.text_input("Fichier cookies", "playwright_state.json")
    max_scrolls_fast = st.number_input("Scrolls max", value=10, min_value=5, max_value=100)
    filter_length = st.number_input("Longueur min adresses", value=25, min_value=20, max_value=50)

post_url = st.text_input("URL Twitter/X", value="https://x.com/johnwesley1453/status/1962832639657676859")

# Options rapides
col1, col2 = st.columns(2)
with col1:
    scrape_post_fast = st.checkbox("✅ Scraper le post", value=True)
    scrape_comments_fast = st.checkbox("✅ Scraper commentaires", value=True)
with col2:
    only_solana = st.checkbox("🟣 Solana uniquement", value=True)
    show_live_count = st.checkbox("📊 Compteur temps réel", value=True)

if st.button("🚀 LANCEMENT ULTRA-RAPIDE"):
    if not post_url:
        st.error("❌ URL requise!")
        st.stop()

    st.info("⚡ Mode ultra-rapide activé!")
    
    scraper = OptimizedStealthCryptoScraper(cookie_file)
    all_addresses = set()

    try:
        # Progress bar
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        if scrape_post_fast:
            status_text.text("🔍 Scraping du post principal...")
            progress_bar.progress(0.2)
            
            post_addresses = scraper.scrape_twitter_post_fast(post_url)
            all_addresses.update(post_addresses)
            st.success(f"✅ Post: {len(post_addresses)} adresses")

        if scrape_comments_fast:
            status_text.text("💬 Scraping des commentaires...")
            progress_bar.progress(0.4)
            
            comment_addresses = scraper.scrape_twitter_comments_fast(post_url, max_scrolls_fast)
            all_addresses.update(comment_addresses)
            progress_bar.progress(0.8)

        # Filtrage final
        if only_solana:
            original_count = len(all_addresses)
            all_addresses = {addr for addr in all_addresses 
                           if 32 <= len(addr) <= 44 and not addr.startswith('0x')}
            st.info(f"🟣 Filtre Solana: {len(all_addresses)}/{original_count} conservées")

        # Filtrage par longueur
        all_addresses = {addr for addr in all_addresses if len(addr) >= filter_length}
        
        progress_bar.progress(1.0)
        status_text.text("✅ Extraction terminée!")

        if all_addresses:
            addresses_list = list(all_addresses)
            st.success(f"🎉 {len(addresses_list)} ADRESSES EXTRAITES!")
            
            # Métriques rapides
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("🎯 Total", len(addresses_list))
            with col2:
                solana_count = len([a for a in addresses_list if 32 <= len(a) <= 44 and not a.startswith('0x')])
                st.metric("🟣 Solana", solana_count)
            with col3:
                eth_count = len([a for a in addresses_list if a.startswith('0x')])
                st.metric("🟦 Ethereum", eth_count)
            with col4:
                btc_count = len([a for a in addresses_list if len(a) in [26,27,34] and a[0] in '13'])
                st.metric("🟨 Bitcoin", btc_count)
            
            # DataFrame optimisé
            df = scraper.save_to_excel_fast(addresses_list)
            st.subheader("📊 Résultats Extraits")
            st.dataframe(df, use_container_width=True)

            # Export rapide
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            col1, col2 = st.columns(2)
            with col1:
                csv_data = df.to_csv(index=False)
                st.download_button(
                    "📥 CSV Rapide", 
                    csv_data,
                    f"crypto_fast_{timestamp}.csv",
                    "text/csv"
                )
            with col2:
                from io import BytesIO
                buffer = BytesIO()
                df.to_excel(buffer, index=False, engine='openpyxl')
                st.download_button(
                    "📊 Excel Complet", 
                    buffer.getvalue(),
                    f"crypto_fast_{timestamp}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            # Aperçu optimisé
            with st.expander("👁️ Aperçu des Adresses"):
                for addr in addresses_list[:25]:  # Plus d'aperçu
                    col1, col2, col3 = st.columns([4, 1, 1])
                    with col1:
                        st.code(addr, language="text")
                    with col2:
                        st.caption(f"L:{len(addr)}")
                    with col3:
                        crypto_type = scraper.guess_crypto_type_fast(addr)
                        st.caption(crypto_type.split()[0])  # Juste l'emoji
                        
                if len(addresses_list) > 25:
                    st.write(f"➕ {len(addresses_list)-25} autres adresses...")
                    
        else:
            st.warning("❌ Aucune adresse trouvée")
            st.info("💡 Suggestions d'optimisation:")
            st.write("• Augmentez le nombre de scrolls à 50+")
            st.write("• Réduisez la longueur minimale à 20")
            st.write("• Désactivez le filtre Solana temporairement")
            st.write("• Vérifiez que la page contient bien des adresses")
            
    except Exception as e:
        st.error(f"💥 Erreur: {e}")
    finally:
        scraper.close()
        st.success("🏁 Scraper fermé - Traitement terminé!")