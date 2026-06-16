from telethon.sync import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
import pandas as pd
import asyncio


api_id = '21991868'  # Remplacez par votre API ID
api_hash = 'b8b47d9336d324823c97050909fe6d27'  # Remplacez par votre API Hash
phone = '+261346656886' 
# Le groupe à scraper
group_username = '@chezrass'

async def get_all_members():
    """Récupère TOUS les membres du groupe"""
    
    async with TelegramClient('session_name', api_id, api_hash) as client:
        print("📱 Connexion à Telegram...")
        await client.start(phone)
        
        print("🔍 Récupération du groupe...")
        group = await client.get_entity(group_username)
        
        print(f"✅ Groupe trouvé : {group.title}")
        print(f"👥 Membres totaux : {group.participants_count}")
        
        all_members = []
        offset = 0
        limit = 200  # Telegram permet max 200 par requête
        
        print("\\n⏳ Récupération des membres...")
        
        while True:
            participants = await client(GetParticipantsRequest(
                channel=group,
                filter=ChannelParticipantsSearch(''),
                offset=offset,
                limit=limit,
                hash=0
            ))
            
            if not participants.users:
                break
            
            for user in participants.users:
                member_data = {
                    'user_id': user.id,
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'username': user.username or '',
                    'phone': user.phone or '',
                    'is_bot': user.bot,
                    'telegram_link': f'https://t.me/{user.username}' if user.username else ''
                }
                all_members.append(member_data)
            
            offset += len(participants.users)
            print(f"✓ Récupérés : {offset}/{group.participants_count} membres")
            
            # Petit délai pour éviter les limites de taux
            await asyncio.sleep(1)
            
            if len(participants.users) < limit:
                break
        
        print(f"\\n✅ TERMINÉ ! {len(all_members)} membres récupérés")
        
        # Sauvegarder dans Excel
        df = pd.DataFrame(all_members)
        filename = 'membres_telegram_COMPLET_API @chezrass.xlsx'
        df.to_excel(filename, index=False)
        
        print(f"\\n📊 STATISTIQUES :")
        print(f"- Total membres : {len(df)}")
        print(f"- Avec username : {len(df[df['username'] != ''])}")
        print(f"- Avec téléphone : {len(df[df['phone'] != ''])}")
        print(f"- Bots : {len(df[df['is_bot'] == True])}")
        print(f"\\n💾 Sauvegardé dans : {filename}")
        
        return all_members

if __name__ == "__main__":
    asyncio.run(get_all_members())
