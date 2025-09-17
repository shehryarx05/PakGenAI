import os
import time
import json
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, request, Response
from dotenv import load_dotenv
from openai import OpenAI
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse
from threading import Thread
from datetime import datetime

# --- Load local .env for development (safe to keep) ---
load_dotenv()

# --- Google Sheets setup (reads creds from env variable GOOGLE_CREDS) ---
google_creds_json = os.environ.get("GOOGLE_CREDS")
if not google_creds_json:
    # If you want local testing using a file, you can support that here.
    # But for production (Render) you should set GOOGLE_CREDS in the service env.
    raise RuntimeError("GOOGLE_CREDS environment variable is not set. Paste service account JSON into that variable.")

try:
    google_creds_dict = json.loads(google_creds_json)
except Exception as e:
    raise RuntimeError(f"Failed to parse GOOGLE_CREDS JSON: {e}")

creds = Credentials.from_service_account_info(
    google_creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
)

gs_client = gspread.authorize(creds)
SHEET_NAME = os.environ.get("SHEET_NAME", "PakGen Feedback")

try:
    sheet = gs_client.open(SHEET_NAME).sheet1
except Exception as e:
    # Provide a helpful error if the sheet is not accessible
    raise RuntimeError(f"Failed to open Google Sheet named '{SHEET_NAME}'. Make sure the service account has Editor access and the sheet exists. Error: {e}")

def save_feedback_placeholder():
    """Append a row with 'No feedback left' and return row index"""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row(["No feedback left", ts])
        row_index = sheet.row_count  # last row index
        print(f"✅ Placeholder saved at row {row_index}")
        return row_index
    except Exception as e:
        print(f"❌ Failed to save placeholder row: {e}")
        return None

def update_feedback_in_sheets(row_index, feedback):
    """Update the placeholder row with actual feedback"""
    try:
        sheet.update_cell(row_index, 1, feedback)  # col 1 = feedback column
        print(f"✅ Feedback updated at row {row_index}")
    except Exception as e:
        print(f"❌ Failed to update feedback at row {row_index}: {e}")


# --- Flask + OpenAI + Twilio setup ---
app = Flask(__name__)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_auth = os.getenv("TWILIO_AUTH_TOKEN")
twilio_whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
if not (twilio_sid and twilio_auth and twilio_whatsapp_number):
    raise RuntimeError("Twilio environment variables (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER) must be set.")

twilio_client = TwilioClient(twilio_sid, twilio_auth)

# --- In-memory user state (OK for MVP) ---
user_states = {}

# --- Questions ---
questions = [
    "1️⃣ What is your current education stream? (FSc Pre-Med, FSc Pre-Engg, ICS, FA, A Levels, IB, etc.)",
    "2️⃣ What is your favorite subject in school or college?",
    "3️⃣ How well do you usually perform in studies?",
    "4️⃣ Be honest, do you enjoy studying or not really?",
    "5️⃣ Do you prefer working indoors or outdoors?",
    "6️⃣ Would you rather work with people, or independently?",
    "7️⃣ What sounds more exciting to you: designing something or solving logical problems?",
    "8️⃣ Do you enjoy building things with your hands or using a computer to create solutions?",
    "9️⃣ What's more important to you: earning a good income, enjoying your work, or helping others?",
    "🔟 What do you usually do in your free time? (e.g. gaming, helping family, browsing tech, etc.)"
]

def split_text(text, max_length=1500):
    parts = []
    while len(text) > max_length:
        idx = text.rfind("\n", 0, max_length)
        if idx == -1:
            idx = max_length
        parts.append(text[:idx])
        text = text[idx:]
    parts.append(text)
    return parts

