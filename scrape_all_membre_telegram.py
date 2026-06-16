import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import time
import re
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "https://web.telegram.org/k/#@lesaffranchisleretour"

async def scrape_telegram_members_with_usernames(context):
    page = await context.new_page()
    await page.goto(BASE_URL, timeout=60000)
    
    print("Attente du chargement de la page...")
    await page.wait_for_timeout(8000)  # Réduit de 5000 à 3000
    
    # Cliquer sur le nombre de membres dans la section info du groupe
    try:
        members_selector = 'div.bottom div.info span.i18n:has-text("members")'
        await page.wait_for_selector(members_selector, timeout=10000)  # Réduit de 15000 à 10000
        
        members_info_parent = await page.query_selector('div.bottom div.info span:has(span.i18n:has-text("members"))')
        if members_info_parent:
            await members_info_parent.click()
        else:
            await page.click(members_selector)
        
        await page.wait_for_timeout(2000)  # Réduit de 3000 à 2000
    except Exception as e:
        print(f"Impossible de cliquer sur le compteur de membres: {e}")
        return []
    
    # Attendre que la liste des membres s'affiche
    try:
        await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=8000)
        print("Liste des membres chargée")
    except:
        print("Erreur: Liste des membres non trouvée")
        return []
    
    members_data = []
    processed_members = set()
    
    # Charger tous les membres en faisant défiler plus rapidement
    print("Chargement de tous les membres...")
    all_member_elements = await load_all_members_fast(page)
    
    total_members = len(all_member_elements)
    print(f"Total de {total_members} membres trouvés")
    
    # Traitement par batch pour plus d'efficacité
    batch_size = 10
    for batch_start in range(0, total_members, batch_size):
        batch_end = min(batch_start + batch_size, total_members)
        batch_data = await process_members_batch(page, batch_start, batch_end, total_members, processed_members)
        members_data.extend(batch_data)
        
        # Sauvegarder plus fréquemment
        if len(members_data) % 25 == 0:  # Réduit de 50 à 25
            await save_progress(members_data, f"progress_{len(members_data)}")
    
    print(f"Scraping terminé. {len(members_data)} membres traités.")
    await page.close()
    return members_data

async def process_members_batch(page, start_idx, end_idx, total_members, processed_members):
    """Traite un batch de membres de manière optimisée"""
    batch_data = []
    
    for i in range(start_idx, end_idx):
        try:
            # Recharger la liste si nécessaire
            current_member_elements = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
            
            if i >= len(current_member_elements):
                await reload_members_list_fast(page)
                current_member_elements = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
                if i >= len(current_member_elements):
                    continue
            
            member_element = current_member_elements[i]
            
            # Récupérer l'ID et le nom
            peer_id = await member_element.get_attribute('data-peer-id')
            name_element = await member_element.query_selector('span.peer-title')
            name = await name_element.inner_text() if name_element else ""
            
            if not peer_id or peer_id in processed_members:
                continue
                
            processed_members.add(peer_id)
            
            print(f"{i+1}/{total_members}: {name} (ID: {peer_id})")
            
            # Scroll et clic optimisés
            await page.evaluate('(element) => element.scrollIntoView({block: "center"})', member_element)
            await page.wait_for_timeout(200)  # Réduit de 500 à 200
            
            await member_element.click()
            await page.wait_for_timeout(1500)  # Réduit de 2500 à 1500
            
            # Extraction rapide du username
            username, telegram_link = await extract_username_fast(page)
            
            batch_data.append({
                'peer_id': peer_id,
                'name': name.strip(),
                'username': username,
                'telegram_link': telegram_link
            })
            
            if username:
                print(f"  -> @{username}")
            # Si pas de username, on n'affiche rien (ligne vide)
            
            # Retour rapide à la liste
            await return_to_members_list_fast(page)
            await page.wait_for_timeout(300)  # Réduit de 800 à 300
                
        except Exception as e:
            try:
                await return_to_members_list_fast(page)
            except:
                await reload_members_list_fast(page)
            continue
    
    return batch_data

async def load_all_members_fast(page):
    """Charge tous les membres plus rapidement"""
    last_count = 0
    consecutive_same = 0
    max_consecutive = 5  # Réduit de 8 à 5
    scroll_attempts = 0
    max_scroll_attempts = 50  # Réduit de 100 à 50
    
    while consecutive_same < max_consecutive and scroll_attempts < max_scroll_attempts:
        current_members = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
        current_count = len(current_members)
        
        if current_count == last_count:
            consecutive_same += 1
        else:
            consecutive_same = 0
            if current_count % 100 == 0:  # Affichage moins fréquent
                print(f"Membres chargés: {current_count}")
            
        last_count = current_count
        scroll_attempts += 1
        
        # Scroll plus agressif
        scroll_container = await page.query_selector('div.search-super-content-container.search-super-content-members')
        if scroll_container:
            await page.evaluate('''(element) => {
                const scrollable = element.querySelector('.scrollable') || element;
                scrollable.scrollTop = scrollable.scrollHeight;
                scrollable.scrollBy(0, 3000);  // Scroll plus important
            }''', scroll_container)
            
            await page.wait_for_timeout(500)  # Réduit de 1000 à 500
            
            # Scroll vers le dernier élément plus rapidement
            if current_members:
                try:
                    last_member = current_members[-1]
                    await page.evaluate('(element) => element.scrollIntoView({block: "end"})', last_member)
                    await page.wait_for_timeout(300)  # Réduit
                except:
                    pass
    
    final_members = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
    print(f"Chargement terminé: {len(final_members)} membres au total")
    return final_members

