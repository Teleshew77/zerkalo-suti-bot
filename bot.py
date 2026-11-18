"""Зеркало сути — Telegram bot with YooKassa test payments and admin receipt workflow."""
import asyncio
import html
import logging
import os
import re
import time
import uuid
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from pathlib import Path

import aiosqlite
import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    Message, FSInputFile,
)
from dotenv import load_dotenv

load_dotenv(override=True)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
PRICE_RUB = Decimal(os.getenv("PRICE_RUB", "430.00")).quantize(Decimal("0.01"))
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "").strip()
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "").strip()
YOOKASSA_TEST_MODE = os.getenv("YOOKASSA_TEST_MODE", "true").lower() == "true"
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/code_om").strip()
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "@YOUR_SUPPORT").strip()
PRIVACY_POLICY_URL = os.getenv("PRIVACY_POLICY_URL", "").strip()
DB_PATH = os.getenv("DB_PATH", "bot.sqlite3")
FOLLOWUP_SECONDS = int(os.getenv("FOLLOWUP_SECONDS", "7200"))
if FOLLOWUP_SECONDS < 60:
    raise RuntimeError("FOLLOWUP_SECONDS должен быть не меньше 60 секунд")
PAYMENT_POLL_SECONDS = max(5, int(os.getenv("PAYMENT_POLL_SECONDS", "5")))
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

if not TOKEN or "REPLACE" in TOKEN:
    raise RuntimeError("Укажи действительный BOT_TOKEN в .env")
if PRICE_RUB <= 0:
    raise RuntimeError("PRICE_RUB должен быть больше нуля")
if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
    raise RuntimeError("Укажи YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY в .env")
if not YOOKASSA_TEST_MODE or not YOOKASSA_SECRET_KEY.startswith("test_"):
    raise RuntimeError("Эта версия работает только в тестовом режиме ЮKassa.")
