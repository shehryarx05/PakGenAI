import os
import time
import csv
from flask import Flask, request
from dotenv import load_dotenv
from openai import OpenAI
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse

from threading import Thread
from datetime import datetime

# Load environment variables
load_dotenv()
app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Twilio setup
twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_auth = os.getenv("TWILIO_AUTH_TOKEN")
twilio_whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
twilio_client = TwilioClient(twilio_sid, twilio_auth)

# User states
user_states = {}

# Feedback file
CSV_FILE = "feedback.csv"
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Phone", "Time", "Feedback"])

# Questions
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
        if idx == -1: idx = max_length
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
        completion = client.chat.completions.create(
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
    phone = sender.split(":")[-1]
    lower_msg = msg.lower()

    print(f"📨 Message from {phone}: {msg}")

    response = MessagingResponse()
    reply = response.message()

    if phone not in user_states:
        user_states[phone] = {"step": -1, "answers": [], "suggested": False}
        reply.body(
            "👋 Hi I’m *PakGenAI*, your personal career counsellor.\n\n"
            "Just answer 10 quick questions and I’ll match you with careers that fit YOU.\n\n"
            "Type *ready* to begin!"
        )
        return str(response)

    state = user_states[phone]["step"]

    if state == -1:
        if lower_msg == "ready":
            user_states[phone]["step"] = 0
            reply.body("Great! Let's begin 🚀\n\n" + questions[0])
        else:
            reply.body("Please type *ready* to begin the quiz.")
        return str(response)

    if 0 <= state < len(questions):
        user_states[phone]["answers"].append(msg)
        user_states[phone]["step"] += 1
        state += 1

        if state < len(questions):
            reply.body(questions[state])
        else:
            reply.body("⏳ Analyzing your answers...")
            Thread(target=send_suggestions_and_feedback, args=(phone,)).start()
        return str(response)

    if user_states[phone].get("suggested") and "feedback" not in user_states[phone]:
        user_states[phone]["feedback"] = msg
        save_feedback(phone, user_states[phone])
        reply.body("✅ Thanks for your feedback! For any queries you can DM us at *PakGenAI* on Instagram.")
        return str(response)

    reply.body("You've completed the quiz. For any queries you can DM us at *PakGenAI* on Instagram.")
    return str(response)

def save_feedback(phone, data):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            phone,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("feedback", ""),
        ])

def send_suggestions_and_feedback(phone):
    answers = user_states[phone]["answers"]
    suggestions = get_career_suggestions(answers)
    user_states[phone]["suggestions"] = suggestions
    chunks = split_text(suggestions)

    for chunk in chunks:
        send_whatsapp_message(phone, chunk)
        time.sleep(1)

    time.sleep(1)
    send_whatsapp_message(phone, "Was this bot helpful? Any feedback or suggestions?")
    user_states[phone]["suggested"] = True

if __name__ == '__main__':
    app.run()
