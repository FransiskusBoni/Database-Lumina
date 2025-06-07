import sys
import os
import discord
import asyncio
import logging
import time
import threading
import json
import re
from flask import Flask, render_template_string, jsonify, request
from werkzeug.serving import run_simple

# ===== App Configuration =====
# The User ID of the bot whose messages we are indexing (e.g., Lord Karbiter)
TARGET_BOT_ID = 1261042392413372520
# Add the ID of the server you want to index messages in
TARGET_SERVER_ID = 123456789012345678 # <-- PASTE YOUR SERVER ID HERE

# --- File paths for the container's filesystem ---
DATA_DIR = '/var/data'
DATABASE_FILE = os.path.join(DATA_DIR, 'card_database.json')
LOG_FILE = os.path.join(DATA_DIR, 'card_indexer.log')

LOG_MESSAGES = []
BOT_STATUS = {"text": "Offline", "color": "grey"}

# --- Flask Web App Setup ---
app = Flask(__name__)
app.logger.disabled = True
log = logging.getLogger('werkzeug')
log.disabled = True

def get_token():
    """Gets the discord token from an environment variable."""
    token = os.environ.get('USER_TOKEN')
    if not token:
        logging.critical("USER_TOKEN environment variable not set. The bot cannot start.")
        sys.exit("Error: USER_TOKEN not set.")
    return token

# ===== Database Functions =====
def load_database():
    """Loads the card database from the JSON file."""
    if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
    if not os.path.exists(DATABASE_FILE): return {}
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except (json.JSONDecodeError, IOError):
        logging.error(f"Could not read or parse {DATABASE_FILE}. Starting with an empty database.")
        return {}

def save_database(db):
    """Saves the card database to the JSON file."""
    if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f: json.dump(db, f, indent=4)
    except IOError: logging.error(f"Could not write to {DATABASE_FILE}.")

# ===== Self-Bot Class (and other functions from your script) =====
class IndexerBot(discord.Client):
    """A self-bot that passively listens and builds a local card database."""
    def __init__(self, status_callback, log_callback, **options):
        super().__init__(self_bot=True, **options)
        self.status_callback = status_callback
        self.log_callback = log_callback
        self.card_database = load_database()
        self.db_lock = threading.Lock()

    async def on_ready(self):
        logging.info(f"Logged in as {self.user.display_name}. Listening for card data...")
        self.status_callback("Online - Indexing", "green")

    async def on_disconnect(self):
        logging.warning("Disconnected from Discord.")
        self.status_callback("Disconnected", "orange")
    
    def clean_card_name(self, line):
        try:
            return re.sub(r'^\d+\s*-\s*[A-Z-]*\s*', '', line).strip()
        except Exception:
            return line

    async def on_message(self, message):
        if message.guild is None or message.guild.id != TARGET_SERVER_ID or message.author.id != TARGET_BOT_ID or not message.embeds: return
        for embed in message.embeds:
            if embed.author and embed.author.name and embed.description and embed.author.icon_url:
                author_name_lower = embed.author.name.lower()
                if 'collection' in author_name_lower or 'wishlist' in author_name_lower:
                    owner_id_match = re.search(r"/avatars/(\d+)/", str(embed.author.icon_url))
                    if not owner_id_match: continue
                    owner_id = owner_id_match.group(1)
                    owner_name = embed.author.name.split("'s")[0]
                    cards_in_embed = [self.clean_card_name(line) for line in embed.description.split('\n')]
                    updated_cards = []
                    with self.db_lock:
                        for card_name in cards_in_embed:
                            if not card_name: continue
                            if card_name not in self.card_database: self.card_database[card_name] = []
                            if owner_id not in self.card_database[card_name]:
                                self.card_database[card_name].append(owner_id)
                                updated_cards.append(card_name)
                    if updated_cards:
                        log_message = f"Indexed {len(updated_cards)} new card(s) from {owner_name} in #{message.channel.name}."
                        logging.info(log_message)
                        self.log_callback(log_message)
                        save_database(self.card_database)

# ===== Web Interface (Flask) and other functions =====
@app.route('/')
def index():
    # I've collapsed the HTML for brevity, but it should be the full HTML from your original file.
    return render_template_string("""<!DOCTYPE html>...</html>""") 

@app.route('/api/status')
def api_status():
    return jsonify(BOT_STATUS)
@app.route('/api/logs')
def api_logs():
    return jsonify({"logs": LOG_MESSAGES})
@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').lower().strip()
    if not query: return jsonify({"owners": []})
    db = load_database()
    found_ids = set()
    for card_name, owner_list in db.items():
        if query in card_name.lower(): found_ids.update(owner_list)
    return jsonify({"owners": sorted(list(found_ids))})

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_instance = IndexerBot(update_status, log_to_global)
    try:
        token = get_token()
        bot_instance.run(token)
    except Exception as e:
        logging.critical(f"Bot thread crashed: {e}", exc_info=True)
        update_status("Crashed", "Crashed")
def update_status(text, color):
    global BOT_STATUS
    BOT_STATUS = {"text": text, "color": color}
def log_to_global(message):
    global LOG_MESSAGES
    LOG_MESSAGES.insert(0, f"[{time.strftime('%H:%M:%S')}] {message}")
    LOG_MESSAGES = LOG_MESSAGES[:50]

if __name__ == "__main__":
    if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)-s] %(message)s', handlers=[logging.FileHandler(LOG_FILE, mode='w'), logging.StreamHandler(sys.stdout)])
    update_status("Connecting...", "Connecting")
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
