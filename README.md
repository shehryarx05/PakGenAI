# PakGenAI

PakGenAI is a Whatsapp based career guidance chatbot that helps choose students choose careers via Whatsapp.

## 🚀 Features
- **AI-Powered Career Guidance** – Uses OpenAI API for well structured and authentic responses.
- **WhatsApp Integration** – Powered by Twilio WhatsApp API.
- **Feedback Collection** – Stores user feedback in Google Sheets.
- **Flask Backend** – Efficient Python 3.11 based server.
- **Render Deployment** – 24/7 hosting on Render.

## Tools used
- **Python 3.11**
- **Flask**
- **Twilio WhatsApp API**
- **OpenAI API**
- **Google Sheets API**
- **Render** (deployment)

## How It Works
1. User sends a WhatsApp message to the bot.
2. Twilio forwards the message to the Flask server through a webhook.
3. The server processes the message using OpenAI API.
4. Responses are sent back to the user instantly.
5. Feedback is stored in Google Sheets.