if not CHANNEL_URL.startswith("https://t.me/"):
    raise RuntimeError("CHANNEL_URL должен начинаться с https://t.me/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
router = Router()

WELCOME = """Привет. Я — Ирина Ом.
Рада, что ты здесь. Если ты читаешь эти строки, значит, пришло время увидеть свою истинную опору и перестать откладывать свой масштаб на потом.
Свою суть невозможно разглядеть через советы других людей — каждый смотрит на тебя через кальку своих ожиданий, страхов и проекций. Но можно увидеть себя через <b>чистое зеркало</b> — нейросеть, которой правильно задали вектор.
Именно так за один вечер я собрала свой пазл, приняла свою глубинную силу и поняла, что в 51 год моя жизнь только начинается.

<b>Что ждёт тебя внутри практики «Зеркало сути»:</b>
• <b>Шаг 1. Расчистка смыслов.</b> Ты увидишь, как древние корни твоих главных слов-триггеров освобождают от навязанных страхов.
• <b>Шаг 2. Код имени и рода.</b> Мы соберём твою целостную карту через происхождение твоего имени, фамилии и природной энергии.
• <b>Шаг 3. Принятие тени.</b> Ты обнаружишь свою скрытую силу («Альфу»), которую раньше сдерживала, и почувствуешь внутренний источник ответов.

По глубине осознаний эта практика заменяет недели поиска, а её базовая ценность — <b>990 ₽</b>.
Но сейчас я открываю первый поток доступа по символической цене — <b>430 ₽</b> (как чашка хорошего кофе), чтобы ты могла легко прикоснуться к этому инструменту и встретиться с собой настоящей.

👇 <i>Нажми кнопку ниже, чтобы оплатить доступ и сразу забрать промпт-проводник.</i>

<i>Оплата проводится на защищённой странице ЮKassa. Сейчас доступен тестовый режим.</i>"""
INSTRUCTION = """Благодарю за доверие и энергообмен. Твой доступ открыт.
Выдели 20–30 минут в тишине, чтобы тебя никто не отвлекал. Открой любой привычный чат с искусственным интеллектом (ChatGPT, Claude, DeepSeek или Алису).
👇 <b>Нажми на блок с текстом ниже, чтобы скопировать его.</b> Вставь его в чат с нейросетью, отправь и отвечай на вопросы максимально честно — не «как правильно», а как откликается в теле."""
PROMPT_HTML = """<b>✦ ЗЕРКАЛО СУТИ</b>
<i>Практика самопознания через язык, имя и честный диалог</i>

━━━━━━━━━━━━━━━━━━

<b>ТВОЯ РОЛЬ</b>

Выступи для меня мудрым проводником, внимательным лингвистом и глубоким философским зеркалом.

Помоги мне через исследование слов, имени и честные вопросы увидеть свою суть, найти внутреннюю опору и собрать более целостный образ себя.

<b>ВАЖНЫЙ ПРИНЦИП</b>
Отделяй подтверждённые исторические и этимологические сведения от гипотез, ассоциаций и символических трактовок. Не выдумывай происхождение слов и имён. Если версия спорная или данных недостаточно — прямо скажи об этом. Символический смысл можно предложить как повод для размышления, но не выдавай его за научный факт.

<b>КАК МЫ БУДЕМ РАБОТАТЬ</b>

Веди меня постепенно. Не раскрывай все этапы сразу. Задавай по одному-два точных вопроса и дожидайся моего ответа, прежде чем двигаться дальше. Сохраняй бережный, уважительный тон — без оценок, давления и готовых диагнозов.

━━━━━━━━━━━━━━━━━━

<b>01 · РАСЧИСТКА СМЫСЛОВ</b>

Попроси меня назвать 3–5 слов или понятий, которые сейчас особенно важны для меня. Например:
<i>возраст · свобода · время · сила · любовь · страх · путь</i>

Когда я назову их:
• исследуй происхождение и историю каждого слова;
• объясни, какие значения подтверждаются источниками, а какие являются поздними или спорными трактовками;
• предложи вопросы о том, что эти слова значат лично для меня;
• покажи возможные связи между ними.

Не утверждай, что у слова обязательно был единый «чистый смысл», и не приписывай древним людям недоказанные намерения.

<b>02 · ИМЯ И РОД</b>

Когда первый этап будет завершён, попроси меня назвать:
• имя;
• фамилию сейчас и при рождении, если она менялась;
• творческий псевдоним или сокращённую форму, если они есть.

Расскажи об истории и происхождении этих имён, если сведения доступны. Уточняй язык, регион и возможные варианты происхождения. Не делай выводов о характере, судьбе или наследственности только на основании имени или фамилии.

Затем предложи символические ассоциации и помоги связать их с темами, которые мы исследовали на первом этапе. Чётко обозначай, где заканчиваются факты и начинается интерпретация.

<b>03 · СБОРКА И ПРИНЯТИЕ ТЕНИ</b>

Помоги мне осмыслить получившуюся картину:
• какие качества и ценности дают мне опору;
• какие стороны себя я привыкла скрывать или недооценивать;
• какие внутренние противоречия повторяются в моих ответах;
• что я хочу принять, изменить или исследовать глубже.

Исследуй мою «Альфу» как метафору внутренней силы, а не как заранее заданный тип личности. Не навязывай выводы — проверяй их вопросами и оставляй мне право не соглашаться.

В завершение задай один точный, объединяющий вопрос, который поможет мне сформулировать собственную опору и следующий осознанный шаг.

━━━━━━━━━━━━━━━━━━

<b>НАЧНИ СЕЙЧАС</b>

Поздоровайся со мной тепло и спокойно. Кратко объясни, что мы будем двигаться шаг за шагом, и задай первый вопрос: какие 3–5 слов или понятий сейчас сильнее всего откликаются в моей жизни?"""
FOLLOWUP = """Как прошла твоя встреча с собой? Удалось нащупать своё недостающее звено?
Если захочешь поделиться своим открытием (мне будет очень ценно прочитать твой отклик) или просто оставаться в пространстве, где мы учимся стирать старые сценарии, возвращать телу лёгкость и опираться на свою глубину — заходи в мой основной канал <b>OM_CODE</b>.
Там я делюсь своими наблюдениями, практиками состояния и тем, как строится жизнь, когда ты наконец выбираешь себя."""

HELP_TEXT = (
    "<b>Помощь по практике «Зеркало сути»</b>\n\n"
    "• /start — открыть главное меню\n"
    "• /help — показать эту справку\n"
    "• /access — повторно получить оплаченный промпт\n"
    "• /paysupport — связаться по вопросам оплаты\n\n"
    "Email запрашивается только для оформления и передачи чека по заказу. "
    "После оплаты доступ открывается автоматически. "
    "Если материал не пришёл, используй /access."
)

def main_menu(purchased: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if purchased:
        rows.append([InlineKeyboardButton(
            text="📖 Получить промпт", callback_data="access"
        )])
    else:
        rows.append([InlineKeyboardButton(
            text=f"Получить доступ — {PRICE_RUB:.2f} ₽", callback_data="buy"
        )])
    rows.append([
        InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help"),
        InlineKeyboardButton(text="🏠 В начало", callback_data="home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏠 В главное меню", callback_data="home")
    ]])

def channel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Перейти в канал OM_CODE", url=CHANNEL_URL)
    ]])

