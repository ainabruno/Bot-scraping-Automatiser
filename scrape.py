import re
import csv
import time
import requests
from urllib.parse import urljoin, urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import random
import json

try:
    from googlesearch import search
except ImportError:
    print("Installer googlesearch-python: pip install googlesearch-python")
    search = None

from playwright.sync_api import sync_playwright
import streamlit as st
import pandas as pd

# -----------------------------
# CONFIGURATION AMÉLIORÉE
# -----------------------------
EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

# Configuration conservative pour éviter le rate limiting
GOOGLE_RESULTS = 50  # Réduit pour éviter le blocage
MAX_RETRIES = 3
MAX_WORKERS = 2  # Réduit pour être moins agressif
PAUSE_BETWEEN_SITES = 5  # Augmenté
MAX_EMAILS_PER_SITE = 50
MAX_PAGES_PER_SITE = 8

# User agents pour éviter la détection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# Sites malgaches pré-définis pour éviter Google Search
MADAGASCAR_SITES = [
    "https://www.instat.mg",
    "https://www.mg.undp.org",
    "https://www.banky-foiben.mg",
    "https://www.edbm.mg",
    "https://www.presidence.gov.mg",
    "https://www.mfb.mg",
    "https://www.groupement-entreprises.mg",
    "https://www.chambre-commerce.mg",
    "https://www.orange.mg",
    "https://www.telma.mg",
    "https://www.airtel.mg",
    "https://www.bni.mg",
    "https://www.bmoi.mg",
    "https://www.unionbank.mg",
    "https://www.plaza-hotel.mg",
    "https://www.hotel-colbert.mg",
    "https://www.air-madagascar.mg",
    "https://www.port-toamasina.mg",
    "https://madagascar-tourisme.com",
    "https://www.madagascar-tribune.com",
    "https://www.newsmada.com",
    "https://www.midi-madagasikara.mg",
    "https://region-analamanga.mg",
    "https://region-atsinanana.mg",
    "https://region-anosy.mg",
    "https://region-diana.mg"
]

# Requêtes de recherche simplifiées (une seule pour éviter rate limit)
SINGLE_SEARCH_QUERIES = [
    'Madagascar entreprise contact email',
    'site:mg contact',
    'Madagascar business directory'
]

# -----------------------------
# ALTERNATIVE À GOOGLE SEARCH
# -----------------------------
def search_with_duckduckgo(query, max_results=30):
    """Alternative avec DuckDuckGo (pas de rate limit)"""
    results = []
    try:
        headers = {
            'User-Agent': random.choice(USER_AGENTS)
        }
        
        # URL DuckDuckGo
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extraire les liens de résultats
            for result in soup.find_all('a', class_='result__a'):
                href = result.get('href')
                if href and ('mg' in href or 'madagascar' in href.lower()):
                    results.append(href)
                    if len(results) >= max_results:
                        break
        
        time.sleep(2)  # Pause entre requêtes
        
    except Exception as e:
        st.warning(f"Erreur DuckDuckGo: {e}")
    
    return results

def get_madagascar_sites_safe():
    """Récupère des sites malgaches de manière sûre"""
    all_sites = set()
    
    # Ajouter les sites pré-définis
    all_sites.update(MADAGASCAR_SITES)
    st.info(f"✅ {len(MADAGASCAR_SITES)} sites pré-définis ajoutés")
    
    # Essayer une recherche Google très limitée
    if search:
        try:
            st.info("🔍 Recherche Google limitée (1 requête)...")
            query = "Madagascar entreprise contact"
            results = list(search(query, num_results=20, sleep_interval=10, lang='fr'))
            all_sites.update(results)
            st.success(f"✅ {len(results)} sites supplémentaires via Google")
            time.sleep(15)  # Pause longue
        except Exception as e:
            st.warning(f"Google bloqué: {e}")
    
    # Alternative avec DuckDuckGo
    st.info("🦆 Recherche alternative avec DuckDuckGo...")
    for query in ['Madagascar entreprise contact', 'Madagascar société email', 'Madagascar business']:
        try:
            results = search_with_duckduckgo(query, 20)
            all_sites.update(results)
            st.info(f"DuckDuckGo: +{len(results)} sites pour '{query}'")
        except Exception as e:
            st.warning(f"Erreur DuckDuckGo '{query}': {e}")
    
    return list(all_sites)

