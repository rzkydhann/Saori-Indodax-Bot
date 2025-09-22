import os
import requests
import datetime
import asyncio
import json
import logging
from cachetools import TTLCache
import pytz

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Set zona waktu WIB
wib = pytz.timezone('Asia/Jakarta')

# Import telegram dengan error handling
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    logging.info("Telegram imports successful")
except ImportError as e:
    logging.error(f"Telegram import error: {e}")
    # Jangan instal di runtime; tambah di requirements.txt
    raise

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
    exit()

# Cache untuk API data (1 menit TTL)
cache = TTLCache(maxsize=100, ttl=60)

# Daftar pair yang valid
VALID_PAIRS = [
    "btcidr", "ethidr", "ltcidr", "xrpidr", "adaidr",
    "dogidr", "shibidr", "maticidr"
]

# Simpan alert harga
alerts = {}

# --- Fungsi Start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Selamat datang di *Indodax Crypto Bot*!\n\n"
        "Perintah yang tersedia:\n"
        "🔹 /price <pair> → Cek harga (contoh: /price btcidr)\n"
        "🔹 /top → Lihat koin populer\n"
        "🔹 /market <pair> → Info market\n"
        "🔹 /alert <pair> <harga> → Pasang alarm harga\n"
        "🔹 /help → Bantuan\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- Fungsi helper untuk API call ---
def get_ticker_data(pair):
    """Helper function untuk get data dari API Indodax dengan cache"""
    if pair not in VALID_PAIRS:
        logging.warning(f"Invalid pair requested: {pair}")
        return None

    if pair in cache:
        logging.info(f"Using cached data for {pair}")
        return cache[pair]

    try:
        url = f"https://indodax.com/api/{pair}/ticker"
        logging.info(f"Fetching data for {pair} from {url}")
        
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        logging.debug(f"API Response for {pair}: {data}")
        
        if 'ticker' not in data:
            logging.error(f"API Response tidak memiliki 'ticker' untuk {pair}")
            return None
            
        cache[pair] = data['ticker']
        return data['ticker']
        
    except requests.exceptions.Timeout:
        logging.error(f"Timeout saat mengakses API untuk {pair}")
        return None
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection error untuk {pair}")
        return None
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP Error {e.response.status_code} untuk {pair}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON response untuk {pair}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error untuk {pair}: {str(e)}")
        return None

