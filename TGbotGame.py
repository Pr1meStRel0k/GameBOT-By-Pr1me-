##Creating By Pr1me_StRel0k##

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
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeChat
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage


CONFIG = {
    
    "BOT_TOKEN": "YOUR BOT TOKEN", 

    
    "ADMIN_ID": 0, 

    
    "CRYPTOBOT_API_TOKEN": "YOUR_CRYPTOBOT_TOKEN_HERE",  
    "CRYPTOBOT_API_URL": "https://pay.crypt.bot/api",

    
    "SUPPORTED_CURRENCIES": ["USDT", "TON", "BTC"], 

    
    "DB_PATH": "betting_bot.db",

    "DROPBOX_REFRESH_TOKEN": "YOUR REFRESH TOKEN",
    "DROPBOX_APP_KEY": "YOUR APP KEY",
    "DROPBOX_APP_SECRET": "YOUR SECRET APP KEY",
    "DB_BACKUP_PATH_DROPBOX": "/backups/betting_bot.db", 
    "PROMO_CODES_FILE_PATH": "/promocodes/promos.txt", 

    
    "WEBHOOK_ENABLED": False,
    "WEBHOOK_PORT": 8080,
    "WEBHOOK_PATH": "/webhook",

    
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


bot = Bot(token=CONFIG["BOT_TOKEN"])
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

def is_happy_hour() -> Tuple[bool, Optional[float]]:
    
    if not CONFIG["HAPPY_HOUR_ENABLED"]:
        return False, None
    
    now = datetime.now()
    start_hour = CONFIG["HAPPY_HOUR_START"]
    end_hour = CONFIG["HAPPY_HOUR_END"]
    
    if start_hour <= now.hour < end_hour:
        return True, CONFIG["HAPPY_HOUR_MULTIPLIER"]
    return False, None


class BetCreation(StatesGroup):
    choosing_game = State()
    choosing_amount = State()

class WithdrawalStates(StatesGroup):
    entering_details = State()

class BetStates(StatesGroup):
    entering_custom_bet_amount = State()



class DepositStates(StatesGroup):
    choosing_currency = State()
    choosing_amount = State()
    entering_custom_amount = State()


class SupportStates(StatesGroup):
    writing_ticket = State()

class PromoStates(StatesGroup):
    entering_code = State()


class PVE_BetCreation(StatesGroup):
    choosing_game = State()
    choosing_amount = State()
    entering_custom_amount = State()
    
class AdminStates(StatesGroup):
    entering_user_id_for_info = State()
    entering_user_id_for_freeze = State()
    entering_user_id_for_zero = State()
    entering_user_id_for_unfreeze = State()
    entering_withdrawal_id_for_approve = State()
    entering_withdrawal_id_for_reject = State()
    entering_ticket_id_for_reply = State()
    writing_reply_to_ticket = State()



active_bets: Dict[str, dict] = {}  
user_bets: Dict[int, str] = {}  


SLOT_ITEMS = ["🍒", "🍋", "🍊", "🍉", "⭐", "💎", "7️⃣"]
SLOT_PAYOUTS = {
    ("🍒", "🍒", "🍒"): 5,
    ("🍋", "🍋", "🍋"): 10,
    ("🍊", "🍊", "🍊"): 15,
    ("🍉", "🍉", "🍉"): 20,
    ("⭐", "⭐", "⭐"): 50,
    ("💎", "💎", "💎"): 100,
    ("7️⃣", "7️⃣", "7️⃣"): 250,
}


class CryptoBotAPI:
    def __init__(self, token: str = None):
        self.token = token or CONFIG["CRYPTOBOT_API_TOKEN"]
        self.base_url = CONFIG["CRYPTOBOT_API_URL"]

        if not self.token or self.token == "YOUR_CRYPTOBOT_TOKEN_HERE":
            logger.warning("⚠️ CryptoBot API token не установлен. Используется тестовый режим.")
            self.test_mode = True
        else:
            self.test_mode = False

    
    async def create_invoice(self, amount: float, asset: str, description: str = "", user_id: int = None) -> Dict[str, Any]:
        if self.test_mode:
            invoice_id = f"test_invoice_{user_id}_{int(datetime.now().timestamp())}"
            return {
                "ok": True,
                "result": {
                    "invoice_id": invoice_id,
                    "bot_invoice_url": f"https://t.me/CryptoBot?start={invoice_id}",
                    "amount": amount,
                    "asset": asset,
                    "status": "active",
                    "created_at": datetime.now().isoformat()
                }
            }

        headers = {"Crypto-Pay-API-Token": self.token}
        data = {
            "asset": asset,
            "amount": str(amount),
            "description": description or f"Пополнение баланса для пользователя {user_id}"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/createInvoice",
                    headers=headers,
                    json=data
                ) as response:
                    return await response.json()
        except Exception as e:
            logger.error(f"Ошибка при создании инвойса: {e}")
            return None

    async def check_invoice(self, invoice_id: str) -> Dict[str, Any]:
        if self.test_mode:
            return {
                "ok": True,
                "result": {
                    "items": [{
                        "invoice_id": invoice_id,
                        "status": "paid",
                        "amount": "10.0",
                        "asset": "USDT",
                        "paid_at": datetime.now().isoformat()
                    }]
                }
            }

        headers = {"Crypto-Pay-API-Token": self.token}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/getInvoices",
                    headers=headers,
                    params={"invoice_ids": invoice_id}
                ) as response:
                    return await response.json()
        except Exception as e:
            logger.error(f"Ошибка при проверке инвойса: {e}")
            return None


crypto_api = CryptoBotAPI()


async def init_db():
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:

        await db.execute("PRAGMA journal_mode=WAL;")

        try:
            await db.execute("ALTER TABLE users ADD COLUMN last_wheel_spin TEXT")
        except sqlite3.OperationalError: pass
        
        try:
            await db.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
        except sqlite3.OperationalError: pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN last_bonus_claim TEXT")
        except sqlite3.OperationalError: pass
        
        try:
            await db.execute("ALTER TABLE users ADD COLUMN games_played_as_referral INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN first_deposit_bonus_received INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                nickname TEXT,
                registration_date TEXT,
                total_wins INTEGER DEFAULT 0,
                total_bets INTEGER DEFAULT 0,
                total_won_amount REAL DEFAULT 0.0,
                last_activity TEXT,
                referrer_id INTEGER,
                last_bonus_claim TEXT,
                games_played_as_referral INTEGER DEFAULT 0,
                first_deposit_bonus_received INTEGER DEFAULT 0 -- 0 for false, 1 for true
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_balances (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0.0,
                frozen_balance REAL DEFAULT 0.0,
                total_deposited REAL DEFAULT 0.0,
                total_withdrawn REAL DEFAULT 0.0,
                last_updated TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                transaction_type TEXT,
                amount REAL,
                status TEXT,
                external_id TEXT,
                description TEXT,
                created_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                fee REAL,
                address TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                processed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        await db.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL, -- 'balance', 'wallet' (deposit bonus)
                value REAL NOT NULL,
                max_uses INTEGER DEFAULT 1,
                uses INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS used_promo_codes (
                user_id INTEGER,
                promo_id INTEGER,
                PRIMARY KEY (user_id, promo_id),
                FOREIGN KEY (promo_id) REFERENCES promo_codes (id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                status TEXT DEFAULT 'open',
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        await db.commit()
        logger.info("✅ База данных инициализирована")

async def process_referral_bonus_for_player(player_id: int, bet_amount: float):
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            async with db.execute("SELECT referrer_id, games_played_as_referral FROM users WHERE user_id = ?", (player_id,)) as cursor:
                result = await cursor.fetchone()
            
            if not result: return
            
            referrer_id, games_played = result
            
            if referrer_id and games_played < 20:
                bonus = bet_amount * 0.10
                await update_user_balance(referrer_id, bonus, "referral_bonus")
                
                
                await db.execute("UPDATE users SET games_played_as_referral = games_played_as_referral + 1 WHERE user_id = ?", (player_id,))
                await db.commit()
                
                
                try:
                    player_info = await bot.get_chat(player_id)
                    player_username = player_info.username or 'игрока'
                    await bot.send_message(
                        referrer_id,
                        f"💰 Ваш реферал @{player_username} сыграл игру! Вам начислен бонус: {bonus:.2f} USDT."
                    )
                except Exception:
                    logger.warning(f"Не удалось уведомить реферера {referrer_id} о бонусе.")
                
                logger.info(f"Начислен реферальный бонус {bonus:.2f} USDT для {referrer_id} от игрока {player_id}")

    except Exception as e:
        logger.error(f"Ошибка начисления реферального бонуса для игрока {player_id}: {e}")

async def register_user(user_id: int, username: str = None, nickname: str = None, referrer_id: int = None) -> bool:
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
                if await cursor.fetchone():
                    return False
            
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
        logger.error(f"Ошибка регистрации пользователя {user_id}: {e}")
        return False

async def is_user_registered(user_id: int) -> bool:
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def get_user_stats(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute('''
            SELECT u.*, b.balance, b.frozen_balance, b.total_deposited, b.total_withdrawn
            FROM users u LEFT JOIN user_balances b ON u.user_id = b.user_id
            WHERE u.user_id = ?
        ''', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'user_id': row[0], 'username': row[1], 'nickname': row[2], 'registration_date': row[3],
                    'total_wins': row[4], 'total_bets': row[5], 'total_won_amount': row[6], 'last_activity': row[7],
                    'balance': row[8] or 0.0, 'frozen_balance': row[9] or 0.0,
                    'total_deposited': row[10] or 0.0, 'total_withdrawn': row[11] or 0.0
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
                (user_id, transaction_type, amount, f"Изменение баланса: {transaction_type}", datetime.now().isoformat())
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка обновления баланса {user_id}: {e}")
        return False

async def freeze_balance(user_id: int, amount: float) -> bool:
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            balance_info = await get_user_balance(user_id)
            if balance_info['available'] < amount:
                return False
            await db.execute(
                "UPDATE user_balances SET frozen_balance = frozen_balance + ?, last_updated = ? WHERE user_id = ?",
                (amount, datetime.now().isoformat(), user_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка заморозки баланса {user_id}: {e}")
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
        logger.error(f"Ошибка разморозки баланса {user_id}: {e}")
        return False


def determine_pve_winner_with_chance(win_chance: float = 0.005) -> bool:

    return random.random() < win_chance

def determine_winner(game_type: str, player1_result: any, player2_result: any) -> int:
    if player1_result > player2_result:
        return 1
    elif player2_result > player1_result:
        return 2
    else:
        return 0

def convert_dice_to_game_result(game_type: str, dice_value: int):
    if game_type in ["football", "basketball"]:
        return dice_value >= 4  
    if game_type == "coinflip":
        return dice_value > 3 
    return dice_value


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard= [
        [InlineKeyboardButton(text="📊 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🎲 Создать ставку", callback_data="create_bet")],
        [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit"),
         InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus"),
         InlineKeyboardButton(text="🎡 Колесо Удачи", callback_data="spin_wheel")],
        [InlineKeyboardButton(text="🤝 Пригласить друга", callback_data="referral_link"),
         InlineKeyboardButton(text="🎟 Промокод", callback_data="enter_promo")],
        [InlineKeyboardButton(text="📨 Поддержка", callback_data="support")],
        [InlineKeyboardButton(text="📝 Инструкция", callback_data="help")]
    ])

def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎫 Просмотреть тикеты", callback_data="admin_view_tickets")],
        [InlineKeyboardButton(text="📝 Ответить на тикет", callback_data="admin_reply_ticket")],
        [InlineKeyboardButton(text="✅ Одобрить вывод", callback_data="admin_approve_withdrawal"),
         InlineKeyboardButton(text="❌ Отклонить вывод", callback_data="admin_reject_withdrawal")],
        [InlineKeyboardButton(text="ℹ️ Инфо о пользователе", callback_data="admin_user_info")],
        [InlineKeyboardButton(text="🥶 Заморозить баланс", callback_data="admin_freeze_user"),
         InlineKeyboardButton(text="🔓 Разморозить баланс", callback_data="admin_unfreeze_user")],
        [InlineKeyboardButton(text="🔥 Обнулить баланс", callback_data="admin_zero_user")],
    ])

def get_game_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice"),
         InlineKeyboardButton(text="🪙 Орел и Решка", callback_data="game_coinflip")],
        [InlineKeyboardButton(text="⚽ Футбол", callback_data="game_football"),
         InlineKeyboardButton(text="🏀 Баскетбол", callback_data="game_basketball")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_darts")],
        [InlineKeyboardButton(text="🤖 Играть с ботом (PvE)", callback_data="pve_menu")], 
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def get_bet_amount_keyboard(is_pve: bool = False) -> InlineKeyboardMarkup:
    back_callback = "pve_menu" if is_pve else "back_to_games"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 1 USDT", callback_data="amount_1"),
         InlineKeyboardButton(text="💰 5 USDT", callback_data="amount_5")],
        [InlineKeyboardButton(text="💰 10 USDT", callback_data="amount_10"),
         InlineKeyboardButton(text="💰 25 USDT", callback_data="amount_25")],
        [InlineKeyboardButton(text="💰 50 USDT", callback_data="amount_50"),
         InlineKeyboardButton(text="💰 100 USDT", callback_data="amount_100")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="custom_bet_amount")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=back_callback)]
    ])


