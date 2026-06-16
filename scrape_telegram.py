import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import time
import re

BASE_URL = "https://web.telegram.org/k/#@lesaffranchisleretour"

async def scrape_telegram_members_with_usernames(context):
    page = await context.new_page()
    await page.goto(BASE_URL, timeout=60000)
    
    print("Attente du chargement de la page...")
    await page.wait_for_timeout(5000)
    
    # Cliquer sur le nombre de membres dans la section info du groupe
    try:
        members_selector = 'div.bottom div.info span.i18n:has-text("members")'
        await page.wait_for_selector(members_selector, timeout=15000)
        
        members_info_parent = await page.query_selector('div.bottom div.info span:has(span.i18n:has-text("members"))')
        if members_info_parent:
            await members_info_parent.click()
            print("Clic sur le compteur de membres effectué")
        else:
            await page.click(members_selector)
            print("Clic alternatif sur le compteur de membres effectué")
        
        await page.wait_for_timeout(3000)
    except Exception as e:
        print(f"Impossible de cliquer sur le compteur de membres: {e}")
        return []
    
    # Attendre que la liste des membres s'affiche
    try:
        await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=10000)
        print("Liste des membres chargée")
    except:
        print("Erreur: Liste des membres non trouvée")
        return []
    
    members_data = []
    processed_members = set()
    
    # Charger tous les membres en faisant défiler
    print("Chargement de tous les membres...")
    all_member_elements = await load_all_members_progressive(page)
    
    total_members = len(all_member_elements)
    print(f"Total de {total_members} membres trouvés")
    
    # Traiter chaque membre
    for i in range(total_members):
        try:
            # Recharger la liste des éléments car ils peuvent changer après navigation
            current_member_elements = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
            
            if i >= len(current_member_elements):
                await reload_members_list(page)
                current_member_elements = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
                
                if i >= len(current_member_elements):
                    continue
            
            member_element = current_member_elements[i]
            
            # Récupérer l'ID et le nom avant de cliquer
            peer_id = await member_element.get_attribute('data-peer-id')
            name_element = await member_element.query_selector('span.peer-title')
            name = await name_element.inner_text() if name_element else ""
            
            if not peer_id or peer_id in processed_members:
                continue
                
            processed_members.add(peer_id)
            
            print(f"{i+1}/{total_members}: {name} (ID: {peer_id})")
            
            # Faire défiler vers l'élément si nécessaire
            await page.evaluate('(element) => element.scrollIntoView({block: "center"})', member_element)
            await page.wait_for_timeout(500)
            
            # Cliquer sur le membre pour ouvrir son profil
            await member_element.click()
            await page.wait_for_timeout(2500)  # Attendre le chargement du profil
            
            # Récupérer le username depuis le profil ouvert
            username, telegram_link = await extract_username_from_profile(page)
            
            # Ajouter aux données
            members_data.append({
                'peer_id': peer_id,
                'name': name.strip(),
                'username': username,
                'telegram_link': telegram_link
            })
            
            status = f"@{username}" if username else "pas de username"
            print(f"  -> {status}")
            
            # Retourner à la liste des membres
            await return_to_members_list(page)
            
            # Pause pour éviter la surcharge
            await page.wait_for_timeout(800)
            
            # Sauvegarder périodiquement
            if len(members_data) % 50 == 0:
                await save_progress(members_data, f"progress_{len(members_data)}")
                
        except Exception as e:
            print(f"Erreur pour le membre {i+1}: {e}")
            try:
                await return_to_members_list(page)
            except:
                await reload_members_list(page)
            continue
    
    print(f"Scraping terminé. {len(members_data)} membres traités.")
    await page.close()
    return members_data

async def load_all_members_progressive(page):
    """Charge tous les membres progressivement en faisant défiler la liste"""
    last_count = 0
    consecutive_same = 0
    max_consecutive = 8
    scroll_attempts = 0
    max_scroll_attempts = 100
    
    print("Chargement progressif des membres...")
    
    while consecutive_same < max_consecutive and scroll_attempts < max_scroll_attempts:
        # Compter les membres actuels
        current_members = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
        current_count = len(current_members)
        
        if current_count == last_count:
            consecutive_same += 1
        else:
            consecutive_same = 0
            print(f"Membres chargés: {current_count}")
            
        last_count = current_count
        scroll_attempts += 1
        
        # Faire défiler de plusieurs façons
        scroll_container = await page.query_selector('div.search-super-content-container.search-super-content-members')
        if scroll_container:
            # Méthode 1: Scroll vers le bas
            await page.evaluate('''(element) => {
                const scrollable = element.querySelector('.scrollable') || element;
                scrollable.scrollTop = scrollable.scrollHeight;
            }''', scroll_container)
            
            await page.wait_for_timeout(1000)
            
            # Méthode 2: Scroll par increment
            await page.evaluate('''(element) => {
                const scrollable = element.querySelector('.scrollable') || element;
                scrollable.scrollBy(0, 1500);
            }''', scroll_container)
            
            await page.wait_for_timeout(1000)
            
            # Méthode 3: Aller au dernier élément visible
            if current_members:
                try:
                    last_member = current_members[-1]
                    await page.evaluate('(element) => element.scrollIntoView({block: "end"})', last_member)
                    await page.wait_for_timeout(1000)
                except:
                    pass
    
    final_members = await page.query_selector_all('div.search-super-content-container.search-super-content-members ul.chatlist a.chatlist-chat')
    print(f"Chargement terminé: {len(final_members)} membres au total")
    
    return final_members

