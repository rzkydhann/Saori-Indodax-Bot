import os
import requests
import datetime
import asyncio
import json
import logging
from cachetools import TTLCache
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Token dari environment variable
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    logging.error("BOT_TOKEN tidak ditemukan di environment variables!")
    logging.info("Set BOT_TOKEN di Secrets tab")
    exit(1)

# Cache untuk API data (diperpanjang ke 2 menit TTL untuk kurangi call)
cache = TTLCache(maxsize=100, ttl=120)

# Daftar pair yang valid
VALID_PAIRS = [
    "btcidr", "ethidr", "ltcidr", "xrpidr", "adaidr",
    "dogidr", "shibidr", "maticidr"
]

# Simpan alert harga
alerts = {}

# Alternative API endpoints untuk fallback (prioritas endpoint stabil)
INDODAX_ENDPOINTS = [
    "https://indodax.com/api/{}/ticker",  # Ubah format agar sesuai
    "https://indodax.com/tapi/ticker",
    "https://api.indodax.com/ticker"
]

# --- Fungsi untuk membuat menu ---
def get_menu_keyboard():
    """Membuat keyboard markup untuk menu perintah"""
    keyboard = [
        [KeyboardButton("/start"), KeyboardButton("/help")],
        [KeyboardButton("/price"), KeyboardButton("/top")],
        [KeyboardButton("/market"), KeyboardButton("/alert")],
        [KeyboardButton("/status")]
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Pilih perintah..."
    )

# --- Fungsi helper untuk API call dengan multiple endpoints (dengan waktu logging) ---
async def get_ticker_data(pair):
    """Async helper untuk get data dari API Indodax dengan cache dan fallback endpoints"""
    if pair not in VALID_PAIRS:
        logging.warning(f"Invalid pair requested: {pair}")
        return None

    if pair in cache:
        logging.info(f"Using cached data for {pair} (saved time)")
        return cache[pair]

    start_time = datetime.datetime.now()
    
    # Try multiple endpoints secara sequential tapi dengan timeout lebih pendek
    for i, endpoint_template in enumerate(INDODAX_ENDPOINTS, 1):
        try:
            # Format URL dengan pair (sesuaikan jika endpoint butuh /pair)
            if '{}' in endpoint_template:
                url = endpoint_template.format(pair)
            else:
                url = endpoint_template  # Jika endpoint global, tapi adjust jika perlu
            
            logging.info(f"Trying endpoint {i}: {url} for {pair}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'id-ID,id;q=0.9,en;q=0.8',
                'Cache-Control': 'no-cache'
            }
            
            # Gunakan session untuk reuse connection
            session = requests.Session()
            response = session.get(url, timeout=8, headers=headers)  # Timeout dikurangi ke 8 detik
            response.raise_for_status()
            
            data = response.json()
            logging.debug(f"API Response for {pair}: {data}")
            
            # Check if response has valid ticker data
            if 'ticker' in data and isinstance(data['ticker'], dict) and 'last' in data['ticker']:
                ticker_data = data['ticker']
                if ticker_data['last']:
                    cache[pair] = ticker_data
                    end_time = datetime.datetime.now()
                    duration = (end_time - start_time).total_seconds()
                    logging.info(f"Success for {pair} from endpoint {i} in {duration:.2f}s")
                    return ticker_data
            
            # Fallback jika direct data
            elif 'last' in data and data['last']:
                cache[pair] = data
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                logging.info(f"Direct success for {pair} from endpoint {i} in {duration:.2f}s")
                return data
                
            logging.warning(f"Invalid response format from {url}: {data}")
            
        except requests.exceptions.Timeout:
            logging.error(f"Timeout ({8}s) for endpoint {i} - {url}")
            continue
        except requests.exceptions.ConnectionError:
            logging.error(f"Connection error for endpoint {i} - {url}")
            continue
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP Error {e.response.status_code} for endpoint {i} - {url}")
            continue
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON from endpoint {i} - {url}: {e}")
            continue
        except Exception as e:
            logging.error(f"Unexpected error for endpoint {i} - {url}: {str(e)}")
            continue
    
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    logging.error(f"All endpoints failed for {pair} after {duration:.2f}s")
    return None

