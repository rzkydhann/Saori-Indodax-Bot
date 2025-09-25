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

# Import scheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Import keep_alive (opsional)
try:
    from keep_alive import keep_alive
except ImportError:
    def keep_alive():
        pass # Buat fungsi kosong jika file tidak ada

# --- Konfigurasi Awal ---
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    logging.error("BOT_TOKEN tidak ditemukan di environment variables!")
    exit(1)

cache = TTLCache(maxsize=100, ttl=60)
VALID_PAIRS = ["btcidr", "ethidr", "ltcidr", "xrpidr", "adaidr", "dogidr", "shibidr", "maticidr"]
alerts = {}
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

# --- Fungsi Inti ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "👋 Selamat datang di *Saori Indodax Crypto Bot*!\n\nGunakan menu tombol di bawah untuk memulai."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_menu_keyboard())

async def get_ticker_data(pair: str):
    if pair not in VALID_PAIRS: return None
    if pair in cache: return cache[pair]

    url = f"{INDODAX_API_URL}/{pair}"
    
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

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Gunakan format: `/price <pair>`", parse_mode="Markdown", reply_markup=get_menu_keyboard())
        return
    
    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"Pair {pair.upper()} tidak valid.", reply_markup=get_menu_keyboard())
        return

    loading_msg = await update.message.reply_text(f"⏳ Mengambil data {pair.upper()}...", reply_markup=get_menu_keyboard())
    ticker = await get_ticker_data(pair)
    
    if ticker:
        last_price = f"{float(ticker['last']):,.0f}"
        msg = f"📊 *Harga {pair.upper()}*\n💰 Terakhir: Rp {last_price}"
        await loading_msg.edit_text(msg, parse_mode="Markdown") # DIUBAH: Hapus reply_markup
    else:
        await loading_msg.edit_text(f"❌ Gagal mengambil data untuk {pair.upper()}.") # DIUBAH: Hapus reply_markup

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pairs = ["btcidr", "ethidr", "dogidr", "shibidr", "maticidr"]
    loading_msg = await update.message.reply_text("⏳ Mengambil data top coins...", reply_markup=get_menu_keyboard())
    
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
    
    if success_count == 0: msg = "❌ Gagal mengambil semua data top coin."

    await loading_msg.edit_text(msg, parse_mode="Markdown") # DIUBAH: Hapus reply_markup

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Gunakan format: `/market <pair>`", parse_mode="Markdown", reply_markup=get_menu_keyboard())
        return

    pair = context.args[0].lower()
    if pair not in VALID_PAIRS:
        await update.message.reply_text(f"Pair {pair.upper()} tidak valid.", reply_markup=get_menu_keyboard())
        return

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
        await loading_msg.edit_text(msg, parse_mode="Markdown") # DIUBAH: Hapus reply_markup
    else:
        await loading_msg.edit_text(f"❌ Gagal mengambil market data untuk {pair.upper()}.") # DIUBAH: Hapus reply_markup
        
async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Gunakan format: `/alert <pair> <harga>`", parse_mode="Markdown", reply_markup=get_menu_keyboard())
        return
    
    pair = context.args[0].lower()
    try: target_price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Harga harus berupa angka.", reply_markup=get_menu_keyboard())
        return
    
    user_id = update.message.chat_id
    alerts[user_id] = {'pair': pair, 'price': target_price}
    await update.message.reply_text(f"🔔 Alert terpasang untuk {pair.upper()} pada harga Rp {target_price:,.0f}", reply_markup=get_menu_keyboard())

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    if not alerts: return
    
    unique_pairs = {a['pair'] for a in alerts.values()}
    for pair in unique_pairs:
        ticker = await get_ticker_data(pair)
        if ticker:
            current_price = float(ticker['last'])
            for user_id, alert_info in list(alerts.items()):
                if alert_info['pair'] == pair and current_price >= alert_info['price']:
                    await context.bot.send_message(user_id, f"🚨 *ALERT HARGA* 🚨\n\n{pair.upper()} telah mencapai target Anda!", parse_mode="Markdown", reply_markup=get_menu_keyboard())
                    del alerts[user_id]

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loading_msg = await update.message.reply_text("⏳ Cek status API Indodax...", reply_markup=get_menu_keyboard())
    ticker = await get_ticker_data("btcidr")
    if ticker: await loading_msg.edit_text("✅ API Indodax beroperasi normal.") # DIUBAH: Hapus reply_markup
    else: await loading_msg.edit_text("❌ API Indodax sepertinya sedang bermasalah.") # DIUBAH: Hapus reply_markup

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🤖 *Bantuan Bot*\n\nGunakan tombol di bawah untuk navigasi. Setiap perintah akan memberikan instruksi lebih lanjut jika dibutuhkan."
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
    
    logging.info("Handlers and jobs are set up.")
    
    keep_alive()
    
    logging.info("Bot is polling...")
    app.run_polling(drop_pending_updates=True) # Tambahkan ini untuk mengabaikan perintah lama saat bot baru nyala

if __name__ == "__main__":
    main()