def get_deposit_amount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 10 USDT", callback_data="deposit_10"),
         InlineKeyboardButton(text="💰 25 USDT", callback_data="deposit_25")],
        [InlineKeyboardButton(text="💰 50 USDT", callback_data="deposit_50"),
         InlineKeyboardButton(text="💰 100 USDT", callback_data="deposit_100")],
        [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="custom_deposit_amount")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")] 
    ])


def get_deposit_currency_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"💳 {currency}", callback_data=f"currency_{currency}")
        for currency in CONFIG["SUPPORTED_CURRENCIES"]
    ]
    keyboard_layout = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard_layout.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_layout)


@router.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            potential_referrer_id = int(args[1].split('_')[1])
            if potential_referrer_id != user_id: 
                if await is_user_registered(potential_referrer_id):
                     referrer_id = potential_referrer_id
                     logger.info(f"Пользователь {user_id} пришел по ссылке от {referrer_id}")
        except (ValueError, IndexError):
            pass 

    
    if not await is_user_registered(user_id):
        await register_user(user_id, username, first_name, referrer_id)
        welcome_text = f"🎉 Добро пожаловать, {first_name}!\n\nВы успешно зарегистрированы."
        if referrer_id:
            try:
                await bot.send_message(referrer_id, f"🎉 По вашей ссылке зарегистрировался новый пользователь: @{username or first_name}!")
            except Exception as e:
                logger.error(f"Не удалось уведомить реферера {referrer_id}: {e}")
            

    else:
        welcome_text = f"👋 С возвращением, {first_name}!"

        happy_hour_active, multiplier = is_happy_hour()
        if happy_hour_active:
            bonus_percent = int((multiplier - 1) * 100)
            welcome_text += f"\n\n🎉 **Сейчас Happy Hour! Все выигрыши +{bonus_percent}%!**"

    welcome_text += "\n\nИспользуйте кнопки ниже для навигации:"
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    
@router.message(Command("bet"))
async def bet_command(message: Message):
    user_id = message.from_user.id
    chat_type = message.chat.type

    if not await is_user_registered(user_id):
        await message.reply("❌ Вы не зарегистрированы! Отправьте /start боту в личных сообщениях.")
        return

    if chat_type == "private":
        await message.reply(
            "🎮 Команда /bet используется в группах!\n\n"
            "💡 Добавьте бота в группу и используйте:\n"
            "• `/bet <сумма> <игра>`\n"
            "• `/bet <сумма> <игра> @username`\n\n"
            "🎯 Примеры:\n"
            "• `/bet 10 dice`\n"
            "• `/bet 25 football @player`",
            reply_markup=get_main_menu_keyboard()
        )
        return

    args = message.text.split()[1:]
    if len(args) < 2:
        await message.reply(
            "❌ Неверный формат!\n"
            "✅ Правильно: `/bet <сумма> <игра> (@username)`\n"
            "🎮 Игры: dice, football, basketball, darts"
        )
        return

    try:
        amount = float(args[0])
        game_type = args[1].lower()
        target_user = args[2] if len(args) > 2 else None

        valid_games = ["dice", "football", "basketball", "darts"]
        if game_type not in valid_games:
            await message.reply(f"❌ Неизвестная игра: {game_type}. Доступные: {', '.join(valid_games)}")
            return

        if not (CONFIG['MIN_BET_AMOUNT'] <= amount <= CONFIG['MAX_BET_AMOUNT']):
            await message.reply(f"❌ Сумма должна быть между {CONFIG['MIN_BET_AMOUNT']:.1f} и {CONFIG['MAX_BET_AMOUNT']:.1f} USDT.")
            return

        balance_info = await get_user_balance(user_id)
        if balance_info['available'] < amount:
            await message.reply(
                f"❌ Недостаточно средств! Доступно: {balance_info['available']:.2f} USDT.",
            )
            return

        if not await freeze_balance(user_id, amount):
            await message.reply("❌ Ошибка заморозки средств. Попробуйте позже.")
            return

        bet_id = f"bet_{user_id}_{int(datetime.now().timestamp())}"
        target_username = target_user.lstrip('@').lower() if target_user else None

        active_bets[bet_id] = {
            "id": bet_id, "creator_id": user_id, "creator_username": message.from_user.username,
            "creator_name": message.from_user.first_name, "game_type": game_type, "amount": amount,
            "status": "waiting", "created_at": datetime.now(), "chat_id": message.chat.id,
            "target_username": target_username, "acceptor_id": None
        }
        user_bets[user_id] = bet_id

        game_names = {"dice": "🎲 Кости", "football": "⚽ Футбол", "basketball": "🏀 Баскетбол", "darts": "🎯 Дартс"}
        bet_text = (
            f"🎮 Создана ставка!\n\n"
            f"🎯 Игра: {game_names[game_type]}\n"
            f"💰 Ставка: {amount} USDT\n"
            f"👤 Создатель: @{message.from_user.username}\n"
        )
        if target_username:
            bet_text += f"🎯 Для игрока: @{target_username}\n"
        else:
            bet_text += f"🌍 Открытая ставка\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять ставку", callback_data=f"accept_{bet_id}")],
            [InlineKeyboardButton(text="❌ Отменить ставку", callback_data=f"cancel_{bet_id}")]
        ])
        
        await message.reply(bet_text, reply_markup=keyboard)
        asyncio.create_task(auto_cancel_bet(bet_id))

    except ValueError:
        await message.reply("❌ Неверная сумма! Используйте число.")
    except Exception as e:
        logger.error(f"Ошибка в команде /bet: {e}")
        await message.reply("❌ Произошла ошибка.")

@router.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await is_user_registered(user_id):
        await callback.answer("❌ Вы не зарегистрированы!", show_alert=True)
        return

    stats = await get_user_stats(user_id)
    balance_info = await get_user_balance(user_id)

    profile_text = (
        f"📊 Ваш профиль\n\n"
        f"👤 Имя: {stats['nickname']}\n"
        f"🆔 Username: @{stats['username'] or 'не указан'}\n\n"
        f"💰 Баланс: {balance_info['balance']:.2f} USDT\n"
        f"🔒 Заморожено: {balance_info['frozen']:.2f} USDT\n"
        f"💵 Доступно: {balance_info['available']:.2f} USDT\n\n"
        f"🏆 Побед: {stats['total_wins']} / {stats['total_bets']} ставок\n"
        f"💎 Всего выиграно: {stats['total_won_amount']:.2f} USDT\n"
    )
    if stats['total_bets'] > 0:
        winrate = (stats['total_wins'] / stats['total_bets']) * 100
        profile_text += f"📈 Винрейт: {winrate:.1f}%"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit"),
         InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(profile_text, reply_markup=keyboard)



@router.callback_query(F.data == "create_bet")
async def create_bet_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BetCreation.choosing_game)
    await callback.message.edit_text(
        "🎮 Выберите тип игры:",
        reply_markup=get_game_selection_keyboard()
    )