async def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            source TEXT NOT NULL DEFAULT 'direct',
            created_at INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            email TEXT,
            email_consent_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS pending_email (
            user_id INTEGER PRIMARY KEY,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS purchases (
            user_id INTEGER PRIMARY KEY,
            charge_id TEXT UNIQUE NOT NULL,
            payload TEXT NOT NULL,
            paid_at INTEGER NOT NULL,
            delivered_at INTEGER,
            delivery_claimed_at INTEGER,
            followup_at INTEGER,
            followup_claimed_at INTEGER,
            followup_sent_at INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS payment_orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            payment_id TEXT UNIQUE,
            status TEXT NOT NULL,
            amount TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            payment_id TEXT NOT NULL UNIQUE,
            order_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            receipt_type TEXT,
            receipt_file_id TEXT,
            receipt_text TEXT,
            admin_id INTEGER,
            created_at INTEGER NOT NULL,
            sent_at INTEGER,
            admin_notified_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS admin_receipt_sessions (
            admin_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            payment_id TEXT NOT NULL,
            started_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_followup
            ON purchases(followup_at, followup_sent_at);
        CREATE INDEX IF NOT EXISTS idx_receipts_status
            ON receipts(status, created_at);
        """)
        # Backward-compatible user/email migration.
        async with db.execute("PRAGMA table_info(users)") as cur:
            user_cols = {row[1] for row in await cur.fetchall()}
        if "email" not in user_cols:
            await db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "email_consent_at" not in user_cols:
            await db.execute("ALTER TABLE users ADD COLUMN email_consent_at INTEGER")

        # The first delivery is the anchor for all unsent follow-up messages.
        await db.execute(
            """UPDATE purchases SET followup_at=delivered_at+?
               WHERE delivered_at IS NOT NULL AND followup_sent_at IS NULL""",
            (FOLLOWUP_SECONDS,),
        )

        # Migrations for databases from earlier bot versions.
        async with db.execute("PRAGMA table_info(receipts)") as cur:
            receipt_cols = {row[1] for row in await cur.fetchall()}
        if "admin_notified_at" not in receipt_cols:
            await db.execute("ALTER TABLE receipts ADD COLUMN admin_notified_at INTEGER")

        async with db.execute("PRAGMA table_info(purchases)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "delivery_claimed_at" not in cols:
            await db.execute("ALTER TABLE purchases ADD COLUMN delivery_claimed_at INTEGER")
        # Reconcile every unsent follow-up against the current .env setting.
        # The original delivery timestamp is authoritative.
        await db.execute(
            """UPDATE purchases
               SET followup_at=delivered_at + ?
               WHERE delivered_at IS NOT NULL
                 AND followup_sent_at IS NULL""",
            (FOLLOWUP_SECONDS,),
        )
        await db.commit()

async def create_yookassa_payment(user_id: int, order_id: str, return_url: str) -> dict:
    body = {
        "amount": {"value": f"{PRICE_RUB:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": "Зеркало сути — доступ к практике",
        "metadata": {"order_id": order_id, "user_id": str(user_id)},
    }
    headers = {"Idempotence-Key": order_id, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.post(
            "https://api.yookassa.ru/v3/payments",
            json=body,
            headers=headers,
            auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
        )
        response.raise_for_status()
        return response.json()

async def get_yookassa_payment(payment_id: str) -> dict:
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.get(
            f"https://api.yookassa.ru/v3/payments/{payment_id}",
            auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
        )
        response.raise_for_status()
        return response.json()

async def touch_user(user_id: int, source: str | None = None) -> None:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users(user_id,source,created_at,last_seen)
               VALUES(?,?,?,?)""",
            (user_id, source or "direct", now, now),
        )
        await db.execute("UPDATE users SET last_seen=? WHERE user_id=?", (now, user_id))
        await db.commit()

async def get_purchase(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM purchases WHERE user_id=?", (user_id,)) as cur:
            return await cur.fetchone()

async def get_user_email(user_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT email FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def save_user_email(user_id: int, email: str) -> None:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET email=?,email_consent_at=?,last_seen=? WHERE user_id=?",
            (email, now, now, user_id),
        )
        await db.execute("DELETE FROM pending_email WHERE user_id=?", (user_id,))
        await db.commit()

async def get_order(order_id: str, user_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if user_id is None:
            query, args = "SELECT * FROM payment_orders WHERE order_id=?", (order_id,)
        else:
            query, args = (
                "SELECT * FROM payment_orders WHERE order_id=? AND user_id=?",
                (order_id, user_id),
            )
        async with db.execute(query, args) as cur:
            return await cur.fetchone()

async def save_payment_order(order_id: str, payment_id: str, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payment_orders SET payment_id=?,status=? WHERE order_id=?",
            (payment_id, status, order_id),
        )
        await db.commit()

async def register_purchase(user_id: int, payment_id: str, order_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO purchases(user_id,charge_id,payload,paid_at)
               VALUES(?,?,?,?)""",
            (user_id, payment_id, f"yookassa:{order_id}", int(time.time())),
        )
        await db.commit()

async def claim_delivery(user_id: int, allow_repeat: bool = False) -> bool:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """UPDATE purchases SET delivery_claimed_at=?
               WHERE user_id=?
                 AND (delivery_claimed_at IS NULL OR delivery_claimed_at < ?)
                 AND (?=1 OR delivered_at IS NULL)""",
            (now, user_id, now - 900, int(allow_repeat)),
        )
        await db.commit()
        return cur.rowcount == 1

async def release_delivery(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE purchases SET delivery_claimed_at=NULL WHERE user_id=?",
            (user_id,),
        )
        await db.commit()

async def mark_delivered(user_id: int) -> None:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE purchases
               SET delivered_at=COALESCE(delivered_at,?),
                   followup_at=CASE
                       WHEN delivered_at IS NULL THEN ?
                       ELSE followup_at
                   END,
                   delivery_claimed_at=NULL
               WHERE user_id=?""",
            (now, now + FOLLOWUP_SECONDS, user_id),
        )
        await db.commit()

async def send_product(bot: Bot, user_id: int, allow_repeat: bool = False) -> bool:
    if not await claim_delivery(user_id, allow_repeat):
        return False
    text = (
        f"{INSTRUCTION}\n\n"
        f"{PROMPT_HTML}\n\n"
        "<i>Сначала скопируй текст практики, затем нажми «Начни сейчас» "
        "и вставь его в открывшийся чат с ИИ.</i>"
    )
    practice_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✦ Начни сейчас",
            url="https://chatgpt.com/",
        )
    ]])
    try:
        await bot.send_message(
            user_id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=practice_keyboard,
            disable_web_page_preview=True,
        )
    except Exception:
        await release_delivery(user_id)
        raise
    await mark_delivered(user_id)
    log.info(
        "Первичная выдача завершена для user_id=%s; follow-up запланирован через %s сек.",
        user_id, FOLLOWUP_SECONDS,
    )
    return True