# --- Fungsi Start (sama seperti sebelumnya) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Selamat datang di *Saori Indodax Crypto Bot*!\n\n"
        "Perintah yang tersedia:\n"
        "🔹 /price <pair> → Cek harga (contoh: /price btcidr)\n"
        "🔹 /top → Lihat koin populer\n"
        "🔹 /market <pair> → Info market\n"
        "🔹 /alert <pair> <harga> → Pasang alarm harga\n"
        "🔹 /help → Bantuan\n\n"
        "🔹 /status → Cek status API\n\n"
        "Gunakan menu di bawah untuk memilih perintah!"
    )
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi cek harga (buat async) ---
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        pairs_list = "\n".join([f"• {p.upper()}" for p in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Gunakan format: /price <pair>\n"
            f"Contoh: /price btcidr\n\n"
            f"Pair yang tersedia:\n{pairs_list}",
            reply_markup=get_menu_keyboard()
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {p.upper()}" for p in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}",
            reply_markup=get_menu_keyboard()
        )
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...")
    
    ticker = await get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text(
            f"❌ Gagal ambil data untuk {pair.upper()}\n\n"
            f"Kemungkinan penyebab:\n"
            f"• API Indodax sedang maintenance\n"
            f"• Koneksi internet bermasalah\n"
            f"• Server overload\n\n"
            f"Gunakan /status untuk cek kondisi API",
            reply_markup=get_menu_keyboard()
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
            f"⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing data untuk {pair}: {e}")
        await loading_msg.edit_text(
            f"❌ Error parsing data untuk {pair.upper()}\n"
            f"Gunakan /status untuk cek kondisi API",
            reply_markup=get_menu_keyboard()
        )

# --- Fungsi Top coin (parallel fetch untuk kecepatan) ---
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs = ["btcidr", "ethidr", "dogidr", "xrpidr", "adaidr"]
    
    loading_msg = await update.message.reply_text("⏳ Mengambil data top coins...")
    
    # Fetch parallel untuk semua pair
    tasks = [get_ticker_data(pair) for pair in pairs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    msg = "🔥 *Top Coin di Indodax:*\n\n"
    success_count = 0
    
    for i, (pair, result) in enumerate(zip(pairs, results)):
        if isinstance(result, Exception):
            msg += f"▫️ {pair.upper()}: Error ({str(result)[:50]}...)\n"
        elif result:
            try:
                price_value = f"{float(result['last']):,.0f}"
                msg += f"▫️ {pair.upper()}: Rp {price_value}\n"
                success_count += 1
            except (KeyError, ValueError):
                msg += f"▫️ {pair.upper()}: Error parsing\n"
        else:
            msg += f"▫️ {pair.upper()}: Tidak tersedia\n"
    
    if success_count > 0:
        msg += f"\n⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}"
        msg += f"\n📊 Berhasil: {success_count}/{len(pairs)} coin"
    else:
        msg = (
            "❌ Gagal mengambil data semua coin.\n\n"
            f"Kemungkinan API Indodax sedang bermasalah.\n"
            f"Gunakan /status untuk cek kondisi API"
        )
    
    await loading_msg.edit_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

# --- Fungsi Market Info (sama, async) ---
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text(
            "⚠️ Gunakan format: /market <pair>\nContoh: /market btcidr",
            reply_markup=get_menu_keyboard()
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {p.upper()}" for p in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}",
            reply_markup=get_menu_keyboard()
        )
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil market data {pair.upper()}...")
    
    ticker = await get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text(
            f"❌ Gagal ambil data untuk {pair.upper()}\n"
            f"Gunakan /status untuk cek kondisi API",
            reply_markup=get_menu_keyboard()
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
            f"⏰ Diperbarui: {datetime.datetime.now().strftime('%H:%M:%S')}"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing market data untuk {pair}: {e}")
        await loading_msg.edit_text(
            f"❌ Error parsing market data untuk {pair.upper()}",
            reply_markup=get_menu_keyboard()
        )

# --- Fungsi Alert (tidak berubah banyak) ---
async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Gunakan format: /alert <pair> <harga>\n"
            "Contoh: /alert btcidr 1000000000\n"
            "(Alert ketika BTC mencapai 1 miliar)",
            reply_markup=get_menu_keyboard()
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {p.upper()}" for p in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}",
            reply_markup=get_menu_keyboard()
        )
        return
    
    try:
        target_price = float(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "❌ Harga harus berupa angka",
            reply_markup=get_menu_keyboard()
        )
        return
    
    user_id = update.message.chat.id
    alerts[user_id] = (pair, target_price)
    
    formatted_price = f"{target_price:,.0f}"
    await update.message.reply_text(
        f"🔔 Alert dipasang!\n\n"
        f"Coin: {pair.upper()}\n"
        f"Target: Rp {formatted_price}\n\n"
        f"Anda akan diberitahu jika harga mencapai target.\n"
        f"⚠️ Alert tergantung pada ketersediaan API Indodax",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi cek alert harga (async) ---
async def check_alerts(app: Application):
    """Check alerts setiap interval"""
    if not alerts:
        return
    
    logging.info(f"Checking {len(alerts)} alerts...")
    
    for user_id, (pair, target_price) in list(alerts.items()):
        try:
            ticker = await get_ticker_data(pair)
            if ticker:
                current_price = float(ticker['last'])
                if current_price >= target_price:
                    formatted_current = f"{current_price:,.0f}"
                    formatted_target = f"{target_price:,.0f}"
                    
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"🚨 *ALERT HARGA!* 🚨\n\n"
                            f"💰 {pair.upper()} mencapai Rp {formatted_current}\n"
                            f"🎯 Target Anda: Rp {formatted_target}\n\n"
                            f"⏰ {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                        ),
                        parse_mode="Markdown",
                        reply_markup=get_menu_keyboard()
                    )
                    del alerts[user_id]
                    logging.info(f"Alert triggered untuk user {user_id}: {pair} @ {current_price}")
            else:
                logging.warning(f"Tidak bisa ambil data untuk {pair}")
        except Exception as e:
            logging.error(f"Error processing alert for {user_id} ({pair}): {e}")

# --- Fungsi Help (sama) ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs_list = ", ".join([p.upper() for p in VALID_PAIRS])
    msg = (
        "🤖 *Bantuan Bot Saori Indodax*\n\n"
        "📋 *Perintah yang tersedia:*\n"
        "• /start - Memulai bot\n"
        "• /price <pair> - Cek harga crypto\n"
        "• /top - Top 5 crypto populer\n"
        "• /market <pair> - Info market detail\n"
        "• /alert <pair> <harga> - Pasang alert harga\n"
        "• /status - Cek status API\n"
        "• /help - Tampilkan bantuan ini\n\n"
        "💡 *Contoh penggunaan:*\n"
        "• `/price btcidr` - Harga Bitcoin\n"
        "• `/market ethidr` - Market Ethereum\n"
        "• `/alert btcidr 1000000000` - Alert BTC 1M\n\n"
        f"🔗 *Pair yang tersedia:*\n{pairs_list}\n\n"
        "⚠️ *Catatan:* Bot bergantung pada API Indodax. Jika ada masalah, gunakan /status untuk cek kondisi API.\n\n"
        "Gunakan menu di bawah untuk memilih perintah!"
    )
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_menu_keyboard()
    )

# --- Fungsi test API status (async dengan waktu) ---
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check API status for all endpoints"""
    loading_msg = await update.message.reply_text("⏳ Checking API status...")
    
    status_msg = "🔍 *API Status Check*\n\n"
    working_endpoints = 0
    total_time = 0
    
    for i, endpoint_template in enumerate(INDODAX_ENDPOINTS, 1):
        start_time = datetime.datetime.now()
        try:
            if '{}' in endpoint_template:
                url = endpoint_template.format('btcidr')
            else:
                url = endpoint_template
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            session = requests.Session()
            response = session.get(url, timeout=8, headers=headers)
            
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            total_time += duration
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if ('ticker' in data and data['ticker']) or 'last' in data:
                        status_msg += f"✅ Endpoint {i}: Working ({duration:.2f}s)\n"
                        working_endpoints += 1
                    else:
                        status_msg += f"⚠️ Endpoint {i}: Invalid response ({duration:.2f}s)\n"
                except:
                    status_msg += f"⚠️ Endpoint {i}: Invalid JSON ({duration:.2f}s)\n"
            else:
                status_msg += f"❌ Endpoint {i}: HTTP {response.status_code} ({duration:.2f}s)\n"
        except requests.exceptions.Timeout:
            duration = 8.0  # Approximate
            status_msg += f"⏰ Endpoint {i}: Timeout ({duration}s)\n"
        except Exception as e:
            duration = (datetime.datetime.now() - start_time).total_seconds()
            status_msg += f"❌ Endpoint {i}: Error ({duration:.2f}s) - {str(e)[:30]}...\n"
    
    status_msg += f"\n📊 Working endpoints: {working_endpoints}/{len(INDODAX_ENDPOINTS)}\n"
    status_msg += f"⏱️ Avg time per endpoint: {total_time / len(INDODAX_ENDPOINTS):.2f}s\n"
    
    if working_endpoints > 0:
        status_msg += "✅ Bot dapat berfungsi (seharusnya <10s per command)"
    else:
        status_msg += "❌ Semua endpoint down, bot tidak dapat mengambil data"
    
    await loading_msg.edit_text(status_msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

# --- Setup Bot (update scheduler ke async job) ---
def main():
    logging.info("Starting Indodax Bot...")
    logging.info(f"Token: {'Found' if TOKEN else 'Missing'}")
    
    try:
        # Create application
        app = (
            Application.builder()
            .token(TOKEN)
            .build()
        )
        logging.info("Bot application created successfully")

        # Add handlers (semua handler sekarang async)
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("price", price))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("market", market))
        app.add_handler(CommandHandler("alert", alert))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(CommandHandler("help", help_command))
        logging.info("Command handlers added")

        # Setup scheduler untuk check alerts (async)
        try:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(check_alerts, "interval", minutes=2, args=[app])
            scheduler.start()
            logging.info("Alert scheduler started (check every 2 minutes)")
        except Exception as e:
            logging.error(f"Scheduler error: {e}")

        # Start keep-alive server
        try:
            from keep_alive import keep_alive
            keep_alive()
            logging.info("Keep-alive server started")
        except ImportError:
            logging.warning("Keep-alive not found, creating placeholder...")
            def keep_alive():
                logging.info("Keep-alive placeholder active")
            keep_alive()

        # Start bot
        logging.info("Bot is starting...")
        logging.info("Bot siap digunakan di Telegram! (Dengan optimasi speed)")
        
        app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logging.error(f"Bot startup error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