@router.callback_query(BetCreation.choosing_game, F.data.startswith("game_"))
async def game_selection_handler(callback: CallbackQuery, state: FSMContext):
    game_type = callback.data.split("_")[1]
    await state.update_data(game_type=game_type)
    await state.set_state(BetCreation.choosing_amount)

    game_names = {
        "dice": "🎲 Кости", "football": "⚽ Футбол",
        "basketball": "🏀 Баскетбол", "darts": "🎯 Дартс", "coinflip": "🪙 Орел и Решка"
    }

    await callback.message.edit_text(
        f"Выбрана игра: {game_names.get(game_type, 'Неизвестно')}\n\n"
        f"💰 Теперь выберите или введите сумму ставки:",
        reply_markup=get_bet_amount_keyboard()
    )

@router.callback_query(BetCreation.choosing_amount, F.data.startswith("amount_"))
async def amount_selection_handler(callback: CallbackQuery, state: FSMContext):
    try:
        amount = float(callback.data.split("_")[1])
        user_id = callback.from_user.id

        if not await is_user_registered(user_id):
            await callback.answer("❌ Вы не зарегистрированы! Используйте /start", show_alert=True)
            return

        balance_info = await get_user_balance(user_id)
        if balance_info['available'] < amount:
            await callback.answer(f"❌ Недостаточно средств! Доступно: {balance_info['available']:.2f} USDT", show_alert=True)
            return

        fsm_data = await state.get_data()
        game_type = fsm_data.get("game_type")
        if not game_type:
            await callback.answer("❌ Ошибка: игра не выбрана. Попробуйте снова.", show_alert=True)
            await state.clear()
            await create_bet_handler(callback, state) 
            return

        if not await freeze_balance(user_id, amount):
            await callback.answer("❌ Ошибка заморозки средств", show_alert=True)
            return

        
        bet_id = f"bet_{user_id}_{int(datetime.now().timestamp())}"
        active_bets[bet_id] = {
            "id": bet_id, "creator_id": user_id, "creator_username": callback.from_user.username,
            "creator_name": callback.from_user.first_name, "game_type": game_type, "amount": amount,
            "status": "waiting", "created_at": datetime.now(), "chat_id": callback.message.chat.id,
            "target_username": None, "acceptor_id": None
        }
        user_bets[user_id] = bet_id

        game_names = {"dice": "🎲 Кости", "football": "⚽ Футбол", "basketball": "🏀 Баскетбол", "darts": "🎯 Дартс", "coinflip": "🪙 Орел и Решка"}
        bet_text = (
            f"🎮 Создана открытая ставка!\n\n"
            f"🎯 Игра: {game_names[game_type]}\n"
            f"💰 Ставка: {amount} USDT\n"
            f"👤 Создатель: @{callback.from_user.username}\n"
            f"💡 Чтобы пригласить друга, просто перешлите ему это сообщение."
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять ставку", callback_data=f"accept_{bet_id}")],
            [InlineKeyboardButton(text="❌ Отменить ставку", callback_data=f"cancel_{bet_id}")]
        ])
        
        await callback.message.edit_text(bet_text, reply_markup=keyboard)
        await state.clear() 
        asyncio.create_task(auto_cancel_bet(bet_id))

    except Exception as e:
        logger.error(f"Ошибка в amount_selection_handler: {e}")
        await callback.answer("Произошла ошибка, попробуйте снова.", show_alert=True)
        await state.clear()



@router.callback_query(F.data == "pve_menu")
async def pve_menu_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PVE_BetCreation.choosing_game)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Кости", callback_data="pvegame_dice"),
         InlineKeyboardButton(text="🪙 Орел и Решка", callback_data="pvegame_coinflip")],
        [InlineKeyboardButton(text="⚽ Футбол", callback_data="pvegame_football"),
         InlineKeyboardButton(text="🏀 Баскетбол", callback_data="pvegame_basketball")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="pvegame_darts"),
         InlineKeyboardButton(text="🎰 Слоты", callback_data="pvegame_slots")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        "🤖 Игра с ботом\n\nВыберите тип игры:",
        reply_markup=keyboard
    )

@router.callback_query(PVE_BetCreation.choosing_game, F.data.startswith("pvegame_"))
async def pve_game_selection_handler(callback: CallbackQuery, state: FSMContext):
    game_type = callback.data.split("_")[1]
    await state.update_data(game_type=game_type)
    await state.set_state(PVE_BetCreation.choosing_amount)

    game_names = {
        "dice": "🎲 Кости", "football": "⚽ Футбол", "basketball": "🏀 Баскетбол",
        "darts": "🎯 Дартс", "coinflip": "🪙 Орел и Решка", "slots": "🎰 Слоты"
    }

    await callback.message.edit_text(
        f"🤖 Выбрана игра с ботом: {game_names.get(game_type, 'Неизвестно')}\n\n"
        f"💰 Теперь выберите или введите сумму ставки:",
        reply_markup=get_bet_amount_keyboard(is_pve=True)
    )

@router.callback_query(PVE_BetCreation.choosing_amount, F.data.startswith("amount_"))
async def pve_amount_selection_handler(callback: CallbackQuery, state: FSMContext):
    try:
        amount = float(callback.data.split("_")[1])
        user_id = callback.from_user.id

        balance_info = await get_user_balance(user_id)
        if balance_info['available'] < amount:
            await callback.answer(f"❌ Недостаточно средств! Доступно: {balance_info['available']:.2f} USDT", show_alert=True)
            return

        fsm_data = await state.get_data()
        game_type = fsm_data.get("game_type")
        if not game_type:
            await callback.answer("❌ Ошибка: игра не выбрана. Попробуйте снова.", show_alert=True)
            await state.clear()
            return
        
        await callback.message.delete()
        await state.clear()
        
        if not await freeze_balance(user_id, amount):
            await bot.send_message(user_id, "❌ Ошибка заморозки средств. Попробуйте снова.")
            return
        
        
        if game_type == 'slots':
            await process_slots_game(user_id, amount, callback.from_user.username)
        else:
            await process_pve_game(user_id, game_type, amount, callback.from_user.username)

    except Exception as e:
        logger.error(f"Ошибка в pve_amount_selection_handler: {e}")
        await callback.answer("Произошла ошибка, попробуйте снова.", show_alert=True)
        await state.clear()



async def process_pve_game(user_id: int, game_type: str, amount: float, username: str):
    chat_id = user_id
    game_emojis = {"dice": "🎲", "football": "⚽", "basketball": "🏀", "darts": "🎯", "coinflip": "🎲"}
    emoji = game_emojis.get(game_type, "🎲")

    try:
        await bot.send_message(chat_id, f"🤖 Игра с ботом началась!\n💰 Ваша ставка: {amount:.2f} USDT")
        await asyncio.sleep(1)

        await bot.send_message(chat_id, f"{emoji} Ваш бросок:")
        player_dice_msg = await bot.send_dice(chat_id, emoji=emoji)
        await asyncio.sleep(4)

        await bot.send_message(chat_id, f"{emoji} Бросок бота:")
        bot_dice_msg = await bot.send_dice(chat_id, emoji=emoji)
        await asyncio.sleep(4)

        player_dice_value = player_dice_msg.dice.value
        bot_dice_value = bot_dice_msg.dice.value
        
        player_wins = determine_pve_winner_with_chance()

        result_text = (
            f"РЕЗУЛЬТАТЫ ИГРЫ С БОТОМ\n\n"
            f"👤 @{username}: {player_dice_value}\n"
            f"🤖 Бот: {bot_dice_value}\n\n"
        )
        
       
        await unfreeze_balance(user_id, amount)

        if player_wins:
            win_amount = amount  
            bonus_text = ""
            happy_hour_active, multiplier = is_happy_hour()

            if happy_hour_active:
                win_amount = round(amount * multiplier, 2)
                bonus_percent = int((multiplier - 1) * 100)
                bonus_text = f" (🎉 +{bonus_percent}% Happy Hour!)"
            
            result_text += f"🏆 ВЫ ПОБЕДИЛИ! Ваш выигрыш: {win_amount:.2f} USDT{bonus_text}"
            await update_user_balance(user_id, win_amount, "pve_win")
            await update_user_stats(user_id, won=True, amount=win_amount)
        else:
            result_text += f"😔 ВЫ ПРОИГРАЛИ! Потеря: {amount:.2f} USDT"
            await update_user_balance(user_id, -amount, "pve_loss")
            await update_user_stats(user_id, won=False)
        
        await process_referral_bonus_for_player(user_id, amount)
        
        await bot.send_message(chat_id, result_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Еще раз!", callback_data="pve_menu")],
            [InlineKeyboardButton(text="Главное меню", callback_data="back_to_menu")]
        ]))

    except Exception as e:
        logger.error(f"Ошибка в процессе PvE игры для {user_id}: {e}")
        await unfreeze_balance(user_id, amount) 
        await bot.send_message(chat_id, "❌ Произошла ошибка во время игры. Ваша ставка возвращена.")



async def process_weekly_cashback():
    CASHBACK_PERCENTAGE = 0.03  
    logger.info("Начинаю еженедельный расчет кэшбэка...")
    
    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                users = await cursor.fetchall()

            for user_tuple in users:
                user_id = user_tuple[0]
                
              
                seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
                async with db.execute(
                    """
                    SELECT SUM(amount) FROM transactions
                    WHERE user_id = ? AND created_at >= ? AND (transaction_type = 'bet_loss' OR transaction_type LIKE 'pve%loss')
                    """, (user_id, seven_days_ago)
                ) as loss_cursor:
                    total_loss_result = await loss_cursor.fetchone()
                
                total_loss = abs(total_loss_result[0]) if total_loss_result and total_loss_result[0] else 0
                
                if total_loss > 0:
                    cashback_amount = round(total_loss * CASHBACK_PERCENTAGE, 2)
                    if cashback_amount > 0.01: 
                        await update_user_balance(user_id, cashback_amount, "weekly_cashback")
                        logger.info(f"Начислен кэшбэк {cashback_amount} USDT для пользователя {user_id} (проигрыш {total_loss} USDT)")
                        try:
                            await bot.send_message(user_id, f"💸 Вам начислен еженедельный кэшбэк в размере {cashback_amount:.2f} USDT за ваши игры!")
                        except Exception as e:
                            logger.warning(f"Не удалось уведомить пользователя {user_id} о кэшбэке: {e}")

    except Exception as e:
        logger.error(f"Ошибка при расчете еженедельного кэшбэка: {e}")

