##Creating by Pr1me_StRel0k##

import asyncio
import logging
import sqlite3
import random
import re
import os
import json
import hashlib
import hmac
import dropbox
from dropbox.exceptions import AuthError
from dropbox.files import WriteMode
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import aiosqlite
import aiohttp
from html import escape


import discord
from discord.ext import commands, tasks
from discord.commands import SlashCommandGroup
from discord import option


CONFIG = {
    "DISCORD_BOT_TOKEN": "Your Token Here", 
    
    "ADMIN_ID": your discord id this, 

    
    "CRYPTOBOT_API_TOKEN": "Your Token",  
    "CRYPTOBOT_API_URL": "https://pay.crypt.bot/api",

    
    "SUPPORTED_CURRENCIES": ["USDT", "TON", "BTC"], 

    
    "DB_PATH": "betting_botds.db",

    
    "DROPBOX_REFRESH_TOKEN": "Your Refresh Token",
    "DROPBOX_APP_KEY": "Your app key",
    "DROPBOX_APP_SECRET": "your secret app key",
    "DB_BACKUP_PATH_DROPBOX": "/backups/betting_botds.db", 
    "PROMO_CODES_FILE_PATH": "/promocodes/promocodes.txt", 

    
    "BET_TIMEOUT_MINUTES": 30,
    "MIN_BET_AMOUNT": 1.0,
    "MAX_BET_AMOUNT": 1000.0,
    "WITHDRAWAL_FEE": 0.06,  
    "MIN_WITHDRAWAL_AMOUNT": 10.0,

    
    "HAPPY_HOUR_ENABLED": True,
    "HAPPY_HOUR_START": 19,  
    "HAPPY_HOUR_END": 22,    
    "HAPPY_HOUR_MULTIPLIER": 1.10, 

    
    "DEBUG": False
}


logging.basicConfig(
    level=logging.INFO if not CONFIG["DEBUG"] else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)



active_bets: Dict[str, dict] = {}  
user_bets: Dict[int, str] = {}  

SLOT_ITEMS = ["🍒", "🍋", "🍊", "🍉", "⭐", "💎", "7️⃣"]
SLOT_PAYOUTS = {
    ("🍒", "🍒", "🍒"): 5, ("🍋", "🍋", "🍋"): 10, ("🍊", "🍊", "🍊"): 15,
    ("🍉", "🍉", "🍉"): 20, ("⭐", "⭐", "⭐"): 50, ("💎", "💎", "💎"): 100,
    ("7️⃣", "7️⃣", "7️⃣"): 250,
}

def is_happy_hour() -> Tuple[bool, Optional[float]]:
    if not CONFIG["HAPPY_HOUR_ENABLED"]: return False, None
    now = datetime.now()
    start_hour, end_hour = CONFIG["HAPPY_HOUR_START"], CONFIG["HAPPY_HOUR_END"]
    if start_hour <= now.hour < end_hour:
        return True, CONFIG["HAPPY_HOUR_MULTIPLIER"]
    return False, None

def determine_pve_winner_with_chance(win_chance: float = 0.005) -> bool:
    return random.random() < win_chance

def determine_winner(game_type: str, player1_result: any, player2_result: any) -> int:
    if player1_result > player2_result: return 1
    elif player2_result > player1_result: return 2
    else: return 0

def convert_dice_to_game_result(game_type: str, dice_value: int):
    if game_type in ["football", "basketball"]: return dice_value >= 4  
    if game_type == "coinflip": return dice_value > 3 
    return dice_value


class CryptoBotAPI:
    def __init__(self, token: str = None):
        self.token = token or CONFIG["CRYPTOBOT_API_TOKEN"]
        self.base_url = CONFIG["CRYPTOBOT_API_URL"]

        if not self.token or self.token == "YOUR_CRYPTOBOT_TOKEN_HERE":
            logger.warning("⚠️ CryptoBot API token is not set. Using test mode.")
            self.test_mode = True
        else:
            self.test_mode = False

    async def create_invoice(self, amount: float, asset: str, description: str = "", user_id: int = None) -> Dict[str, Any]:
        if self.test_mode:
            invoice_id = f"test_invoice_{user_id}_{int(datetime.now().timestamp())}"
            return {
                "ok": True,
                "result": { "invoice_id": invoice_id, "bot_invoice_url": f"https://t.me/CryptoBot?start={invoice_id}" }
            }
        headers = {"Crypto-Pay-API-Token": self.token}
        data = { "asset": asset, "amount": str(amount), "description": description or f"Balance deposit for user {user_id}" }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/createInvoice", headers=headers, json=data) as response:
                    return await response.json()
        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            return None

    async def check_invoice(self, invoice_id: str) -> Dict[str, Any]:
        if self.test_mode:
            return {
                "ok": True,
                "result": { "items": [{ "invoice_id": invoice_id, "status": "paid", "amount": "10.0", "asset": "USDT" }] }
            }
        headers = {"Crypto-Pay-API-Token": self.token}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/getInvoices", headers=headers, params={"invoice_ids": invoice_id}) as response:
                    return await response.json()
        except Exception as e:
            logger.error(f"Error checking invoice: {e}")
            return None

crypto_api = CryptoBotAPI()