def get_career_suggestions(answers):
    prompt = "A Pakistani student answered the following questions:\n\n"
    for i, answer in enumerate(answers):
        prompt += f"{questions[i]} {answer}\n"
    prompt += (
        "\nBased on these answers, suggest 3–5 realistic career paths that might suit this student from Pakistan. "
        "For each option, include:\n- A simple explanation\n- How this career is doing in Pakistan\n"
        "- Which degree is usually needed\n- Top universities in Pakistan offering it. At the end of the answer, please add a short explanation on how to get into each university you mentioned (what tests to take, how to prepare etc). Make sure all info is accurate and authentic. "
        "Reply as if you're directly talking to the student. At the end say: 'You can DM us at PakGenAI on Instagram for further guidance and queries.'"
    )

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You're a career counselor helping Pakistani high school students."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=750,
            temperature=0.7
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ OpenAI Error: {e}")
        return f"⚠️ Something went wrong with OpenAI: {e}"

def send_whatsapp_message(to, body):
    try:
        twilio_client.messages.create(
            from_=f"whatsapp:{twilio_whatsapp_number}",
            to=f"whatsapp:{to}",
            body=body
        )
    except Exception as e:
        print(f"❌ Failed to send message to {to}: {e}")

@app.route("/bot", methods=["POST"])
def whatsapp_bot():
    sender = request.form.get("From")
    msg = (request.form.get("Body") or "").strip()
    if not sender:
        print("No 'From' field in request")
        return Response(status=400)

    phone = sender.split(":")[-1]
    lower_msg = msg.lower()

    print(f"📨 Message from {phone}: {msg}")

    response = MessagingResponse()
    reply = response.message()

    # New user - show intro
    if phone not in user_states:
        user_states[phone] = {"step": -1, "answers": [], "suggested": False}
        reply.body(
            "👋 Hi I’m *PakGenAI*, your personal career counsellor.\n\n"
            "Just answer 10 quick questions and I’ll match you with careers that fit YOU.\n\n"
            "Type *ready* to begin!"
        )
        return str(response)

    state = user_states[phone]["step"]

    # Start
    if state == -1:
        if lower_msg == "ready":
            user_states[phone]["step"] = 0
            reply.body("Great! Let's begin 🚀\n\n" + questions[0])
        else:
            reply.body("Please type *ready* to begin the quiz.")
        return str(response)

    # During quiz
    if 0 <= state < len(questions):
        user_states[phone]["answers"].append(msg)
        user_states[phone]["step"] += 1
        state += 1

        if state < len(questions):
            reply.body(questions[state])
        else:
            reply.body("⏳ Analyzing your answers...")
            # run OpenAI & sending in background
            Thread(target=send_suggestions_and_feedback, args=(phone,)).start()
        return str(response)

    # Collect feedback (the user replies after suggested = True)
    if user_states[phone].get("suggested") and "feedback" not in user_states[phone]:
        user_feedback = msg
        user_states[phone]["feedback"] = user_feedback
        try:
            row_index = user_states[phone].get("sheet_row")
            if row_index:
                update_feedback_in_sheets(row_index, user_feedback)
            else:
                # fallback: append normally if row not tracked
                save_feedback_to_sheets(user_feedback)
        except Exception as e:
            print(f"❌ Error saving feedback: {e}")
        reply.body("✅ Thanks for your feedback! For any queries you can DM us at *PakGenAI* on Instagram.")
        return str(response)


    reply.body("You've completed the quiz. For any queries you can DM us at *PakGenAI* on Instagram.")
    return str(response)

def send_suggestions_and_feedback(phone):
    answers = user_states[phone]["answers"]
    suggestions = get_career_suggestions(answers)
    user_states[phone]["suggestions"] = suggestions

    # Save placeholder row ("No feedback left")
    row_index = save_feedback_placeholder()
    if row_index:
        user_states[phone]["sheet_row"] = row_index  # remember which row belongs to this user
    
    chunks = split_text(suggestions)

    for chunk in chunks:
        send_whatsapp_message(phone, chunk)
        time.sleep(1)  # spacing to avoid Twilio rate limits

    time.sleep(1)
    send_whatsapp_message(phone, "Was this bot helpful? Please reply with feedback and suggestions.")
    user_states[phone]["suggested"] = True

# --- Run block ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