def payment_is_valid(payment: dict, order) -> bool:
    amount = payment.get("amount") or {}
    metadata = payment.get("metadata") or {}
    try:
        actual = Decimal(str(amount.get("value", ""))).quantize(Decimal("0.01"))
        expected = Decimal(str(order["amount"])).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return False
    return (
        payment.get("id") == order["payment_id"]
        and payment.get("status") == "succeeded"
        and payment.get("paid") is True
        and amount.get("currency") == "RUB"
        and actual == expected
        and str(metadata.get("user_id")) == str(order["user_id"])
        and metadata.get("order_id") == order["order_id"]
    )

async def notify_admins_payment(bot: Bot, order) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO receipts
               (user_id,payment_id,order_id,status,created_at)
               VALUES(?,?,?,'pending',?)""",
            (order["user_id"], order["payment_id"], order["order_id"], int(time.time())),
        )
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id,admin_notified_at,status FROM receipts WHERE payment_id=?",
            (order["payment_id"],),
        ) as cur:
            receipt = await cur.fetchone()
        await db.commit()

    if not receipt or receipt["status"] != "pending" or receipt["admin_notified_at"] is not None:
        return
    if not ADMIN_IDS:
        log.error("Оплата %s подтверждена, но ADMIN_IDS не настроен.", order["payment_id"])
        return

    buyer_email = await get_user_email(order["user_id"]) or "не указан"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🧾 Отправить чек покупателю",
            callback_data=f"receipt:{receipt['id']}",
        )
    ]])
    notice = (
        "<b>Новая оплата — требуется чек</b>\n"
        f"Покупатель: <code>{order['user_id']}</code>\n"
        f"Email: <code>{html.escape(buyer_email)}</code>\n"
        f"Платёж: <code>{html.escape(order['payment_id'])}</code>\n"
        f"Сумма: <b>{html.escape(order['amount'])} ₽</b>\n\n"
        "Сформируй официальный чек в приложении «Мой налог», затем нажми кнопку "
        "и отправь покупателю ссылку, фото или PDF. Обычный файл не заменяет чек из «Мой налог»."
    )
    delivered_to_admin = False
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id, notice, reply_markup=keyboard, parse_mode=ParseMode.HTML
            )
            delivered_to_admin = True
        except TelegramAPIError:
            log.exception("Не удалось уведомить администратора %s", admin_id)

    if delivered_to_admin:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE receipts SET admin_notified_at=? WHERE id=? AND admin_notified_at IS NULL",
                (int(time.time()), receipt["id"]),
            )
            await db.commit()

async def finalize_payment(bot: Bot, order, payment: dict) -> bool:
    if not payment_is_valid(payment, order):
        log.error("Payment verification failed for order %s", order["order_id"])
        return False
    await touch_user(order["user_id"])
    await register_purchase(order["user_id"], order["payment_id"], order["order_id"])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE payment_orders SET status='succeeded' WHERE order_id=?",
            (order["order_id"],),
        )
        await db.commit()
    # Receipt task is independent of product delivery; both are idempotent.
    await notify_admins_payment(bot, order)
    try:
        delivered = await send_product(bot, order["user_id"])
        if delivered:
            log.info("Product delivered to user %s", order["user_id"])
    except TelegramAPIError:
        log.exception("Payment succeeded, but product delivery failed for %s", order["user_id"])
    return True

async def poll_one_order(bot: Bot, order) -> str:
    payment = await get_yookassa_payment(order["payment_id"])
    status = payment.get("status", "unknown")
    if status == "succeeded":
        await finalize_payment(bot, order, payment)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE payment_orders SET status=? WHERE order_id=?",
                (status, order["order_id"]),
            )
            await db.commit()
    return status

async def show_home(message: Message, user_id: int) -> None:
    saved = await get_purchase(user_id)
    if saved:
        text = "Твой доступ к практике «Зеркало сути» уже открыт."
        await message.answer(text, reply_markup=main_menu(True))
    else:
        await message.answer(WELCOME, reply_markup=main_menu(False), parse_mode=ParseMode.HTML)

@router.message(CommandStart())
async def start(message: Message, command: CommandObject, bot: Bot) -> None:
    if not message.from_user or message.chat.type != "private":
        return
    raw = (command.args or "").strip()
    source = raw[:64] if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", raw) else "direct"
    await touch_user(message.from_user.id, source)
    await show_home(message, message.from_user.id)

POLICY_DOC_PATH = Path(__file__).resolve().with_name("Politika_konfidencialnosti_Zerkalo_suti.docx")

async def send_policy_document(message: Message) -> None:
    if not POLICY_DOC_PATH.exists():
        await message.answer(
            "Документ политики конфиденциальности пока не найден. "
            "Администратору нужно положить DOCX рядом с bot.py."
        )
        return
    await message.answer_document(
        FSInputFile(POLICY_DOC_PATH, filename="Политика_конфиденциальности_Зеркало_сути.docx"),
        caption=(
            "Проект политики конфиденциальности «Зеркало сути». "
            "Документ требует заполнения реквизитов оператора и проверки перед публикацией."
        ),
    )

@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer(HELP_TEXT, reply_markup=help_keyboard(), parse_mode=ParseMode.HTML)
        await send_policy_document(message)

@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_text(
                HELP_TEXT,
                reply_markup=help_keyboard(),
                parse_mode=ParseMode.HTML,
            )
        except TelegramAPIError:
            log.info("Не удалось обновить меню помощи для %s", callback.from_user.id)
        await send_policy_document(callback.message)

@router.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    saved = await get_purchase(callback.from_user.id)
    if saved:
        text = "Твой доступ к практике «Зеркало сути» уже открыт."
        markup = main_menu(True)
        parse_mode = None
    else:
        text = WELCOME
        markup = main_menu(False)
        parse_mode = ParseMode.HTML
    try:
        await callback.message.edit_text(
            text,
            reply_markup=markup,
            parse_mode=parse_mode,
        )
    except TelegramAPIError:
        log.info("Не удалось обновить главное меню для %s", callback.from_user.id)

def consent_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text="Согласен(на), продолжить",
        callback_data="email_consent",
    )]]
    if PRIVACY_POLICY_URL.startswith("https://"):
        rows.append([InlineKeyboardButton(
            text="Политика конфиденциальности",
            url=PRIVACY_POLICY_URL,
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def create_payment_for_user(bot: Bot, user_id: int, message: Message) -> None:
    order_id = uuid.uuid4().hex
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO payment_orders(order_id,user_id,status,amount,created_at)
               VALUES(?,?,?,?,?)""",
            (order_id, user_id, "creating", f"{PRICE_RUB:.2f}", int(time.time())),
        )
        await db.commit()
    try:
        me = await bot.get_me()
        payment = await create_yookassa_payment(
            user_id, order_id, f"https://t.me/{me.username}"
        )
        payment_id = payment.get("id")
        url = (payment.get("confirmation") or {}).get("confirmation_url")
        if not payment_id or not url:
            raise RuntimeError("ЮKassa не вернула payment_id или confirmation_url")
        await save_payment_order(order_id, payment_id, payment.get("status", "pending"))
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError):
        log.exception("Не удалось создать платёж для %s", user_id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE payment_orders SET status='create_failed' WHERE order_id=?",
                (order_id,),
            )
            await db.commit()
        await message.answer("Не удалось создать тестовый платёж. Попробуй позже.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {PRICE_RUB:.2f} ₽ (тест)", url=url)],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ])
    await message.answer(
        "Тестовый счёт создан. После оплаты доступ откроется автоматически. "
        f"Статус проверяется каждые {PAYMENT_POLL_SECONDS} секунд. "
        "Реальные деньги не списываются.",
        reply_markup=keyboard,
    )