async def init_db():
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
       
        columns_to_add = [
            ("users", "last_wheel_spin", "TEXT"),
            ("users", "referrer_id", "INTEGER"),
            ("users", "last_bonus_claim", "TEXT"),
            ("users", "games_played_as_referral", "INTEGER DEFAULT 0"),
            ("users", "first_deposit_bonus_received", "INTEGER DEFAULT 0")
        ]
        for table, column, col_type in columns_to_add:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass 

        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, nickname TEXT, registration_date TEXT,
                total_wins INTEGER DEFAULT 0, total_bets INTEGER DEFAULT 0, total_won_amount REAL DEFAULT 0.0,
                last_activity TEXT, referrer_id INTEGER, last_bonus_claim TEXT,
                games_played_as_referral INTEGER DEFAULT 0, first_deposit_bonus_received INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_balances (
                user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0.0, frozen_balance REAL DEFAULT 0.0,
                total_deposited REAL DEFAULT 0.0, total_withdrawn REAL DEFAULT 0.0, last_updated TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, transaction_type TEXT,
                amount REAL, status TEXT, external_id TEXT, description TEXT, created_at TEXT,
                completed_at TEXT, FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, fee REAL,
                address TEXT, status TEXT DEFAULT 'pending', created_at TEXT, processed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, type TEXT NOT NULL,
                value REAL NOT NULL, max_uses INTEGER DEFAULT 1, uses INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS used_promo_codes (
                user_id INTEGER, promo_id INTEGER, PRIMARY KEY (user_id, promo_id),
                FOREIGN KEY (promo_id) REFERENCES promo_codes (id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, message TEXT,
                status TEXT DEFAULT 'open', created_at TEXT, FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        await db.commit()
        logger.info("✅ Database initialized")

async def register_user(user_id: int, username: str, nickname: str, referrer_id: int = None) -> bool:
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) now db:
            async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
                if await cursor.fetchone(): return False
            
            await db.execute(
                "INSERT INTO users (user_id, username, nickname, registration_date, last_activity, referrer_id) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, nickname, datetime.now().isoformat(), datetime.now().isoformat(), referrer_id)
            )
            await db.execute(
                "INSERT INTO user_balances (user_id, last_updated) VALUES (?, ?)",
                (user_id, datetime.now().isoformat())
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error registering user {user_id}: {e}")
        return False

async def is_user_registered(user_id: int) -> bool:
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def get_user_stats(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute('''
            SELECT u.*, b.balance, b.frozen_balance, b.total_deposited, b.total_withdrawn
            FROM users u LEFT JOIN user_balances b ON u.user_id = b.user_id WHERE u.user_id = ?
        ''', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'user_id': row[0], 'username': row[1], 'nickname': row[2], 'registration_date': row[3],
                    'total_wins': row[4], 'total_bets': row[5], 'total_won_amount': row[6], 'balance': row[8] or 0.0, 
                    'frozen_balance': row[9] or 0.0, 'total_deposited': row[10] or 0.0, 'total_withdrawn': row[11] or 0.0
                }
            return None

async def get_user_balance(user_id: int) -> Dict[str, float]:
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT balance, frozen_balance FROM user_balances WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                balance, frozen = row
                return {'balance': balance or 0.0, 'frozen': frozen or 0.0, 'available': (balance or 0.0) - (frozen or 0.0)}
            return {'balance': 0.0, 'frozen': 0.0, 'available': 0.0}

async def update_user_balance(user_id: int, amount: float, transaction_type: str = "manual") -> bool:
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            await db.execute(
                "UPDATE user_balances SET balance = balance + ?, last_updated = ? WHERE user_id = ?",
                (amount, datetime.now().isoformat(), user_id)
            )
            await db.execute(
                "INSERT INTO transactions (user_id, transaction_type, amount, status, description, created_at) VALUES (?, ?, ?, 'completed', ?, ?)",
                (user_id, transaction_type, amount, f"Balance change: {transaction_type}", datetime.now().isoformat())
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error updating balance for {user_id}: {e}")
        return False

async def freeze_balance(user_id: int, amount: float) -> bool:
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            balance_info = await get_user_balance(user_id)
            if balance_info['available'] < amount: return False
            await db.execute(
                "UPDATE user_balances SET frozen_balance = frozen_balance + ?, last_updated = ? WHERE user_id = ?",
                (amount, datetime.now().isoformat(), user_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error freezing balance for {user_id}: {e}")
        return False

async def unfreeze_balance(user_id: int, amount: float) -> bool:
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            await db.execute(
                "UPDATE user_balances SET frozen_balance = MAX(0, frozen_balance - ?), last_updated = ? WHERE user_id = ?",
                (amount, datetime.now().isoformat(), user_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error unfreezing balance for {user_id}: {e}")
        return False
        
async def update_user_stats(user_id: int, won: bool, amount: float = 0):
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            if won:
                await db.execute(
                    "UPDATE users SET total_wins = total_wins + 1, total_bets = total_bets + 1, total_won_amount = total_won_amount + ?, last_activity = ? WHERE user_id = ?",
                    (amount, datetime.now().isoformat(), user_id)
                )
            else:
                await db.execute(
                    "UPDATE users SET total_bets = total_bets + 1, last_activity = ? WHERE user_id = ?",
                    (datetime.now().isoformat(), user_id)
                )
            await db.commit()
    except Exception as e:
        logger.error(f"Error updating stats for {user_id}: {e}")

async def process_referral_bonus_for_player(player_id: int, bet_amount: float):
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            cursor = await db.execute("SELECT referrer_id, games_played_as_referral FROM users WHERE user_id = ?", (player_id,))
            result = await cursor.fetchone()
            if not result: return
            referrer_id, games_played = result
            
            if referrer_id and games_played < 20:
                bonus = bet_amount * 0.10
                await update_user_balance(referrer_id, bonus, "referral_bonus")
                await db.execute("UPDATE users SET games_played_as_referral = games_played_as_referral + 1 WHERE user_id = ?", (player_id,))
                await db.commit()
                
                try:
                    referrer_user = await bot.fetch_user(referrer_id)
                    player_user = await bot.fetch_user(player_id)
                    await referrer_user.send(f"💰 Your referral {player_user.mention} played a game! You've been credited with a bonus: {bonus:.2f} USDT.")
                except Exception:
                    logger.warning(f"Failed to notify referrer {referrer_id} about the bonus.")
    except Exception as e:
        logger.error(f"Error processing referral bonus for player {player_id}: {e}")



class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📊 Profile", style=discord.ButtonStyle.primary, row=0, custom_id="main_profile")
    async def profile_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await handle_profile_interaction(interaction)

    @discord.ui.button(label="🎲 Create Bet", style=discord.ButtonStyle.success, row=1, custom_id="main_create_bet")
    async def create_bet_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        embed = discord.Embed(title="🎮 Game Mode", description="Choose whether to play against the bot (PvE) or other players (PvP).", color=discord.Color.blue())
        await interaction.response.edit_message(embed=embed, view=BetTypeSelectionView())

    @discord.ui.button(label="💰 Deposit", style=discord.ButtonStyle.secondary, row=2, custom_id="main_deposit")
    async def deposit_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        embed = discord.Embed(title="👇 Choose Currency", description="Select the currency for your deposit.", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=DepositCurrencyView())

    @discord.ui.button(label="💸 Withdraw", style=discord.ButtonStyle.secondary, row=2, custom_id="main_withdraw")
    async def withdraw_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(WithdrawalModal())

    @discord.ui.button(label="🎁 Daily Bonus", style=discord.ButtonStyle.secondary, row=3, custom_id="main_daily_bonus")
    async def daily_bonus_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await handle_daily_bonus(interaction)

    @discord.ui.button(label="🎡 Spin Wheel", style=discord.ButtonStyle.secondary, row=3, custom_id="main_spin_wheel")
    async def spin_wheel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await handle_spin_wheel(interaction)
        
    @discord.ui.button(label="🤝 Refer a Friend", style=discord.ButtonStyle.secondary, row=4, custom_id="main_referral")
    async def referral_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        referral_link = f"Tell your friends to use `/start referrer_id:{interaction.user.id}` when they begin!"
        embed = discord.Embed(
            title="🤝 Your Referral Link",
            description=f"Invite your friends!\n\nFor every referred friend who plays 20 games, you will receive **10%** of their bet amount as a bonus.\n\n**How to invite:**\nTell your friend to use the command `/start` with your ID.\nExample: `/start referrer_id:{interaction.user.id}`",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=BackToMenuView())
        
    @discord.ui.button(label="🎟️ Promo Code", style=discord.ButtonStyle.secondary, row=4, custom_id="main_promo")
    async def promo_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(PromoCodeModal())

    @discord.ui.button(label="📨 Support", style=discord.ButtonStyle.secondary, row=5, custom_id="main_support")
    async def support_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(SupportTicketModal())

    @discord.ui.button(label="📝 Help", style=discord.ButtonStyle.secondary, row=5, custom_id="main_help")
    async def help_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await handle_help_interaction(interaction)

class BackToMenuView(discord.ui.View):
    def __init__(self, timeout=180):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="🔙 Back to Menu", style=discord.ButtonStyle.danger)
    async def back_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await send_main_menu(interaction, edit=True)

class BetTypeSelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="🤖 Play with Bot (PvE)", style=discord.ButtonStyle.primary)
    async def pve_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        embed = discord.Embed(title="🤖 Play with Bot", description="Choose a game to play against the bot.", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=GameSelectionView(is_pve=True))

    @discord.ui.button(label="👥 Play with Player (PvP)", style=discord.ButtonStyle.primary)
    async def pvp_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        embed = discord.Embed(
            title="👥 Play with Players (PvP)", 
            description="To create a PvP bet, please use the `/bet` command in a server channel where the bot is present.\n\n**Example:** `/bet amount:10 game:dice`",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=BackToMenuView())
        
    @discord.ui.button(label="🔙 Back", style=discord.ButtonStyle.grey, row=1)
    async def back_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await send_main_menu(interaction, edit=True)

class GameSelectionView(discord.ui.View):
    def __init__(self, is_pve: bool):
        super().__init__(timeout=180)
        self.is_pve = is_pve
        self.game_options = [
            discord.SelectOption(label="Dice", value="dice", emoji="🎲"),
            discord.SelectOption(label="Coinflip", value="coinflip", emoji="🪙"),
            discord.SelectOption(label="Football", value="football", emoji="⚽"),
            discord.SelectOption(label="Basketball", value="basketball", emoji="🏀"),
            discord.SelectOption(label="Darts", value="darts", emoji="🎯"),
        ]
        if self.is_pve:
            self.game_options.append(discord.SelectOption(label="Slots", value="slots", emoji="🎰"))
        
        select = discord.ui.Select(placeholder="Choose a game...", options=self.game_options)
        select.callback = self.select_callback
        self.add_item(select)
        
        back_button = discord.ui.Button(label="🔙 Back", style=discord.ButtonStyle.danger, row=1)
        back_button.callback = self.back_callback
        self.add_item(back_button)

    async def select_callback(self, interaction: discord.Interaction):
        game_type = interaction.data['values'][0]
        embed = discord.Embed(title=f"💰 Bet Amount for {game_type.capitalize()}", description="Choose your bet amount.", color=discord.Color.gold())
        await interaction.response.edit_message(embed=embed, view=AmountSelectionView(game_type=game_type, is_pve=self.is_pve))
        
    async def back_callback(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🎮 Game Mode", description="Choose whether to play against the bot (PvE) or other players (PvP).", color=discord.Color.blue())
        await interaction.response.edit_message(embed=embed, view=BetTypeSelectionView())


class AmountSelectionView(discord.ui.View):
    def __init__(self, game_type: str, is_pve: bool):
        super().__init__(timeout=180)
        self.game_type = game_type
        self.is_pve = is_pve
        amounts = [1, 5, 10, 25, 50, 100]
        row = 0
        for i, amount in enumerate(amounts):
            if i % 3 == 0 and i != 0:
                row += 1
            button = discord.ui.Button(label=f"💰 {amount} USDT", style=discord.ButtonStyle.secondary, row=row)
            button.callback = self.create_amount_callback(amount)
            self.add_item(button)
            
        custom_button = discord.ui.Button(label="✏️ Custom Amount", style=discord.ButtonStyle.primary, row=row+1)
        custom_button.callback = self.custom_amount_callback
        self.add_item(custom_button)

        back_button = discord.ui.Button(label="🔙 Back", style=discord.ButtonStyle.danger, row=row+1)
        back_button.callback = self.back_callback
        self.add_item(back_button)
        
    def create_amount_callback(self, amount):
        async def amount_callback(interaction: discord.Interaction):
            await handle_pve_game_start(interaction, self.game_type, float(amount))
        return amount_callback
        
    async def custom_amount_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CustomAmountModal(game_type=self.game_type, is_pve=self.is_pve))
    
    async def back_callback(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🤖 Play with Bot", description="Choose a game to play against the bot.", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=GameSelectionView(is_pve=self.is_pve))


class DepositCurrencyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        for currency in CONFIG["SUPPORTED_CURRENCIES"]:
            button = discord.ui.Button(label=f"💳 {currency}", style=discord.ButtonStyle.primary)
            button.callback = self.create_currency_callback(currency)
            self.add_item(button)
        back_button = discord.ui.Button(label="🔙 Back", style=discord.ButtonStyle.danger, row=1)
        back_button.callback = self.back_callback
        self.add_item(back_button)
        
    def create_currency_callback(self, currency: str):
        async def currency_callback(interaction: discord.Interaction):
            embed = discord.Embed(
                title=f"💰 Deposit Amount ({currency})",
                description="Choose the amount to deposit in USDT (it will be auto-converted).",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=DepositAmountView(currency=currency))
        return currency_callback
        
    async def back_callback(self, interaction: discord.Interaction):
        await send_main_menu(interaction, edit=True)

class DepositAmountView(discord.ui.View):
    def __init__(self, currency: str):
        super().__init__(timeout=180)
        self.currency = currency
        amounts = [10, 25, 50, 100]
        for amount in amounts:
            button = discord.ui.Button(label=f"💰 {amount} USDT", style=discord.ButtonStyle.secondary)
            button.callback = self.create_amount_callback(amount)
            self.add_item(button)
        
        custom_button = discord.ui.Button(label="✏️ Custom Amount", style=discord.ButtonStyle.primary, row=1)
        custom_button.callback = self.custom_amount_callback
        self.add_item(custom_button)
        
        back_button = discord.ui.Button(label="🔙 Back", style=discord.ButtonStyle.danger, row=1)
        back_button.callback = self.back_callback
        self.add_item(back_button)

    def create_amount_callback(self, amount: float):
        async def amount_callback(interaction: discord.Interaction):
            await handle_deposit_creation(interaction, self.currency, amount)
        return amount_callback
    
    async def custom_amount_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CustomDepositModal(currency=self.currency))

    async def back_callback(self, interaction: discord.Interaction):
        embed = discord.Embed(title="👇 Choose Currency", description="Select the currency for your deposit.", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed, view=DepositCurrencyView())




class CustomAmountModal(discord.ui.Modal):
    def __init__(self, game_type: str, is_pve: bool):
        super().__init__(title="Enter Custom Bet Amount")
        self.game_type = game_type
        self.is_pve = is_pve
        self.add_item(discord.ui.InputText(label=f"Amount ({CONFIG['MIN_BET_AMOUNT']:.1f} - {CONFIG['MAX_BET_AMOUNT']:.1f} USDT)"))

    async def callback(self, interaction: discord.Interaction):
        try:
            amount = float(self.children[0].value)
            if not (CONFIG['MIN_BET_AMOUNT'] <= amount <= CONFIG['MAX_BET_AMOUNT']):
                await interaction.response.send_message(f"❌ Amount must be between {CONFIG['MIN_BET_AMOUNT']:.1f} and {CONFIG['MAX_BET_AMOUNT']:.1f} USDT.", ephemeral=True)
                return
            
            await handle_pve_game_start(interaction, self.game_type, amount)

        except ValueError:
            await interaction.response.send_message("❌ Invalid amount! Please enter a number.", ephemeral=True)

class CustomDepositModal(discord.ui.Modal):
    def __init__(self, currency: str):
        super().__init__(title="Enter Custom Deposit Amount")
        self.currency = currency
        self.add_item(discord.ui.InputText(label=f"Amount in USDT (Min: {CONFIG['MIN_BET_AMOUNT']:.1f})"))
        
    async def callback(self, interaction: discord.Interaction):
        try:
            amount = float(self.children[0].value)
            if amount < CONFIG['MIN_BET_AMOUNT']:
                await interaction.response.send_message(f"❌ Minimum deposit amount is {CONFIG['MIN_BET_AMOUNT']:.1f} USDT.", ephemeral=True)
                return
            await handle_deposit_creation(interaction, self.currency, amount)
        except ValueError:
            await interaction.response.send_message("❌ Invalid amount! Please enter a number.", ephemeral=True)

class WithdrawalModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Withdrawal Request")
        self.add_item(discord.ui.InputText(label="Amount to Withdraw (USDT)"))
        self.add_item(discord.ui.InputText(label="Your USDT TRC-20 Wallet Address", style=discord.InputTextStyle.long))

    async def callback(self, interaction: discord.Interaction):
        await handle_withdrawal_request(interaction, self.children[0].value, self.children[1].value)

class PromoCodeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Enter Promo Code")
        self.add_item(discord.ui.InputText(label="Promo Code"))
    
    async def callback(self, interaction: discord.Interaction):
        await handle_promo_code(interaction, self.children[0].value)

class SupportTicketModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Create Support Ticket")
        self.add_item(discord.ui.InputText(label="Your Message", style=discord.InputTextStyle.long))
    
    async def callback(self, interaction: discord.Interaction):
        await handle_support_ticket(interaction, self.children[0].value)



@bot.event
async def on_ready():
    logger.info(f"✅ Bot is logged in as {bot.user}")
    logger.info("🚀 Launching GameBot for Discord...")
    await init_db()
    
    if CONFIG.get("DROPBOX_REFRESH_TOKEN") and CONFIG.get("DROPBOX_APP_KEY"):
        logger.info("Dropbox config found. Starting sync and backups.")
        await sync_promo_codes_from_dropbox()
        backup_task.start()
    else:
        logger.warning("Dropbox token not configured. Backups and promo codes are disabled.")
        
    cashback_task.start()

    if crypto_api.test_mode:
        logger.warning("⚠️ Bot is running in TEST MODE")
    else:
        logger.info("✅ Bot is connected to CryptoBot API")
        
    logger.info("✅ Bot is ready to operate!")

@bot.slash_command(name="start", description="🚀 Register and start using the bot!")
@option("referrer_id", description="ID of the user who referred you.", required=False)
async def start_command(ctx: discord.ApplicationContext, referrer_id: str = None):
    user = ctx.author
    parsed_referrer_id = None
    if referrer_id:
        try:
            potential_referrer_id = int(referrer_id)
            if potential_referrer_id != user.id and await is_user_registered(potential_referrer_id):
                parsed_referrer_id = potential_referrer_id
                logger.info(f"User {user.id} came from referrer {parsed_referrer_id}")
        except (ValueError, TypeError):
            pass

    if not await is_user_registered(user.id):
        await register_user(user.id, user.name, user.display_name, parsed_referrer_id)
        welcome_text = f"🎉 Welcome, {user.mention}! You have been successfully registered."
        if parsed_referrer_id:
            try:
                referrer_user = await bot.fetch_user(parsed_referrer_id)
                await referrer_user.send(f"🎉 A new user, {user.mention}, registered using your referral!")
            except Exception as e:
                logger.error(f"Failed to notify referrer {parsed_referrer_id}: {e}")
    else:
        welcome_text = f"👋 Welcome back, {user.mention}!"

    await send_main_menu(ctx, custom_text=welcome_text, ephemeral=True)


async def send_main_menu(ctx, custom_text=None, edit=False, ephemeral=False):
    
    menu_text = "🎲 **Main Menu**\n\nSelect an action:"
    if custom_text:
        menu_text = f"{custom_text}\n\nUse the buttons below to navigate."

    happy_hour_active, multiplier = is_happy_hour()
    if happy_hour_active:
        bonus_percent = int((multiplier - 1) * 100)
        menu_text += f"\n\n🎉 **Happy Hour is active! All wins are increased by +{bonus_percent}%!**"

    embed = discord.Embed(description=menu_text, color=discord.Color.blue())
    
    
    interaction = ctx if isinstance(ctx, discord.Interaction) else None
    
    if edit and interaction:
        try:
            await interaction.response.edit_message(embed=embed, view=MainMenuView())
        except discord.errors.InteractionResponded:
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=MainMenuView())
    elif interaction:
         await interaction.response.send_message(embed=embed, view=MainMenuView(), ephemeral=ephemeral)
    else: 
        await ctx.respond(embed=embed, view=MainMenuView(), ephemeral=ephemeral)




async def handle_profile_interaction(interaction: discord.Interaction):
    user_id = interaction.user.id
    if not await is_user_registered(user_id):
        await interaction.response.send_message("❌ You are not registered! Use `/start` first.", ephemeral=True)
        return

    stats = await get_user_stats(user_id)
    balance_info = await get_user_balance(user_id)

    embed = discord.Embed(title=f"📊 Profile for {interaction.user.display_name}", color=discord.Color.purple())
    embed.add_field(name="💰 Balance", value=f"{balance_info['balance']:.2f} USDT", inline=True)
    embed.add_field(name="🔒 Frozen", value=f"{balance_info['frozen']:.2f} USDT", inline=True)
    embed.add_field(name="💵 Available", value=f"{balance_info['available']:.2f} USDT", inline=True)
    
    winrate = (stats['total_wins'] / stats['total_bets'] * 100) if stats['total_bets'] > 0 else 0
    embed.add_field(name="🏆 Wins", value=f"{stats['total_wins']} / {stats['total_bets']} games", inline=False)
    embed.add_field(name="📈 Winrate", value=f"{winrate:.1f}%", inline=True)
    embed.add_field(name="💎 Total Won", value=f"{stats['total_won_amount']:.2f} USDT", inline=True)
    
    view = BackToMenuView()
    await interaction.response.edit_message(embed=embed, view=view)

async def handle_help_interaction(interaction: discord.Interaction):
    help_text = """
    **🎮 AVAILABLE GAMES:**
    • 🎲 **Dice**: Higher number wins (1-6).
    • 🪙 **Coinflip**: Heads (4-6) or Tails (1-3).
    • ⚽ **Football**: Score a goal on 4-6.
    • 🏀 **Basketball**: Make a shot on 4-6.
    • 🎯 **Darts**: Higher score wins (1-6).
    • 🎰 **Slots**: Match three symbols to win.

    **💰 HOW TO PLAY:**
    1. Deposit funds using the `/deposit` command or the menu button. CryptoBot is used for payments.
    2. To play against the bot (PvE), use the menu. To play against players (PvP), use the `/bet` command in a server.
    3. Game results are determined automatically and fairly.

    **💸 WITHDRAWALS:**
    • Available in the main menu.
    • Network: **USDT TRC-20**.
    • Withdrawal Fee: 6%.
    • Requests are processed manually by an administrator.
    """
    embed = discord.Embed(title="📝 Bot Instructions", description=help_text, color=discord.Color.orange())
    await interaction.response.edit_message(embed=embed, view=BackToMenuView())
    
async def handle_spin_wheel(interaction: discord.Interaction):
    user_id = interaction.user.id
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute("SELECT last_wheel_spin FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        last_spin_str = result[0] if result else None

    time_now = datetime.now()
    if last_spin_str:
        last_spin_time = datetime.fromisoformat(last_spin_str)
        if time_now - last_spin_time < timedelta(hours=24):
            time_left = timedelta(hours=24) - (time_now - last_spin_time)
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await interaction.response.send_message(f"Next spin is available in {hours}h {minutes}m.", ephemeral=True)
            return

    await interaction.response.defer() 

    win_amount = round(random.uniform(0.5, 10.0), 2)
    await update_user_balance(user_id, win_amount, "wheel_of_fortune")

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute("UPDATE users SET last_wheel_spin = ? WHERE user_id = ?", (time_now.isoformat(), user_id))
        await db.commit()
    
    embed = discord.Embed(title="🎡 Wheel of Fortune 🎡", description=f"🎉 Congratulations! You won **{win_amount} USDT**!", color=discord.Color.gold())
    await interaction.followup.send(embed=embed)


async def handle_daily_bonus(interaction: discord.Interaction):
    user_id = interaction.user.id
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute("SELECT last_bonus_claim FROM users WHERE user_id = ?", (user_id,))
        last_claim_str = (await cursor.fetchone())[0]

    time_now = datetime.now()
    if last_claim_str:
        last_claim_time = datetime.fromisoformat(last_claim_str)
        if (time_now - last_claim_time) < timedelta(hours=24):
            time_left = timedelta(hours=24) - (time_now - last_claim_time)
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await interaction.response.send_message(f"You can claim the next bonus in {hours}h {minutes}m.", ephemeral=True)
            return

    bonus_amount = round(random.uniform(0.1, 0.5), 2)
    await update_user_balance(user_id, bonus_amount, "daily_bonus")

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute("UPDATE users SET last_bonus_claim = ? WHERE user_id = ?", (time_now.isoformat(), user_id))
        await db.commit()

    await interaction.response.send_message(f"🎉 You received a daily bonus of **{bonus_amount} USDT**!", ephemeral=True)

async def handle_promo_code(interaction: discord.Interaction, code_text: str):
    user_id = interaction.user.id
    code_text = code_text.upper().strip()
    
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute("SELECT id, type, value, max_uses, uses FROM promo_codes WHERE code = ?", (code_text,))
        promo = await cursor.fetchone()

        if not promo:
            await interaction.response.send_message("❌ Promo code not found or invalid.", ephemeral=True)
            return
        
        promo_id, promo_type, value, max_uses, uses = promo

        if uses >= max_uses:
            await interaction.response.send_message("❌ This promo code has reached its maximum usage limit.", ephemeral=True)
            return

        cursor = await db.execute("SELECT promo_id FROM used_promo_codes WHERE user_id = ? AND promo_id = ?", (user_id, promo_id))
        if await cursor.fetchone():
            await interaction.response.send_message("❌ You have already used this promo code.", ephemeral=True)
            return

        await update_user_balance(user_id, value, f"promo_{code_text}")
        await interaction.response.send_message(f"✅ Promo code activated! You have been credited with **{value:.2f} USDT**.", ephemeral=True)
        
        await db.execute("UPDATE promo_codes SET uses = uses + 1 WHERE id = ?", (promo_id,))
        await db.execute("INSERT INTO used_promo_codes (user_id, promo_id) VALUES (?, ?)", (user_id, promo_id))
        await db.commit()


async def handle_support_ticket(interaction: discord.Interaction, ticket_text: str):
    user = interaction.user
    
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute(
            "INSERT INTO tickets (user_id, username, message, created_at) VALUES (?, ?, ?, ?)",
            (user.id, user.name, ticket_text, datetime.now().isoformat())
        )
        await db.commit()
        ticket_id = cursor.lastrowid
        
    await interaction.response.send_message(f"✅ Your ticket #{ticket_id} has been received! An admin will review it shortly.", ephemeral=True)
    
    try:
        admin_user = await bot.fetch_user(CONFIG["ADMIN_ID"])
        embed = discord.Embed(title=f"‼️ New Support Ticket #{ticket_id}", color=discord.Color.red())
        embed.add_field(name="From", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Message", value=ticket_text, inline=False)
        await admin_user.send(embed=embed)
    except Exception as e:
        logger.error(f"Failed to notify admin of new ticket: {e}")




async def handle_pve_game_start(interaction: discord.Interaction, game_type: str, amount: float):
    user_id = interaction.user.id

    balance_info = await get_user_balance(user_id)
    if balance_info['available'] < amount:
        await interaction.response.send_message(f"❌ Insufficient funds! Available: {balance_info['available']:.2f} USDT.", ephemeral=True)
        return

    if not await freeze_balance(user_id, amount):
        await interaction.response.send_message("❌ Error freezing funds. Please try again later.", ephemeral=True)
        return

    
    await interaction.response.defer()
    
    if game_type == 'slots':
        await process_slots_game(interaction, amount)
    else:
        await process_pve_game(interaction, game_type, amount)


async def process_pve_game(interaction: discord.Interaction, game_type: str, amount: float):
    user = interaction.user
    game_emojis = {"dice": "🎲", "football": "⚽", "basketball": "🏀", "darts": "🎯", "coinflip": "🎲"}
    emoji = game_emojis.get(game_type, "🎲")

    try:
        embed = discord.Embed(title=f"{emoji} Game with Bot Started!", description=f"Your bet: **{amount:.2f} USDT**", color=discord.Color.blurple())
        await interaction.followup.send(embed=embed)
        
        await asyncio.sleep(1)
        
        
        player_roll_msg = await interaction.channel.send(f"{user.mention} is rolling... {emoji}")
        await asyncio.sleep(3)
        player_dice_value = random.randint(1, 6)
        await player_roll_msg.edit(content=f"{user.mention} rolled a **{player_dice_value}**! {emoji}")

        bot_roll_msg = await interaction.channel.send(f"The bot is rolling... {emoji}")
        await asyncio.sleep(3)
        bot_dice_value = random.randint(1, 6)
        await bot_roll_msg.edit(content=f"The bot rolled a **{bot_dice_value}**! {emoji}")

        player_wins = determine_pve_winner_with_chance()
        await unfreeze_balance(user.id, amount)

        result_embed = discord.Embed(title="🤖 Game Results")
        result_embed.add_field(name=f"{user.display_name}", value=str(player_dice_value), inline=True)
        result_embed.add_field(name="Bot", value=str(bot_dice_value), inline=True)

        if player_wins:
            win_amount = amount
            bonus_text = ""
            happy_hour_active, multiplier = is_happy_hour()
            if happy_hour_active:
                win_amount = round(amount * multiplier, 2)
                bonus_percent = int((multiplier - 1) * 100)
                bonus_text = f" (🎉 +{bonus_percent}% Happy Hour!)"
            
            result_embed.description = f"🏆 **YOU WON!**\nYour winnings: **{win_amount:.2f} USDT**{bonus_text}"
            result_embed.color = discord.Color.green()
            await update_user_balance(user.id, win_amount, "pve_win")
            await update_user_stats(user.id, won=True, amount=win_amount)
        else:
            result_embed.description = f"😔 **YOU LOST!**\nYou lost: **{amount:.2f} USDT**"
            result_embed.color = discord.Color.red()
            await update_user_balance(user.id, -amount, "pve_loss")
            await update_user_stats(user.id, won=False)
        
        await process_referral_bonus_for_player(user.id, amount)
        
       
        view = discord.ui.View(timeout=None)
        again_button = discord.ui.Button(label="Play Again!", style=discord.ButtonStyle.success)
        again_button.callback = lambda i: i.response.edit_message(embed=discord.Embed(title="🤖 Play with Bot", description="Choose a game to play."), view=GameSelectionView(is_pve=True))
        menu_button = discord.ui.Button(label="Main Menu", style=discord.ButtonStyle.primary)
        menu_button.callback = lambda i: send_main_menu(i, edit=True)
        view.add_item(again_button)
        view.add_item(menu_button)
        
        await interaction.channel.send(embed=result_embed, view=view)

    except Exception as e:
        logger.error(f"Error in PvE game for {user.id}: {e}")
        await unfreeze_balance(user.id, amount)
        await interaction.followup.send("❌ An error occurred during the game. Your bet has been returned.")

async def process_slots_game(interaction: discord.Interaction, amount: float):
    user = interaction.user
    try:
        embed = discord.Embed(title="🎰 Slots!", description=f"Your bet: **{amount:.2f} USDT**\nSpinning the reels...", color=discord.Color.gold())
        msg = await interaction.followup.send(embed=embed)

        for _ in range(3):
            reels = ' '.join([random.choice(SLOT_ITEMS) for _ in range(3)])
            embed.description = f"Your bet: **{amount:.2f} USDT**\n\n**{reels}**"
            await msg.edit(embed=embed)
            await asyncio.sleep(0.7)

        player_wins = determine_pve_winner_with_chance()
        await unfreeze_balance(user.id, amount)
        
        result_embed = discord.Embed(title="🎰 Slot Results")

        if player_wins:
            final_reels_tuple = random.choice(list(SLOT_PAYOUTS.keys()))
            payout_multiplier = SLOT_PAYOUTS[final_reels_tuple]
            win_amount = amount * (payout_multiplier - 1)

            happy_hour_active, multiplier = is_happy_hour()
            bonus_text = ""
            if happy_hour_active:
                win_amount = round(win_amount * multiplier, 2)
                bonus_text = " (with Happy Hour bonus!)"

            result_embed.description = f"**{' '.join(final_reels_tuple)}**\n\n🎉 **WINNER!**\nYour net win: **{win_amount:.2f} USDT** (x{payout_multiplier}){bonus_text}"
            result_embed.color = discord.Color.green()
            await update_user_balance(user.id, win_amount, "pve_slots_win")
            await update_user_stats(user.id, won=True, amount=win_amount)
        else:
            while True:
                final_reels_tuple = tuple(random.choice(SLOT_ITEMS) for _ in range(3))
                if final_reels_tuple not in SLOT_PAYOUTS: break
            
            result_embed.description = f"**{' '.join(final_reels_tuple)}**\n\n😔 **Better luck next time!**\nYou lost: **{amount:.2f} USDT**"
            result_embed.color = discord.Color.red()
            await update_user_balance(user.id, -amount, "pve_slots_loss")
            await update_user_stats(user.id, won=False)
        
        await msg.edit(embed=result_embed)
        await process_referral_bonus_for_player(user.id, amount)

    except Exception as e:
        logger.error(f"Error in slots game for {user.id}: {e}")
        await unfreeze_balance(user.id, amount)
        await interaction.followup.send("❌ An error occurred during the game. Your bet has been returned.")



async def handle_deposit_creation(interaction: discord.Interaction, asset: str, amount: float):
    user_id = interaction.user.id
    
    await interaction.response.defer(ephemeral=True)

    invoice_data = await crypto_api.create_invoice(amount=amount, asset=asset, user_id=user_id)
    if not invoice_data or not invoice_data.get("ok"):
        await interaction.followup.send("❌ Error creating payment invoice.", ephemeral=True)
        return
        
    invoice = invoice_data["result"]
    invoice_id = invoice['invoice_id']

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute(
            "INSERT INTO transactions (user_id, transaction_type, amount, status, external_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "deposit", amount, "pending", invoice_id, datetime.now().isoformat())
        )
        await db.commit()

    embed = discord.Embed(title="💰 Balance Deposit", color=discord.Color.blue())
    embed.description = f"**Amount**: {amount} USDT (in {asset})\n**Invoice ID**: `{invoice_id}`"

    if crypto_api.test_mode:
        embed.description += "\n\n⚠️ **TEST MODE**: Payment will be credited in 10 seconds."
        asyncio.create_task(simulate_payment(interaction, invoice_id, user_id, amount))

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="💳 Pay Now", style=discord.ButtonStyle.link, url=invoice["bot_invoice_url"]))
    check_button = discord.ui.Button(label="🔄 Check Payment", style=discord.ButtonStyle.success)
    check_button.callback = lambda i: check_payment_handler(i, invoice_id)
    view.add_item(check_button)
    
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def check_payment_handler(interaction: discord.Interaction, invoice_id: str):
    await interaction.response.defer(ephemeral=True)
    user_id = interaction.user.id

    payment_data = await crypto_api.check_invoice(invoice_id)
    if not payment_data or not payment_data.get("ok") or not payment_data["result"].get("items"):
        await interaction.followup.send("❌ Error checking payment status.", ephemeral=True)
        return

    payment = payment_data["result"]["items"][0]
    if payment["status"] == "paid":
        amount = float(payment["amount"])
        
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            cursor = await db.execute("SELECT status FROM transactions WHERE external_id = ?", (invoice_id,))
            transaction = await cursor.fetchone()
            if transaction and transaction[0] == 'completed':
                await interaction.followup.send("✅ This payment has already been credited.", ephemeral=True)
                return
            
            cursor = await db.execute("SELECT first_deposit_bonus_received FROM users WHERE user_id = ?", (user_id,))
            bonus_info = await cursor.fetchone()
            
            final_amount = amount
            bonus_message = ""
            if bonus_info and bonus_info[0] == 0:
                bonus_amount = amount 
                final_amount += bonus_amount
                bonus_message = f"\n\n🎁 You also received a **+{bonus_amount:.2f} USDT** bonus for your first deposit!"
                await db.execute("UPDATE users SET first_deposit_bonus_received = 1 WHERE user_id = ?", (user_id,))
            
            await update_user_balance(user_id, final_amount, "deposit")
            await db.execute(
                "UPDATE transactions SET status = 'completed', completed_at = ? WHERE external_id = ?",
                (datetime.now().isoformat(), invoice_id)
            )
            await db.commit()
        
        await interaction.followup.send(f"✅ Payment of **{amount} USDT** successfully credited!{bonus_message}", ephemeral=True)
    else:
        await interaction.followup.send("⏳ Payment has not been received yet.", ephemeral=True)

async def simulate_payment(interaction: discord.Interaction, invoice_id: str, user_id: int, amount: float):
    await asyncio.sleep(10)
   
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute("SELECT status FROM transactions WHERE external_id = ? AND status = 'completed'", (invoice_id,))
        if await cursor.fetchone():
            return 
            
        cursor = await db.execute("SELECT first_deposit_bonus_received FROM users WHERE user_id = ?", (user_id,))
        bonus_info = await cursor.fetchone()
        
        final_amount = amount
        bonus_message = ""
        if bonus_info and bonus_info[0] == 0:
            bonus_amount = amount 
            final_amount += bonus_amount
            bonus_message = f"\n🎁 You also received a **+{bonus_amount:.2f} USDT** first deposit bonus!"
            await db.execute("UPDATE users SET first_deposit_bonus_received = 1 WHERE user_id = ?", (user_id,))

        await update_user_balance(user_id, final_amount, "deposit")
        await db.execute(
            "UPDATE transactions SET status = 'completed', completed_at = ? WHERE external_id = ?",
            (datetime.now().isoformat(), invoice_id)
        )
        await db.commit()
    
    await interaction.user.send(f"✅ Your test payment of **{amount} USDT** has been processed!{bonus_message}")

async def handle_withdrawal_request(interaction: discord.Interaction, amount_str: str, address: str):
    user_id = interaction.user.id
    try:
        amount = float(amount_str)
    except ValueError:
        await interaction.response.send_message("❌ Amount must be a number.", ephemeral=True)
        return

    if not (address.startswith("T") and 34 <= len(address) <= 42):
        await interaction.response.send_message("❌ Invalid USDT TRC-20 address format. It must start with 'T'.", ephemeral=True)
        return
        
    if amount < CONFIG["MIN_WITHDRAWAL_AMOUNT"]:
        await interaction.response.send_message(f"❌ Minimum withdrawal amount is {CONFIG['MIN_WITHDRAWAL_AMOUNT']:.2f} USDT.", ephemeral=True)
        return

    fee = amount * CONFIG["WITHDRAWAL_FEE"]
    total_to_deduct = amount + fee
    balance = await get_user_balance(user_id)

    if balance['available'] < total_to_deduct:
        await interaction.response.send_message(
            f"❌ Insufficient funds. You need **{total_to_deduct:.2f} USDT** (including fee), but you only have {balance['available']:.2f} USDT available.",
            ephemeral=True
        )
        return

    if not await freeze_balance(user_id, total_to_deduct):
        await interaction.response.send_message("❌ Error freezing funds. Please try again.", ephemeral=True)
        return

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute(
            "INSERT INTO withdrawal_requests (user_id, amount, fee, address, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, fee, address, datetime.now().isoformat())
        )
        await db.commit()
        request_id = cursor.lastrowid

    await interaction.response.send_message(
        f"✅ Your withdrawal request has been created!\n\n**ID**: #{request_id}\n**Amount**: {amount:.2f} USDT\n**Fee**: {fee:.2f} USDT\n**Address**: `{address}`\n\n⏳ Please wait for admin approval.",
        ephemeral=True
    )

    try:
        admin_user = await bot.fetch_user(CONFIG["ADMIN_ID"])
        embed = discord.Embed(title=f"❗️ New Withdrawal Request #{request_id}", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{interaction.user.mention} (`{user_id}`)", inline=False)
        embed.add_field(name="Amount", value=f"{amount:.2f} USDT", inline=True)
        embed.add_field(name="Address", value=f"`{address}`", inline=False)
        
        view = discord.ui.View()
        approve_btn = discord.ui.Button(label="Approve", style=discord.ButtonStyle.success)
        approve_btn.callback = lambda i: _admin_process_withdrawal(i, request_id, 'approve')
        reject_btn = discord.ui.Button(label="Reject", style=discord.ButtonStyle.danger)
        reject_btn.callback = lambda i: _admin_process_withdrawal(i, request_id, 'reject')
        view.add_item(approve_btn)
        view.add_item(reject_btn)

        await admin_user.send(embed=embed, view=view)
    except Exception as e:
        logger.error(f"Failed to notify admin of new withdrawal request: {e}")




@bot.slash_command(name="bet", description="Create a PvP bet in a server channel.")
@option("amount", description="The amount to bet in USDT.", type=float, min_value=CONFIG['MIN_BET_AMOUNT'], max_value=CONFIG['MAX_BET_AMOUNT'])
@option("game", description="The game to play.", choices=["dice", "coinflip", "football", "basketball", "darts"])
@option("opponent", description="Challenge a specific user.", type=discord.Member, required=False)
async def bet_command(ctx: discord.ApplicationContext, amount: float, game: str, opponent: discord.Member = None):
    if ctx.guild is None:
        await ctx.respond("This command can only be used in a server.", ephemeral=True)
        return

    creator = ctx.author
    if not await is_user_registered(creator.id):
        await ctx.respond(f"❌ You are not registered! Please use `/start` in my DMs first.", ephemeral=True)
        return
        
    if opponent and opponent.bot:
        await ctx.respond("❌ You cannot challenge a bot.", ephemeral=True)
        return
    
    if opponent and opponent.id == creator.id:
        await ctx.respond("❌ You cannot challenge yourself.", ephemeral=True)
        return

    balance_info = await get_user_balance(creator.id)
    if balance_info['available'] < amount:
        await ctx.respond(f"❌ Insufficient funds! You only have {balance_info['available']:.2f} USDT available.", ephemeral=True)
        return
    
    if not await freeze_balance(creator.id, amount):
        await ctx.respond("❌ Failed to freeze your balance. Please try again.", ephemeral=True)
        return

    bet_id = f"bet_{creator.id}_{int(datetime.now().timestamp())}"
    active_bets[bet_id] = {
        "id": bet_id, "creator_id": creator.id, "creator": creator, "game_type": game, "amount": amount,
        "status": "waiting", "created_at": datetime.now(), "channel_id": ctx.channel.id,
        "target_id": opponent.id if opponent else None, "acceptor_id": None
    }
    user_bets[creator.id] = bet_id

    game_names = {"dice": "🎲 Dice", "football": "⚽ Football", "basketball": "🏀 Basketball", "darts": "🎯 Darts", "coinflip": "🪙 Coinflip"}
    embed = discord.Embed(title=f"🎮 New Bet Created!", color=discord.Color.blue())
    embed.add_field(name="Game", value=game_names[game], inline=True)
    embed.add_field(name="Amount", value=f"**{amount} USDT**", inline=True)
    embed.add_field(name="Creator", value=creator.mention, inline=False)
    if opponent:
        embed.description = f"This bet is a direct challenge to {opponent.mention}!"
    else:
        embed.description = "This is an open bet for anyone to accept!"
        
    await ctx.respond(embed=embed, view=PvPBetView(bet_id))
    asyncio.create_task(auto_cancel_bet(bet_id, ctx.channel))


class PvPBetView(discord.ui.View):
    def __init__(self, bet_id: str):
        super().__init__(timeout=CONFIG["BET_TIMEOUT_MINUTES"] * 60)
        self.bet_id = bet_id

    @discord.ui.button(label="✅ Accept Bet", style=discord.ButtonStyle.success)
    async def accept_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.bet_id not in active_bets:
            await interaction.response.send_message("❌ This bet is no longer available.", ephemeral=True)
            return

        bet_info = active_bets[self.bet_id]
        acceptor = interaction.user

        if acceptor.id == bet_info["creator_id"]:
            await interaction.response.send_message("❌ You cannot accept your own bet.", ephemeral=True)
            return
        
        if bet_info["target_id"] and acceptor.id != bet_info["target_id"]:
            target_user = await bot.fetch_user(bet_info["target_id"])
            await interaction.response.send_message(f"❌ This bet is only for {target_user.mention}.", ephemeral=True)
            return
            
        if not await is_user_registered(acceptor.id):
            await interaction.response.send_message("❌ You are not registered! Use `/start` in my DMs first.", ephemeral=True)
            return
            
        balance_info = await get_user_balance(acceptor.id)
        if balance_info['available'] < bet_info["amount"]:
            await interaction.response.send_message(f"❌ Insufficient funds! You need {bet_info['amount']:.2f} USDT.", ephemeral=True)
            return
            
        if not await freeze_balance(acceptor.id, bet_info["amount"]):
            await interaction.response.send_message("❌ Failed to freeze your balance. Please try again.", ephemeral=True)
            return
            
        bet_info.update({"acceptor_id": acceptor.id, "acceptor": acceptor, "status": "accepted"})
        user_bets[acceptor.id] = self.bet_id
        
        self.stop()
        await interaction.response.edit_message(content=f"Bet accepted by {acceptor.mention}! The game is starting...", view=None)
        await start_pvp_game(self.bet_id, interaction.channel)

    @discord.ui.button(label="❌ Cancel Bet", style=discord.ButtonStyle.danger)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.bet_id not in active_bets:
            await interaction.response.edit_message(content="This bet has already been completed or cancelled.", view=None)
            return

        bet_info = active_bets[self.bet_id]
        if interaction.user.id != bet_info["creator_id"]:
            await interaction.response.send_message("❌ Only the creator can cancel the bet.", ephemeral=True)
            return
        
        await unfreeze_balance(bet_info["creator_id"], bet_info["amount"])
        del active_bets[self.bet_id]
        if bet_info["creator_id"] in user_bets: del user_bets[bet_info["creator_id"]]
        
        self.stop()
        await interaction.response.edit_message(content="❌ Bet cancelled by the creator.", embed=None, view=None)

async def auto_cancel_bet(bet_id: str, channel: discord.TextChannel):
    await asyncio.sleep(CONFIG["BET_TIMEOUT_MINUTES"] * 60)
    if bet_id in active_bets and active_bets[bet_id]["status"] == "waiting":
        bet_info = active_bets.pop(bet_id)
        await unfreeze_balance(bet_info["creator_id"], bet_info["amount"])
        if bet_info["creator_id"] in user_bets: del user_bets[bet_info["creator_id"]]
        logger.info(f"⏰ Bet {bet_id} cancelled due to timeout")
        await channel.send(f"⏰ The bet created by {bet_info['creator'].mention} for {bet_info['amount']} USDT has expired and was automatically cancelled.")


async def start_pvp_game(bet_id: str, channel: discord.TextChannel):
    if bet_id not in active_bets: return
    bet_info = active_bets[bet_id]
    bet_info["status"] = "playing"

    creator = bet_info["creator"]
    acceptor = bet_info["acceptor"]
    game_type = bet_info["game_type"]
    amount = bet_info["amount"]
    
    game_emojis = {"dice": "🎲", "football": "⚽", "basketball": "🏀", "darts": "🎯", "coinflip": "🎲"}
    emoji = game_emojis.get(game_type, "🎲")

    try:
        await channel.send(f"🎮 Game started!\n{creator.mention} vs {acceptor.mention} for **{amount} USDT**")
        
        creator_roll_msg = await channel.send(f"{creator.mention} is rolling... {emoji}")
        await asyncio.sleep(3)
        creator_dice = random.randint(1, 6)
        await creator_roll_msg.edit(content=f"{creator.mention} rolled a **{creator_dice}**! {emoji}")
        
        acceptor_roll_msg = await channel.send(f"{acceptor.mention} is rolling... {emoji}")
        await asyncio.sleep(3)
        acceptor_dice = random.randint(1, 6)
        await acceptor_roll_msg.edit(content=f"{acceptor.mention} rolled a **{acceptor_dice}**! {emoji}")

        creator_result = convert_dice_to_game_result(game_type, creator_dice)
        acceptor_result = convert_dice_to_game_result(game_type, acceptor_dice)
        
        winner_code = determine_winner(game_type, creator_result, acceptor_result)
        
        await finish_pvp_game(bet_id, winner_code, creator_dice, acceptor_dice, channel)

    except Exception as e:
        logger.error(f"Error during PvP game round {bet_id}: {e}")
        await unfreeze_balance(creator.id, amount)
        await unfreeze_balance(acceptor.id, amount)
        if bet_id in active_bets: del active_bets[bet_id]
        await channel.send(f"❌ A critical error occurred. The game is cancelled and funds have been returned to both players.")


async def finish_pvp_game(bet_id: str, winner_code: int, creator_dice: int, acceptor_dice: int, channel: discord.TextChannel):
    if bet_id not in active_bets: return
    
    bet_info = active_bets.pop(bet_id)
    creator = bet_info["creator"]
    acceptor = bet_info["acceptor"]
    amount = bet_info["amount"]

    await process_referral_bonus_for_player(creator.id, amount)
    await process_referral_bonus_for_player(acceptor.id, amount)

    await unfreeze_balance(creator.id, amount)
    await unfreeze_balance(acceptor.id, amount)
    
    happy_hour_active, multiplier = is_happy_hour()
    win_amount = amount * multiplier if happy_hour_active else amount
    
    embed = discord.Embed(title="🎮 Game Results", color=discord.Color.dark_gold())
    embed.add_field(name=creator.display_name, value=f"Rolled: **{creator_dice}**", inline=True)
    embed.add_field(name=acceptor.display_name, value=f"Rolled: **{acceptor_dice}**", inline=True)

    if winner_code == 1: 
        await update_user_balance(creator.id, win_amount, "bet_win")
        await update_user_balance(acceptor.id, -amount, "bet_loss")
        await update_user_stats(creator.id, won=True, amount=win_amount)
        await update_user_stats(acceptor.id, won=False)
        embed.description = f"🏆 **{creator.mention} wins {win_amount:.2f} USDT!**"
    elif winner_code == 2: 
        await update_user_balance(acceptor.id, win_amount, "bet_win")
        await update_user_balance(creator.id, -amount, "bet_loss")
        await update_user_stats(acceptor.id, won=True, amount=win_amount)
        await update_user_stats(creator.id, won=False)
        embed.description = f"🏆 **{acceptor.mention} wins {win_amount:.2f} USDT!**"
    else: 
        await update_user_stats(creator.id, won=False)
        await update_user_stats(acceptor.id, won=False)
        embed.description = "🤝 **It's a draw!** Funds have been returned."

    if happy_hour_active and winner_code != 0:
        embed.set_footer(text="🎉 Happy Hour Bonus Applied!")

    await channel.send(embed=embed)
    
    if creator.id in user_bets: del user_bets[creator.id]
    if acceptor.id in user_bets: del user_bets[acceptor.id]
    logger.info(f"✅ Game {bet_id} finished. Winner code: {winner_code}")



admin = SlashCommandGroup("admin", "Commands for bot administration.")

@admin.command(name="panel", description="Show the admin control panel.")
async def admin_panel(ctx: discord.ApplicationContext):
    if ctx.author.id != CONFIG["ADMIN_ID"]:
        return await ctx.respond("❌ You do not have permission to use this command.", ephemeral=True)
    embed = discord.Embed(title="👑 Admin Panel", description="Select an action.", color=discord.Color.red())
    await ctx.respond(embed=embed, view=AdminPanelView(), ephemeral=True)

class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.secondary)
    async def stats_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            user_count = (await cursor.fetchone())[0]
            cursor = await db.execute("SELECT SUM(balance) FROM user_balances")
            total_balance = (await cursor.fetchone())[0] or 0
        embed = discord.Embed(title="Bot Statistics", color=discord.Color.blue())
        embed.add_field(name="Total Users", value=str(user_count))
        embed.add_field(name="Total Balance in Wallets", value=f"{total_balance:.2f} USDT")
        await interaction.response.edit_message(embed=embed)

    @discord.ui.button(label="ℹ️ User Info", style=discord.ButtonStyle.primary)
    async def user_info_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(AdminIDModal(action='info'))

    @discord.ui.button(label="🥶 Freeze Balance", style=discord.ButtonStyle.danger)
    async def freeze_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(AdminIDModal(action='freeze'))
        
    @discord.ui.button(label="🔓 Unfreeze Balance", style=discord.ButtonStyle.success)
    async def unfreeze_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(AdminIDModal(action='unfreeze'))
        
    @discord.ui.button(label="🔥 Zero Balance", style=discord.ButtonStyle.danger, row=1)
    async def zero_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(AdminIDModal(action='zero'))

    @discord.ui.button(label="🎫 View Tickets", style=discord.ButtonStyle.secondary, row=1)
    async def view_tickets_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            cursor = await db.execute("SELECT id, user_id, username, message FROM tickets WHERE status = 'open' LIMIT 5")
            tickets = await cursor.fetchall()
        if not tickets:
            return await interaction.response.send_message("No open tickets.", ephemeral=True)
        embed = discord.Embed(title="🎫 Open Support Tickets", color=discord.Color.gold())
        for ticket in tickets:
            user = await bot.fetch_user(ticket[1])
            embed.add_field(name=f"ID: {ticket[0]} | From: {user.name}", value=f"_{ticket[3][:100]}_", inline=False)
        await interaction.response.edit_message(embed=embed)

    @discord.ui.button(label="📝 Reply to Ticket", style=discord.ButtonStyle.primary, row=1)
    async def reply_ticket_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(AdminReplyModal())
        
bot.add_application_command(admin)

class AdminIDModal(discord.ui.Modal):
    def __init__(self, action: str):
        super().__init__(title=f"{action.capitalize()} User")
        self.action = action
        self.add_item(discord.ui.InputText(label="User ID"))

    async def callback(self, interaction: discord.Interaction):
        try:
            user_id = int(self.children[0].value)
        except ValueError:
            return await interaction.response.send_message("Invalid ID.", ephemeral=True)
            
        if self.action == 'info':
            stats = await get_user_stats(user_id)
            if not stats: return await interaction.response.send_message("User not found.", ephemeral=True)
            embed = discord.Embed(title=f"Info for {stats['username']}", color=discord.Color.blue())
            for key, value in stats.items():
                embed.add_field(name=key.replace('_', ' ').title(), value=str(value))
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        elif self.action == 'freeze':
            balance = await get_user_balance(user_id)
            await freeze_balance(user_id, balance['available'])
            await interaction.response.send_message(f"Frozen {balance['available']:.2f} USDT for user {user_id}.", ephemeral=True)
            
        elif self.action == 'unfreeze':
            balance = await get_user_balance(user_id)
            await unfreeze_balance(user_id, balance['frozen'])
            await interaction.response.send_message(f"Unfrozen {balance['frozen']:.2f} USDT for user {user_id}.", ephemeral=True)

        elif self.action == 'zero':
            async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
                await db.execute("UPDATE user_balances SET balance = 0, frozen_balance = 0 WHERE user_id = ?", (user_id,))
                await db.commit()
            await interaction.response.send_message(f"Balance zeroed for user {user_id}.", ephemeral=True)

class AdminReplyModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Reply to Support Ticket")
        self.add_item(discord.ui.InputText(label="Ticket ID"))
        self.add_item(discord.ui.InputText(label="Your Reply", style=discord.InputTextStyle.long))
        
    async def callback(self, interaction: discord.Interaction):
        try:
            ticket_id = int(self.children[0].value)
        except ValueError:
            return await interaction.response.send_message("Invalid Ticket ID.", ephemeral=True)
            
        reply_text = self.children[1].value
        
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            cursor = await db.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
            result = await cursor.fetchone()
            if not result:
                return await interaction.response.send_message("Ticket not found.", ephemeral=True)
            
            user_id = result[0]
            await db.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
            await db.commit()
            
        try:
            user = await bot.fetch_user(user_id)
            await user.send(f"📨 **Support Reply for Ticket #{ticket_id}**:\n\n{reply_text}")
            await interaction.response.send_message(f"✅ Reply sent to user for ticket #{ticket_id}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to send message to user: {e}", ephemeral=True)
            
async def _admin_process_withdrawal(interaction: discord.Interaction, request_id: int, action: str):
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute("SELECT user_id, amount, fee, status FROM withdrawal_requests WHERE id = ?", (request_id,))
        request = await cursor.fetchone()

    if not request:
        return await interaction.response.edit_message(content=f"Request #{request_id} not found.", view=None)
    
    user_id, amount, fee, status = request
    if status != 'pending':
        return await interaction.response.edit_message(content=f"Request #{request_id} was already processed (status: {status}).", view=None)

    total_amount = amount + fee
    user = await bot.fetch_user(user_id)

    if action == 'approve':
        await unfreeze_balance(user_id, total_amount)
        await update_user_balance(user_id, -total_amount, "withdrawal")
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            await db.execute("UPDATE withdrawal_requests SET status = 'approved', processed_at = ? WHERE id = ?", (datetime.now().isoformat(), request_id))
            await db.execute("UPDATE user_balances SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()
        await interaction.response.edit_message(content=f"✅ Approved withdrawal #{request_id} for {user.mention}.", view=None)
        await user.send(f"✅ Your withdrawal request #{request_id} for **{amount} USDT** has been approved.")
        
    elif action == 'reject':
        await unfreeze_balance(user_id, total_amount)
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            await db.execute("UPDATE withdrawal_requests SET status = 'rejected', processed_at = ? WHERE id = ?", (datetime.now().isoformat(), request_id))
            await db.commit()
        await interaction.response.edit_message(content=f"❌ Rejected withdrawal #{request_id} for {user.mention}.", view=None)
        await user.send(f"❌ Your withdrawal request #{request_id} for **{amount} USDT** has been rejected. Funds returned to your balance.")



def get_dropbox_client():
    try:
        return dropbox.Dropbox(
            oauth2_refresh_token=CONFIG["DROPBOX_REFRESH_TOKEN"],
            app_key=CONFIG["DROPBOX_APP_KEY"],
            app_secret=CONFIG["DROPBOX_APP_SECRET"]
        )
    except AuthError as e:
        logger.error(f"Dropbox Auth Error: {e}")
        return None

async def sync_promo_codes_from_dropbox():
    dbx = get_dropbox_client()
    if not dbx: return
    try:
        logger.info("Syncing promo codes from Dropbox...")
        _, res = dbx.files_download(CONFIG["PROMO_CODES_FILE_PATH"])
        content = res.content.decode('utf-8')
        
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            for line in content.splitlines():
                if not line.strip() or line.startswith('#'): continue
                try:
                    code, promo_type, value, max_uses = line.strip().split()
                    await db.execute(
                        "INSERT INTO promo_codes (code, type, value, max_uses) VALUES (?, ?, ?, ?) ON CONFLICT(code) DO NOTHING",
                        (code.upper(), promo_type, float(value), int(max_uses))
                    )
                except ValueError:
                    logger.warning(f"Invalid promo code format: {line}")
            await db.commit()
        logger.info("Promo code sync complete.")
    except Exception as e:
        logger.error(f"Error syncing promo codes: {e}")

@tasks.loop(hours=6)
async def backup_task():
    dbx = get_dropbox_client()
    if not dbx: return
    try:
        with open(CONFIG["DB_PATH"], 'rb') as f:
            await asyncio.to_thread(
                dbx.files_upload,
                f.read(),
                CONFIG["DB_BACKUP_PATH_DROPBOX"],
                mode=WriteMode('overwrite')
            )
        logger.info("✅ Database backup successful to Dropbox.")
    except Exception as e:
        logger.error(f"❌ Database backup failed: {e}")

@tasks.loop(hours=24) 
async def cashback_task():
    CASHBACK_PERCENTAGE = 0.03
    logger.info("Starting weekly cashback calculation...")
    if datetime.now().weekday() != 0: 
        logger.info("Not Monday, skipping cashback.")
        return

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        users = await cursor.fetchall()
        
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        for user_tuple in users:
            user_id = user_tuple[0]
            loss_cursor = await db.execute(
                "SELECT SUM(amount) FROM transactions WHERE user_id = ? AND created_at >= ? AND (transaction_type LIKE '%loss')",
                (user_id, seven_days_ago)
            )
            total_loss = abs((await loss_cursor.fetchone())[0] or 0)
            
            if total_loss > 0:
                cashback_amount = round(total_loss * CASHBACK_PERCENTAGE, 2)
                if cashback_amount > 0.01:
                    await update_user_balance(user_id, cashback_amount, "weekly_cashback")
                    logger.info(f"Credited cashback {cashback_amount} USDT to user {user_id}")
                    try:
                        user = await bot.fetch_user(user_id)
                        await user.send(f"💸 You received a weekly cashback of **{cashback_amount:.2f} USDT**!")
                    except Exception as e:
                        logger.warning(f"Failed to notify user {user_id} of cashback: {e}")


if __name__ == "__main__":
    if CONFIG["DISCORD_BOT_TOKEN"] == "YOUR_DISCORD_BOT_TOKEN" or CONFIG["ADMIN_ID"] == 123456789012345678:
        logger.error("❌ ERROR: Please set your DISCORD_BOT_TOKEN and ADMIN_ID in the CONFIG section!")
    else:
        try:
            bot.run(CONFIG["DISCORD_BOT_TOKEN"])
        except (KeyboardInterrupt, SystemExit):
            logger.info("👋 Bot stopped.")
