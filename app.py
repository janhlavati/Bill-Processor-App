import os
import io
import json
import base64
import requests
import pandas as pd
from datetime import datetime
from flask import Flask, request
import google.generativeai as genai

# --- Environment Variables ---
# IMPORTANT: You must replace these with your actual tokens and IDs.
# For security, these should be in a separate config file or environment variables in a production app.
WHATSAPP_TOKEN = "EAAZAN14jeOmkBPaLpGkAZAyhRG3xL1d7F1cbF6ZCGcS2qlXrYxUnZCZC3c9FJjVWHecs5xVhN2ZAg2s08kWaa2yBmwZAgpAhiZAIxIV0iJaPmvRa5CqbiTkBLNLF6iWcCX1iTmVEvpuBDZAranWLqF6RPvhFc4glk67PBqRQTjvrPMLsfAKVKKvTumyYJbSVxZC1TLGTrYXZAIgySrGZBf1ZASM9VqHH6vsNiK6ZCOhgraEyqhZCOw2GwZDZD"
WHATSAPP_PHONE_NUMBER_ID = "713297775208207"
GEMINI_API_KEY = "AIzaSyD0jRXRDXkQ0psbb8znka2WA_zqptHnXgQ"
VERIFY_TOKEN = "myapplicationprocessing"

# --- Flask App Setup ---
app = Flask(__name__)

# --- Gemini API Configuration ---
genai.configure(api_key=GEMINI_API_KEY)


# --- Utility Functions ---
# Function to get the current date for the Excel file
def get_current_date():
    """Returns the current date and time in a string format."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# Function to save data to an Excel file
def save_to_excel(data):
    """
    Saves a dictionary of extracted bill data to an Excel file.
    It appends to an existing file or creates a new one.
    """
    file_path = "bills.xlsx"
    try:
        # Check if the file exists and has data
        if os.path.exists(file_path):
            df_existing = pd.read_excel(file_path)
            if not df_existing.empty:
                # Concatenate the new data with the existing data
                df = pd.concat([df_existing, pd.DataFrame([data])], ignore_index=True)
            else:
                # Create a new DataFrame if the file is empty
                df = pd.DataFrame([data])
        else:
            # Create a new DataFrame if the file doesn't exist
            df = pd.DataFrame([data])

        # Save the DataFrame to the Excel file
        df.to_excel(file_path, index=False)
        print("Data saved to Excel successfully.")
    except Exception as e:
        print(f"Error saving to Excel: {e}")


# Function to send a message back to the user via WhatsApp
def send_whatsapp_message(user_id, text):
    """Sends a text message to a user via the WhatsApp Cloud API."""
    try:
        url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {'Authorization': f'Bearer {WHATSAPP_TOKEN}', 'Content-Type': 'application/json'}

        data = {
            'messaging_product': 'whatsapp',
            'to': user_id,
            'type': 'text',
            'text': {'body': text}
        }

        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()  # Raise an exception for bad status codes
        print("Message sent to WhatsApp successfully.")
    except Exception as e:
        print(f"Error sending message to WhatsApp: {e}")


# Function to encode image URL content as base64 for Gemini API
def get_image_as_base64(image_url):
    """Downloads an image from a URL and returns its base64 string representation."""
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        return base64.b64encode(response.content).decode('utf-8')
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None


# --- Webhook Endpoint ---
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    """
    Main webhook endpoint to handle both verification (GET) and
    incoming messages (POST) from the WhatsApp Cloud API.
    """
    # Verification GET request from Meta
    if request.method == 'GET':
        print("Received GET request for webhook verification.")
        print("Request arguments:", request.args)

        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode and token and mode == 'subscribe' and token == VERIFY_TOKEN:
            print("Webhook verification successful!")
            return challenge, 200
        else:
            print("Webhook verification FAILED. Tokens do not match or request is invalid.")
            return "Invalid verification token", 403

    # POST request with message data
    elif request.method == 'POST':
        try:
            data = request.json
            print("Received WhatsApp Webhook Data:", json.dumps(data, indent=2))

            # Navigate the JSON structure specific to WhatsApp webhook
            if 'object' in data and 'entry' in data:
                for entry in data['entry']:
                    if 'changes' in entry:
                        for change in entry['changes']:
                            if 'messages' in change['value']:
                                for message in change['value']['messages']:
                                    user_id = message['from']

                                    # Check for an image attachment
                                    if message['type'] == 'image':
                                        image_id = message['image']['id']

                                        # Use the image ID to get the image URL from the WhatsApp Cloud API
                                        image_url_response = requests.get(
                                            f"https://graph.facebook.com/v19.0/{image_id}",
                                            headers={'Authorization': f'Bearer {WHATSAPP_TOKEN}'})
                                        image_url_response.raise_for_status()
                                        image_url = image_url_response.json()['url']

                                        print(f"Image received from user {user_id}: {image_url}")

                                        # Send a quick confirmation to the user
                                        send_whatsapp_message(user_id, "Got your bill! I'm processing it now.")

                                        # --- Core Logic: Call Gemini API and process data ---

                                        # Encode the image from the URL to base64
                                        base64_image = get_image_as_base64(image_url)
                                        if not base64_image:
                                            send_whatsapp_message(user_id, "Sorry, I couldn't download the image.")
                                            return "OK", 200

                                        # Create the prompt for Gemini
                                        prompt_parts = [
                                            {
                                                "inline_data": {
                                                    "mime_type": "image/jpeg",
                                                    "data": base64_image
                                                }
                                            },
                                            {
                                                "text": "Extract the date, total amount, and vendor name from this bill. Return the data as a JSON object with keys 'date', 'total', and 'vendor'. If any information is missing, use 'null'."}
                                        ]

                                        model = genai.GenerativeModel("gemini-1.5-pro")

                                        try:
                                            response = model.generate_content(prompt_parts)
                                            # Clean up the Gemini response from markdown formatting
                                            extracted_text = response.text.replace("```json\n", "").replace("\n```",
                                                                                                            "").strip()
                                            extracted_data = json.loads(extracted_text)

                                            # Add current date and save to Excel
                                            extracted_data['processed_date'] = get_current_date()
                                            save_to_excel(extracted_data)

                                            # Format the final response message for the user
                                            response_message = f"I've processed your bill!\nVendor: {extracted_data['vendor']}\nDate: {extracted_data['date']}\nTotal: {extracted_data['total']}"
                                            send_whatsapp_message(user_id, response_message)

                                        except Exception as e:
                                            print(f"Error with Gemini API or JSON parsing: {e}")
                                            send_whatsapp_message(user_id,
                                                                  "I'm sorry, I couldn't process that bill. Please try another image.")

            return "OK", 200

        except Exception as e:
            print(f"Error processing webhook request: {e}")
            return "Error", 500


# Run the Flask app
if __name__ == '__main__':
    app.run(port=5000)