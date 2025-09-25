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
        one_time_keyboard=False, # Keyboard tidak akan hilang setelah ditekan
        input_field_placeholder="Pilih perintah..."
    )

# --- Fungsi Start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Selamat datang di *Saori Indodax Crypto Bot*!\n\n"
        "Gunakan menu di bawah untuk memilih perintah atau ketik /help untuk bantuan."
    )
    # --- DIUBAH: Menambahkan reply_markup ---
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi helper untuk API call ---
# (Fungsi get_ticker_data tetap sama, tidak perlu diubah)
def get_ticker_data(pair):
    """Helper function untuk get data dari API Indodax dengan cache dan fallback endpoints"""
    if pair not in VALID_PAIRS:
        logging.warning(f"Invalid pair requested: {pair}")
        return None

    if pair in cache:
        logging.info(f"Using cached data for {pair}")
        return cache[pair]

    # Try multiple endpoints
    for endpoint_template in INDODAX_ENDPOINTS:
        try:
            # PERBAIKAN PENTING: URL harus digabung dengan pair
            url = f"{endpoint_template}/{pair}"
            logging.info(f"Trying endpoint: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, timeout=15, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            
            if 'ticker' in data and data['ticker'] and 'last' in data['ticker']:
                ticker_data = data['ticker']
                cache[pair] = ticker_data
                logging.info(f"Successfully got data for {pair} from {url}")
                return ticker_data
            
            logging.warning(f"Invalid response format from {url}: {data}")
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error for {url}: {e}")
            continue
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON response from {url}: {e}")
            continue
    
    logging.error(f"All endpoints failed for {pair}")
    return None

# --- Fungsi test API status ---
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loading_msg = await update.message.reply_text("⏳ Checking API status...")
    
    status_msg = "🔍 *API Status Check*\n\n"
    working_endpoints = 0
    
    for i, endpoint_template in enumerate(INDODAX_ENDPOINTS, 1):
        try:
            url = f"{endpoint_template}/btcidr" # Test dengan BTCIDR
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
    
    # --- DIUBAH: Menambahkan reply_markup ---
    await loading_msg.edit_text(
        status_msg,
        parse_mode="Markdown",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi cek harga ---
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text(
            "⚠️ Gunakan format: /price <pair>\nContoh: /price btcidr",
            reply_markup=get_menu_keyboard() # --- DIUBAH ---
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!",
            reply_markup=get_menu_keyboard() # --- DIUBAH ---
        )
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...")
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text(
            f"❌ Gagal ambil data untuk {pair.upper()}.\nCoba lagi atau cek /status.",
            reply_markup=get_menu_keyboard() # --- DIUBAH ---
        )
        return

    try:
        last_price = f"{float(ticker['last']):,.0f}"
        high_price = f"{float(ticker.get('high', 0)):,.0f}"
        low_price = f"{float(ticker.get('low', 0)):,.0f}"
        
        msg = (
            f"📊 *Harga {pair.upper()}*\n\n"
            f"💰 Terakhir: Rp {last_price}\n"
            f"📈 Tertinggi 24j: Rp {high_price}\n"
            f"📉 Terendah 24j: Rp {low_price}\n\n"
            f"⏰ {datetime.datetime.now().strftime('%H:%M:%S')}"
        )
        await loading_msg.edit_text(
            msg,
            parse_mode="Markdown",
            reply_markup=get_menu_keyboard() # --- DIUBAH ---
        )
        
    except (KeyError, ValueError) as e:
        await loading_msg.edit_text(
            f"❌ Error parsing data untuk {pair.upper()}.",
            reply_markup=get_menu_keyboard() # --- DIUBAH ---
        )

# --- (Sisa fungsi lainnya seperti top, market, alert, help juga perlu ditambahkan `reply_markup`) ---
# ... (Untuk keringkasan, saya akan tunjukkan contoh pada fungsi help)

# --- Fungsi Help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs_list = ", ".join(VALID_PAIRS)
    msg = (
        "🤖 *Bantuan Bot Saori Indodax*\n\n"
        "📋 *Perintah yang tersedia:*\n"
        "• /price <pair> - Cek harga crypto\n"
        "• /top - Top 5 crypto populer\n"
        "• /market <pair> - Info market detail\n"
        "• /alert <pair> <harga> - Pasang alert harga\n"
        "• /status - Cek status API\n"
        "• /help - Tampilkan bantuan ini\n\n"
        f"🔗 *Pair yang tersedia:*\n{pairs_list}"
    )
    # --- DIUBAH: Menambahkan reply_markup ---
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_menu_keyboard()
    )

# --- (Fungsi top, market, alert, check_alerts, dan main tetap sama strukturnya) ---
# --- Pastikan Anda menambahkan `reply_markup=get_menu_keyboard()` pada setiap `reply_text` atau `edit_text` ---
# --- yang mengirim pesan akhir ke pengguna di fungsi-fungsi tersebut agar menunya konsisten. ---

# --- Setup Bot (Contoh lengkap dari `main` tidak diubah) ---
def main():
    logging.info("Starting Indodax Bot...")
    app = Application.builder().token(TOKEN).build()
    logging.info("Bot application created successfully")

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    # app.add_handler(CommandHandler("top", top)) # Anda perlu update fungsi ini
    # app.add_handler(CommandHandler("market", market)) # Anda perlu update fungsi ini
    # app.add_handler(CommandHandler("alert", alert)) # Anda perlu update fungsi ini
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    logging.info("Command handlers added")

    # (Scheduler dan keep_alive tetap sama)

    logging.info("Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
