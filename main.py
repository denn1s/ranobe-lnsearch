# main.py

import os
import asyncio
import logging
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import requests
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

# --- Reusable Core Logic ---
def search_ranobedb(query: str, limit: int = 5):
    """Searches for books by a query string."""
    api_url = "https://ranobedb.org/api/v0/books"
    params = {'q': query, 'limit': limit, 'sort': 'Release date asc'}
    try:
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('books', [])
    except requests.exceptions.RequestException as e:
        logger.error(f"API search failed: {e}")
        return []

def get_book_details(book_id: int):
    """Fetches details for a single book by its ID."""
    api_url = f"https://ranobedb.org/api/v0/book/{book_id}"
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API detail fetch failed for book ID {book_id}: {e}")
        return None

def create_book_embed(book_data: dict):
    """Creates a Discord embed dictionary for a single book."""
    embed = {
        "title": book_data.get('title', 'Unknown Title'),
        "color": 0x0099ff,
        "url": f"https://ranobedb.org/book/{book_data.get('id', '')}",
        "fields": [], "image": {}, "footer": {"text": "Powered by RanobeDB"}
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

# --- Background Task to process the initial search ---
async def process_search_command(interaction: dict):
    """Handles the initial search and sends the follow-up message."""
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
            {
                "label": book.get('title', 'Unknown Title')[:100],
                "value": str(book['id']), # Pass the actual book ID
                "description": f"Language: {book.get('lang', '?').upper()}"
            } for book in books
        ]
        response_data = {
            "content": "I found several books. Please select one from the list:",
            "components": [{"type": 1, "components": [{"type": 3, "custom_id": "select_book", "options": options, "placeholder": "Choose a book"}]}]
        }
    
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    requests.post(followup_url, json=response_data, headers=headers)

# --- Main Web Server Endpoint ---
@app.post("/interactions")
async def handle_interactions(request: Request):
    """Handles all incoming interaction requests from Discord."""
    signature = request.headers.get("x-signature-ed25519")
    timestamp = request.headers.get("x-signature-timestamp")
    body = await request.body()
    if signature is None or timestamp is None or not verify_key(body, signature, timestamp, PUBLIC_KEY):
        return Response(content="Bad request signature", status_code=401)

    interaction = await request.json()

    if interaction["type"] == InteractionType.PING:
        return JSONResponse({"type": InteractionResponseType.PONG})

    if interaction["type"] == InteractionType.APPLICATION_COMMAND:
        # Defer immediately and run the search in the background
        asyncio.create_task(process_search_command(interaction))
        return JSONResponse({"type": InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE})

    if interaction["type"] == InteractionType.MESSAGE_COMPONENT:
        # A user selected a book from the dropdown
        book_id = int(interaction['data']['values'][0])
        book_details = await asyncio.to_thread(get_book_details, book_id)
        
        if book_details:
            embed = create_book_embed(book_details)
            # This time, we respond by updating the original message
            return JSONResponse({
                "type": InteractionResponseType.UPDATE_MESSAGE,
                "data": {
                    "content": "Here are the details for your selection:",
                    "embeds": [embed],
                    "components": [] # Remove the dropdown
                }
            })
        else:
            # Handle case where detail fetch fails
            return JSONResponse({
                "type": InteractionResponseType.UPDATE_MESSAGE,
                "data": { "content": "Sorry, I couldn't retrieve details for that selection.", "components": []}
            })
        
    return Response(status_code=404)