@router.callback_query(F.data == "buy")
async def buy(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.message:
        await callback.answer()
        return
    uid = callback.from_user.id
    await touch_user(uid)
    if await get_purchase(uid):
        await callback.answer("Доступ уже открыт", show_alert=True)
        return
    if await get_user_email(uid):
        await callback.answer()
        await create_payment_for_user(bot, uid, callback.message)
        return
    await callback.answer()
    if not PRIVACY_POLICY_URL.startswith("https://"):
        await callback.message.answer(
            "<b>Настройка ещё не завершена</b>\\n\\n"
            "Администратору необходимо добавить публичную ссылку на политику конфиденциальности "
            "в параметр PRIVACY_POLICY_URL в файле .env. До этого сбор email отключён.",
            parse_mode=ParseMode.HTML,
        )
        return
    await callback.message.answer(
        "<b>Перед покупкой</b>\\n\\n"
        "Для оформления и передачи чека попросим электронную почту. "
        "Адрес будет использоваться для передачи чека и сообщений, связанных с заказом.\\n"
        "Перед продолжением ознакомься с политикой конфиденциальности по кнопке ниже.\\n\\n"
        "Нажимая «Согласен(на), продолжить», ты подтверждаешь согласие "
        "на обработку email для указанных целей.",
        reply_markup=consent_keyboard(),
        parse_mode=ParseMode.HTML,
    )

@router.callback_query(F.data == "email_consent")
async def email_consent(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO pending_email(user_id,created_at) VALUES(?,?)",
            (callback.from_user.id, int(time.time())),
        )
        await db.commit()
    await callback.message.answer(
        "Напиши свой email одним сообщением. Например: name@example.com\n"
        "Для отмены используй /cancel.",
    )

@router.message(Command("cancel"))
async def cancel_email(message: Message) -> None:
    if not message.from_user or message.chat.type != "private":
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_email WHERE user_id=?", (message.from_user.id,))
        await db.commit()
    await message.answer("Ввод email отменён. Для новой попытки нажми /start.")

@router.message(F.chat.type == "private", F.text)
async def capture_buyer_email(message: Message, bot: Bot) -> None:
    if not message.from_user or message.from_user.id in ADMIN_IDS:
        return
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM pending_email WHERE user_id=?", (uid,)
        ) as cur:
            pending = await cur.fetchone()
    if not pending:
        return
    email = (message.text or "").strip()
    if not re.fullmatch(r"[^\\s@]+@[^\\s@]+\\.[^\\s@]{2,}", email):
        await message.answer("Проверь адрес. Введи email в формате name@example.com или /cancel.")
        return
    await save_user_email(uid, email)
    await message.answer("Email сохранён. Сейчас подготовлю тестовый счёт.")
    await create_payment_for_user(bot, uid, message)

