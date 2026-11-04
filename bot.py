import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, 
    ChatJoinRequest, 
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    PreCheckoutQuery,
    LabeledPrice
)
from aiogram.enums import ChatMemberStatus
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
dp = Dispatcher()

DB_PATH = "saas_bot.db"
FREE_LIMIT = 100 
PREMIUM_PRICE = 150

# ==========================================
# БАЗА ДАННЫХ
# ==========================================
def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                user_id INTEGER PRIMARY KEY, username TEXT, joined_at TEXT, referrer_id INTEGER
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY, owner_id INTEGER, title TEXT,
                is_active BOOLEAN DEFAULT 1, requests_used INTEGER DEFAULT 0, 
                is_premium BOOLEAN DEFAULT 0, bonus_requests INTEGER DEFAULT 0
            )
        """)
        con.commit()

def save_owner(user_id, username, referrer_id=None):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT user_id FROM owners WHERE user_id = ?", (user_id,))
        if not cur.fetchone():
            con.execute("INSERT INTO owners (user_id, username, joined_at, referrer_id) VALUES (?, ?, ?, ?)",
                        (user_id, username, datetime.now().isoformat(), referrer_id))
        con.commit()

def save_channel(channel_id, owner_id, title):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            INSERT INTO channels (channel_id, owner_id, title, is_active) 
            VALUES (?, ?, ?, 1)
            ON CONFLICT(channel_id) DO UPDATE SET owner_id = excluded.owner_id, title = excluded.title, is_active = 1
        """, (channel_id, owner_id, title))
        con.commit()

def check_limit(channel_id):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT requests_used, is_premium, bonus_requests FROM channels WHERE channel_id = ?", (channel_id,))
        row = cur.fetchone()
        if not row: return False
        used, is_premium, bonus = row
        if is_premium == 1: return True
        return used < (FREE_LIMIT + bonus)

def increment_requests(channel_id):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE channels SET requests_used = requests_used + 1 WHERE channel_id = ?", (channel_id,))
        con.commit()

def set_premium(channel_id):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE channels SET is_premium = 1 WHERE channel_id = ?", (channel_id,))
        con.commit()

def get_user_channels(owner_id):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT title, channel_id, requests_used, is_premium, bonus_requests FROM channels WHERE owner_id = ? AND is_active = 1", (owner_id,))
        return cur.fetchall()

def add_referral_bonus(referrer_id):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE channels SET bonus_requests = bonus_requests + 100 WHERE owner_id = ?", (referrer_id,))
        con.commit()

# ==========================================
# ГЛАВНОЕ МЕНЮ И КНОПКИ
# ==========================================

def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои каналы", callback_data="menu_channels")],
        [InlineKeyboardButton(text="💎 Купить безлимит", callback_data="menu_buy")],
        [InlineKeyboardButton(text="🤝 Пригласить друга", callback_data="menu_ref")],
        [InlineKeyboardButton(text="ℹ️ Инструкция", callback_data="menu_help")]
    ])

@dp.message(CommandStart(deep_link=True))
async def start_with_ref(message: Message, command: CommandStart):
    referrer_id = None
    if command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args.split("_")[1])
        except ValueError:
            pass
    
    save_owner(message.from_user.id, message.from_user.username, referrer_id)
    if referrer_id:
        await message.answer("🎁 Вы перешли по приглашению! Ваш друг получит бонус, когда вы подключите канал.")
    await start_cmd(message)

@dp.message(Command("start"))
async def start_cmd(message: Message):
    save_owner(message.from_user.id, message.from_user.username)
    text = (
        "👋 Привет! Я бот для автоматического одобрения заявок в Telegram-каналы.\n\n"
        "Я работаю 24/7 и пускаю людей в канал моментально, как только они нажимают «Подать заявку».\n\n"
        "Выбери нужное действие в меню ниже 👇"
    )
    await message.answer(text, reply_markup=get_main_menu())

# ==========================================
# ОБРАБОТКА КНОПОК МЕНЮ
# ==========================================

@dp.callback_query(F.data == "menu_channels")
async def menu_channels(callback: CallbackQuery):
    channels = get_user_channels(callback.from_user.id)
    if not channels:
        await callback.message.answer("У вас пока нет подключенных каналов.\n\nДобавьте меня в свой канал как администратора с правом «Приглашать пользователей», и я автоматически подхвачу его.")
    else:
        text = "📋 **Ваши каналы:**\n\n"
        for title, ch_id, used, prem, bonus in channels:
            total_limit = FREE_LIMIT + bonus
            status = "💎 Премиум (безлимит)" if prem else f"Осталось заявок: {total_limit - used} из {total_limit}"
            text += f"▪️ **{title}**\n   └ {status}\n\n"
        await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "menu_ref")