def search_in_sitemap(base_url):
    """Cherche des URLs dans le sitemap d'un site"""
    urls = []
    try:
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/robots.txt"
        ]
        
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        
        for sitemap_url in sitemap_urls:
            try:
                response = requests.get(sitemap_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    # Chercher des URLs dans le contenu
                    content = response.text
                    found_urls = re.findall(r'<loc>(.*?)</loc>', content)
                    urls.extend(found_urls[:10])  # Limiter à 10 URLs
                    break
            except:
                continue
                
    except Exception as e:
        print(f"Erreur sitemap {base_url}: {e}")
    
    return urls

# -----------------------------
# FONCTIONS D'EXTRACTION AMÉLIORÉES
# -----------------------------
def extract_emails_robust(url, page):
    """Extraction d'emails ultra-robuste"""
    emails = set()
    
    try:
        # Configuration page
        page.set_extra_http_headers({
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8'
        })
        
        page.goto(url, timeout=60000, wait_until='domcontentloaded')
        time.sleep(3)
        
        # Attendre que la page se charge complètement
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        
        # Obtenir tout le contenu
        content = page.content().lower()
        
        # Patterns d'emails très larges
        email_patterns = [
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(?:mg|com|org|net|fr|edu|gov)",
            r"[a-zA-Z0-9._%+-]+\s*@\s*[a-zA-Z0-9.-]+\s*\.\s*(?:mg|com|org|net|fr)",
            r"[a-zA-Z0-9._%+-]+\[at\][a-zA-Z0-9.-]+\[dot\](?:mg|com|org)",
            r"[a-zA-Z0-9._%+-]+\(at\)[a-zA-Z0-9.-]+\(dot\)(?:mg|com|org)",
            r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.(?:mg|com|org|net|fr))"
        ]
        
        for pattern in email_patterns:
            try:
                matches = re.findall(pattern, content, flags=re.IGNORECASE)
                for match in matches:
                    # Nettoyage
                    if isinstance(match, tuple):
                        email = match[0]
                    else:
                        email = match
                    
                    email = email.replace("[at]", "@").replace("(at)", "@")
                    email = email.replace("[dot]", ".").replace("(dot)", ".")
                    email = email.replace(" ", "").strip().lower()
                    
                    # Validation
                    if (email and "@" in email and "." in email.split("@")[-1] 
                        and len(email) > 5 and email.count("@") == 1):
                        emails.add(email)
            except Exception as e:
                print(f"Erreur pattern {pattern}: {e}")
                continue
        
        # Recherche spécifique dans les éléments HTML
        try:
            # Links mailto
            for link in page.query_selector_all('a[href*="mailto"]'):
                href = link.get_attribute("href")
                if href:
                    email = href.replace("mailto:", "").split("?")[0].lower()
                    if "@" in email and "." in email.split("@")[-1]:
                        emails.add(email)
        except:
            pass
        
        # Recherche dans le texte visible
        try:
            text_content = page.inner_text("body")
            simple_emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text_content)
            emails.update([e.lower() for e in simple_emails])
        except:
            pass
        
    except Exception as e:
        print(f"⚠️ Erreur extraction {url}: {e}")
    
    # Filtrage final
    valid_emails = set()
    blocked_domains = ['example.com', 'test.com', 'noreply', 'no-reply']
    
    for email in emails:
        domain = email.split("@")[-1] if "@" in email else ""
        if (email and not any(blocked in email for blocked in blocked_domains) 
            and len(email.split("@")[0]) > 1):
            valid_emails.add(email)
    
    return valid_emails

