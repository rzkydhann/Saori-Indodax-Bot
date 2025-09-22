from flask import Flask
from threading import Thread
import time
import logging
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <div style='text-align: center; font-family: Arial; padding: 50px;'>
        <h1>🤖 Indodax Crypto Bot</h1>
        <p style='color: green; font-size: 18px;'>✅ Bot sedang online dan berjalan!</p>
        <p style='color: blue;'>📱 Gunakan bot di Telegram</p>
        <p style='color: gray; font-size: 12px;'>Keep-alive server active</p>
    </div>
    """

@app.route('/health')
def health():
    return {
        "status": "healthy",
        "bot": "indodax-crypto-bot",
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
    }

def run():
    # Railway menyediakan PORT via environment variable
    port = int(os.environ.get('PORT', 8080))
    retries = 3
    
    for attempt in range(retries):
        try:
            logging.info(f"Starting Flask keep-alive server on port {port}...")
            app.run(host='0.0.0.0', port=port, debug=False)
            break
        except Exception as e:
            logging.error(f"Keep-alive server error (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                logging.info("Retrying in 5 seconds...")
                time.sleep(5)
            else:
                logging.error("Failed to start keep-alive server after retries")

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    port = int(os.environ.get('PORT', 8080))
    logging.info(f"Keep-alive server started on port {port}")
    return t
