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

# Import telegram
try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, ContextTypes
except ImportError as e:
    logging.error(f"Telegram import error: {e}. Pastikan library sudah terinstal.")
    exit(1)

# Import keep_alive (opsional)
try:
    from keep_alive import keep_alive
except ImportError:
    def keep_alive(): pass

# --- Konfigurasi Awal ---
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    logging.error("BOT_TOKEN tidak ditemukan di environment variables!")
    exit(1)

cache = TTLCache(maxsize=100, ttl=60)
# DIUBAH: Memperbaiki dogidr -> dogeidr
VALID_PAIRS = ["btcidr", "ethidr", "ltcidr", "xrpidr", "adaidr", "dogeidr", "shibidr", "maticidr"]
alerts = {}
# DIUBAH: Menyederhanakan ke satu endpoint yang valid
INDODAX_API_URL = "https://indodax.com/api/ticker"

# --- Fungsi Menu Tombol ---
def get_menu_keyboard():
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

# --- Fungsi Helper Pengambilan Data (Disederhanakan dan Non-Blocking) ---
def fetch_data_sync(pair):
    """Fungsi ini berjalan di thread terpisah untuk mengambil data tanpa memblokir bot."""
    if pair not in VALID_PAIRS:
        logging.warning(f"Invalid pair requested: {pair}")
        return None
    
    url = f"{INDODAX_API_URL}/{pair}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if 'ticker' in data and 'last' in data['ticker']:
            logging.info(f"Successfully fetched data for {pair}")
            return data['ticker']
        else:
            logging.warning(f"Invalid JSON structure for {pair}: {data}")
            return None
    except (requests.RequestException, json.JSONDecodeError) as e:
        logging.error(f"Failed to fetch data for {pair} from {url}: {e}")
        return None

async def get_ticker_data(pair: str):
    if pair in cache:
        logging.info(f"Using cached data for {pair}")
        return cache[pair]
    
    ticker_data = await asyncio.to_thread(fetch_data_sync, pair)
    
    if ticker_data:
        cache[pair] = ticker_data
    return ticker_data

# --- Fungsi Perintah Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "👋 Selamat datang di *Saori Indodax Crypto Bot*!\n\nGunakan menu tombol di bawah untuk memulai."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Gunakan format: `/price <pair>`", reply_markup=get_menu_keyboard())
        return
    
    pair = context.args[0].lower()
    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...", reply_markup=get_menu_keyboard())
    ticker = await get_ticker_data(pair)
    
    if ticker:
        last_price = f"{float(ticker['last']):,.0f}"
        msg = f"📊 *Harga {pair.upper()}*\n💰 Terakhir: Rp {last_price}"
        await loading_msg.edit_text(msg, parse_mode="Markdown")
    else:
        await loading_msg.edit_text(f"❌ Gagal mengambil data untuk {pair.upper()}. Pair mungkin tidak valid atau API bermasalah.")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # DIUBAH: Memperbaiki dogidr -> dogeidr
    pairs = ["btcidr", "ethidr", "dogeidr", "shibidr", "maticidr"]
    loading_msg = await update.message.reply_text("⏳ Mengambil data top coins...", reply_markup=get_menu_keyboard())
    
    tasks = [get_ticker_data(pair) for pair in pairs]
    results = await asyncio.gather(*tasks)
    
    msg = "🔥 *Top Coin di Indodax:*\n\n"
    for pair, ticker in zip(pairs, results):
        if ticker:
            price_val = f"{float(ticker['last']):,.0f}"
            msg += f"▪️ {pair.upper()}: Rp {price_val}\n"
        else:
            msg += f"▪️ {pair.upper()}: Gagal dimuat\n"

    await loading_msg.edit_text(msg, parse_mode="Markdown")

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Gunakan format: `/market <pair>`", reply_markup=get_menu_keyboard())
        return

    pair = context.args[0].lower()
    loading_msg = await update.message.reply_text(f"⏳ Mengambil market data {pair.upper()}...", reply_markup=get_menu_keyboard())
    ticker = await get_ticker_data(pair)

    if ticker:
        high = f"{float(ticker.get('high', 0)):,.0f}"
        low = f"{float(ticker.get('low', 0)):,.0f}"
        coin_name = pair.replace("idr", "")
        vol_key = f"vol_{coin_name}"
        vol_value = float(ticker.get(vol_key, 0))
        vol_formatted = f"{vol_value:,.2f}"
        
        msg = (
            f"📊 *Market {pair.upper()}*\n\n"
            f"📈 Tertinggi 24j: Rp {high}\n"
            f"📉 Terendah 24j: Rp {low}\n"
            f"📦 Volume: {vol_formatted} {coin_name.upper()}"
        )
        await loading_msg.edit_text(msg, parse_mode="Markdown")
    else:
        await loading_msg.edit_text(f"❌ Gagal mengambil market data untuk {pair.upper()}.")
        
async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Gunakan format: `/alert <pair> <harga>`", reply_markup=get_menu_keyboard())
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"Pair {pair} tidak valid.", reply_markup=get_menu_keyboard())
        return
    try:
        target_price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Harga harus berupa angka.", reply_markup=get_menu_keyboard())
        return
    
    user_id = update.message.chat_id
    alerts[user_id] = {'pair': pair, 'price': target_price}
    await update.message.reply_text(f"🔔 Alert terpasang untuk {pair.upper()} pada harga Rp {target_price:,.0f}", reply_markup=get_menu_keyboard())

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    if not alerts: return
    
    alert_list = list(alerts.items())
    for user_id, alert_info in alert_list:
        pair = alert_info['pair']
        ticker = await get_ticker_data(pair)
        if ticker and float(ticker['last']) >= alert_info['price']:
            await context.bot.send_message(user_id, f"🚨 *ALERT HARGA* 🚨\n\n{pair.upper()} telah mencapai target Anda!", parse_mode="Markdown", reply_markup=get_menu_keyboard())
            del alerts[user_id]

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loading_msg = await update.message.reply_text("⏳ Cek status API Indodax...", reply_markup=get_menu_keyboard())
    ticker = await get_ticker_data("btcidr")
    if ticker:
        await loading_msg.edit_text("✅ API Indodax beroperasi normal.")
    else:
        await loading_msg.edit_text("❌ API Indodax sepertinya sedang bermasalah atau koneksi server gagal.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🤖 *Bantuan Bot*\n\nGunakan tombol di bawah untuk navigasi. Jika perintah gagal, coba gunakan `/status` untuk mendiagnosa masalah koneksi."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

# --- Main Program ---
def main():
    logging.info("Starting bot...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("alert", alert))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    
    app.job_queue.run_repeating(check_alerts, interval=60, first=10)
    
    logging.info("All handlers and jobs are set up.")
    
    keep_alive()
    
    logging.info("Bot is polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