async def extract_username_fast(page):
    """Extraction de username optimisée pour la vitesse"""
    username = ""
    telegram_link = ""
    
    try:
        await page.wait_for_timeout(800)  # Réduit de 2000 à 1000
        
        # Recherche prioritaire dans l'ordre d'efficacité
        # 1. Section Username (plus rapide)
        try:
            username_rows = await page.query_selector_all('div.row.row-with-icon.row-with-padding div.row-subtitle:has(span.i18n:text("Username"))')
            for row in username_rows:
                parent_row = await row.evaluate_handle('el => el.parentElement')
                title_element = await parent_row.query_selector('div.row-title')
                if title_element:
                    username_text = await title_element.inner_text()
                    if username_text and username_text.strip():
                        username = username_text.strip()
                        telegram_link = f"https://t.me/{username}"
                        print(f"    Username trouvé dans section Username: @{username}")
                        return username, telegram_link
        except:
            pass
        
        # 2. Mentions classiques (plus direct)
        try:
            mention_elements = await page.query_selector_all('a.mention')
            for element in mention_elements:
                href = await element.get_attribute('href')
                if href and href.startswith('https://t.me/'):
                    potential_username = href.replace('https://t.me/', '')
                    if potential_username and not potential_username.startswith('+') and '/' not in potential_username:
                        username = potential_username
                        telegram_link = href
                        print(f"    Username trouvé (mention classique): @{username}")
                        return username, telegram_link
        except:
            pass
        
        # 3. Liens t.me directs
        try:
            link_elements = await page.query_selector_all('a[href^="https://t.me/"]')
            for element in link_elements[:3]:  # Limite à 3 premiers liens
                href = await element.get_attribute('href')
                if href:
                    potential_username = href.replace('https://t.me/', '')
                    if potential_username and not potential_username.startswith('+') and '/' not in potential_username and len(potential_username) >= 3:
                        username = potential_username
                        telegram_link = href
                        print(f"    Username trouvé (lien t.me): @{username}")
                        return username, telegram_link
        except:
            pass
        
        # 4. Recherche regex rapide (en dernier recours)
        try:
            page_text = await page.evaluate('() => document.body.innerText')
            matches = re.findall(r'@([a-zA-Z][a-zA-Z0-9_]{2,31})', page_text[:500])  # Limite la recherche
            if matches:
                common_channels = ['undeadtag', 'umbrellamarketplace', 'channel', 'admin', 'bot']
                for match in matches[:5]:  # Limite à 5 premiers matches
                    if match.lower() not in common_channels:
                        username = match
                        print(f"    Username trouvé (regex): @{username}")
                        break
        except:
            pass
                    
    except:
        pass
    
    if not username:
        pass  # Ne rien afficher si pas de username
    
    return username, telegram_link

async def return_to_members_list_fast(page):
    """Retour rapide à la liste des membres"""
    try:
        await page.go_back()
        await page.wait_for_timeout(800)  # Réduit de 2000 à 1000
        
        try:
            await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=2000)
            return True
        except:
            pass
    except:
        pass
    
    # Essai rapide des boutons
    try:
        close_buttons = ['button.btn-icon.tgico-back', 'button.btn-icon']
        for selector in close_buttons[:2]:  # Limite à 2 boutons
            try:
                button = await page.query_selector(selector)
                if button:
                    await button.click()
                    await page.wait_for_timeout(800)
                    try:
                        await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=1500)
                        return True
                    except:
                        continue
            except:
                continue
    except:
        pass
    
    await reload_members_list_fast(page)
    return False

async def reload_members_list_fast(page):
    """Rechargement rapide de la liste"""
    try:
        await page.goto(BASE_URL, timeout=20000)  # Réduit timeout
        await page.wait_for_timeout(1000)  # Réduit
        
        members_selector = 'div.bottom div.info span.i18n:has-text("members")'
        await page.wait_for_selector(members_selector, timeout=8000)
        
        members_info_parent = await page.query_selector('div.bottom div.info span:has(span.i18n:has-text("members"))')
        if members_info_parent:
            await members_info_parent.click()
        else:
            await page.click(members_selector)
        
        await page.wait_for_timeout(2000)
        await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=8000)
    except:
        pass

async def save_progress(members_data, filename):
    """Sauvegarde rapide en arrière-plan"""
    try:
        df = pd.DataFrame(members_data)
        df.to_excel(f'{filename}.xlsx', index=False)
    except:
        pass

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-extensions',
                '--disable-plugins-discovery',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=VizDisplayCompositor',
                '--disable-images',  # Désactive les images pour plus de vitesse
                '--disable-javascript-harmony-shipping',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding'
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1400, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        try:
            print("=== DÉBUT DU SCRAPING TELEGRAM OPTIMISÉ ===")
            start_time = time.time()
            
            members_with_usernames = await scrape_telegram_members_with_usernames(context)
            
            end_time = time.time()
            duration = end_time - start_time
            
            if members_with_usernames:
                df = pd.DataFrame(members_with_usernames)
                df.to_excel('membres_telegram_FINAL_FAST.xlsx', index=False)
                
                print(f"\n=== SCRAPING TERMINÉ EN {duration/60:.1f} MINUTES ===")
                print(f"Vitesse: {len(members_with_usernames)/(duration/3600):.0f} membres/heure")
                
                total_members = len(df)
                with_username = len(df[df['username'].str.len() > 0])
                
                print(f"\n=== RÉSULTATS ===")
                print(f"- Total membres: {total_members}")
                print(f"- Avec username: {with_username}")
                print(f"- Pourcentage: {(with_username/total_members)*100:.1f}%")
                        
            else:
                print("❌ Aucun membre trouvé.")
                
        except Exception as e:
            print(f"❌ Erreur: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())