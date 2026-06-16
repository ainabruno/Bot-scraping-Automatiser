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

class OptimizedCryptoScraper:
    def __init__(self, cookie_file="playwright_state.json"):
        self.addresses = set()
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

    def extract_crypto_addresses_only(self, text):
        """Extraction ultra-précise des adresses crypto uniquement"""
        # Patterns crypto spécifiques et précis
        crypto_patterns = {
            'solana': r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b',
            'bitcoin': r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b',
            'bitcoin_bech32': r'\bbc1[a-z0-9]{39,59}\b',
            'ethereum': r'\b0x[a-fA-F0-9]{40}\b',
        }
        
        found_addresses = set()
        
        for crypto_type, pattern in crypto_patterns.items():
            matches = re.findall(pattern, text)
            for match in matches:
                if self.is_valid_crypto_address_strict(match):
                    found_addresses.add(match)
                    st.success(f"💰 {crypto_type.upper()}: {match}")
        
        return found_addresses

    def is_valid_crypto_address_strict(self, address):
        """Validation stricte pour éviter les faux positifs"""
        # Longueur basique
        if len(address) < 25 or len(address) > 70:
            return False
        
        # Mots interdits étendus (commentaires, URLs, etc.)
        forbidden_words = [
            'http', 'https', 'www', 'com', 'org', 'net', 'io', 'co', 'me',
            'twitter', 'x.com', 'status', 'follow', 'like', 'retweet', 'share',
            'click', 'link', 'watch', 'subscribe', 'channel', 'video',
            'image', 'photo', 'pic', 'img', 'jpeg', 'png', 'gif',
            'comment', 'reply', 'quote', 'thread', 'post',
            'AAAAAA', 'BBBBBB', 'CCCCCC', 'DDDDDD', 'EEEEEE',
            '000000', '111111', '222222', '333333', '444444',
            'example', 'test', 'demo', 'sample', 'placeholder'
        ]
        
        address_lower = address.lower()
        if any(word in address_lower for word in forbidden_words):
            return False
        
        # Diversité des caractères (éviter les répétitions)
        if len(set(address)) < 10:
            return False
        
        # Éviter les séquences trop répétitives
        for i in range(len(address) - 4):
            if address[i:i+3] == address[i+1:i+4]:
                return False
        
        # Validation spécifique par type
        if address.startswith('0x'):
            # Ethereum - doit être exactement 42 caractères
            return len(address) == 42 and all(c in '0123456789abcdefABCDEF' for c in address[2:])
        
        elif address.startswith('bc1'):
            # Bitcoin Bech32
            return 39 <= len(address) <= 59
        
        elif address[0] in '13':
            # Bitcoin Legacy
            return 25 <= len(address) <= 34
        
        elif 32 <= len(address) <= 44:
            # Solana probable
            # Vérifier qu'il n'y a pas de caractères interdits Solana
            solana_chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz123456789'
            return all(c in solana_chars for c in address)
        
        return True

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
                st.warning("⚠️ Vérification détectée - Bypass en cours...")
                
                # Attente intelligente avec feedback
                for i in range(6):
                    st.info(f"⏳ Attente {i*5+5}s... ({i+1}/6)")
                    self.random_delay(5000, 7000)
                    self.simulate_human_behavior()
                
                # Vérifier le succès
                self.page.reload(wait_until="load", timeout=120000)
                self.random_delay(5000, 8000)
                
                return True
                
            return True
            
        except Exception as e:
            st.warning(f"Bypass: {e}")
            return True

    def extract_from_page(self, url, extract_comments=True, max_scroll=3):
        """Extraction unifiée optimisée"""
        all_addresses = set()
        
        try:
            st.info(f"🔍 Connexion: {url}")
            
            # Navigation robuste
            for attempt in range(2):
                try:
                    self.page.goto(url, wait_until="load", timeout=120000)
                    st.success("✅ Page chargée!")
                    break
                except PlaywrightTimeoutError:
                    if attempt == 0:
                        st.warning("⏱️ Retry...")
                        self.random_delay(5000, 8000)
                    else:
                        raise
            
            # Bypass et attente initiale
            self.bypass_verification_check()
            self.random_delay(8000, 12000)
            
            # Extraction du contenu principal
            st.info("📄 Extraction du post principal...")
            main_content = self.extract_main_post_content()
            all_addresses.update(main_content)
            
            if extract_comments and max_scroll > 0:
                st.info("💬 Extraction des commentaires...")
                comment_addresses = self.extract_comments_content(max_scroll)
                all_addresses.update(comment_addresses)
            
        except Exception as e:
            st.error(f"Erreur extraction: {e}")
            
        return list(all_addresses)

    def extract_main_post_content(self):
        """Extraction focalisée du post principal"""
        addresses = set()
        
        # Sélecteurs spécifiques au contenu principal
        main_selectors = [
            'div[data-testid="tweetText"]',
            'article[data-testid="tweet"] div[lang] span',
            'article[data-testid="tweet"] div[dir="auto"] span'
        ]
        
        for selector in main_selectors:
            try:
                elements = self.page.query_selector_all(selector)
                st.info(f"🔍 Sélecteur '{selector}': {len(elements)} éléments")
                
                for element in elements:
                    try:
                        text = element.inner_text().strip()
                        if text and len(text) > 10:  # Filtrer textes courts
                            st.info(f"📝 Analyse: {text[:80]}...")
                            found = self.extract_crypto_addresses_only(text)
                            addresses.update(found)
                    except:
                        continue
                        
            except Exception as e:
                st.debug(f"Erreur sélecteur {selector}: {e}")
                continue
        
        return addresses

    def extract_comments_content(self, max_scroll):
        """Extraction optimisée des commentaires"""
        addresses = set()
        
        for scroll in range(max_scroll):
            st.info(f"📜 Scroll {scroll+1}/{max_scroll}")
            
            # Scroll progressif
            self.page.evaluate(f"window.scrollBy(0, {400 + scroll*200})")
            self.random_delay(4000, 6000)
            
            # Extraction après chaque scroll
            comment_selectors = [
                'div[data-testid="tweetText"]',
                'article div[lang] span',
                'div[dir="auto"] span'
            ]
            
            scroll_addresses = set()
            for selector in comment_selectors:
                try:
                    elements = self.page.query_selector_all(selector)
                    
                    for element in elements:
                        try:
                            text = element.inner_text().strip()
                            if text and len(text) > 10:
                                found = self.extract_crypto_addresses_only(text)
                                scroll_addresses.update(found)
                        except:
                            continue
                            
                except:
                    continue
            
            new_addresses = scroll_addresses - addresses
            addresses.update(scroll_addresses)
            
            st.info(f"📊 Scroll {scroll+1}: +{len(new_addresses)} nouvelles | Total: {len(addresses)}")
            
            # Pause intelligente
            self.random_delay(3000, 5000)
        
        return addresses

    def create_results_dataframe(self, addresses):
        """Création DataFrame optimisée"""
        if not addresses:
            return None
            
        df_data = []
        for addr in addresses:
            df_data.append({
                'Adresse': addr,
                'Longueur': len(addr),
                'Type': self.identify_crypto_type(addr),
                'Validité': '✅ Valide',
                'Extraction': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        
        df = pd.DataFrame(df_data)
        return df.sort_values(['Type', 'Longueur'])

    def identify_crypto_type(self, address):
        """Identification précise du type de crypto"""
        if len(address) == 42 and address.startswith('0x'):
            return "🟦 Ethereum"
        elif len(address) in [26, 27, 34] and address[0] in '13':
            return "🟠 Bitcoin Legacy"
        elif address.startswith('bc1'):
            return "🟡 Bitcoin Bech32"
        elif 32 <= len(address) <= 44 and not address.startswith('0x'):
            return "🟣 Solana"
        else:
            return "⚪ Autre"

    def close(self):
        """Fermeture propre"""
        try:
            self.page.close()
            self.context.close()
            self.browser.close()
            self.playwright.stop()
        except:
            pass


# ===================== Interface Streamlit Optimisée =====================
st.set_page_config(page_title="Crypto Address Extractor", page_icon="💰", layout="wide")

st.title("💰 Extracteur d'Adresses Crypto - Mode Précision")
st.markdown("### 🎯 Extraction uniquement des adresses cryptocurrency")

# Configuration simplifiée mais efficace
with st.expander("⚙️ Configuration"):
    col1, col2 = st.columns(2)
    with col1:
        cookie_file = st.text_input("Fichier cookies", "playwright_state.json")
        include_comments = st.checkbox("Inclure commentaires", value=True)
    with col2:
        max_scrolls = st.slider("Scrolls max", 1, 50, 30)
        crypto_filter = st.selectbox("Filtre crypto", 
                                   ["Toutes", "Solana uniquement", "Ethereum uniquement", "Bitcoin uniquement"])

# URL Input
post_url = st.text_input("🔗 URL du post Twitter/X:", value="https://x.com/Leo107111/status/1962834807437611235")

# Bouton principal
if st.button("🚀 EXTRAIRE LES ADRESSES", type="primary", use_container_width=True):
    if not post_url:
        st.error("❌ Veuillez entrer une URL valide")
        st.stop()

    # Initialisation
    with st.spinner("🔧 Initialisation du scraper..."):
        scraper = OptimizedCryptoScraper(cookie_file)

    # Extraction
    progress_bar = st.progress(0)
    status_placeholder = st.empty()
    
    try:
        with st.container():
            status_placeholder.info("🔍 Extraction en cours...")
            progress_bar.progress(25)
            
            # Extraction principale
            addresses = scraper.extract_from_page(
                post_url, 
                extract_comments=include_comments,
                max_scroll=max_scrolls
            )
            
            progress_bar.progress(75)
            
            # Filtrage selon sélection
            if crypto_filter != "Toutes":
                original_count = len(addresses)
                if crypto_filter == "Solana uniquement":
                    addresses = [a for a in addresses if 32 <= len(a) <= 44 and not a.startswith('0x')]
                elif crypto_filter == "Ethereum uniquement":
                    addresses = [a for a in addresses if len(a) == 42 and a.startswith('0x')]
                elif crypto_filter == "Bitcoin uniquement":
                    addresses = [a for a in addresses if (len(a) in [26,27,34] and a[0] in '13') or a.startswith('bc1')]
                
                st.info(f"🔍 Filtre {crypto_filter}: {len(addresses)}/{original_count} conservées")
            
            progress_bar.progress(100)
            
            # Affichage des résultats
            if addresses:
                st.success(f"🎉 {len(addresses)} adresses extraites avec succès!")
                
                # Statistiques détaillées
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("📊 Total", len(addresses))
                with col2:
                    solana = len([a for a in addresses if 32 <= len(a) <= 44 and not a.startswith('0x')])
                    st.metric("🟣 Solana", solana)
                with col3:
                    ethereum = len([a for a in addresses if a.startswith('0x')])
                    st.metric("🟦 Ethereum", ethereum)
                with col4:
                    bitcoin = len([a for a in addresses if len(a) in [26,27,34] and a[0] in '13'])
                    st.metric("🟠 Bitcoin", bitcoin)
                
                # DataFrame
                df = scraper.create_results_dataframe(addresses)
                st.subheader("📋 Adresses Extraites")
                st.dataframe(df, use_container_width=True, height=400)
                
                # Téléchargements
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    csv_data = df.to_csv(index=False, encoding='utf-8')
                    st.download_button(
                        "📥 CSV",
                        data=csv_data,
                        file_name=f"crypto_addresses_{timestamp}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                
                with col2:
                    # Excel export
                    from io import BytesIO
                    excel_buffer = BytesIO()
                    df.to_excel(excel_buffer, index=False, engine='openpyxl')
                    st.download_button(
                        "📊 Excel",
                        data=excel_buffer.getvalue(),
                        file_name=f"crypto_addresses_{timestamp}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                
                with col3:
                    # TXT simple (adresses seulement)
                    txt_data = '\n'.join(addresses)
                    st.download_button(
                        "📄 TXT",
                        data=txt_data,
                        file_name=f"crypto_addresses_{timestamp}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                
                # Aperçu rapide
                with st.expander("👁️ Aperçu des adresses"):
                    for i, addr in enumerate(addresses[:10]):
                        col_addr, col_type, col_len = st.columns([4, 2, 1])
                        with col_addr:
                            st.code(addr, language="text")
                        with col_type:
                            st.caption(scraper.identify_crypto_type(addr))
                        with col_len:
                            st.caption(f"L:{len(addr)}")
                    
                    if len(addresses) > 10:
                        st.info(f"... et {len(addresses)-10} autres adresses")
            
            else:
                st.warning("❌ Aucune adresse crypto trouvée")
                st.info("💡 Suggestions:")
                st.write("• Vérifiez l'URL du post")
                st.write("• Augmentez le nombre de scrolls")  
                st.write("• Changez le filtre crypto")
                st.write("• Vérifiez vos cookies de session")
                
    except Exception as e:
        st.error(f"💥 Erreur: {e}")
        
    finally:
        progress_bar.empty()
        status_placeholder.empty()
        scraper.close()
        st.success("🔚 Extraction terminée")

# Footer info
st.markdown("---")
st.markdown("**ℹ️ Info:** Cet outil extrait uniquement les adresses cryptocurrency valides, sans commentaires ni autres contenus.")