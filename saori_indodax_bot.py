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
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
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

# Daftar pair yang valid dengan nama yang lebih friendly
VALID_PAIRS = {
    "btcidr": "Bitcoin (BTC)",
    "ethidr": "Ethereum (ETH)",
    "ltcidr": "Litecoin (LTC)",
    "xrpidr": "Ripple (XRP)",
    "adaidr": "Cardano (ADA)",
    "dogidr": "Dogecoin (DOGE)",
    "shibidr": "Shiba Inu (SHIB)",
    "maticidr": "Polygon (MATIC)"
}

# Simpan alert harga
alerts = {}

# Alternative API endpoints untuk fallback
INDODAX_ENDPOINTS = [
    "https://indodax.com/api/ticker",
    "https://indodax.com/tapi/ticker",
    "https://api.indodax.com/ticker"
]

# --- Fungsi untuk membuat menu utama ---
def get_main_menu():
    """Buat keyboard menu utama"""
    keyboard = [
        [
            InlineKeyboardButton("💰 Cek Harga", callback_data="menu_price"),
            InlineKeyboardButton("🔥 Top Coins", callback_data="menu_top")
        ],
        [
            InlineKeyboardButton("📊 Market Info", callback_data="menu_market"),
            InlineKeyboardButton("🔔 Set Alert", callback_data="menu_alert")
        ],
        [
            InlineKeyboardButton("📡 Status API", callback_data="menu_status"),
            InlineKeyboardButton("❓ Bantuan", callback_data="menu_help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Fungsi untuk membuat menu pilihan pair ---
def get_pair_menu(action_type):
    """Buat keyboard untuk memilih pair crypto"""
    keyboard = []
    pairs = list(VALID_PAIRS.keys())
    
    # Buat 2 kolom per baris
    for i in range(0, len(pairs), 2):
        row = []
        for j in range(2):
            if i + j < len(pairs):
                pair = pairs[i + j]
                pair_name = VALID_PAIRS[pair]
                # Singkat nama untuk button
                short_name = pair_name.split('(')[1].replace(')', '') if '(' in pair_name else pair.upper()
                callback_data = f"{action_type}_{pair}"
                row.append(InlineKeyboardButton(short_name, callback_data=callback_data))
        keyboard.append(row)
    
    # Tambah tombol kembali
    keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(keyboard)

# --- Fungsi Start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 Selamat datang di *Saori Indodax Crypto Bot*!\n\n"
        "Bot ini membantu Anda memantau harga cryptocurrency di Indodax dengan mudah.\n\n"
        "Pilih menu di bawah untuk memulai:"
    )
    
    reply_markup = get_main_menu()
    
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

# --- Handler untuk callback query ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "back_to_main":
        await start(update, context)
    
    elif data == "menu_price":
        msg = "💰 *Pilih cryptocurrency untuk cek harga:*"
        reply_markup = get_pair_menu("price")
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    
    elif data == "menu_market":
        msg = "📊 *Pilih cryptocurrency untuk info market:*"
        reply_markup = get_pair_menu("market")
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    
    elif data == "menu_alert":
        msg = "🔔 *Pilih cryptocurrency untuk set alert:*"
        reply_markup = get_pair_menu("alert")
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    
    elif data == "menu_top":
        await show_top_coins(query)
    
    elif data == "menu_status":
        await show_api_status(query)
    
    elif data == "menu_help":
        await show_help(query)
    
    elif data.startswith("price_"):
        pair = data.replace("price_", "")
        await show_price(query, pair)
    
    elif data.startswith("market_"):
        pair = data.replace("market_", "")
        await show_market_info(query, pair)
    
    elif data.startswith("alert_"):
        pair = data.replace("alert_", "")
        await show_alert_setup(query, pair)

# --- Fungsi helper untuk API call dengan multiple endpoints ---
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
            url = endpoint_template.format(pair)
            logging.info(f"Trying endpoint: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'id-ID,id;q=0.9,en;q=0.8',
                'Cache-Control': 'no-cache'
            }
            
            response = requests.get(url, timeout=15, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            logging.debug(f"API Response for {pair}: {data}")
            
            # Check if response has valid ticker data
            if 'ticker' in data and data['ticker']:
                ticker_data = data['ticker']
                # Validate required fields
                if 'last' in ticker_data and ticker_data['last']:
                    cache[pair] = ticker_data
                    logging.info(f"Successfully got data for {pair} from {url}")
                    return ticker_data
            
            # If no ticker field, maybe direct response
            elif 'last' in data and data['last']:
                cache[pair] = data
                logging.info(f"Successfully got direct data for {pair} from {url}")
                return data
                
            logging.warning(f"Invalid response format from {url}: {data}")
            
        except requests.exceptions.Timeout:
            logging.error(f"Timeout for endpoint {url}")
            continue
        except requests.exceptions.ConnectionError:
            logging.error(f"Connection error for endpoint {url}")
            continue
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP Error {e.response.status_code} for {url}")
            continue
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON response from {url}: {e}")
            continue
        except Exception as e:
            logging.error(f"Unexpected error for {url}: {str(e)}")
            continue
    
    logging.error(f"All endpoints failed for {pair}")
    return None

# --- Fungsi show price melalui callback ---
async def show_price(query, pair):
    """Tampilkan harga crypto dari callback"""
    pair_name = VALID_PAIRS.get(pair, pair.upper())
    
    # Edit message untuk loading
    await query.edit_message_text(f"⏳ Mengambil data {pair_name}...")
    
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        back_button = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data="menu_price")]])
        await query.edit_message_text(
            f"❌ Gagal ambil data untuk {pair_name}\n\n"
            f"Kemungkinan penyebab:\n"
            f"• API Indodax sedang maintenance\n"
            f"• Koneksi internet bermasalah\n"
            f"• Server overload\n\n"
            f"Coba lagi dalam beberapa saat.",
            reply_markup=back_button
        )
        return

    try:
        last_price = f"{float(ticker['last']):,.0f}"
        high_price = f"{float(ticker.get('high', ticker['last'])):,.0f}"
        low_price = f"{float(ticker.get('low', ticker['last'])):,.0f}"
        volume = f"{float(ticker.get('vol_idr', 0)):,.2f}"
        
        msg = (
            f"💰 *Harga {pair_name}*\n\n"
            f"💵 Terakhir: Rp {last_price}\n"
            f"📈 Tertinggi 24h: Rp {high_price}\n"
            f"📉 Terendah 24h: Rp {low_price}\n"
            f"📦 Volume 24h: Rp {volume}\n\n"
            f"⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"price_{pair}")],
            [InlineKeyboardButton("🔙 Pilih Coin Lain", callback_data="menu_price")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing data untuk {pair}: {e}")
        back_button = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data="menu_price")]])
        await query.edit_message_text(
            f"❌ Error parsing data untuk {pair_name}\n"
            f"Data yang diterima tidak sesuai format yang diharapkan.",
            reply_markup=back_button
        )