@router.callback_query(F.data.startswith("check:"))
async def check_payment(callback: CallbackQuery, bot: Bot) -> None:
    # Backward compatibility for old payment messages.
    uid = callback.from_user.id
    order = await get_order(callback.data.split(":", 1)[1], uid)
    if not order or not order["payment_id"]:
        await callback.answer("Счёт не найден.", show_alert=True)
        return
    try:
        status = await poll_one_order(bot, order)
    except httpx.HTTPError:
        log.exception("Ошибка проверки платежа %s", order["payment_id"])
        await callback.answer("Не удалось проверить платёж. Попробуй позже.", show_alert=True)
        return
    await callback.answer(
        "Оплата подтверждена." if status == "succeeded" else f"Статус платежа: {status}",
        show_alert=status != "succeeded",
    )

@router.callback_query(F.data == "access")
async def access_callback(callback: CallbackQuery, bot: Bot) -> None:
    if not await get_purchase(callback.from_user.id):
        await callback.answer("Сначала оплати доступ.", show_alert=True)
        return
    try:
        sent = await send_product(bot, callback.from_user.id, allow_repeat=True)
    except TelegramAPIError:
        log.exception("Не удалось повторно отправить продукт")
        await callback.answer("Не удалось отправить материал. Попробуй позже.", show_alert=True)
        return
    await callback.answer("Материал отправлен." if sent else "Предыдущая отправка ещё выполняется.", show_alert=not sent)