async def extract_username_from_profile(page):
    """Extrait le username et le lien Telegram du profil ouvert avec les nouveaux sélecteurs"""
    username = ""
    telegram_link = ""
    
    try:
        # Attendre que le profil se charge complètement
        await page.wait_for_timeout(500)
        
        # 1. Nouveau sélecteur: Chercher dans la section Username spécifique
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
        except Exception as e:
            print(f"    Erreur section Username: {e}")
        
        # 2. Nouveau sélecteur: Chercher dans la section Bio avec mentions
        try:
            bio_rows = await page.query_selector_all('div.row.row-with-icon.row-with-padding div.row-subtitle:has(span.i18n:text("Bio"))')
            for row in bio_rows:
                parent_row = await row.evaluate_handle('el => el.parentElement')
                bio_content = await parent_row.query_selector('div.row-title.pre-wrap')
                if bio_content:
                    # Chercher les mentions dans la bio
                    mention_links = await bio_content.query_selector_all('a.mention')
                    for link in mention_links:
                        href = await link.get_attribute('href')
                        text = await link.inner_text()
                        if href and href.startswith('https://t.me/'):
                            username = href.replace('https://t.me/', '')
                            telegram_link = href
                            print(f"    Username trouvé dans Bio (mention): @{username}")
                            return username, telegram_link
                        elif text and text.startswith('@'):
                            username = text.replace('@', '')
                            print(f"    Username trouvé dans Bio (texte): @{username}")
                            break
        except Exception as e:
            print(f"    Erreur section Bio: {e}")
        
        # 3. Méthode classique: Chercher toutes les mentions sur la page
        try:
            mention_elements = await page.query_selector_all('a.mention')
            for element in mention_elements:
                href = await element.get_attribute('href')
                text = await element.inner_text()
                
                if href and href.startswith('https://t.me/'):
                    potential_username = href.replace('https://t.me/', '')
                    if potential_username and not potential_username.startswith('+') and '/' not in potential_username:
                        username = potential_username
                        telegram_link = href
                        print(f"    Username trouvé (mention classique): @{username}")
                        return username, telegram_link
                elif text and text.startswith('@'):
                    username = text.replace('@', '')
                    print(f"    Username trouvé (texte mention): @{username}")
                    break
        except Exception as e:
            print(f"    Erreur mentions classiques: {e}")
        
        # 4. Chercher tous les liens t.me sur la page
        try:
            if not username:
                link_elements = await page.query_selector_all('a[href^="https://t.me/"]')
                for element in link_elements:
                    href = await element.get_attribute('href')
                    if href:
                        potential_username = href.replace('https://t.me/', '')
                        if potential_username and not potential_username.startswith('+') and '/' not in potential_username and len(potential_username) >= 3:
                            username = potential_username
                            telegram_link = href
                            print(f"    Username trouvé (lien t.me): @{username}")
                            return username, telegram_link
        except Exception as e:
            print(f"    Erreur liens t.me: {e}")
        
        # 5. Recherche par regex dans tout le texte de la page
        try:
            if not username:
                page_text = await page.evaluate('() => document.body.innerText')
                # Regex plus stricte pour éviter les faux positifs
                matches = re.findall(r'@([a-zA-Z][a-zA-Z0-9_]{2,31})', page_text)
                if matches:
                    # Prendre le premier username qui n'est pas un nom de canal commun
                    common_channels = ['undeadtag', 'umbrellamarketplace', 'channel', 'admin', 'bot']
                    for match in matches:
                        if match.lower() not in common_channels:
                            username = match
                            print(f"    Username trouvé (regex): @{username}")
                            break
        except Exception as e:
            print(f"    Erreur regex: {e}")
                    
    except Exception as e:
        print(f"    Erreur générale lors de l'extraction: {e}")
    
    if not username:
        print("    Aucun username trouvé")
    
    return username, telegram_link

