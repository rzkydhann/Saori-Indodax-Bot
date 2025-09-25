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

# --- DIUBAH: Menambahkan import untuk Keyboard ---
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
    logging.info("Set BOT_TOKEN di Secrets tab")
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

# Alternative API endpoints untuk fallback
INDODAX_ENDPOINTS = [
    "https://indodax.com/api/ticker",
    "https://indodax.com/tapi/ticker",
    "https://api.indodax.com/ticker"
]

# --- BARU: Fungsi untuk membuat menu tombol ---
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
    # --- DIUBAH: Menambahkan reply_markup ---
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

# --- Fungsi helper untuk API call dengan multiple endpoints ---
def get_ticker_data(pair):
    """Helper function untuk get data dari API Indodax dengan cache dan fallback endpoints"""
    if pair not in VALID_PAIRS:
        logging.warning(f"Invalid pair requested: {pair}")
        return None

    if pair in cache:
        logging.info(f"Using cached data for {pair}")
        return cache[pair]

    for endpoint_template in INDODAX_ENDPOINTS:
        try:
            # PENTING: URL yang benar adalah endpoint + "/" + pair
            url = f"{endpoint_template}/{pair}"
            logging.info(f"Trying endpoint: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, timeout=15, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            logging.debug(f"API Response for {pair}: {data}")
            
            if 'ticker' in data and data['ticker'] and 'last' in data['ticker']:
                ticker_data = data['ticker']
                cache[pair] = ticker_data
                logging.info(f"Successfully got data for {pair} from {url}")
                return ticker_data
            
            logging.warning(f"Invalid response format from {url}: {data}")
            
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            logging.error(f"Error for endpoint {url}: {e}")
            continue
    
    logging.error(f"All endpoints failed for {pair}")
    return None

# --- Fungsi test API status ---
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loading_msg = await update.message.reply_text("⏳ Checking API status...", reply_markup=get_menu_keyboard())
    
    status_msg = "🔍 *API Status Check*\n\n"
    working_endpoints = 0
    
    for i, endpoint_template in enumerate(INDODAX_ENDPOINTS, 1):
        try:
            url = f"{endpoint_template}/btcidr"
            response = requests.get(url, timeout=10)
            if response.status_code == 200 and 'ticker' in response.json():
                status_msg += f"✅ Endpoint {i}: Working\n"
                working_endpoints += 1
            else:
                status_msg += f"❌ Endpoint {i}: HTTP {response.status_code}\n"
        except Exception:
            status_msg += f"❌ Endpoint {i}: Error/Timeout\n"
    
    status_msg += f"\n📊 Working endpoints: {working_endpoints}/{len(INDODAX_ENDPOINTS)}\n"
    
    if working_endpoints > 0:
        status_msg += "✅ Bot dapat berfungsi"
    else:
        status_msg += "❌ Semua endpoint down, bot tidak dapat mengambil data"
    
    # edit_text tidak bisa menggunakan ReplyKeyboardMarkup
    await loading_msg.edit_text(status_msg, parse_mode="Markdown")

# --- Fungsi cek harga ---
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text(
            "⚠️ Gunakan format: /price <pair>\nContoh: /price btcidr",
            reply_markup=get_menu_keyboard()
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"⚠️ Pair {pair.upper()} tidak valid!", reply_markup=get_menu_keyboard())
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...", reply_markup=get_menu_keyboard())
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text("❌ Gagal ambil data. Coba lagi atau cek `/status`.")
        return

    try:
        last_price = f"{float(ticker['last']):,.0f}"
        high_price = f"{float(ticker.get('high', 0)):,.0f}"
        low_price = f"{float(ticker.get('low', 0)):,.0f}"
        
        msg = (
            f"📊 *Harga {pair.upper()}*\n\n"
            f"💰 Terakhir: Rp {last_price}\n"
            f"📈 Tertinggi 24j: Rp {high_price}\n"
            f"📉 Terendah 24j: Rp {low_price}"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown")
        
    except (KeyError, ValueError) as e:
        await loading_msg.edit_text(f"❌ Error parsing data untuk {pair.upper()}.")

# --- Fungsi Top coin ---
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs = ["btcidr", "ethidr", "dogidr", "xrpidr", "adaidr"]
    loading_msg = await update.message.reply_text("⏳ Mengambil data top coins...", reply_markup=get_menu_keyboard())
    
    msg = "🔥 *Top Coin di Indodax:*\n\n"
    success_count = 0
    
    for pair in pairs:
        ticker = get_ticker_data(pair)
        if ticker:
            price_value = f"{float(ticker.get('last', 0)):,.0f}"
            msg += f"▫️ {pair.upper()}: Rp {price_value}\n"
            success_count += 1
        else:
            msg += f"▫️ {pair.upper()}: Tidak tersedia\n"
    
    if success_count == 0:
        msg = "❌ Gagal mengambil data semua coin."
    
    await loading_msg.edit_text(msg, parse_mode="Markdown")

# --- Fungsi Market Info ---
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ Gunakan format: /market <pair>", reply_markup=get_menu_keyboard())
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"⚠️ Pair {pair.upper()} tidak valid!", reply_markup=get_menu_keyboard())
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil market data {pair.upper()}...", reply_markup=get_menu_keyboard())
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text("❌ Gagal ambil data. Coba lagi atau cek `/status`.")
        return
    
    try:
        coin_name = pair.replace("idr", "")
        vol_key = f"vol_{coin_name}"
        vol_value = float(ticker.get(vol_key, 0))
        vol_formatted = f"{vol_value:,.2f}"

        msg = (
            f"📊 *Market {pair.upper()}*\n\n"
            f"📈 High 24j: Rp {float(ticker.get('high', 0)):,.0f}\n"
            f"📉 Low 24j: Rp {float(ticker.get('low', 0)):,.0f}\n"
            f"💰 Last: Rp {float(ticker.get('last', 0)):,.0f}\n"
            f"📦 Volume: {vol_formatted} {coin_name.upper()}"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown")
        
    except (KeyError, ValueError) as e:
        await loading_msg.edit_text(f"❌ Error parsing market data untuk {pair.upper()}.")

# --- Fungsi Alert ---
async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Gunakan format: /alert <pair> <harga>\nContoh: /alert btcidr 1000000000",
            reply_markup=get_menu_keyboard()
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"⚠️ Pair {pair.upper()} tidak valid!", reply_markup=get_menu_keyboard())
        return
    
    try:
        target_price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Harga harus berupa angka.", reply_markup=get_menu_keyboard())
        return
    
    user_id = update.message.chat.id
    alerts[user_id] = (pair, target_price)
    
    await update.message.reply_text(
        f"🔔 Alert dipasang untuk {pair.upper()} pada Rp {target_price:,.0f}",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi cek alert harga ---
async def check_alerts(app: Application):
    if not alerts:
        return
    
    for user_id, (pair, target_price) in list(alerts.items()):
        try:
            ticker = get_ticker_data(pair)
            if ticker and float(ticker.get('last', 0)) >= target_price:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=f"🚨 *ALERT HARGA!* 🚨\n\n{pair.upper()} telah mencapai target Anda!",
                    parse_mode="Markdown",
                    reply_markup=get_menu_keyboard()
                )
                del alerts[user_id]
        except Exception as e:
            logging.error(f"Error processing alert for {user_id} ({pair}): {e}")

# --- Fungsi Help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *Bantuan Bot Saori Indodax*\n\n"
        "Gunakan tombol di bawah untuk memilih perintah yang tersedia."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

# --- Setup Bot ---
def main():
    logging.info("Starting Indodax Bot...")
    
    app = Application.builder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("alert", alert))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    logging.info("Command handlers added")

    # Setup scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_alerts, "interval", minutes=2, args=[app])
    scheduler.start()
    logging.info("Alert scheduler started")

    # Start keep-alive server
    try:
        keep_alive()
        logging.info("Keep-alive server started")
    except Exception as e:
        logging.error(f"Keep-alive server error: {e}")

    # Start bot
    logging.info("Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