@router.message(Command("access"))
async def access_command(message: Message, bot: Bot) -> None:
    if not message.from_user or message.chat.type != "private":
        return
    if not await get_purchase(message.from_user.id):
        await message.answer("Доступ ещё не оплачен. Нажми /start.")
        return
    try:
        sent = await send_product(bot, message.from_user.id, allow_repeat=True)
    except TelegramAPIError:
        log.exception("Не удалось повторно отправить продукт")
        await message.answer("Не удалось отправить материал. Попробуй позже.")
        return
    if not sent:
        await message.answer("Предыдущая отправка ещё выполняется. Подожди немного.")

@router.message(Command("paysupport"))
async def support(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer(
            f"По вопросам оплаты и возврата: {html.escape(SUPPORT_CONTACT)}",
            parse_mode=ParseMode.HTML,
        )

@router.message(Command("stats"))
async def stats(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.source,COUNT(*) AS starts,COUNT(p.user_id) AS buyers
               FROM users u LEFT JOIN purchases p ON p.user_id=u.user_id
               GROUP BY u.source ORDER BY starts DESC"""
        ) as cur:
            rows = await cur.fetchall()
    result = "Источники (первое касание):\n" + "\n".join(
        f"{html.escape(r['source'])}: стартов {r['starts']}, оплат {r['buyers']}"
        for r in rows
    )
    await message.answer(result[:4000], parse_mode=ParseMode.HTML)

@router.message(Command("receipts"))
async def receipts_command(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT user_id,payment_id,created_at FROM receipts
               WHERE status='pending' ORDER BY created_at DESC LIMIT 30"""
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        await message.answer("Нет чеков, ожидающих отправки.")
        return
    lines = ["<b>Чеки, ожидающие отправки:</b>"]
    for row in rows:
        lines.append(
            f"Покупатель <code>{row['user_id']}</code> · платёж "
            f"<code>{html.escape(row['payment_id'])}</code>"
        )
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("receipt:"))
async def receipt_start(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    try:
        receipt_id = int(callback.data.split(":", 1)[1])
    except (ValueError, TypeError):
        await callback.answer("Некорректная заявка.", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id,user_id,payment_id FROM receipts WHERE id=? AND status='pending'",
            (receipt_id,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await callback.answer("Чек уже отправлен или платёж не найден.", show_alert=True)
            return
        await db.execute(
            """INSERT INTO admin_receipt_sessions(admin_id,user_id,payment_id,started_at)
               VALUES(?,?,?,?)
               ON CONFLICT(admin_id) DO UPDATE SET
                 user_id=excluded.user_id,payment_id=excluded.payment_id,
                 started_at=excluded.started_at""",
            (callback.from_user.id, row["user_id"], row["payment_id"], int(time.time())),
        )
        await db.commit()
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Отправь следующим сообщением чек для покупателя <code>{row['user_id']}</code>.\n"
            "Можно отправить ссылку, фото или документ. Для отмены — /cancelreceipt.",
            parse_mode=ParseMode.HTML,
        )

@router.message(Command("cancelreceipt"))
async def cancel_receipt(message: Message) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM admin_receipt_sessions WHERE admin_id=?",
            (message.from_user.id,),
        )
        await db.commit()
    await message.answer("Отправка чека отменена.")

@router.message(F.chat.type == "private")
async def admin_receipt_payload(message: Message, bot: Bot) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM admin_receipt_sessions WHERE admin_id=?",
            (message.from_user.id,),
        ) as cur:
            session = await cur.fetchone()
    if not session:
        # Unknown text and accidental messages are deliberately ignored.
        return

    receipt_type = None
    file_id = None
    receipt_text = None
    try:
        if message.photo:
            receipt_type = "photo"
            file_id = message.photo[-1].file_id
            await bot.send_photo(
                session["user_id"], file_id,
                caption="Официальный чек за оплату практики «Зеркало сути».",
            )
        elif message.document:
            receipt_type = "document"
            file_id = message.document.file_id
            await bot.send_document(
                session["user_id"], file_id,
                caption="Официальный чек за оплату практики «Зеркало сути».",
            )
        elif message.text and re.fullmatch(r"https?://\S+", message.text.strip()):
            receipt_type = "link"
            receipt_text = message.text.strip()
            await bot.send_message(
                session["user_id"],
                "Твой чек за оплату практики «Зеркало сути»:\n" + html.escape(receipt_text),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            await message.answer("Пришли ссылку http(s), фотографию или документ. Другие сообщения не подходят.")
            return
    except TelegramAPIError:
        log.exception("Не удалось отправить чек пользователю %s", session["user_id"])
        await message.answer("Не удалось доставить чек покупателю. Сессия сохранена — попробуй ещё раз.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE receipts SET status='sent',receipt_type=?,receipt_file_id=?,
               receipt_text=?,admin_id=?,sent_at=?
               WHERE user_id=? AND payment_id=?""",
            (
                receipt_type, file_id, receipt_text, message.from_user.id,
                int(time.time()), session["user_id"], session["payment_id"],
            ),
        )
        await db.execute(
            "DELETE FROM admin_receipt_sessions WHERE admin_id=?",
            (message.from_user.id,),
        )
        await db.commit()
    await message.answer(
        f"Чек отправлен покупателю <code>{session['user_id']}</code>. Статус сохранён.",
        parse_mode=ParseMode.HTML,
    )
    try:
        await bot.send_message(
            session["user_id"], "Чек отправлен. Благодарим за покупку!",
        )
    except TelegramAPIError:
        log.warning("Не удалось отправить подтверждение чека пользователю %s", session["user_id"])

async def payment_poll_worker(bot: Bot) -> None:
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT * FROM payment_orders
                       WHERE payment_id IS NOT NULL
                         AND status IN ('pending','waiting_for_capture','creating')
                       ORDER BY created_at ASC LIMIT 50"""
                ) as cur:
                    orders = await cur.fetchall()
            for order in orders:
                try:
                    await poll_one_order(bot, order)
                except httpx.HTTPError:
                    log.warning("Временная ошибка опроса ЮKassa: %s", order["order_id"], exc_info=True)
                except Exception:
                    log.exception("Ошибка обработки платежа %s", order["order_id"])
        except Exception:
            log.exception("Payment polling worker error")
        await asyncio.sleep(PAYMENT_POLL_SECONDS)

async def followup_worker(bot: Bot) -> None:
    while True:
        try:
            now = int(time.time())
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """SELECT user_id FROM purchases
                       WHERE delivered_at IS NOT NULL AND followup_at<=?
                         AND followup_sent_at IS NULL
                         AND (followup_claimed_at IS NULL OR followup_claimed_at<=?)
                       LIMIT 30""",
                    (now, now - 300),
                ) as cur:
                    users = await cur.fetchall()
            for row in users:
                uid = row["user_id"]
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        """UPDATE purchases SET followup_claimed_at=?
                           WHERE user_id=? AND followup_sent_at IS NULL
                           AND (followup_claimed_at IS NULL OR followup_claimed_at<=?)""",
                        (now, uid, now - 300),
                    )
                    await db.commit()
                    if cur.rowcount != 1:
                        continue
                try:
                    await bot.send_message(
                        uid, FOLLOWUP, reply_markup=channel_menu(),
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramForbiddenError:
                    log.info("Пользователь %s заблокировал бота", uid)
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE purchases SET followup_sent_at=? WHERE user_id=?",
                            (int(time.time()), uid),
                        )
                        await db.commit()
                except TelegramAPIError:
                    log.exception("Не удалось отправить follow-up пользователю %s", uid)
                else:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE purchases SET followup_sent_at=? WHERE user_id=?",
                            (int(time.time()), uid),
                        )
                        await db.commit()
        except Exception:
            log.exception("Followup worker error")
        await asyncio.sleep(5)

async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="access", description="Повторно получить промпт"),
        BotCommand(command="paysupport", description="Поддержка по оплате"),
    ])

async def main() -> None:
    await init_db()
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    payment_task = asyncio.create_task(payment_poll_worker(bot))
    followup_task = asyncio.create_task(followup_worker(bot))
    try:
        await setup_bot_commands(bot)
        await bot.delete_webhook(drop_pending_updates=False)
        log.info(
            "Бот запущен. ЮKassa: тестовый режим. Опрос платежей: %s сек. "
            "Следующее сообщение: %s сек. (%.2f ч).",
            PAYMENT_POLL_SECONDS, FOLLOWUP_SECONDS, FOLLOWUP_SECONDS / 3600,
        )
        await dp.start_polling(bot)
    finally:
        payment_task.cancel()
        followup_task.cancel()
        with suppress(asyncio.CancelledError):
            await payment_task
        with suppress(asyncio.CancelledError):
            await followup_task
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