async def run_periodic_tasks():
    
    while True:
        now = datetime.now()
        
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= 12: 
            days_until_monday = 7 
            
        next_run_date = (now + timedelta(days=days_until_monday)).replace(hour=12, minute=0, second=0, microsecond=0)
        
        sleep_duration = (next_run_date - now).total_seconds()
        
        logger.info(f"Следующий расчет кэшбэка через {sleep_duration / 3600:.2f} часов.")
        await asyncio.sleep(sleep_duration)
        await process_weekly_cashback()
        

async def process_slots_game(user_id: int, amount: float, username: str):
    chat_id = user_id
    try:
        msg = await bot.send_message(chat_id, f"🎰 Слоты! Ваша ставка: {amount:.2f} USDT\nКрутим барабаны...")
        await asyncio.sleep(1)

        for _ in range(3):
            reels = [random.choice(SLOT_ITEMS) for _ in range(3)]
            await msg.edit_text(f"🎰 Слоты! Ваша ставка: {amount:.2f} USDT\n\n{' '.join(reels)}")
            await asyncio.sleep(0.5)

        player_wins = determine_pve_winner_with_chance()
        
        await unfreeze_balance(user_id, amount)

        if player_wins:
            
            final_reels = random.choice(list(SLOT_PAYOUTS.keys()))
            payout_multiplier = SLOT_PAYOUTS[final_reels]
            win_amount = amount * (payout_multiplier -1) 

            happy_hour_active, multiplier = is_happy_hour()
            if happy_hour_active:
                win_amount = round(win_amount * multiplier, 2)

            bonus_text = f" (с учетом бонуса Happy Hour!)" if happy_hour_active else ""
            result_text = (
                f"РЕЗУЛЬТАТЫ ИГРЫ В СЛОТЫ\n\n"
                f"<b>{' '.join(final_reels)}</b>\n\n"
                f"🎉 ПОЗДРАВЛЯЕМ, @{username}!\n"
                f"Выигрышная комбинация! Ваш чистый выигрыш: {win_amount:.2f} USDT (x{payout_multiplier}){bonus_text}"
            )
            await update_user_balance(user_id, win_amount, "pve_slots_win")
            await update_user_stats(user_id, won=True, amount=win_amount)
        else:
            
            while True:
                final_reels = tuple(random.choice(SLOT_ITEMS) for _ in range(3))
                if final_reels not in SLOT_PAYOUTS:
                    break
            
            result_text = (
                f"РЕЗУЛЬТАТЫ ИГРЫ В СЛОТЫ\n\n"
                f"<b>{' '.join(final_reels)}</b>\n\n"
                f"😔 Увы, @{username}, в этот раз не повезло.\n"
                f"Вы проиграли: {amount:.2f} USDT"
            )
            await update_user_balance(user_id, -amount, "pve_slots_loss")
            await update_user_stats(user_id, won=False)
            
        await msg.edit_text(result_text, parse_mode="HTML")

        await process_referral_bonus_for_player(user_id, amount)

        await bot.send_message(chat_id, "Сыграем еще?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎰 Еще раз в слоты!", callback_data="pvegame_slots")],
            [InlineKeyboardButton(text="🎲 Другая игра", callback_data="pve_menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
        ]))


    except Exception as e:
        logger.error(f"Ошибка в процессе игры в слоты для {user_id}: {e}")
        await unfreeze_balance(user_id, amount)
        await bot.send_message(chat_id, "❌ Произошла ошибка во время игры. Ваша ставка возвращена.")


@router.callback_query(PVE_BetCreation.choosing_amount, F.data == "custom_bet_amount")
async def pve_custom_bet_amount_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PVE_BetCreation.entering_custom_amount)
    amount_text = (
        f"🤖 Введите сумму для игры с ботом\n\n"
        f"Лимиты: от {CONFIG['MIN_BET_AMOUNT']:.1f} до {CONFIG['MAX_BET_AMOUNT']:.1f} USDT."
    )
    await callback.message.edit_text(amount_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="pve_menu")]
    ]))

def get_dropbox_client():
    try:
        return dropbox.Dropbox(
            oauth2_refresh_token=CONFIG["DROPBOX_REFRESH_TOKEN"],
            app_key=CONFIG["DROPBOX_APP_KEY"],
            app_secret=CONFIG["DROPBOX_APP_SECRET"]
        )
    except AuthError as e:
        logger.error(f"Ошибка аутентификации Dropbox: {e}")
        return None

async def sync_promo_codes_from_dropbox():
    dbx = get_dropbox_client()
    if not dbx:
        return

    try:
        logger.info("Синхронизация промокодов из Dropbox...")
        _, res = dbx.files_download(CONFIG["PROMO_CODES_FILE_PATH"])
        content = res.content.decode('utf-8')
        
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            for line in content.splitlines():
                if not line.strip() or line.startswith('#'):
                    continue
                try:
                    code, promo_type, value, max_uses = line.strip().split()
                    await db.execute(
                        "INSERT INTO promo_codes (code, type, value, max_uses) VALUES (?, ?, ?, ?) ON CONFLICT(code) DO NOTHING",
                        (code.upper(), promo_type, float(value), int(max_uses))
                    )
                except ValueError:
                    logger.warning(f"Неверный формат строки промокода: {line}")
            await db.commit()
        logger.info("Синхронизация промокодов завершена.")
        
    except dropbox.exceptions.ApiError as e:
        if isinstance(e.error, dropbox.files.DownloadError):
            logger.error(f"Файл с промокодами не найден в Dropbox: {CONFIG['PROMO_CODES_FILE_PATH']}")
        else:
            logger.error(f"Ошибка API Dropbox при получении промокодов: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при синхронизации промокодов: {e}")


async def backup_db_to_dropbox():
    dbx = get_dropbox_client()
    if not dbx:
        logger.error("Не удалось создать бэкап: клиент Dropbox не инициализирован.")
        return

    try:
        with open(CONFIG["DB_PATH"], 'rb') as f:
            db_content = f.read()

        
        await asyncio.to_thread(
            dbx.files_upload,
            db_content,
            CONFIG["DB_BACKUP_PATH_DROPBOX"],
            mode=WriteMode('overwrite')
        )
        
        logger.info(f"✅ Бэкап базы данных успешно сохранен в Dropbox: {CONFIG['DB_BACKUP_PATH_DROPBOX']}")
    except Exception as e:
        logger.error(f"❌ Ошибка при создании бэкапа базы данных: {e}")

async def run_periodic_backups():
    while True:
        await asyncio.sleep(3600 * 6)
        await backup_db_to_dropbox()


@router.message(PVE_BetCreation.entering_custom_amount)
async def pve_process_custom_bet_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if not (CONFIG['MIN_BET_AMOUNT'] <= amount <= CONFIG['MAX_BET_AMOUNT']):
            await message.reply(f"❌ Сумма должна быть между {CONFIG['MIN_BET_AMOUNT']:.1f} и {CONFIG['MAX_BET_AMOUNT']:.1f} USDT.")
            return

        callback_data = f"amount_{amount}"
        fake_callback = CallbackQuery(
            id=str(message.message_id), from_user=message.from_user,
            chat_instance="-1", message=message, data=callback_data
        )
        
        parent_state_data = await state.get_data()
        await state.set_state(PVE_BetCreation.choosing_amount)
        await state.set_data(parent_state_data)
        
        await pve_amount_selection_handler(fake_callback, state)
        
    except ValueError:
        await message.reply("❌ Неверный формат! Введите число.")
    except Exception as e:
        logger.error(f"Error in pve_process_custom_bet_amount: {e}")



async def auto_cancel_bet(bet_id: str):
    await asyncio.sleep(CONFIG["BET_TIMEOUT_MINUTES"] * 60)
    
    if bet_id in active_bets and active_bets[bet_id]["status"] == "waiting":
        bet_info = active_bets[bet_id]
        
        await unfreeze_balance(bet_info["creator_id"], bet_info["amount"])
        
        creator_id = bet_info["creator_id"]
        del active_bets[bet_id]
        if creator_id in user_bets and user_bets[creator_id] == bet_id:
            del user_bets[creator_id]
        
        logger.info(f"⏰ Ставка {bet_id} отменена по таймауту")
        try:
            await bot.send_message(creator_id, f"⏰ Ваша ставка на {bet_info['amount']} USDT была автоматически отменена, так как ее никто не принял.")
        except Exception as e:
            logger.error(f"Не удалось уведомить об отмене ставки {bet_id}: {e}")

@router.callback_query(F.data.startswith("accept_"))
async def accept_bet_handler(callback: CallbackQuery):
    bet_id = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    
    if bet_id not in active_bets:
        await callback.answer("❌ Ставка не найдена или уже завершена.", show_alert=True)
        return
    
    bet_info = active_bets[bet_id]
    
    if user_id == bet_info["creator_id"]:
        await callback.answer("❌ Вы не можете принять собственную ставку.", show_alert=True)
        return
    
    if not await is_user_registered(user_id):
        await callback.answer("❌ Вы не зарегистрированы! Используйте /start в боте.", show_alert=True)
        return
    
    if bet_info.get("target_username") and callback.from_user.username.lower() != bet_info["target_username"].lower():
        await callback.answer(f"❌ Ставка предназначена только для @{bet_info['target_username']}", show_alert=True)
        return
    
    balance_info = await get_user_balance(user_id)
    if balance_info['available'] < bet_info["amount"]:
        await callback.answer(f"❌ Недостаточно средств! Нужно: {bet_info['amount']:.2f} USDT.", show_alert=True)
        return
    
    if not await freeze_balance(user_id, bet_info["amount"]):
        await callback.answer("❌ Ошибка заморозки средств.", show_alert=True)
        return
    
    bet_info.update({
        "acceptor_id": user_id,
        "acceptor_username": callback.from_user.username,
        "acceptor_name": callback.from_user.first_name,
        "status": "accepted"
    })
    user_bets[user_id] = bet_id
    
    await callback.answer("✅ Ставка принята! Начинаем игру...", show_alert=False)
    await callback.message.delete() 
    await start_game(bet_id)

