import os
import requests
import datetime
import asyncio
import json
import logging
from cachetools import TTLCache

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Import telegram dengan error handling
try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, ContextTypes
    logging.info("Telegram imports successful")
except ImportError as e:
    logging.error(f"Telegram import error: {e}")
    exit(1)

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Import keep_alive dengan error handling
try:
    from keep_alive import keep_alive
    logging.info("Keep-alive import successful")
except ImportError:
    logging.warning("Keep-alive not found, creating placeholder...")
    def keep_alive():
        logging.info("Keep-alive placeholder active")

# Token dari environment variable
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    logging.error("BOT_TOKEN tidak ditemukan di environment variables!")
    exit(1)

# Cache untuk API data (1 menit TTL)
cache = TTLCache(maxsize=100, ttl=60)

# Daftar pair yang valid
VALID_PAIRS = [
    "btcidr", "ethidr", "ltcidr", "xrpidr", "adaidr",
    "dogidr", "shibidr", "maticidr"
]

# Simpan alert harga
alerts = {}

# API endpoints
INDODAX_ENDPOINTS = [
    "https://indodax.com/api/ticker"
]

# --- Fungsi untuk membuat menu tombol ---
def get_menu_keyboard():
    """Membuat keyboard markup untuk menu perintah"""
    keyboard = [
        [KeyboardButton("/price"), KeyboardButton("/top")],
        [KeyboardButton("/market"), KeyboardButton("/alert")],
        [KeyboardButton("/status"), KeyboardButton("/help")]
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Pilih perintah..."
    )

# --- Fungsi Start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Selamat datang di *Saori Indodax Crypto Bot*!\n\n"
        "Gunakan menu tombol di bawah untuk berinteraksi dengan bot."
    )
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi helper API Call (Non-Blocking) ---
async def get_ticker_data(pair: str):
    if pair not in VALID_PAIRS:
        return None
    if pair in cache:
        return cache[pair]

    url = f"{INDODAX_ENDPOINTS[0]}/{pair}"
    
    def sync_request():
        try:
            response = requests.get(url, timeout=8)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            logging.error(f"Error fetching {url}: {e}")
            return None

    data = await asyncio.to_thread(sync_request)
    
    if data and 'ticker' in data and 'last' in data['ticker']:
        cache[pair] = data['ticker']
        return data['ticker']
    return None

# --- Fungsi cek harga ---
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Gunakan format: `/price <pair>`\nContoh: `/price btcidr`",
            parse_mode="Markdown",
            reply_markup=get_menu_keyboard()
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"Pair {pair.upper()} tidak valid.", reply_markup=get_menu_keyboard())
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...")
    ticker = await get_ticker_data(pair)
    
    if ticker:
        last_price = f"{float(ticker['last']):,.0f}"
        msg = f"📊 *Harga {pair.upper()}*\n💰 Terakhir: Rp {last_price}"
        await loading_msg.edit_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())
    else:
        await loading_msg.edit_text(f"❌ Gagal mengambil data untuk {pair.upper()}.", reply_markup=get_menu_keyboard())

# --- Fungsi Top coin ---
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs = ["btcidr", "ethidr", "dogidr", "shibidr", "maticidr"]
    loading_msg = await update.message.reply_text("⏳ Mengambil data top coins...")
    
    tasks = [get_ticker_data(pair) for pair in pairs]
    results = await asyncio.gather(*tasks)
    
    msg = "🔥 *Top Coin di Indodax:*\n\n"
    success_count = 0
    for pair, ticker in zip(pairs, results):
        if ticker:
            price_val = f"{float(ticker['last']):,.0f}"
            msg += f"▪️ {pair.upper()}: Rp {price_val}\n"
            success_count += 1
        else:
            msg += f"▪️ {pair.upper()}: Gagal dimuat\n"
    
    if success_count == 0:
        msg = "❌ Gagal mengambil semua data top coin."

    await loading_msg.edit_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

