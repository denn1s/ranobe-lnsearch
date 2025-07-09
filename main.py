# main.py

import os
import asyncio
import logging
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import requests
# Import the manual verification function instead of the decorator
from discord_interactions import verify_key, InteractionType, InteractionResponseType

# --- Configuration ---
load_dotenv()
PUBLIC_KEY = os.getenv('DISCORD_PUBLIC_KEY')
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
APPLICATION_ID = os.getenv('DISCORD_APPLICATION_ID')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI App ---
app = FastAPI()

# --- Reusable Core Logic (Unchanged) ---
def search_ranobedb(query: str, limit: int = 5):
    """Searches the RanobeDB API for books."""
    api_url = "https://ranobedb.org/api/v0/books"
    params = {'q': query, 'limit': limit, 'sort': 'Release date asc'}
    try:
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('books', [])
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return []

def create_book_embed(book_data: dict):
    """Creates a Discord embed dictionary for a single book."""
    embed = {
        "title": book_data.get('title', 'Unknown Title'),
        "color": 0x0099ff, # Blue color
        "url": f"https://ranobedb.org/book/{book_data.get('id', '')}",
        "fields": [],
        "image": {},
        "footer": {"text": "Powered by RanobeDB"}
    }
    if book_data.get('title_orig'):
        embed["fields"].append({"name": "Original Title", "value": book_data['title_orig'], "inline": False})
    if release_date := book_data.get('c_release_date'):
        date_str = str(release_date)
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        embed["fields"].append({"name": "Release Date", "value": formatted_date, "inline": True})
    if lang := book_data.get('lang'):
        embed["fields"].append({"name": "Language", "value": lang.upper(), "inline": True})
    if image_info := book_data.get('image'):
        if filename := image_info.get('filename'):
            embed["image"]["url"] = f"https://images.ranobedb.org/{filename}"
    return embed

# --- Background Task for Slash Commands (Unchanged) ---
async def process_search_command(interaction: dict):
    """Handles the actual logic after the initial defer response."""
    query = interaction['data']['options'][0]['value']
    books = await asyncio.to_thread(search_ranobedb, query)
    
    followup_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{interaction['token']}"

    if not books:
        response_data = {"content": f"Sorry, I couldn't find any books matching **{query}**."}
    elif len(books) == 1:
        embed = create_book_embed(books[0])
        response_data = {"embeds": [embed]}
    else:
        options = [
            {"label": book.get('title', 'Unknown Title')[:100], "value": f"book_{i}", "description": f"Language: {book.get('lang', '?').upper()}"}
            for i, book in enumerate(books)
        ]
        response_data = {
            "content": "I found several books. Please select one from the list:",
            "components": [{"type": 1, "components": [{"type": 3, "custom_id": "select_book", "options": options, "placeholder": "Choose a book"}]}]
        }
    
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    requests.post(followup_url, json=response_data, headers=headers)

# --- Main Web Server Endpoint ---
# The decorator has been removed from here
@app.post("/interactions")
async def handle_interactions(request: Request):
    """Handles all incoming interaction requests from Discord."""
    # Manually verify the request signature
    signature = request.headers.get("x-signature-ed25519")
    timestamp = request.headers.get("x-signature-timestamp")
    body = await request.body()

    if signature is None or timestamp is None or not verify_key(body, signature, timestamp, PUBLIC_KEY):
        return Response(content="Bad request signature", status_code=401)

    # If verification passes, process the interaction
    interaction = await request.json()

    if interaction["type"] == InteractionType.PING:
        return JSONResponse({"type": InteractionResponseType.PONG})

    if interaction["type"] == InteractionType.APPLICATION_COMMAND:
        asyncio.create_task(process_search_command(interaction))
        return JSONResponse({"type": InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE})

    if interaction["type"] == InteractionType.MESSAGE_COMPONENT:
        return JSONResponse({"type": InteractionResponseType.DEFERRED_UPDATE_MESSAGE})
        
    return Response(status_code=404)
