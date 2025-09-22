import logging
from saori_indodax_bot import main as bot_main

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    logging.info("Starting bot...")
    bot_main()  # Jalankan bot Telegram saja