def find_contact_pages_advanced(url, page, domain):
    """Trouve les pages de contact de manière avancée"""
    contact_urls = set()
    
    try:
        page.goto(url, timeout=30000)
        time.sleep(2)
        
        # Recherche de liens de contact
        contact_keywords = [
            "contact", "contactez", "nous-contacter", "contactez-nous",
            "about", "apropos", "a-propos", "equipe", "team", "staff",
            "direction", "administration", "bureau"
        ]
        
        # Chercher dans tous les liens
        links = page.query_selector_all("a")
        for link in links:
            try:
                href = link.get_attribute("href")
                text = link.inner_text().lower() if link.inner_text() else ""
                
                if href:
                    href_lower = href.lower()
                    if (any(keyword in href_lower for keyword in contact_keywords) or
                        any(keyword in text for keyword in contact_keywords)):
                        
                        full_url = urljoin(url, href)
                        if domain in full_url:
                            contact_urls.add(full_url)
            except:
                continue
                
        # Ajouter des URLs communes
        common_paths = ["/contact", "/contactez-nous", "/about", "/equipe"]
        for path in common_paths:
            contact_urls.add(urljoin(url, path))
            
    except Exception as e:
        print(f"Erreur recherche contact {url}: {e}")
    
    return list(contact_urls)[:5]  # Limiter à 5

def process_single_site(site_url, secteur="", ville=""):
    """Traite un site unique de manière complète"""
    found_emails = []
    domain = urlparse(site_url).netloc
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # URLs à analyser
            urls_to_check = [site_url]
            
            # Ajouter les pages de contact
            try:
                contact_pages = find_contact_pages_advanced(site_url, page, domain)
                urls_to_check.extend(contact_pages)
            except:
                pass
            
            # Ajouter des URLs du sitemap
            try:
                sitemap_urls = search_in_sitemap(site_url)
                urls_to_check.extend(sitemap_urls[:3])
            except:
                pass
            
            # Analyser chaque URL
            for i, url in enumerate(urls_to_check):
                if i >= MAX_PAGES_PER_SITE:
                    break
                
                try:
                    emails = extract_emails_robust(url, page)
                    
                    for email in emails:
                        if len(found_emails) >= MAX_EMAILS_PER_SITE:
                            break
                            
                        found_emails.append({
                            "site": site_url,
                            "email": email,
                            "page": url,
                            "secteur": secteur,
                            "ville": ville,
                            "domain": email.split("@")[-1]
                        })
                    
                    time.sleep(2)  # Pause entre pages
                    
                except Exception as e:
                    print(f"Erreur sur {url}: {e}")
                    continue
            
            browser.close()
            
    except Exception as e:
        print(f"Erreur globale {site_url}: {e}")
    
    return found_emails

# -----------------------------
# INTERFACE STREAMLIT
# -----------------------------
st.title("🇲🇬 Scraper Emails Madagascar - Anti-Rate-Limit")
st.markdown("### Version optimisée pour éviter les blocages Google")

# Avertissement
st.info("⚠️ Cette version utilise des méthodes anti-blocage : sites pré-définis + DuckDuckGo + recherche limitée Google")

col1, col2 = st.columns(2)
with col1:
    secteur = st.text_input("Secteur", placeholder="Tourisme, Banque, Commerce...")
    ville = st.text_input("Ville", placeholder="Antananarivo, Toamasina...")

with col2:
    domain_filter = st.text_input("Filtrer domaines", placeholder=".mg, .com")
    max_sites = st.number_input("Max sites à analyser", value=30, min_value=10, max_value=100)

# Options
use_predefined = st.checkbox("Utiliser les sites pré-définis", value=True)
use_duckduckgo = st.checkbox("Utiliser DuckDuckGo", value=True)
use_google_limited = st.checkbox("Google (risque de blocage)", value=False)