@router.callback_query(F.data.startswith("cancel_"))
async def cancel_bet_handler(callback: CallbackQuery):
    bet_id = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    
    if bet_id not in active_bets:
        await callback.answer("❌ Ставка не найдена.", show_alert=True)
        return
    
    bet_info = active_bets[bet_id]
    
    if user_id != bet_info["creator_id"]:
        await callback.answer("❌ Только создатель может отменить ставку.", show_alert=True)
        return
    
    await unfreeze_balance(bet_info["creator_id"], bet_info["amount"])
    
    del active_bets[bet_id]
    if user_id in user_bets and user_bets[user_id] == bet_id:
        del user_bets[user_id]
    
    await callback.message.edit_text("❌ Ставка отменена создателем.")

async def start_game(bet_id: str):
    if bet_id not in active_bets: return
    bet_info = active_bets[bet_id]
    bet_info["status"] = "playing"
    await play_game_round(bet_id)

async def play_game_round(bet_id: str):
    if bet_id not in active_bets: return
    bet_info = active_bets[bet_id]
    chat_id = bet_info.get("chat_id")

    game_names = {"dice": "🎲", "football": "⚽", "basketball": "🏀", "darts": "🎯", "coinflip": "🎲"}
    emoji = game_names.get(bet_info['game_type'], "🎲")

    try:
        roll_text = (
            f"🎮 Игра началась!\n\n"
            f"@{bet_info['creator_username']} vs @{bet_info['acceptor_username']}\n"
            f"💰 Ставка: {bet_info['amount']} USDT"
        )
        await bot.send_message(chat_id, roll_text)

        await bot.send_message(chat_id, f"{emoji} Бросок @{bet_info['creator_username']}:")
        creator_dice_msg = await bot.send_dice(chat_id, emoji=emoji)
        await asyncio.sleep(4)

        await bot.send_message(chat_id, f"{emoji} Бросок @{bet_info['acceptor_username']}:")
        acceptor_dice_msg = await bot.send_dice(chat_id, emoji=emoji)
        await asyncio.sleep(4)
        
        creator_dice_value = creator_dice_msg.dice.value
        acceptor_dice_value = acceptor_dice_msg.dice.value
        
        creator_result = convert_dice_to_game_result(bet_info["game_type"], creator_dice_value)
        acceptor_result = convert_dice_to_game_result(bet_info["game_type"], acceptor_dice_value)
        
        bet_info.update({
            "creator_dice": creator_dice_value, "acceptor_dice": acceptor_dice_value,
            "creator_result": creator_result, "acceptor_result": acceptor_result
        })
        
        winner = determine_winner(bet_info["game_type"], creator_result, acceptor_result)
        
        await send_game_results(bet_id, winner)
        await finish_game(bet_id, winner)
        
    except Exception as e:
        logger.error(f"Ошибка в игровом раунде {bet_id}: {e}")
        await unfreeze_balance(bet_info["creator_id"], bet_info["amount"])
        await unfreeze_balance(bet_info["acceptor_id"], bet_info["amount"])
        if bet_id in active_bets: del active_bets[bet_id]
        error_text = "❌ Произошла ошибка в игре. Средства возвращены."
        try:
            await bot.send_message(chat_id, f"{error_text}\n👥 @{bet_info['creator_username']} и @{bet_info['acceptor_username']}")
        except:
            pass

async def send_game_results(bet_id: str, winner: int):
    bet_info = active_bets[bet_id]
    
    result_text = f"🎮 РЕЗУЛЬТАТЫ ИГРЫ\n\n"
    result_text += f"👤 @{bet_info['creator_username']}: {bet_info['creator_dice']}\n"
    result_text += f"👤 @{bet_info['acceptor_username']}: {bet_info['acceptor_dice']}\n\n"
    
    if winner == 0:
        result_text += f"🤝 НИЧЬЯ! Средства возвращены игрокам."
    elif winner == 1:
        result_text += f"🏆 ПОБЕДИТЕЛЬ: @{bet_info['creator_username']} (+{bet_info['amount']:.2f} USDT)"
    else:
        result_text += f"🏆 ПОБЕДИТЕЛЬ: @{bet_info['acceptor_username']} (+{bet_info['amount']:.2f} USDT)"
    
    chat_id = bet_info.get("chat_id")
    try:
        await bot.send_message(chat_id, result_text)
    except Exception as e:
        logger.error(f"Ошибка отправки результатов в чат {chat_id}: {e}")


async def finish_game(bet_id: str, winner: int):
    if bet_id not in active_bets: return
    
    bet_info = active_bets[bet_id]
    amount = bet_info["amount"]
    creator_id = bet_info["creator_id"]
    acceptor_id = bet_info["acceptor_id"]

    try:
        await process_referral_bonus_for_player(creator_id, amount)
        await process_referral_bonus_for_player(acceptor_id, amount)

        await unfreeze_balance(creator_id, amount)
        await unfreeze_balance(acceptor_id, amount)

        happy_hour_active, multiplier = is_happy_hour()
        win_amount = amount

        if happy_hour_active:
            win_amount = round(amount * multiplier, 2)
        
        if winner == 1:
            await update_user_balance(creator_id, win_amount, "bet_win_hh" if happy_hour_active else "bet_win")
            await update_user_balance(acceptor_id, -amount, "bet_loss")
            await update_user_stats(creator_id, won=True, amount=win_amount)
            await update_user_stats(acceptor_id, won=False)
        elif winner == 2:
            await update_user_balance(acceptor_id, win_amount, "bet_win_hh" if happy_hour_active else "bet_win")
            await update_user_balance(creator_id, -amount, "bet_loss")
            await update_user_stats(acceptor_id, won=True, amount=win_amount)
            await update_user_stats(creator_id, won=False)
        else: 
             await update_user_stats(creator_id, won=False)
             await update_user_stats(acceptor_id, won=False)
        
        if creator_id in user_bets: del user_bets[creator_id]
        if acceptor_id in user_bets: del user_bets[acceptor_id]
        del active_bets[bet_id]
        
        logger.info(f"✅ Игра {bet_id} завершена. Победитель: {winner}")
        
    except Exception as e:
        logger.error(f"Ошибка завершения игры {bet_id}: {e}")

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
        logger.error(f"Ошибка обновления статистики {user_id}: {e}")


@router.callback_query(F.data == "deposit")
async def deposit_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.choosing_currency)
    await callback.message.edit_text("👇 Выберите валюту для пополнения:", reply_markup=get_deposit_currency_keyboard())


