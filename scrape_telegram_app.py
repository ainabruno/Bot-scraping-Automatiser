import pyautogui
import pygetwindow as gw
import time
import pandas as pd
import pyperclip
import tkinter as tk
from tkinter import messagebox
import json
import keyboard  # Pour la détection des touches

class SimpleTelegramAutomation:
    def __init__(self):
        self.members = []
        self.window = None
        
    def find_telegram_window(self):
        """Trouve et active la fenêtre Telegram"""
        print("🔍 Recherche de Telegram Desktop...")
        
        # Recherche parmi toutes les fenêtres
        windows = gw.getAllWindows()
        telegram_windows = []
        
        for window in windows:
            # Recherche plus spécifique pour Telegram
            title_lower = window.title.lower()
            if (('telegram' in title_lower and 'desktop' in title_lower) or
                window.title == 'Telegram' or
                'telegram.exe' in title_lower) and window.visible:
                telegram_windows.append(window)
                print(f"Fenêtre Telegram trouvée: {window.title}")
        
        if not telegram_windows:
            print("Fenêtres disponibles:")
            for window in windows:
                if window.visible and window.title.strip():
                    print(f"  - {window.title}")
            
            messagebox.showerror("Erreur", 
                "Telegram Desktop non trouvé!\n"
                "Assurez-vous que:\n"
                "- Telegram Desktop est ouvert (pas la version web)\n"
                "- Vous êtes connecté\n"
                "- La fenêtre est visible")
            return False
        
        # Prendre la première fenêtre Telegram trouvée
        self.window = telegram_windows[0]
        
        # Redimensionner et activer
        try:
            self.window.activate()
            self.window.maximize()  # Maximiser pour plus de visibilité
            time.sleep(2)
            print(f"✅ Telegram trouvé: {self.window.title}")
            return True
        except:
            print("⚠️ Impossible d'activer la fenêtre")
            return False
    
    def manual_positioning_guide(self):
        """Guide pour positionner manuellement"""
        root = tk.Tk()
        root.withdraw()
        
        steps = [
            "1. Ouvrez Telegram Desktop",
            "2. Allez dans le canal 'Les Affranchis'",
            "3. Cliquez sur le nombre de membres (ex: 2762)",
            "4. Attendez que la liste des membres s'affiche",
            "5. Positionnez la liste au début (tout en haut)",
            "6. Fermez cette fenêtre pour continuer"
        ]
        
        message = "GUIDE DE PRÉPARATION:\n\n" + "\n".join(steps)
        messagebox.showinfo("Préparation manuelle", message)
    
    def get_screen_coordinates(self):
        """Aide à obtenir les coordonnées d'écran"""
        print("\n🎯 CALIBRAGE DES COORDONNÉES")
        print("Déplacez votre souris et appuyez sur ESPACE pour capturer la position")
        print("Appuyez sur ÉCHAP pour arrêter le calibrage")
        
        coordinates = {}
        
        positions_needed = [
            ("zone_membres", "Zone de la liste des membres"),
            ("scroll_area", "Zone de scroll dans la liste"),
            ("first_member", "Premier membre de la liste")
        ]
        
        for pos_name, description in positions_needed:
            print(f"\n👆 Positionnez la souris sur: {description}")
            print("Appuyez sur ESPACE quand c'est bon...")
            
            while True:
                try:
                    # Utiliser keyboard au lieu de pyautogui.isKeyPressed
                    if keyboard.is_pressed('space'):
                        x, y = pyautogui.position()
                        coordinates[pos_name] = (x, y)
                        print(f"✅ {pos_name}: ({x}, {y})")
                        time.sleep(1)  # Éviter les captures multiples
                        break
                    elif keyboard.is_pressed('esc'):
                        return None
                    time.sleep(0.1)
                except Exception as e:
                    print(f"Erreur détection touche: {e}")
                    # Fallback : demander à l'utilisateur de cliquer
                    input(f"Appuyez sur ENTRÉE après avoir positionné la souris sur: {description}")
                    x, y = pyautogui.position()
                    coordinates[pos_name] = (x, y)
                    print(f"✅ {pos_name}: ({x}, {y})")
                    break
        
        return coordinates
    
    def extract_members_simple(self, coordinates):
        """Extraction simple par copie de texte"""
        print("🚀 Début de l'extraction...")
        
        if not coordinates:
            print("❌ Coordonnées non définies")
            return []
        
        members = []
        scroll_area = coordinates.get('scroll_area', (600, 400))
        member_area = coordinates.get('zone_membres', (500, 300))
        
        last_member_count = 0
        stable_count = 0
        max_scrolls = 200  # Maximum de scrolls
        
        for scroll_num in range(max_scrolls):
            try:
                # Vérifier si l'utilisateur veut arrêter
                if keyboard.is_pressed('esc'):
                    print("⚠️ Arrêt demandé par l'utilisateur")
                    break
            except:
                pass
            
            # Cliquer dans la zone des membres
            pyautogui.click(member_area[0], member_area[1])
            time.sleep(0.5)
            
            # Sélectionner tout le texte visible (Ctrl+A)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.5)
            
            # Copier le texte
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.5)
            
            # Récupérer le texte
            text = pyperclip.paste()
            
            # Parser les membres
            current_members = self.parse_members_from_text(text)
            
            # Compter les nouveaux membres
            new_members = 0
            for member in current_members:
                if member not in members:
                    members.append(member)
                    new_members += 1
            
            print(f"📊 Scroll {scroll_num + 1}: {len(members)} membres total (+{new_members} nouveaux)")
            
            # Vérifier si on a fini
            if new_members == 0:
                stable_count += 1
                if stable_count >= 5:  # 5 scrolls sans nouveaux membres
                    print("✅ Tous les membres récupérés")
                    break
            else:
                stable_count = 0
            
            # Scroll vers le bas
            pyautogui.click(scroll_area[0], scroll_area[1])
            pyautogui.scroll(-10)  # Scroll vers le bas
            time.sleep(1)  # Pause entre les scrolls
            
            # Sauvegarde intermédiaire tous les 50 membres
            if len(members) % 50 == 0 and len(members) != last_member_count:
                self.save_intermediate_results(members)
                last_member_count = len(members)
        
        return members
    
    def parse_members_from_text(self, text):
        """Parse simple des membres depuis le texte"""
        members = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 2:
                continue
            
            # Ignorer les éléments d'interface
            skip_words = ['members', 'online', 'subscribers', 'search', 'info', 'settings', 'last seen', 'recently']
            if any(word in line.lower() for word in skip_words):
                continue
            
            # Extraire nom et username
            if '@' in line and len(line) < 100:  # Éviter les longues lignes
                # Ligne avec username
                parts = line.split('@')
                if len(parts) >= 2:
                    name = parts[0].strip()
                    username = parts[1].strip().split()[0] if parts[1].strip() else ""
                else:
                    continue
            else:
                # Ligne sans username (juste le nom)
                name = line
                username = ""
            
            # Valider le nom (plus permissif)
            if name and len(name) > 1 and len(name) < 50:
                # Vérifier que ce n'est pas juste des caractères spéciaux
                if any(c.isalpha() for c in name):
                    member_info = {
                        'name': name,
                        'username': username,
                        'telegram_link': f"https://t.me/{username}" if username else "",
                        'extracted_from': line
                    }
                    
                    # Éviter les doublons
                    if not any(m['name'] == name and m['username'] == username for m in members):
                        members.append(member_info)
        
        return members
    
    def save_intermediate_results(self, members):
        """Sauvegarde intermédiaire"""
        try:
            df = pd.DataFrame(members)
            filename = f'telegram_members_backup_{len(members)}.xlsx'
            df.to_excel(filename, index=False)
            print(f"💾 Sauvegarde: {filename}")
        except Exception as e:
            print(f"Erreur sauvegarde: {e}")
    
    def save_final_results(self, members):
        """Sauvegarde finale avec statistiques"""
        if not members:
            print("❌ Aucun membre à sauvegarder")
            return
        
        # Créer le DataFrame
        df = pd.DataFrame(members)
        
        # Nettoyer les données
        df = df.drop_duplicates(subset=['name', 'username'])
        df['name'] = df['name'].str.strip()
        df['username'] = df['username'].str.strip()
        
        # Sauvegarder en Excel
        filename = f'members_telegram_desktop_final.xlsx'
        df.to_excel(filename, index=False)
        
        # Sauvegarder en JSON aussi
        json_filename = 'members_telegram_desktop_final.json'
        df.to_json(json_filename, orient='records', indent=2)
        
        # Statistiques
        total = len(df)
        with_username = len(df[df['username'] != ''])
        
        print(f"\n🎉 EXTRACTION TERMINÉE!")
        print(f"📊 Total membres: {total}")
        print(f"📊 Avec username: {with_username} ({(with_username/total*100):.1f}%)")
        print(f"💾 Fichier principal: {filename}")
        print(f"💾 Fichier JSON: {json_filename}")
        
        return filename