async def menu_ref(callback: CallbackQuery, bot: Bot):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"
    text = (
        "🤝 **Реферальная программа**\n\n"
        "Пригласи владельца другого канала. Как только он добавит меня в свой канал, "
        "ты получишь **+100 бесплатных заявок** на свой баланс!\n\n"
        f"Твоя ссылка для приглашения:\n`{ref_link}`\n\n"
        "Просто скопируй её и отправь другу."
    )
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery):
    text = (
        "ℹ️ **Как это работает:**\n\n"
        "1. Нажми «Принять в группу» в профиле бота (или добавь его в админы вручную).\n"
        "2. Выбери свой канал.\n"
        "3. Обязательно поставь галочку **«Приглашать пользователей»**.\n"
        "4. В настройках канала включи **«Заявки на вступление»**.\n\n"
        "Всё! Теперь любой, кто нажмёт «Подать заявку», будет мгновенно одобрен."
    )
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "menu_buy")
async def menu_buy(callback: CallbackQuery):
    channels = get_user_channels(callback.from_user.id)
    if not channels:
        await callback.message.answer("Сначала подключите канал, чтобы купить для него безлимит.")
    else:
        kb_buttons = []
        for title, ch_id, used, prem, bonus in channels:
            if not prem:
                kb_buttons.append([InlineKeyboardButton(text=f"Оплатить {title}", callback_data=f"buy_{ch_id}")])
        
        if not kb_buttons:
            await callback.message.answer("У всех ваших каналов уже куплен безлимит (Премиум).")
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
            await callback.message.answer(f"Выберите канал для покупки безлимита за {PREMIUM_PRICE} ⭐:", reply_markup=kb)
    await callback.answer()

# ==========================================
# АВТООДОБРЕНИЕ И РЕФЕРАЛКА
# ==========================================

@dp.my_chat_member()
async def bot_added_to_chat(update: ChatMemberUpdated, bot: Bot):
    if update.chat.type != "channel": return
    chat_id, title, owner_id = update.chat.id, update.chat.title, update.from_user.id
    
    if update.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR and update.new_chat_member.can_invite_users:
        save_channel(chat_id, owner_id, title)
        try:
            await bot.send_message(owner_id, f"✅ Канал **{title}** подключен!\nУ вас есть {FREE_LIMIT} бесплатных заявок.", parse_mode="Markdown", reply_markup=get_main_menu())
        except Exception: pass
        
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute("SELECT referrer_id FROM owners WHERE user_id = ?", (owner_id,))
            row = cur.fetchone()
            if row and row[0]:
                referrer = row[0]
                add_referral_bonus(referrer)
                con.execute("UPDATE owners SET referrer_id = NULL WHERE user_id = ?", (owner_id,))
                con.commit()
                try:
                    await bot.send_message(referrer, "🎉 По вашей ссылке подключили канал! Вам начислено **+100 бесплатных заявок**.", parse_mode="Markdown")
                except Exception: pass

@dp.chat_join_request()
async def auto_approve_join(request: ChatJoinRequest, bot: Bot):
    channel_id, user_id = request.chat.id, request.from_user.id
    
    if not check_limit(channel_id):
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute("SELECT owner_id, title FROM channels WHERE channel_id = ?", (channel_id,))
            owner_data = cur.fetchone()
            if owner_data:
                owner_id, title = owner_data
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"Купить безлимит за {PREMIUM_PRICE} ⭐", callback_data=f"buy_{channel_id}")]
                ])
                try:
                    await bot.send_message(owner_id, f"⚠️ В канале **{title}** закончились заявки! Купите безлимит.", reply_markup=kb, parse_mode="Markdown")
                except Exception: pass
        return

    try:
        await bot.approve_chat_join_request(chat_id=channel_id, user_id=user_id)
        increment_requests(channel_id)
    except Exception as e:
        logging.error(f"❌ Ошибка: {e}")

# ==========================================
# ОПЛАТА
# ==========================================

@dp.callback_query(F.data.startswith("buy_"))
async def buy_premium(callback: CallbackQuery, bot: Bot):
    channel_id = int(callback.data.split("_")[1])
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Безлимитные заявки",
        description="Автоматическое одобрение без ограничений.",
        payload=f"premium_{channel_id}",
        provider_token="", currency="XTR",
        prices=[LabeledPrice(label="Безлимит", amount=PREMIUM_PRICE)],
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    payload = message.successful_payment.invoice_payload
    channel_id = int(payload.split("_")[1])
    set_premium(channel_id)
    await message.answer("💎 **Оплата прошла успешно!** Ваш канал теперь безлимитный.", parse_mode="Markdown")

async def main():
    init_db()
    bot = Bot(token=BOT_TOKEN)
    logging.info("🚀 SaaS-Бот с меню запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