@router.callback_query(DepositStates.choosing_currency, F.data.startswith("currency_"))
async def choose_deposit_currency_handler(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[1]
    await state.update_data(deposit_currency=currency)
    await state.set_state(DepositStates.choosing_amount)
    await callback.message.edit_text(f"💰 Выбрана валюта: {currency}\n\nТеперь выберите сумму пополнения в USDT (она будет автоматически конвертирована).", reply_markup=get_deposit_amount_keyboard())


@router.callback_query(DepositStates.choosing_amount, F.data.startswith("deposit_"))
async def deposit_amount_handler(callback: CallbackQuery, state: FSMContext):
    amount = float(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    data = await state.get_data()
    asset = data.get("deposit_currency")

    if not asset:
        await callback.answer("❌ Ошибка: валюта не выбрана. Попробуйте снова.", show_alert=True)
        await state.clear()
        return

   
    invoice_data = await crypto_api.create_invoice(amount=amount, asset=asset, user_id=user_id)
    
    if not invoice_data or not invoice_data.get("ok"):
        await callback.answer("❌ Ошибка создания платежа.", show_alert=True)
        return
    
    invoice = invoice_data["result"]
    invoice_id = invoice['invoice_id']

    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            await db.execute(
                "INSERT INTO transactions (user_id, transaction_type, amount, status, external_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, "deposit", amount, "pending", invoice_id, datetime.now().isoformat())
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения транзакции: {e}")

    deposit_text = f"💰 Пополнение баланса\n💵 Сумма: {amount} USDT (в {asset})\n🔗 ID: {invoice_id}\n\n"
    
    if crypto_api.test_mode:
        deposit_text += f"⚠️ ТЕСТОВЫЙ РЕЖИМ\n💡 Платеж будет засчитан через 10 секунд."
        asyncio.create_task(simulate_payment(invoice_id, user_id, amount))
    else:
        deposit_text += "👆 Нажмите кнопку ниже для оплаты через @CryptoBot."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=invoice["bot_invoice_url"])],
        [InlineKeyboardButton(text="🔄 Проверить платеж", callback_data=f"check_{invoice_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    
    await callback.message.edit_text(deposit_text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("check_"))
async def check_payment_handler(callback: CallbackQuery):
    invoice_id = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id

    payment_data = await crypto_api.check_invoice(invoice_id)
    if not payment_data or not payment_data.get("ok") or not payment_data["result"]["items"]:
        await callback.answer("❌ Ошибка проверки платежа.", show_alert=True)
        return

    payment = payment_data["result"]["items"][0]
    if payment["status"] == "paid":
        amount = float(payment["amount"])
        
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            async with db.execute("SELECT status FROM transactions WHERE external_id = ?", (invoice_id,)) as cursor:
                transaction = await cursor.fetchone()
                if transaction and transaction[0] == 'completed':
                    await callback.answer("✅ Этот платеж уже был зачислен.", show_alert=True)
                    return
            
            
            async with db.execute("SELECT first_deposit_bonus_received FROM users WHERE user_id = ?", (user_id,)) as cursor:
                bonus_info = await cursor.fetchone()
            
            final_amount = amount
            bonus_message = ""
            if bonus_info and bonus_info[0] == 0:
                bonus_amount = amount 
                final_amount += bonus_amount
                bonus_message = f"\n\n🎁 Вам начислен бонус +{bonus_amount:.2f} USDT за первое пополнение!"
                await db.execute("UPDATE users SET first_deposit_bonus_received = 1 WHERE user_id = ?", (user_id,))
            

        await update_user_balance(user_id, final_amount, "deposit")
        try:
            async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
                await db.execute(
                    "UPDATE transactions SET status = 'completed', completed_at = ? WHERE external_id = ? AND user_id = ?",
                    (datetime.now().isoformat(), invoice_id, user_id)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Ошибка обновления транзакции: {e}")
        
        await callback.message.edit_text(f"✅ Платеж на {amount} USDT успешно зачислен!{bonus_message}", reply_markup=get_main_menu_keyboard())
    else:
        await callback.answer("⏳ Платеж еще не поступил.", show_alert=True)
        
async def simulate_payment(invoice_id: str, user_id: int, amount: float):
    await asyncio.sleep(10)

    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            
            async with db.execute("SELECT first_deposit_bonus_received FROM users WHERE user_id = ?", (user_id,)) as cursor:
                bonus_info = await cursor.fetchone()

            final_amount = amount
            bonus_message = ""
            if bonus_info and bonus_info[0] == 0:
                bonus_amount = amount 
                final_amount += bonus_amount
                bonus_message = f"\n🎁 Вам также начислен бонус +{bonus_amount:.2f} USDT за первое пополнение!"
                await db.execute("UPDATE users SET first_deposit_bonus_received = 1 WHERE user_id = ?", (user_id,))
            
            await update_user_balance(user_id, final_amount, "deposit")

            await db.execute(
                "UPDATE transactions SET status = 'completed', completed_at = ? WHERE external_id = ?",
                (datetime.now().isoformat(), invoice_id)
            )
            await db.commit()
        await bot.send_message(user_id, f"✅ Тестовый платеж на {amount} USDT обработан!{bonus_message}")
    except Exception as e:
        logger.error(f"Ошибка симуляции платежа: {e}")


@router.callback_query(F.data == "withdraw")
async def withdraw_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    balance = await get_user_balance(user_id)
    fee_percent = CONFIG["WITHDRAWAL_FEE"] * 100
    min_amount = CONFIG["MIN_WITHDRAWAL_AMOUNT"]

    withdraw_text = (
        f"💸 Вывод средств\n\n"
        f"Ваш доступный баланс: **{balance['available']:.2f} USDT**\n\n"
        f"Комиссия за вывод: **{fee_percent:.0f}%**\n"
        f"Минимальная сумма: **{min_amount:.2f} USDT**\n\n"
        f"⚠️ Вывод осуществляется на кошельки **USDT TRC-20**.\n\n"
        f"Пожалуйста, отправьте сообщение в формате:\n"
        f"`сумма адрес_кошелька`\n\n"
        f"**Пример:**\n`15.5 T...`"
    )

    await state.set_state(WithdrawalStates.entering_details)
    await callback.message.edit_text(
        withdraw_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в профиль", callback_data="profile")]
        ])
    )

@router.message(WithdrawalStates.entering_details)
async def process_withdrawal_details(message: Message, state: FSMContext):
    user_id = message.from_user.id
    parts = message.text.split()

    if len(parts) != 2:
        await message.reply("❌ Неверный формат. Отправьте сообщение как: `сумма адрес`\n\nПример: `15.5 T...`")
        return

    try:
        amount = float(parts[0])
        address = parts[1]
    except ValueError:
        await message.reply("❌ Сумма должна быть числом. Попробуйте снова.")
        return

    if not (address.startswith("T") and 34 <= len(address) <= 42):
        await message.reply("❌ Неверный формат адреса USDT TRC-20. Он должен начинаться с 'T'.")
        return

    if amount < CONFIG["MIN_WITHDRAWAL_AMOUNT"]:
        await message.reply(f"❌ Минимальная сумма для вывода: {CONFIG['MIN_WITHDRAWAL_AMOUNT']:.2f} USDT.")
        return
    
    fee = amount * CONFIG["WITHDRAWAL_FEE"]
    total_to_deduct = amount + fee
    balance = await get_user_balance(user_id)

    if balance['available'] < total_to_deduct:
        await message.reply(
            f"❌ Недостаточно средств для вывода с учетом комиссии.\n"
            f"Нужно: {total_to_deduct:.2f} USDT (сумма {amount:.2f} + комиссия {fee:.2f})\n"
            f"Доступно: {balance['available']:.2f} USDT"
        )
        return

    if not await freeze_balance(user_id, total_to_deduct):
        await message.reply("❌ Ошибка заморозки средств. Попробуйте позже.")
        return

    try:
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            cursor = await db.execute(
                "INSERT INTO withdrawal_requests (user_id, amount, fee, address, created_at, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                (user_id, amount, fee, address, datetime.now().isoformat())
            )
            await db.commit()
            request_id = cursor.lastrowid

        
        await message.reply(
            f"✅ Ваш запрос на вывод средств создан!\n\n"
            f"ID заявки: **#{request_id}**\n"
            f"Сумма: **{amount:.2f} USDT**\n"
            f"Комиссия: **{fee:.2f} USDT**\n"
            f"Адрес: `{address}`\n\n"
            f"⏳ Ожидайте обработки администратором.",
            parse_mode="Markdown"
        )
        
        safe_username = escape(message.from_user.username or "N/A")
        
        admin_text = (
            f"❗️ Новый запрос на вывод!\n\n"
            f"<b>ID заявки:</b> #{request_id}\n"
            f'<b>Пользователь:</b> <a href="tg://user?id={user_id}">@{safe_username}</a> (ID: <code>{user_id}</code>)\n'
            f"<b>Сумма:</b> {amount:.2f} USDT\n"
            f"<b>Адрес:</b> <code>{address}</code>\n\n"
            f"Для подтверждения: <code>/approve_withdrawal {request_id}</code>\n"
            f"Для отклонения: <code>/reject_withdrawal {request_id}</code>"
        )
        await bot.send_message(CONFIG["ADMIN_ID"], admin_text, parse_mode="HTML")
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка создания запроса на вывод: {e}")
        await unfreeze_balance(user_id, total_to_deduct)
        await message.reply("❌ Произошла ошибка при создании запроса.")

async def _process_approve_withdrawal(request_id: int) -> str:
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT * FROM withdrawal_requests WHERE id = ?", (request_id,)) as cursor:
            request = await cursor.fetchone()

    if not request:
        return f"❌ Запрос #{request_id} не найден."
    
    if request[5] != 'pending':
        return f"⚠️ Запрос #{request_id} уже обработан (статус: {request[5]})."

    user_id, amount, fee = request[1], request[2], request[3]
    total_deducted = amount + fee
    
    await unfreeze_balance(user_id, total_deducted)
    await update_user_balance(user_id, -total_deducted, "withdrawal")

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute(
            "UPDATE withdrawal_requests SET status = 'approved', processed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), request_id)
        )
        await db.execute(
            "UPDATE user_balances SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()
    
    try:
        await bot.send_message(user_id, f"✅ Ваш запрос на вывод #{request_id} на сумму {amount} USDT был одобрен и отправлен в обработку.")
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id} об одобрении вывода: {e}")
        
    return f"✅ Запрос на вывод #{request_id} на сумму {amount} USDT для пользователя {user_id} одобрен."


async def _process_reject_withdrawal(request_id: int) -> str:
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT * FROM withdrawal_requests WHERE id = ?", (request_id,)) as cursor:
            request = await cursor.fetchone()

    if not request:
        return f"❌ Запрос #{request_id} не найден."
    
    if request[5] != 'pending':
        return f"⚠️ Запрос #{request_id} уже обработан (статус: {request[5]})."

    user_id, amount, fee = request[1], request[2], request[3]
    total_to_unfreeze = amount + fee
    
    await unfreeze_balance(user_id, total_to_unfreeze)

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute(
            "UPDATE withdrawal_requests SET status = 'rejected', processed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), request_id)
        )
        await db.commit()

    try:
        await bot.send_message(user_id, f"❌ Ваш запрос на вывод #{request_id} на сумму {amount} USDT был отклонен. Средства возвращены на ваш баланс.")
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id} об отклонении вывода: {e}")
        
    return f"❌ Запрос на вывод #{request_id} отклонен. Средства возвращены пользователю {user_id}."


async def is_admin(user_id: int) -> bool:
    return user_id == CONFIG["ADMIN_ID"]

@router.message(Command("approve_withdrawal"))

async def approve_withdrawal_command(message: Message):
    if not await is_admin(message.from_user.id): return

    args = message.text.split()
    if len(args) != 2:
        await message.reply("Используйте: /approve_withdrawal <ID>")
        return
    
    try:
        request_id = int(args[1])
        response_text = await _process_approve_withdrawal(request_id)
        await message.reply(response_text)
    except ValueError:
        await message.reply("❌ ID должен быть числом.")
        
    request_id = int(args[1])
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT * FROM withdrawal_requests WHERE id = ?", (request_id,)) as cursor:
            request = await cursor.fetchone()

    if not request:
        await message.reply(f"Запрос #{request_id} не найден.")
        return
    
    if request[5] != 'pending':
        await message.reply(f"Запрос #{request_id} уже обработан (статус: {request[5]}).")
        return

    user_id, amount, fee = request[1], request[2], request[3]
    total_deducted = amount + fee

    
    await unfreeze_balance(user_id, total_deducted)
    await update_user_balance(user_id, -total_deducted, "withdrawal")

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute(
            "UPDATE withdrawal_requests SET status = 'approved', processed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), request_id)
        )
        await db.execute(
            "UPDATE user_balances SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()

    await message.reply(f"✅ Запрос на вывод #{request_id} на сумму {amount} USDT для пользователя {user_id} одобрен.")
    try:
        await bot.send_message(user_id, f"✅ Ваш запрос на вывод #{request_id} на сумму {amount} USDT был одобрен и отправлен в обработку.")
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id} об одобрении вывода: {e}")

@router.message(Command("reject_withdrawal"))
async def reject_withdrawal_command(message: Message):
    if not await is_admin(message.from_user.id): return

    args = message.text.split()
    if len(args) != 2:
        await message.reply("Используйте: /reject_withdrawal <ID>")
        return
        
    try:
        request_id = int(args[1])
        response_text = await _process_reject_withdrawal(request_id)
        await message.reply(response_text)
    except ValueError:
        await message.reply("❌ ID должен быть числом.")
        
    request_id = int(args[1])
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT * FROM withdrawal_requests WHERE id = ?", (request_id,)) as cursor:
            request = await cursor.fetchone()

    if not request:
        await message.reply(f"Запрос #{request_id} не найден.")
        return
    
    if request[5] != 'pending':
        await message.reply(f"Запрос #{request_id} уже обработан (статус: {request[5]}).")
        return

    user_id, amount, fee = request[1], request[2], request[3]
    total_to_unfreeze = amount + fee
    
    await unfreeze_balance(user_id, total_to_unfreeze)

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute(
            "UPDATE withdrawal_requests SET status = 'rejected', processed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), request_id)
        )
        await db.commit()

    await message.reply(f"❌ Запрос на вывод #{request_id} отклонен. Средства возвращены пользователю {user_id}.")
    try:
        await bot.send_message(user_id, f"❌ Ваш запрос на вывод #{request_id} на сумму {amount} USDT был отклонен. Средства возвращены на ваш баланс.")
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id} об отклонении вывода: {e}")