# --- Fungsi cek harga ---
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Gunakan format: /price <pair>\n"
            f"Contoh: /price btcidr\n\n"
            f"Pair yang tersedia:\n{pairs_list}"
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}"
        )
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...")
    
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text(
            f"❌ Gagal ambil data untuk {pair.upper()}\n"
            f"Pastikan pair crypto benar atau coba lagi dalam beberapa saat."
        )
        return

    try:
        last_price = f"{float(ticker['last']):,.0f}"
        high_price = f"{float(ticker['high']):,.0f}"
        low_price = f"{float(ticker['low']):,.0f}"
        volume = f"{float(ticker.get('vol_idr', 0)):,.2f}"
        
        msg = (
            f"📊 *Harga {pair.upper()}*\n\n"
            f"💰 Terakhir: Rp {last_price}\n"
            f"📈 Tertinggi 24h: Rp {high_price}\n"
            f"📉 Terendah 24h: Rp {low_price}\n"
            f"📦 Volume 24h: Rp {volume}\n\n"
            f"⏰ Diperbarui: {datetime.now(wib).strftime('%H:%M:%S %d-%m-%Y')}"  # Diperbaiki
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown")
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing data untuk {pair}: {e}")
        await loading_msg.edit_text(f"❌ Error parsing data untuk {pair.upper()}: {str(e)}")

# --- Fungsi Top coin ---
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
                msg += f"▫️ {pair.upper()}: Error\n"
        else:
            msg += f"▫️ {pair.upper()}: Tidak tersedia\n"
    
    msg += f"\n⏰ Diperbarui: {datetime.now(wib).strftime('%H:%M:%S %d-%m-%Y')}"  # Diperbaiki
    
    if success_count == 0:
        msg = "❌ Gagal mengambil data semua coin. Coba lagi nanti."
    
    await loading_msg.edit_text(msg, parse_mode="Markdown")

# --- Fungsi Market Info ---
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ Gunakan format: /market <pair>\nContoh: /market btcidr")
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}"
        )
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil market data {pair.upper()}...")
    
    ticker = get_ticker_data(pair)
    
    if ticker is None:
        await loading_msg.edit_text(f"❌ Gagal ambil data untuk {pair.upper()}")
        return
    
    try:
        high = f"{float(ticker['high']):,.0f}"
        low = f"{float(ticker['low']):,.0f}"
        last = f"{float(ticker['last']):,.0f}"
        volume = f"{float(ticker.get('vol_idr', 0)):,.2f}"
        buy = float(ticker.get('buy', 0))
        sell = float(ticker.get('sell', 0))
        
        msg = (
            f"📊 *Market {pair.upper()}*\n\n"
            f"📈 High 24h: Rp {high}\n"
            f"📉 Low 24h: Rp {low}\n"
            f"💰 Last Price: Rp {last}\n"
            f"💵 Buy Price: Rp {buy:,.0f}\n"
            f"💴 Sell Price: Rp {sell:,.0f}\n"
            f"📦 Volume 24h: Rp {volume}\n\n"
            f"⏰ Diperbarui: {datetime.now(wib).strftime('%H:%M:%S %d-%m-%Y')}"  # Diperbaiki
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown")
        
    except (KeyError, ValueError) as e:
        logging.error(f"Error parsing market data untuk {pair}: {e}")
        await loading_msg.edit_text(f"❌ Error parsing market data: {str(e)}")

# --- Fungsi Alert ---
async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Gunakan format: /alert <pair> <harga>\n"
            "Contoh: /alert btcidr 1000000000\n"
            "(Alert ketika BTC mencapai 1 miliar)"
        )
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        pairs_list = "\n".join([f"• {pair}" for pair in VALID_PAIRS])
        await update.message.reply_text(
            f"⚠️ Pair {pair.upper()} tidak valid!\n"
            f"Pair yang tersedia:\n{pairs_list}"
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
    await update.message.reply_text(
        f"🔔 Alert dipasang!\n\n"
        f"Coin: {pair.upper()}\n"
        f"Target: Rp {formatted_price}\n\n"
        f"Anda akan diberitahu jika harga mencapai target."
    )

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
                    
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"🚨 *ALERT HARGA!* 🚨\n\n"
                            f"💰 {pair.upper()} mencapai Rp {formatted_current}\n"
                            f"🎯 Target Anda: Rp {formatted_target}\n\n"
                            f"⏰ {datetime.now(wib).strftime('%d/%m/%Y %H:%M:%S')}"  # Diperbaiki
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
    pairs_list = ", ".join(VALID_PAIRS)
    msg = (
        "🤖 *Bantuan Bot Indodax*\n\n"
        "📋 *Perintah yang tersedia:*\n"
        "• /start - Memulai bot\n"
        "• /price <pair> - Cek harga crypto\n"
        "• /top - Top 5 crypto populer\n"
        "• /market <pair> - Info market detail\n"
        "• /alert <pair> <harga> - Pasang alert harga\n"
        "• /help - Tampilkan bantuan ini\n\n"
        "💡 *Contoh penggunaan:*\n"
        "• `/price btcidr` - Harga Bitcoin\n"
        "• `/market ethidr` - Market Ethereum\n"
        "• `/alert btcidr 1000000000` - Alert BTC 1M\n\n"
        f"🔗 *Pair yang tersedia:*\n{pairs_list}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- Setup Bot ---
def main():
    logging.info("Starting Indodax Bot...")
    logging.info(f"Token: {'Found' if TOKEN else 'Missing'}")
    
    try:
        # Create application
        app = Application.builder().token(TOKEN).build()
        logging.info("Bot application created successfully")

        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("price", price))
        app.add_handler(CommandHandler("top", top))
        app.add_handler(CommandHandler("market", market))
        app.add_handler(CommandHandler("alert", alert))
        app.add_handler(CommandHandler("help", help_command))
        logging.info("Command handlers added")

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
        logging.info("Bot siap digunakan di Telegram!")
        
        app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logging.error(f"Bot startup error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