async def return_to_members_list(page):
    """Retourne à la liste des membres de manière silencieuse et efficace"""
    try:
        # Méthode 1: Utiliser le bouton retour du navigateur
        await page.go_back()
        await page.wait_for_timeout(500)
        
        # Vérifier si on est bien sur la liste des membres
        try:
            await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=1000)
            return True
        except:
            pass
            
    except:
        pass
    
    try:
        # Méthode 2: Chercher les boutons de fermeture/retour
        close_buttons = [
            'button.btn-icon[title*="Back"]',
            'button.btn-icon.rip',
            'button[data-overlay-key]',
            '.btn-circle',
            'button.btn-icon.tgico-back',
            'button.btn-icon'
        ]
        
        for selector in close_buttons:
            try:
                button = await page.query_selector(selector)
                if button:
                    await button.click()
                    await page.wait_for_timeout(500)
                    
                    # Vérifier si on est revenu à la liste
                    try:
                        await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=800)
                        return True
                    except:
                        continue
            except:
                continue
                
    except:
        pass
    
    # Si toutes les méthodes échouent, recharger la liste
    await reload_members_list(page)
    return False

async def reload_members_list(page):
    """Recharge la liste des membres depuis le début"""
    try:
        await page.goto(BASE_URL, timeout=30000)
        await page.wait_for_timeout(1000)
        
        # Cliquer à nouveau sur le compteur de membres
        members_selector = 'div.bottom div.info span.i18n:has-text("members")'
        await page.wait_for_selector(members_selector, timeout=10000)
        
        members_info_parent = await page.query_selector('div.bottom div.info span:has(span.i18n:has-text("members"))')
        if members_info_parent:
            await members_info_parent.click()
        else:
            await page.click(members_selector)
        
        await page.wait_for_timeout(1000)
        await page.wait_for_selector('div.search-super-content-container.search-super-content-members', timeout=10000)
        
    except Exception as e:
        print(f"    Erreur lors du rechargement: {e}")

async def save_progress(members_data, filename):
    """Sauvegarde les données de progression"""
    try:
        df = pd.DataFrame(members_data)
        df.to_excel(f'{filename}.xlsx', index=False)
        print(f"    Progression sauvegardée: {filename}.xlsx")
    except Exception as e:
        print(f"    Erreur lors de la sauvegarde: {e}")

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
                '--disable-features=VizDisplayCompositor'
            ]
        )
        
        context = await browser.new_context(
            viewport={'width': 1400, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        try:
            print("=== DÉBUT DU SCRAPING TELEGRAM ===")
            members_with_usernames = await scrape_telegram_members_with_usernames(context)
            
            if members_with_usernames:
                # Créer un DataFrame et sauvegarder
                df = pd.DataFrame(members_with_usernames)
                df.to_excel('membres_telegram_FINAL.xlsx', index=False)
                
                print(f"\n=== SAUVEGARDE TERMINÉE ===")
                print(f"Fichier créé: membres_telegram_FINAL.xlsx")
                
                # Statistiques détaillées
                total_members = len(df)
                with_username = len(df[df['username'].str.len() > 0])
                with_link = len(df[df['telegram_link'].str.len() > 0])
                unique_usernames = len(df[df['username'].str.len() > 0]['username'].unique())
                
                print(f"\n=== RÉSULTATS FINAUX ===")
                print(f"- Total membres traités: {total_members}")
                print(f"- Avec username: {with_username}")
                print(f"- Avec lien Telegram: {with_link}")
                print(f"- Usernames uniques: {unique_usernames}")
                print(f"- Sans username: {total_members - with_username}")
                
                # Afficher les premiers membres avec username
                members_with_username = df[df['username'].str.len() > 0]
                if not members_with_username.empty:
                    print(f"\n=== APERÇU DES MEMBRES AVEC USERNAME ===")
                    for i, (_, member) in enumerate(members_with_username.head(15).iterrows()):
                        print(f"{i+1:2d}. {member['name'][:30]:<30} -> @{member['username']}")
                        
                # Statistiques des usernames les plus fréquents
                if with_username > 0:
                    username_counts = df[df['username'].str.len() > 0]['username'].value_counts()
                    print(f"\n=== USERNAMES LES PLUS FRÉQUENTS ===")
                    for username, count in username_counts.head(10).items():
                        print(f"@{username}: {count} fois")
                        
            else:
                print("❌ Aucun membre trouvé.")
                
        except Exception as e:
            print(f"❌ Erreur lors de l'exécution: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())