@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    
    menu_text = "🎲 Главное меню\n\nВыберите действие:"

    
    happy_hour_active, multiplier = is_happy_hour()
    if happy_hour_active:
        bonus_percent = int((multiplier - 1) * 100)
        happy_hour_message = f"🎉 **Сейчас Happy Hour! Все выигрыши +{bonus_percent}%!**\n\n"
        
        menu_text = happy_hour_message + menu_text
        
    
    await callback.message.edit_text(
        menu_text, 
        reply_markup=get_main_menu_keyboard(), 
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_to_games")
async def back_to_games_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BetCreation.choosing_game)
    await callback.message.edit_text("🎮 Выберите тип игры:", reply_markup=get_game_selection_keyboard())


@router.callback_query(F.data == "custom_bet_amount")
async def custom_bet_amount_handler(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state == PVE_BetCreation.choosing_amount:
        await pve_custom_bet_amount_handler(callback, state)
        return

    await state.set_state(BetStates.entering_custom_bet_amount)
    amount_text = (
        f"💰 Введите сумму ставки\n\n"
        f"Лимиты: от {CONFIG['MIN_BET_AMOUNT']:.1f} до {CONFIG['MAX_BET_AMOUNT']:.1f} USDT."
    )
    await callback.message.edit_text(amount_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_bet_amounts")]
    ]))


@router.callback_query(F.data == "custom_deposit_amount")
async def custom_deposit_amount_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.entering_custom_amount)
    amount_text = (
        f"💰 Введите сумму пополнения в USDT\n\n"
        f"Лимиты: от {CONFIG['MIN_BET_AMOUNT']:.1f} до {CONFIG['MAX_BET_AMOUNT']:.1f}."
    )
    await callback.message.edit_text(amount_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_deposit_amounts")]
    ]))

@router.message(BetStates.entering_custom_bet_amount)
async def process_custom_bet_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if not (CONFIG['MIN_BET_AMOUNT'] <= amount <= CONFIG['MAX_BET_AMOUNT']):
            await message.reply(f"❌ Сумма должна быть между {CONFIG['MIN_BET_AMOUNT']:.1f} и {CONFIG['MAX_BET_AMOUNT']:.1f} USDT.")
            return

        
        callback_data = f"amount_{amount}"
        fake_callback = CallbackQuery(
            id=str(message.message_id), from_user=message.from_user,
            chat_instance="-1", message=message, data=callback_data
        )
        
        parent_state_data = await state.get_data()
        await state.clear()
        
        await state.set_state(BetCreation.choosing_amount)
        await state.set_data(parent_state_data)
        
        await amount_selection_handler(fake_callback, state)
        
    except ValueError:
        await message.reply("❌ Неверный формат! Введите число.")
    except Exception as e:
        logger.error(f"Error in process_custom_bet_amount: {e}")



@router.message(DepositStates.entering_custom_amount)
async def process_custom_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        
        if amount < CONFIG['MIN_BET_AMOUNT']:
            await message.answer(f"❌ Сумма слишком мала! Минимум: {CONFIG['MIN_BET_AMOUNT']:.1f} USDT")
            return
        
        callback_data = f"deposit_{amount}"
        fake_callback = CallbackQuery(
            id=str(message.message_id), from_user=message.from_user,
            chat_instance="-1", message=message, data=callback_data
        )

        parent_state_data = await state.get_data()
        await state.set_state(DepositStates.choosing_amount)
        await state.set_data(parent_state_data)

        await deposit_amount_handler(fake_callback, state)

    except ValueError:
        await message.answer("❌ Неверный формат! Введите число.")


@router.callback_query(F.data == "back_to_bet_amounts")
async def back_to_bet_amounts_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BetCreation.choosing_amount)
    await callback.message.edit_text(
        f"💰 Выберите сумму ставки:",
        reply_markup=get_bet_amount_keyboard()
    )


@router.callback_query(F.data == "back_to_deposit_amounts")
async def back_to_deposit_amounts_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.choosing_amount)
    await callback.message.edit_text(
        "💰 Выберите сумму пополнения:",
        reply_markup=get_deposit_amount_keyboard()
    )


@router.callback_query(F.data == "help")
async def help_handler(callback: CallbackQuery):
    help_text = """🎲 Инструкция по использованию бота

🎮 ДОСТУПНЫЕ ИГРЫ:
• 🎲 Кости - выигрывает большее число (1-6)
• 🪙 Орел и Решка - определяется по значению кости (1-3 - одна сторона, 4-6 - другая)
• ⚽ Футбол - гол, если выпало 4-6
• 🏀 Баскетбол - попадание, если выпало 4-6
• 🎯 Дартс - больше очков побеждает (1-6)
• 🎰 Слоты - соберите выигрышную комбинацию из трех символов

💰 КАК ИГРАТЬ:
1. Пополните баланс через @CryptoBot (доступны USDT, TON, BTC).
2. Создайте ставку (PvP или PvE), выбрав игру и сумму.
3. В PvP дождитесь принятия ставки другим игроком. В PvE игра начнется сразу.
4. Результаты определяются автоматически и честно.

💸 ВЫВОД СРЕДСТВ:
• Вывод доступен в профиле.
• Сеть: USDT TRC-20.
• Комиссия за вывод: 6%.
• Запросы обрабатываются администратором вручную."""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    
    await callback.message.edit_text(help_text, reply_markup=keyboard)



@router.callback_query(F.data == "spin_wheel")
async def spin_wheel_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT last_wheel_spin FROM users WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()
            last_spin_str = result[0] if result else None

    time_now = datetime.now()
    if last_spin_str:
        last_spin_time = datetime.fromisoformat(last_spin_str)
        if time_now - last_spin_time < timedelta(hours=24):
            time_left = timedelta(hours=24) - (time_now - last_spin_time)
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await callback.answer(f"Следующее вращение доступно через {hours} ч. {minutes} мин.", show_alert=True)
            return

    await callback.message.edit_text("🎡 Вращаем колесо удачи...")
    await asyncio.sleep(2)

    win_amount = round(random.uniform(0.5, 10.0), 2)
    
    await update_user_balance(user_id, win_amount, "wheel_of_fortune")

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute("UPDATE users SET last_wheel_spin = ? WHERE user_id = ?", (time_now.isoformat(), user_id))
        await db.commit()

    await callback.message.edit_text(
        f"🎉 Поздравляем! Ваш выигрыш в Колесе Удачи составил **{win_amount} USDT**!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await callback.answer()


@router.callback_query(F.data == "referral_link")
async def referral_link_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    text = (
        f"🤝 Ваша реферальная ссылка:\n\n"
        f"<code>{referral_link}</code>\n\n"
        f"Отправьте эту ссылку друзьям! За каждого приведенного друга, который сыграет 20 игр, вы будете получать 10% от суммы его ставки."
    )
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "enter_promo")
async def enter_promo_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PromoStates.entering_code)
    await callback.message.edit_text(
        "🎟️ Введите ваш промокод:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
    )

@router.message(PromoStates.entering_code)
async def process_promo_code(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    code_text = message.text.upper().strip()

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        
        async with db.execute("SELECT id, type, value, max_uses, uses FROM promo_codes WHERE code = ?", (code_text,)) as cursor:
            promo = await cursor.fetchone()

        if not promo:
            await message.answer("❌ Промокод не найден или недействителен.", reply_markup=get_main_menu_keyboard())
            return
            
        promo_id, promo_type, value, max_uses, uses = promo

        if uses >= max_uses:
            await message.answer("❌ Этот промокод уже использован максимальное количество раз.", reply_markup=get_main_menu_keyboard())
            return

        
        async with db.execute("SELECT promo_id FROM used_promo_codes WHERE user_id = ? AND promo_id = ?", (user_id, promo_id)) as cursor:
            if await cursor.fetchone():
                await message.answer("❌ Вы уже использовали этот промокод.", reply_markup=get_main_menu_keyboard())
                return

        
        if promo_type == 'balance':
            await update_user_balance(user_id, value, f"promo_{code_text}")
            await message.answer(f"✅ Промокод успешно активирован! Вам начислено {value:.2f} USDT.", reply_markup=get_main_menu_keyboard())
        elif promo_type == 'wallet':
            await update_user_balance(user_id, value, f"promo_{code_text}")
            await message.answer(f"✅ Промокод на бонус к пополнению активирован! Вам начислено {value:.2f} USDT.", reply_markup=get_main_menu_keyboard())
        else:
            await message.answer("🤔 Неизвестный тип промокода. Обратитесь в поддержку.", reply_markup=get_main_menu_keyboard())
            return

        await db.execute("UPDATE promo_codes SET uses = uses + 1 WHERE id = ?", (promo_id,))
        await db.execute("INSERT INTO used_promo_codes (user_id, promo_id) VALUES (?, ?)", (user_id, promo_id))
        await db.commit()

@router.callback_query(F.data == "daily_bonus")
async def daily_bonus_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT last_bonus_claim FROM users WHERE user_id = ?", (user_id,)) as cursor:
            last_claim_str = (await cursor.fetchone())[0]

    time_now = datetime.now()
    if last_claim_str:
        last_claim_time = datetime.fromisoformat(last_claim_str)
        time_passed = time_now - last_claim_time
        if time_passed < timedelta(hours=24):
            time_left = timedelta(hours=24) - time_passed
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await callback.answer(f"Вы сможете получить следующий бонус через {hours} ч. {minutes} мин.", show_alert=True)
            return

    bonus_amount = round(random.uniform(0.1, 0.5), 2)
    await update_user_balance(user_id, bonus_amount, "daily_bonus")

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        await db.execute("UPDATE users SET last_bonus_claim = ? WHERE user_id = ?", (time_now.isoformat(), user_id))
        await db.commit()

    await callback.answer(f"🎉 Вы получили ежедневный бонус в размере {bonus_amount} USDT!", show_alert=True)


@router.callback_query(F.data == "support")
async def support_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportStates.writing_ticket)
    await callback.message.edit_text(
        "📨 Введите ваше сообщение для поддержки. Оно будет передано администратору.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
    )

