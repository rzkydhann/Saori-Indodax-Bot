from flask import Flask
from threading import Thread
import time
import logging

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
    retries = 3
    for attempt in range(retries):
        try:
            logging.info("Starting Flask keep-alive server on port 8080...")
            app.run(host='0.0.0.0', port=8080, debug=False)
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
    logging.info("Keep-alive server started on port 8080")
    return t