def main():
    """Fonction principale simplifiée"""
    print("🤖 === TELEGRAM DESKTOP AUTOMATION (VERSION CORRIGÉE) ===")
    
    automation = SimpleTelegramAutomation()
    
    try:
        # Étape 1: Trouver Telegram
        if not automation.find_telegram_window():
            return
        
        # Étape 2: Guide manuel
        automation.manual_positioning_guide()
        
        # Étape 3: Calibrage des coordonnées
        print("\n🎯 Calibrage des coordonnées...")
        coordinates = automation.get_screen_coordinates()
        
        if not coordinates:
            print("❌ Calibrage annulé")
            return
        
        # Étape 4: Extraction des membres
        print("\n📄 Début de l'extraction...")
        input("Appuyez sur ENTRÉE quand vous êtes prêt...")
        
        members = automation.extract_members_simple(coordinates)
        
        # Étape 5: Sauvegarde finale
        if members:
            automation.save_final_results(members)
        else:
            print("❌ Aucun membre extrait")
    
    except KeyboardInterrupt:
        print("\n⚠️ Arrêt manuel - Sauvegarde des données...")
        if automation.members:
            automation.save_final_results(automation.members)
    
    except Exception as e:
        print(f"❌ Erreur: {e}")
        if automation.members:
            automation.save_final_results(automation.members)

if __name__ == "__main__":
    import sys
    
    try:
        main()
    except ImportError as e:
        print(f"❌ Dépendance manquante: {e}")
        print("\nInstallez les dépendances avec:")
        print("pip install pyautogui pygetwindow pandas openpyxl pyperclip keyboard")
    except Exception as e:
        print(f"❌ Erreur: {e}")