@router.message(SupportStates.writing_ticket)
async def process_ticket_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "N/A"
    ticket_text = message.text

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        cursor = await db.execute(
            "INSERT INTO tickets (user_id, username, message, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, ticket_text, datetime.now().isoformat())
        )
        await db.commit()
        ticket_id = cursor.lastrowid
    
    await message.reply(f"✅ Ваше обращение #{ticket_id} принято! Администратор скоро с вами свяжется.")
    
    
    admin_text = (
        f"‼️ Новое обращение в поддержку!\n\n"
        f"<b>Тикет ID:</b> #{ticket_id}\n"
        f"<b>От:</b> @{username} (<code>{user_id}</code>)\n"
        f"<b>Сообщение:</b>\n{escape(ticket_text)}"
    )
    await bot.send_message(CONFIG["ADMIN_ID"], admin_text, parse_mode="HTML")
    await state.clear()


@router.message(Command("admin"))
async def admin_command(message: Message):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Добро пожаловать в панель администратора!", reply_markup=get_admin_keyboard())



@router.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT user_id, username, registration_date FROM users") as cursor:
            users = await cursor.fetchall()
    
    text = f"👥 Всего пользователей: {len(users)}\n\n"
    user_list = "\n".join([f"ID: <code>{user[0]}</code>, @{user[1]}, Рег: {user[2][:10]}" for user in users[:20]])
    text += user_list
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()



@router.callback_query(F.data.in_({
    "admin_user_info", "admin_freeze_user", "admin_zero_user", "admin_unfreeze_user",
    "admin_approve_withdrawal", "admin_reject_withdrawal", "admin_reply_ticket"
}))
async def admin_prompt_for_id(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    
    actions = {
        "admin_user_info": (AdminStates.entering_user_id_for_info, "Введите ID пользователя для получения информации:"),
        "admin_freeze_user": (AdminStates.entering_user_id_for_freeze, "Введите ID пользователя для заморозки баланса:"),
        "admin_zero_user": (AdminStates.entering_user_id_for_zero, "Введите ID пользователя для обнуления баланса:"),
        "admin_approve_withdrawal": (AdminStates.entering_withdrawal_id_for_approve, "Введите ID заявки на вывод для одобрения:"),
        "admin_unfreeze_user": (AdminStates.entering_user_id_for_unfreeze, "Введите ID пользователя для разморозки баланса:"),
        "admin_reject_withdrawal": (AdminStates.entering_withdrawal_id_for_reject, "Введите ID заявки на вывод для отклонения:"),
        "admin_reply_ticket": (AdminStates.entering_ticket_id_for_reply, "Введите ID тикета для ответа:")
    }
    
    action = actions[callback.data]
    await state.set_state(action[0])
    await callback.message.edit_text(action[1])
    await callback.answer()



@router.message(AdminStates.entering_user_id_for_info)
async def admin_get_user_info(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        
        user_id = int(message.text.strip()) 
        stats = await get_user_stats(user_id)
        if not stats:
            await message.answer("Пользователь не найден.")
            await state.clear() 
            return

        info_text = (
            f"ℹ️ Информация о пользователе <code>{user_id}</code>\n"
            f"<b>Ник:</b> {stats['nickname']}\n"
            f"<b>Юзернейм:</b> @{stats['username'] or 'не указан'}\n"
            f"<b>Баланс:</b> {stats['balance']:.2f} USDT\n"
            f"<b>Заморожено:</b> {stats['frozen_balance']:.2f} USDT\n"
            f"<b>Всего ставок:</b> {stats['total_bets']}\n"
            f"<b>Побед:</b> {stats['total_wins']}\n"
        )
        await message.answer(info_text, parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Неверный ID. Пожалуйста, введите только цифры.")
    finally:
        await state.clear()

@router.message(AdminStates.entering_user_id_for_zero)
async def admin_zero_user_balance(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        user_id = int(message.text)
        async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
            await db.execute("UPDATE user_balances SET balance = 0, frozen_balance = 0 WHERE user_id = ?", (user_id,))
            await db.commit()
        await message.answer(f"Баланс пользователя <code>{user_id}</code> обнулен.", parse_mode="HTML")
    except ValueError:
        await message.answer("Неверный ID.")
    finally:
        await state.clear()

@router.message(AdminStates.entering_user_id_for_freeze)
async def admin_freeze_user_balance(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        user_id = int(message.text)
        balance_info = await get_user_balance(user_id)
        await freeze_balance(user_id, balance_info['available'])
        await message.answer(f"Доступный баланс пользователя <code>{user_id}</code> ({balance_info['available']:.2f} USDT) заморожен.", parse_mode="HTML")
    except ValueError:
        await message.answer("Неверный ID.")
    finally:
        await state.clear()

@router.message(AdminStates.entering_user_id_for_unfreeze)
async def admin_unfreeze_user_balance(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        user_id = int(message.text)
        balance_info = await get_user_balance(user_id)
        frozen_amount = balance_info.get('frozen', 0.0)
        
        if frozen_amount > 0:
            await unfreeze_balance(user_id, frozen_amount)
            await message.answer(f"Баланс пользователя <code>{user_id}</code> разморожен на сумму {frozen_amount:.2f} USDT.", parse_mode="HTML")
        else:
            await message.answer(f"У пользователя <code>{user_id}</code> нет замороженных средств.", parse_mode="HTML")
            
    except ValueError:
        await message.answer("Неверный ID.")
    finally:
        await state.clear()

@router.message(AdminStates.entering_withdrawal_id_for_approve)
async def admin_process_approve_from_panel(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        request_id = int(message.text)
        response_text = await _process_approve_withdrawal(request_id)
        await message.answer(response_text)
    except ValueError:
        await message.answer("❌ Неверный ID. Введите только число.")
    finally:
        await state.clear()


@router.message(AdminStates.entering_withdrawal_id_for_reject)
async def admin_process_reject_from_panel(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        request_id = int(message.text)
        response_text = await _process_reject_withdrawal(request_id)
        await message.answer(response_text)
    except ValueError:
        await message.answer("❌ Неверный ID. Введите только число.")
    finally:
        await state.clear()
        
@router.callback_query(F.data == "admin_view_tickets")
async def admin_view_tickets_handler(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        async with db.execute("SELECT id, user_id, username, message FROM tickets WHERE status = 'open' LIMIT 10") as cursor:
            tickets = await cursor.fetchall()
    
    if not tickets:
        await callback.answer("Нет открытых тикетов.", show_alert=True)
        return
        
    text = "🎫 Открытые тикеты:\n\n"
    for ticket in tickets:
        text += f"<b>ID:</b> {ticket[0]}, <b>От:</b> @{ticket[2]} (<code>{ticket[1]}</code>)\n"
        text += f"<i>Сообщение:</i> {escape(ticket[3][:100])}...\n---\n"
    
    await callback.message.edit_text(text, parse_mode="HTML")

@router.message(AdminStates.entering_ticket_id_for_reply)
async def admin_enter_ticket_reply_text(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    try:
        ticket_id = int(message.text)
        
        await state.update_data(ticket_id=ticket_id)
        await state.set_state(AdminStates.writing_reply_to_ticket)
        await message.answer(f"Введите текст ответа для тикета #{ticket_id}:")
    except ValueError:
        await message.answer("Неверный ID тикета.")
        await state.clear()

@router.message(AdminStates.writing_reply_to_ticket)
async def admin_send_reply_to_user(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    reply_text = message.text

    async with aiosqlite.connect(CONFIG["DB_PATH"]) as db:
        
        async with db.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,)) as cursor:
            result = await cursor.fetchone()
        
        if not result:
            await message.answer(f"Тикет #{ticket_id} не найден.")
            await state.clear()
            return

        user_id_to_reply = result[0]
        
        await db.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
        await db.commit()
    
    try:
        await bot.send_message(user_id_to_reply, f"📨 Ответ от поддержки по вашему обращению #{ticket_id}:\n\n{reply_text}")
        await message.answer(f"✅ Ответ на тикет #{ticket_id} успешно отправлен пользователю.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ пользователю {user_id_to_reply}. Возможно, он заблокировал бота. Ошибка: {e}")
    finally:
        await state.clear()



async def main():
    if CONFIG["BOT_TOKEN"] == "Your Token Here":
        logger.error("❌ ОШИБКА: Не установлен BOT_TOKEN!")
        return
    if CONFIG["ADMIN_ID"] == 0:
        logger.error("❌ ОШИБКА: Не установлен ADMIN_ID!")
        return
    
    logger.info("🚀 Запуск GameBot...")
    await init_db()

    asyncio.create_task(run_periodic_tasks())

    
    if CONFIG.get("DROPBOX_REFRESH_TOKEN") and CONFIG.get("DROPBOX_APP_KEY"):
        logger.info("Найдена конфигурация Dropbox. Запускаю синхронизацию и бэкапы.")
        await sync_promo_codes_from_dropbox()
        asyncio.create_task(run_periodic_backups())
    else:
        logger.warning("Токен Dropbox не настроен. Бэкапы и промокоды отключены.")
        
    commands = [
        BotCommand(command="start", description="🚀 Запуск бота"),
        BotCommand(command="bet", description="🎮 Создать ставку в группе"),
        BotCommand(command="profile", description="📊 Мой профиль")
    ]
    admin_commands = [
        BotCommand(command="approve_withdrawal", description="✅ Одобрить вывод"),
        BotCommand(command="reject_withdrawal", description="❌ Отклонить вывод")
    ]
    await bot.set_my_commands(commands)
    await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=CONFIG["ADMIN_ID"]))
    
    if crypto_api.test_mode:
        logger.warning("⚠️ Бот запущен в ТЕСТОВОМ РЕЖИМЕ")
    else:
        logger.info("✅ Бот запущен с CryptoBot API")
    
    logger.info("✅ Бот готов к работе!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот остановлен.")