# --- Fungsi show market info melalui callback ---
async def show_market_info(query, pair):
    """Tampilkan info market dari callback"""
    pair_name = VALID_PAIRS.get(pair, pair.upper())
    
    await query.edit_message_text(f"⏳ Mengambil market data {pair_name}...")
    
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        back_button = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data="menu_market")]])
        await query.edit_message_text(
            f"❌ Gagal ambil data untuk {pair_name}",
            reply_markup=back_button
        )
        return
    
    try:
        high = f"{float(ticker.get('high', ticker['last'])):,.0f}"
        low = f"{float(ticker.get('low', ticker['last'])):,.0f}"
        last = f"{float(ticker['last']):,.0f}"
        volume = f"{float(ticker.get('vol_idr', 0)):,.2f}"
        buy = float(ticker.get('buy', ticker.get('last', 0)))
        sell = float(ticker.get('sell', ticker.get('last', 0)))
        
        msg = (
            f"📊 *Market {pair_name}*\n\n"
            f"📈 High 24h: Rp {high}\n"
            f"📉 Low 24h: Rp {low}\n"
            f"💰 Last Price: Rp {last}\n"
            f"💵 Buy Price: Rp {buy:,.0f}\n"
            f"💴 Sell Price: Rp {sell:,.0f}\n"
            f"📦 Volume 24h: Rp {volume}\n\n"
            f"⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"market_{pair}")],
            [InlineKeyboardButton("🔙 Pilih Coin Lain", callback_data="menu_market")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing market data untuk {pair}: {e}")
        back_button = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data="menu_market")]])
        await query.edit_message_text(
            f"❌ Error parsing market data untuk {pair_name}",
            reply_markup=back_button
        )