if st.button("🚀 Lancer l'extraction sécurisée", type="primary"):
    
    # Collecte des sites
    all_sites = []
    
    if use_predefined:
        all_sites.extend(MADAGASCAR_SITES)
        st.success(f"✅ {len(MADAGASCAR_SITES)} sites pré-définis ajoutés")
    
    if use_duckduckgo:
        st.info("🦆 Recherche DuckDuckGo en cours...")
        duck_sites = []
        for query in ['Madagascar entreprise', 'Madagascar contact', 'site:mg business']:
            results = search_with_duckduckgo(query, 15)
            duck_sites.extend(results)
            time.sleep(3)
        
        all_sites.extend(duck_sites)
        st.success(f"✅ {len(duck_sites)} sites DuckDuckGo ajoutés")
    
    if use_google_limited and search:
        st.info("🔍 Recherche Google très limitée...")
        try:
            google_sites = list(search("Madagascar contact", num_results=10, sleep_interval=15))
            all_sites.extend(google_sites)
            st.success(f"✅ {len(google_sites)} sites Google ajoutés")
            time.sleep(10)
        except Exception as e:
            st.warning(f"Google bloqué: {e}")
    
    # Nettoyage et limitation
    unique_sites = list(set(all_sites))[:max_sites]
    
    if not unique_sites:
        st.error("❌ Aucun site trouvé. Activez au moins une option de recherche.")
        st.stop()
    
    st.info(f"📊 {len(unique_sites)} sites uniques sélectionnés pour analyse")
    
    # Affichage aperçu
    with st.expander("Aperçu des sites"):
        for i, site in enumerate(unique_sites[:15]):
            st.write(f"{i+1}. {site}")
        if len(unique_sites) > 15:
            st.write(f"... et {len(unique_sites)-15} autres")
    
    # Extraction
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_single_site, site, secteur, ville): site 
            for site in unique_sites
        }
        
        completed = 0
        
        for future in as_completed(futures):
            site = futures[future]
            completed += 1
            
            try:
                site_results = future.result()
                
                # Filtrage
                if domain_filter:
                    filters = [f.strip().lower() for f in domain_filter.split(",")]
                    site_results = [
                        r for r in site_results 
                        if any(f in r["email"].lower() for f in filters)
                    ]
                
                results.extend(site_results)
                
                status_text.text(f"✅ Site {completed}/{len(unique_sites)}: {len(site_results)} emails sur {site}")
                
            except Exception as e:
                status_text.text(f"❌ Erreur {site}: {str(e)[:50]}...")
            
            progress_bar.progress(completed / len(unique_sites))
            time.sleep(1)
    
    # Résultats
    if results:
        df = pd.DataFrame(results)
        df_unique = df.drop_duplicates(subset=['email'])
        
        st.success(f"🎉 {len(df_unique)} emails uniques extraits de {len(df['site'].unique())} sites")
        
        # Stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Emails uniques", len(df_unique))
        with col2:
            st.metric("Sites avec emails", len(df_unique['site'].unique()))
        with col3:
            mg_emails = len(df_unique[df_unique['domain'].str.contains('.mg', na=False)])
            st.metric("Emails .mg", mg_emails)
        
        # Tableau
        st.dataframe(df_unique, use_container_width=True)
        
        # Export
        csv_data = df_unique.to_csv(index=False, encoding='utf-8')
        filename = f"emails_madagascar_{int(time.time())}.csv"
        
        st.download_button(
            "📥 Télécharger CSV",
            data=csv_data,
            file_name=filename,
            mime="text/csv"
        )
        
    else:
        st.error("❌ Aucun email trouvé")
        st.info("💡 Essayez d'activer plus d'options de recherche ou relancez plus tard")

st.markdown("---")
st.markdown("**🛡️ Version anti-blocage** - Utilise plusieurs sources pour éviter les limitations")