# --- Fungsi Market Info ---
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Gunakan format: `/market <pair>`\nContoh: `/market btcidr`",
            parse_mode="Markdown",
            reply_markup=get_menu_keyboard()
        )
        return

    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"Pair {pair.upper()} tidak valid.", reply_markup=get_menu_keyboard())
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil market data {pair.upper()}...")
    ticker = await get_ticker_data(pair)

    if ticker:
        high = f"{float(ticker.get('high', 0)):,.0f}"
        low = f"{float(ticker.get('low', 0)):,.0f}"
        vol = f"{float(ticker.get(f'vol_{pair.replace("idr", "")}', 0)):,.2f}"
        msg = (
            f"📊 *Market {pair.upper()}*\n\n"
            f"📈 Tertinggi 24j: Rp {high}\n"
            f"📉 Terendah 24j: Rp {low}\n"
            f"📦 Volume: {vol} {pair.replace('idr','').upper()}"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())
    else:
        await loading_msg.edit_text(f"❌ Gagal mengambil market data untuk {pair.upper()}.", reply_markup=get_menu_keyboard())
        
# --- Fungsi Alert ---
async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Gunakan format: `/alert <pair> <harga>`\nContoh: `/alert btcidr 1000000000`",
            parse_mode="Markdown", reply_markup=get_menu_keyboard()
        )
        return
    
    pair = context.args[0].lower()
    try:
        target_price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Harga harus berupa angka.", reply_markup=get_menu_keyboard())
        return
    
    user_id = update.message.chat_id
    alerts[user_id] = {'pair': pair, 'price': target_price}
    
    await update.message.reply_text(
        f"🔔 Alert terpasang untuk {pair.upper()} pada harga Rp {target_price:,.0f}",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi cek alert harga ---
async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    if not alerts:
        return
    
    unique_pairs = {a['pair'] for a in alerts.values()}
    price_tasks = {pair: get_ticker_data(pair) for pair in unique_pairs}
    
    current_prices = {}
    for pair, task in price_tasks.items():
        current_prices[pair] = await task

    for user_id, alert_info in list(alerts.items()):
        pair = alert_info['pair']
        ticker = current_prices.get(pair)
        if ticker and float(ticker['last']) >= alert_info['price']:
            await context.bot.send_message(
                user_id,
                f"🚨 *ALERT HARGA* 🚨\n\n{pair.upper()} telah mencapai target harga Anda!",
                parse_mode="Markdown", reply_markup=get_menu_keyboard()
            )
            del alerts[user_id]

# --- Fungsi API Status ---
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"{INDODAX_ENDPOINTS[0]}/btcidr"
    loading_msg = await update.message.reply_text("⏳ Cek status API Indodax...")
    
    def sync_request():
        try:
            r = requests.get(url, timeout=8)
            return r.status_code == 200 and 'ticker' in r.json()
        except:
            return False

    is_ok = await asyncio.to_thread(sync_request)
    
    if is_ok:
        await loading_msg.edit_text("✅ API Indodax beroperasi normal.", reply_markup=get_menu_keyboard())
    else:
        await loading_msg.edit_text("❌ API Indodax sepertinya sedang bermasalah.", reply_markup=get_menu_keyboard())

# --- Fungsi Help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *Bantuan Bot*\n\n"
        "Gunakan tombol di bawah untuk navigasi. Setiap perintah akan memberikan instruksi lebih lanjut jika dibutuhkan."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

# --- Setup Bot ---
def main():
    logging.info("Starting bot...")
    app = Application.builder().token(TOKEN).build()

    # Daftarkan semua command handler
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("alert", alert))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    
    # Jadwalkan pengecekan alert
    app.job_queue.run_repeating(check_alerts, interval=60, first=10)
    
    logging.info("All handlers and jobs are set up.")
    
    # Jalankan keep-alive jika ada
    try:
        keep_alive()
        logging.info("Keep-alive server started.")
    except NameError:
        pass # keep_alive tidak terdefinisi, abaikan

    logging.info("Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