# --- Fungsi show alert setup ---
async def show_alert_setup(query, pair):
    """Setup alert untuk pair tertentu"""
    pair_name = VALID_PAIRS.get(pair, pair.upper())
    
    msg = (
        f"🔔 *Setup Alert untuk {pair_name}*\n\n"
        f"Untuk mengatur alert harga, gunakan perintah:\n"
        f"`/alert {pair} <harga_target>`\n\n"
        f"Contoh:\n"
        f"`/alert {pair} 1000000`\n\n"
        f"Bot akan memberitahu Anda ketika harga mencapai target yang ditentukan."
    )
    
    keyboard = [
        [InlineKeyboardButton("🔙 Pilih Coin Lain", callback_data="menu_alert")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

# --- Fungsi show top coins ---
async def show_top_coins(query):
    """Tampilkan top coins"""
    pairs = ["btcidr", "ethidr", "dogidr", "xrpidr", "adaidr"]
    
    await query.edit_message_text("⏳ Mengambil data top coins...")
    
    msg = "🔥 *Top Coins di Indodax:*\n\n"
    success_count = 0
    
    for pair in pairs:
        ticker = get_ticker_data(pair)
        if ticker:
            try:
                price_value = f"{float(ticker['last']):,.0f}"
                pair_name = VALID_PAIRS.get(pair, pair.upper())
                crypto_name = pair_name.split('(')[1].replace(')', '') if '(' in pair_name else pair.upper()
                msg += f"▫️ {crypto_name}: Rp {price_value}\n"
                success_count += 1
            except (KeyError, ValueError):
                crypto_name = VALID_PAIRS.get(pair, pair.upper()).split('(')[1].replace(')', '')
                msg += f"▫️ {crypto_name}: Error parsing\n"
        else:
            crypto_name = VALID_PAIRS.get(pair, pair.upper()).split('(')[1].replace(')', '')
            msg += f"▫️ {crypto_name}: Tidak tersedia\n"
    
    if success_count > 0:
        msg += f"\n⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}"
        msg += f"\n📊 Berhasil: {success_count}/{len(pairs)} coin"
    else:
        msg = (
            "❌ Gagal mengambil data semua coin.\n\n"
            f"Kemungkinan API Indodax sedang bermasalah."
        )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu_top")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

# --- Fungsi show API status ---
async def show_api_status(query):
    """Check API status untuk semua endpoints"""
    await query.edit_message_text("⏳ Checking API status...")
    
    status_msg = "📡 *API Status Check*\n\n"
    working_endpoints = 0
    
    for i, endpoint_template in enumerate(INDODAX_ENDPOINTS, 1):
        try:
            url = endpoint_template.format('btcidr')
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, timeout=10, headers=headers)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if ('ticker' in data and data['ticker']) or 'last' in data:
                        status_msg += f"✅ Endpoint {i}: Working\n"
                        working_endpoints += 1
                    else:
                        status_msg += f"⚠️ Endpoint {i}: Invalid response\n"
                except:
                    status_msg += f"⚠️ Endpoint {i}: Invalid JSON\n"
            else:
                status_msg += f"❌ Endpoint {i}: HTTP {response.status_code}\n"
        except requests.exceptions.Timeout:
            status_msg += f"⏰ Endpoint {i}: Timeout\n"
        except Exception as e:
            status_msg += f"❌ Endpoint {i}: Error\n"
    
    status_msg += f"\n📊 Working endpoints: {working_endpoints}/{len(INDODAX_ENDPOINTS)}\n"
    
    if working_endpoints > 0:
        status_msg += "✅ Bot dapat berfungsi"
    else:
        status_msg += "❌ Semua endpoint down, bot tidak dapat mengambil data"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu_status")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(status_msg, parse_mode="Markdown", reply_markup=reply_markup)

# --- Fungsi show help ---
async def show_help(query):
    """Tampilkan bantuan"""
    pairs_list = ", ".join([f"{k.upper()}" for k in VALID_PAIRS.keys()])
    msg = (
        "🤖 *Bantuan Bot Saori Indodax*\n\n"
        "📋 *Cara menggunakan:*\n"
        "• Gunakan menu interaktif untuk navigasi mudah\n"
        "• Atau gunakan perintah manual:\n\n"
        "🔸 `/start` - Tampilkan menu utama\n"
        "🔸 `/price <pair>` - Cek harga crypto\n"
        "🔸 `/top` - Top 5 crypto populer\n"
        "🔸 `/market <pair>` - Info market detail\n"
        "🔸 `/alert <pair> <harga>` - Pasang alert harga\n"
        "🔸 `/status` - Cek status API\n"
        "🔸 `/help` - Tampilkan bantuan\n\n"
        "💡 *Contoh perintah manual:*\n"
        "• `/price btcidr` - Harga Bitcoin\n"
        "• `/market ethidr` - Market Ethereum\n"
        "• `/alert btcidr 1000000000` - Alert BTC 1M\n\n"
        f"📈 *Crypto yang tersedia:*\n{pairs_list}\n\n"
        "⚠️ *Catatan:* Bot bergantung pada API Indodax."
    )
    
    keyboard = [
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

# --- Fungsi command handler lama (untuk backward compatibility) ---
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS.keys()])
        await update.message.reply_text(
            f"⚠️ Gunakan format: /price <pair>\n"
            f"Contoh: /price btcidr\n\n"
            f"Atau gunakan /start untuk menu interaktif\n\n"
            f"Pair yang tersedia:\n{pairs_list}"
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS.keys()])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}\n\n"
            f"Atau gunakan /start untuk menu interaktif"
        )
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...")
    
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text(
            f"❌ Gagal ambil data untuk {pair.upper()}\n\n"
            f"Gunakan /start untuk menu interaktif atau /status untuk cek kondisi API"
        )
        return

    try:
        last_price = f"{float(ticker['last']):,.0f}"
        high_price = f"{float(ticker.get('high', ticker['last'])):,.0f}"
        low_price = f"{float(ticker.get('low', ticker['last'])):,.0f}"
        volume = f"{float(ticker.get('vol_idr', 0)):,.2f}"
        
        msg = (
            f"📊 *Harga {pair.upper()}*\n\n"
            f"💰 Terakhir: Rp {last_price}\n"
            f"📈 Tertinggi 24h: Rp {high_price}\n"
            f"📉 Terendah 24h: Rp {low_price}\n"
            f"📦 Volume 24h: Rp {volume}\n\n"
            f"⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}\n\n"
            f"💡 Gunakan /start untuk menu interaktif"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown")
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing data untuk {pair}: {e}")
        await loading_msg.edit_text(
            f"❌ Error parsing data untuk {pair.upper()}\n"
            f"Gunakan /start untuk menu interaktif"
        )

# Fungsi command handler lainnya tetap sama seperti sebelumnya...
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs = ["btcidr", "ethidr", "dogidr", "xrpidr", "adaidr"]
    
    loading_msg = await update.message.reply_text("⏳ Mengambil data top coins...")
    
    msg = "🔥 *Top Coin di Indodax:*\n\n"
    success_count = 0
    
    for pair in pairs:
        ticker = get_ticker_data(pair)
        if ticker:
            try:
                price_value = f"{float(ticker['last']):,.0f}"
                msg += f"▫️ {pair.upper()}: Rp {price_value}\n"
                success_count += 1
            except (KeyError, ValueError):
                msg += f"▫️ {pair.upper()}: Error parsing\n"
        else:
            msg += f"▫️ {pair.upper()}: Tidak tersedia\n"
    
    if success_count > 0:
        msg += f"\n⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}"
        msg += f"\n📊 Berhasil: {success_count}/{len(pairs)} coin"
        msg += f"\n\n💡 Gunakan /start untuk menu interaktif"
    else:
        msg = (
            "❌ Gagal mengambil data semua coin.\n\n"
            f"Gunakan /start untuk menu interaktif atau /status untuk cek kondisi API"
        )
    
    await loading_msg.edit_text(msg, parse_mode="Markdown")

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ Gunakan format: /market <pair>\nContoh: /market btcidr\n\nAtau gunakan /start untuk menu interaktif")
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS.keys()])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}\n\n"
            f"Atau gunakan /start untuk menu interaktif"
        )
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil market data {pair.upper()}...")
    
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text(
            f"❌ Gagal ambil data untuk {pair.upper()}\n"
            f"Gunakan /start untuk menu interaktif"
        )
        return
    
    try:
        high = f"{float(ticker.get('high', ticker['last'])):,.0f}"
        low = f"{float(ticker.get('low', ticker['last'])):,.0f}"
        last = f"{float(ticker['last']):,.0f}"
        volume = f"{float(ticker.get('vol_idr', 0)):,.2f}"
        buy = float(ticker.get('buy', ticker.get('last', 0)))
        sell = float(ticker.get('sell', ticker.get('last', 0)))
        
        msg = (
            f"📊 *Market {pair.upper()}*\n\n"
            f"📈 High 24h: Rp {high}\n"
            f"📉 Low 24h: Rp {low}\n"
            f"💰 Last Price: Rp {last}\n"
            f"💵 Buy Price: Rp {buy:,.0f}\n"
            f"💴 Sell Price: Rp {sell:,.0f}\n"
            f"📦 Volume 24h: Rp {volume}\n\n"
            f"⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}\n\n"
            f"💡 Gunakan /start untuk menu interaktif"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown")
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing market data untuk {pair}: {e}")
        await loading_msg.edit_text(f"❌ Error parsing market data untuk {pair.upper()}")

async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Gunakan format: /alert <pair> <harga>\n"
            "Contoh: /alert btcidr 1000000000\n"
            "(Alert ketika BTC mencapai 1 miliar)\n\n"
            "Atau gunakan /start untuk menu interaktif"
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS.keys()])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}\n\n"
            f"Atau gunakan /start untuk menu interaktif"
        )
        return
    
    try:
        target_price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Harga harus berupa angka")
        return
    
    user_id = update.message.chat.id
    alerts[user_id] = (pair, target_price)
    
    formatted_price = f"{target_price:,.0f}"
    pair_name = VALID_PAIRS.get(pair, pair.upper())
    await update.message.reply_text(
        f"🔔 Alert dipasang!\n\n"
        f"Coin: {pair_name}\n"
        f"Target: Rp {formatted_price}\n\n"
        f"Anda akan diberitahu jika harga mencapai target.\n"
        f"⚠️ Alert tergantung pada ketersediaan API Indodax\n\n"
        f"💡 Gunakan /start untuk menu interaktif"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check API status for all endpoints"""
    loading_msg = await update.message.reply_text("⏳ Checking API status...")
    
    status_msg = "📡 *API Status Check*\n\n"
    working_endpoints = 0
    
    for i, endpoint_template in enumerate(INDODAX_ENDPOINTS, 1):
        try:
            url = endpoint_template.format('btcidr')
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, timeout=10, headers=headers)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if ('ticker' in data and data['ticker']) or 'last' in data:
                        status_msg += f"✅ Endpoint {i}: Working\n"
                        working_endpoints += 1
                    else:
                        status_msg += f"⚠️ Endpoint {i}: Invalid response\n"
                except:
                    status_msg += f"⚠️ Endpoint {i}: Invalid JSON\n"
            else:
                status_msg += f"❌ Endpoint {i}: HTTP {response.status_code}\n"
        except requests.exceptions.Timeout:
            status_msg += f"⏰ Endpoint {i}: Timeout\n"
        except Exception as e:
            status_msg += f"❌ Endpoint {i}: Error\n"
    
    status_msg += f"\n📊 Working endpoints: {working_endpoints}/{len(INDODAX_ENDPOINTS)}\n"
    
    if working_endpoints > 0:
        status_msg += "✅ Bot dapat berfungsi"
    else:
        status_msg += "❌ Semua endpoint down, bot tidak dapat mengambil data"
    
    status_msg += "\n\n💡 Gunakan /start untuk menu interaktif"
    
    await loading_msg.edit_text(status_msg, parse_mode="Markdown")

# --- Fungsi cek alert harga ---
async def check_alerts(app: Application):
    """Check alerts setiap interval"""
    if not alerts:
        return
    
    logging.info(f"Checking {len(alerts)} alerts...")
    
    for user_id, (pair, target_price) in list(alerts.items()):
        try:
            ticker = get_ticker_data(pair)
            if ticker:
                current_price = float(ticker['last'])
                if current_price >= target_price:
                    formatted_current = f"{current_price:,.0f}"
                    formatted_target = f"{target_price:,.0f}"
                    pair_name = VALID_PAIRS.get(pair, pair.upper())
                    
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"🚨 *ALERT HARGA!* 🚨\n\n"
                            f"💰 {pair_name} mencapai Rp {formatted_current}\n"
                            f"🎯 Target Anda: Rp {formatted_target}\n\n"
                            f"⏰ {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
                            f"💡 Gunakan /start untuk menu interaktif"
                        ),
                        parse_mode="Markdown"
                    )
                    del alerts[user_id]
                    logging.info(f"Alert triggered untuk user {user_id}: {pair} @ {current_price}")
            else:
                logging.warning(f"Tidak bisa ambil data untuk {pair}")
        except Exception as e:
            logging.error(f"Error processing alert for {user_id} ({pair}): {e}")

# --- Fungsi Help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs_list = ", ".join(VALID_PAIRS.keys())
    msg = (
        "🤖 *Bantuan Bot Saori Indodax*\n\n"
        "📋 *Cara menggunakan:*\n"
        "• Gunakan /start untuk menu interaktif (RECOMMENDED)\n"
        "• Atau gunakan perintah manual:\n\n"
        "🔸 `/start` - Menu interaktif\n"
        "🔸 `/price <pair>` - Cek harga crypto\n"
        "🔸 `/top` - Top 5 crypto populer\n"
        "🔸 `/market <pair>` - Info market detail\n"
        "🔸 `/alert <pair> <harga>` - Pasang alert harga\n"
        "🔸 `/status` - Cek status API\n"
        "🔸 `/help` - Tampilkan bantuan ini\n\n"
        "💡 *Contoh perintah manual:*\n"
        "• `/price btcidr` - Harga Bitcoin\n"
        "• `/market ethidr` - Market Ethereum\n"
        "• `/alert btcidr 1000000000` - Alert BTC 1M\n\n"
        f"📈 *Pair yang tersedia:*\n{pairs_list}\n\n"
        "⚠️ *Catatan:* Bot bergantung pada API Indodax.\n\n"
        "🎯 *Gunakan /start untuk pengalaman yang lebih baik!*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- Setup Bot ---
def main():
    logging.info("Starting Indodax Bot with Interactive Menu...")
    logging.info(f"Token: {'Found' if TOKEN else 'Missing'}")
    
    try:
        # Create application
        app = (
            Application.builder()
            .token(TOKEN)
            .build()
        )
        logging.info("Bot application created successfully")

        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("price", price))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("market", market))
        app.add_handler(CommandHandler("alert", alert))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(CommandHandler("help", help_command))
        
        # Add callback query handler untuk menu interaktif
        app.add_handler(CallbackQueryHandler(button_handler))
        
        logging.info("Command handlers and callback handlers added")

        # Setup scheduler untuk check alerts
        try:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(check_alerts, "interval", minutes=2, args=[app])
            scheduler.start()
            logging.info("Alert scheduler started (check every 2 minutes)")
        except Exception as e:
            logging.error(f"Scheduler error: {e}")

        # Start keep-alive server
        try:
            keep_alive()
            logging.info("Keep-alive server started")
        except Exception as e:
            logging.error(f"Keep-alive server error: {e}")

        # Start bot
        logging.info("Bot is starting...")
        logging.info("Bot siap digunakan di Telegram dengan menu interaktif!")
        logging.info("Pengguna bisa menggunakan /start untuk menu atau perintah manual")
        
        app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logging.error(f"Bot startup error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
