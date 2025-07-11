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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App ---
app = FastAPI()

# --- Reusable Core Logic (Unchanged) ---
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
        "fields": [],
        "image": {},
        "footer": {"text": "Powered by RanobeDB"}
    }
    
    # Add the description to the main body of the embed
    if description := book_data.get('description'):
        # Increase the character limit before truncating
        max_len = 1024 
        if len(description) > max_len:
            embed['description'] = description[:max_len].strip() + "..."
        else:
            embed['description'] = description

    if image_info := book_data.get('image'):
        if filename := image_info.get('filename'):
            embed["image"]["url"] = f"https://images.ranobedb.org/{filename}"
    
    return embed

# --- Background Task to process the initial search ---
async def process_search_command(interaction: dict):
    """Handles the initial search and sends the follow-up message."""
    logger.info("DEBUG: Starting background search task.")
    query = interaction['data']['options'][0]['value']
    books = await asyncio.to_thread(search_ranobedb, query)
    followup_url = f"https://discord.com/api/v10/webhooks/{APPLICATION_ID}/{interaction['token']}"

    response_data = {}

    if not books:
        response_data = {"content": f"Sorry, I couldn't find any books matching **{query}**."}
    elif len(books) == 1:
        # If there's one result, we need to fetch its full details for the description
        logger.info(f"DEBUG: Single result found. Fetching full details for book ID {books[0]['id']}.")
        book_id = books[0]['id']
        book_details = await asyncio.to_thread(get_book_details, book_id)
        
        if book_details and 'book' in book_details:
            embed = create_book_embed(book_details['book'])
            response_data = {"embeds": [embed]}
        else:
            response_data = {"content": "Sorry, I couldn't retrieve the details for that book."}
    else:
        # If there are multiple results, create the dropdown as before
        options = [
            {"label": book.get('title', 'Unknown Title')[:100], "value": str(book['id']), "description": f"Language: {book.get('lang', '?').upper()}"}
            for book in books
        ]
        response_data = {
            "content": "I found several books. Please select one from the list:",
            "components": [{"type": 1, "components": [{"type": 3, "custom_id": "select_book", "options": options, "placeholder": "Choose a book"}]}]
        }
    
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    logger.info("DEBUG: Sending followup message to Discord.")
    try:
        requests.post(followup_url, json=response_data, headers=headers)
        logger.info("DEBUG: Followup message sent successfully.")
    except Exception as e:
        logger.error(f"DEBUG: Failed to send followup message: {e}")


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
    interaction_type = interaction["type"]
    
    if interaction_type == InteractionType.PING:
        return JSONResponse({"type": InteractionResponseType.PONG})

    if interaction_type == InteractionType.APPLICATION_COMMAND:
        asyncio.create_task(process_search_command(interaction))
        return JSONResponse({"type": InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE})

    if interaction_type == InteractionType.MESSAGE_COMPONENT:
        book_id = int(interaction['data']['values'][0])
        book_details = await asyncio.to_thread(get_book_details, book_id)
        
        if book_details and 'book' in book_details:
            embed = create_book_embed(book_details['book'])
            
            return JSONResponse({
                "type": InteractionResponseType.UPDATE_MESSAGE,
                "data": {
                    "content": "", # Set to an empty string to remove the text
                    "embeds": [embed],
                    "components": [] 
                }
            })
        else:
            return JSONResponse({
                "type": InteractionResponseType.UPDATE_MESSAGE,
                "data": { "content": "Sorry, I couldn't retrieve details for that selection.", "components": []}
            })
        
    return Response(status_code=404)
