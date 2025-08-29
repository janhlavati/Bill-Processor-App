import os
import json
import base64
import requests
import pandas as pd
from datetime import datetime
from flask import Flask, request
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()


WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

app = Flask(__name__)

# --- Configuration of Gemini - AI API with the key from the environment ---
genai.configure(api_key=GEMINI_API_KEY)


# --- Function to return date and time in String format for Excel data ---
def get_current_date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_to_excel(data):
    """
    Saves a dictionary of extracted bill data to an Excel file.
    It appends to an existing file or creates a new one.
    """
    file_path = "bills.xlsx"
    try:
        # Check if the file already exists on the local disk
        if os.path.exists(file_path):
            try:
                df_existing = pd.read_excel(file_path, engine='openpyxl')
                # Concatenate the new data with the existing data
                df = pd.concat([df_existing, pd.DataFrame([data])], ignore_index=True)
            except Exception as e:
                print(f"File exists but an error occurred reading it: {e}. Creating a new file.")
                df = pd.DataFrame([data])
        else:
            df = pd.DataFrame([data])

        df.to_excel(file_path, index=False, engine='openpyxl')
        print("Data saved to Excel successfully.")
    except Exception as e:
        print(f"Error saving to Excel: {e}")


def send_whatsapp_message(user_id, text):

    try:
        url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {'Authorization': f'Bearer {WHATSAPP_TOKEN}', 'Content-Type': 'application/json'}

        data = {
            'messaging_product': 'whatsapp',
            'to': user_id,
            'type': 'text',
            'text': {'body': text}
        }

        #API call to send the message
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        print("Message sent to WhatsApp successfully.")
    except Exception as e:
        print(f"Error sending message to WhatsApp: {e}")


# --- Processing image as Base64 string, therefore, we can embed the image into the Gemini API directly ---
def get_image_as_base64(image_url):
    try:
        response = requests.get(image_url, headers={'Authorization': f'Bearer {WHATSAPP_TOKEN}'})
        response.raise_for_status()
        return base64.b64encode(response.content).decode('utf-8')
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None

# --- Webhook handlers ---
def handle_verification(args):

    mode = args.get('hub.mode')
    token = args.get('hub.verify_token')
    challenge = args.get('hub.challenge')

    if mode and token and mode == 'subscribe' and token == VERIFY_TOKEN:
        print("Webhook verification successful!")
        return challenge, 200
    else:
        print("Webhook verification FAILED. Tokens do not match or request is invalid.")
        return "Invalid verification token", 403


def extract_data(changes):
    for message in changes.get('value', {}).get('messages', []):
        user_id = message['from']
        if message.get('type') == 'image':
            process_image_message(message, user_id)


def handle_message(data):
    if 'object' in data and 'entry' in data:
        for entry in data['entry']:
            for change in entry.get('changes', []):
                extract_data(change)
    return "OK", 200



def process_image_message(message, user_id):

    image_id = message['image']['id']

    image_url_response = requests.get(
        f"https://graph.facebook.com/v19.0/{image_id}",
        headers={'Authorization': f'Bearer {WHATSAPP_TOKEN}'})
    image_url_response.raise_for_status()
    image_url = image_url_response.json()['url']

    print(f"Image received from user {user_id}: {image_url}")

    send_whatsapp_message(user_id, "Got your bill! I'm processing it now.")

    # --- Core Logic: Calling the Gemini API and process data ---

    base64_image = get_image_as_base64(image_url)
    if not base64_image:
        send_whatsapp_message(user_id, "Sorry, I couldn't download the image.")
        return "OK", 200

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

    model = genai.GenerativeModel("gemini-1.5-flash")

    try:
        response = model.generate_content(prompt_parts)
        extracted_text = response.text.replace("```json\n", "").replace("\n```",
                                                                        "").strip()
        extracted_data = json.loads(extracted_text)

        extracted_data['processed_date'] = get_current_date()
        save_to_excel(extracted_data)

        response_message = f"I've processed your bill!\nVendor: {extracted_data['vendor']}\nDate: {extracted_data['date']}\nTotal: {extracted_data['total']}"
        send_whatsapp_message(user_id, response_message)

    except Exception as e:
        print(f"Error with Gemini API or JSON parsing: {e}")
        send_whatsapp_message(user_id,
                              "I'm sorry, I couldn't process that bill. Please try another image.")


# --- Flask webhook route ---
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():

    if request.method == 'GET':
        return handle_verification(request.args)

    elif request.method == 'POST':
        try:
            data = request.json
            print("Received WhatsApp Webhook Data:", json.dumps(data, indent=2))

            handle_message(data)
            return "OK", 200

        except Exception as e:
            print(f"Error processing webhook request: {e}")
            return "Error", 500


# --- Run the Flask app ---
if __name__ == '__main__':
    app.run(port=5000)