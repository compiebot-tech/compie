import os
import re  # ← ADD THIS at the top with other imports
import logging
import requests
import threading
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROUP_ID  = int(os.environ.get("GROUP_ID"))
API_KEY   = os.environ.get("API_KEY")
API_URL   = os.environ.get("API_URL")


# ── Rate Limit Tracker ────────────────────────────────────
ask_usage = {}

# ── Tips ─────────────────────────────────────────────────
TIPS = [
    "Be specific in your prompts. Instead of asking 'explain AI', try 'explain how a large language model processes a question in simple terms.' The more context you give, the better the answer.",
    "Give Alpie a role. Try starting your question with 'As a financial advisor...' or 'As a teacher explaining to a 10 year old...' and watch how the response shifts in tone and depth.",
    "If an answer feels too short or surface level, just follow up with 'can you go deeper on that?' or 'give me an example.' Alpie responds well to follow-ups.",
    "Use numbered steps when asking for instructions. Try 'Give me 5 steps to start a blog' instead of just 'how do I blog?' You will get a much more actionable response.",
    "Ask Alpie to compare things. 'Compare Python vs JavaScript for beginners' gives you a clear, structured breakdown rather than a vague explanation of each.",
]
tip_index = [0]

# ── Quiz Bank ─────────────────────────────────────────────
QUIZ_BANK = [
    {
        "question": "What does LLM stand for in the context of AI?",
        "options": ["A) Large Language Model", "B) Logical Learning Machine", "C) Linear Language Module", "D) Layered Logic Mechanism"],
        "answer": "A",
        "explanation": "LLM stands for Large Language Model. Examples include GPT-4 and Alpie."
    },
    {
        "question": "Which company created the GPT series of AI models?",
        "options": ["A) Google", "B) Meta", "C) OpenAI", "D) Microsoft"],
        "answer": "C",
        "explanation": "The GPT series was created by OpenAI."
    },
    {
        "question": "What does API stand for?",
        "options": ["A) Automated Program Interface", "B) Application Programming Interface", "C) Applied Process Integration", "D) Advanced Protocol Input"],
        "answer": "B",
        "explanation": "API stands for Application Programming Interface. It allows different software systems to communicate."
    },
]
quiz_index   = [0]
pending_quiz = {}

# ── Flask Keep-Alive ──────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Compie is running.", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

# ── Scheduled Messages ────────────────────────────────────
def send_morning(bot):
    import asyncio
    message = (
        "Good morning, everyone!\n\n"
        "I'm Compie, your AI companion in this group, powered by Alpie by 169Pi.\n\n"
        "Here's a quick reminder of what I can do for you right here in this group:\n\n"
        "- /ask [your question] - Ask me anything, I'll answer using Alpie's intelligence\n"
        "- /about - Learn what Alpie and 169Pi are all about\n"
        "- /tip - Get a quick AI or prompt engineering tip\n"
        "- /quiz - Test your AI knowledge\n\n"
        "What is Alpie?\n"
        "Alpie is an AI assistant built by the 169Pi team. It is designed to be conversational, "
        "deeply knowledgeable, and genuinely useful across almost any topic you can think of.\n\n"
        "What is 169Pi?\n"
        "169Pi is the team behind Alpie. They build AI-powered tools and provide API access so "
        "developers, communities, and businesses can plug Alpie's intelligence directly into their own projects.\n\n"
        "Start your day with a good question. I'm here."
    )
    asyncio.run(bot.send_message(chat_id=GROUP_ID, text=message))

def send_evening(bot):
    import asyncio
    message = (
        "Good evening, everyone!\n\n"
        "Before the day wraps up, here's something worth thinking about:\n\n"
        "Alpie is not just a chatbot. It is built to work through complex questions, explain ideas clearly, "
        "and give you answers that are actually useful, whether you are curious about AI, exploring what "
        "169Pi offers, or trying to build something new.\n\n"
        "The best way to understand what Alpie can do is simply to try it.\n\n"
        "Type /ask followed by any question, right here in this group, and see for yourself.\n\n"
        "See you tomorrow morning."
    )
    asyncio.run(bot.send_message(chat_id=GROUP_ID, text=message))

# ── Command Handlers ──────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey! I'm Compie, an AI companion built by a community member to bring Alpie's intelligence right into this group.\n\n"
        "Alpie is the AI behind my answers, developed by the 169Pi team. I'm an independent project, "
        "not an official 169Pi product, but I'm powered by their API.\n\n"
        "Here's what I can do:\n"
        "- /ask [question] - Ask me anything\n"
        "- /about - Learn about Alpie and 169Pi\n"
        "- /tip - Get a prompt engineering tip\n"
        "- /quiz - Test your AI knowledge\n\n"
        "Try it now. Type /ask followed by any question."
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Alpie is an AI assistant built by 169Pi.\n\n"
        "It is designed to be conversational, knowledgeable, and helpful across a wide range of topics "
        "including science, technology, business, education, health, and more.\n\n"
        "169Pi is the team that built Alpie. They provide API access so developers and communities can "
        "integrate Alpie's intelligence into their own platforms and projects.\n\n"
        "This group exists to explore, learn, and make the most of what Alpie and 169Pi have to offer.\n\n"
        "Want to try Alpie right now?\n"
        "Type /ask followed by your question."
    )

async def tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_tip = TIPS[tip_index[0] % len(TIPS)]
    tip_index[0] += 1
    await update.message.reply_text(f"Tip of the moment:\n\n{current_tip}")

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = QUIZ_BANK[quiz_index[0] % len(QUIZ_BANK)]
    quiz_index[0] += 1
    pending_quiz[update.effective_user.id] = q["answer"]
    options_text = "\n".join(q["options"])
    await update.message.reply_text(
        f"AI Quiz Time!\n\n{q['question']}\n\n{options_text}\n\nReply with A, B, C, or D.\nType /answer [your choice] when ready."
    )

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pending_quiz:
        await update.message.reply_text("No active quiz found. Type /quiz to start one.")
        return
    if not context.args:
        await update.message.reply_text("Please type /answer followed by A, B, C, or D.")
        return
    user_answer   = context.args[0].upper()
    correct       = pending_quiz.pop(user_id)
    q_data        = next((q for q in QUIZ_BANK if q["answer"] == correct), None)
    if user_answer == correct:
        await update.message.reply_text(
            f"Correct! Well done.\n\n{q_data['explanation'] if q_data else ''}"
        )
    else:
        await update.message.reply_text(
            f"Not quite. The correct answer is {correct}.\n\n{q_data['explanation'] if q_data else ''}"
        )

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    # Rate limit check
    if user_id in ask_usage:
        if ask_usage[user_id]["date"] == today_str:
            if ask_usage[user_id]["count"] >= 3:
                await update.message.reply_text(
                    "You have reached today's limit for questions. "
                    "Come back tomorrow and ask away again.\n\n"
                    "In the meantime, try /tip or /quiz, both are unlimited and always ready."
                )
                return
        else:
            ask_usage[user_id] = {"date": today_str, "count": 0}
    else:
        ask_usage[user_id] = {"date": today_str, "count": 0}

    if not context.args:
        await update.message.reply_text("Please type /ask followed by your question.")
        return

    question = " ".join(context.args)
    await update.message.reply_text("Let me think about that...")

    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "alpie-32b",
            "messages": [
                {"role": "user", "content": question}
            ]
        }
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        data     = response.json()
        reply    = data["choices"][0]["message"]["content"]

        # ── Strip internal thinking block ──────────────────
        reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL).strip()
        # ──────────────────────────────────────────────────

        ask_usage[user_id]["count"] += 1
        await update.message.reply_text(reply)
    except Exception as e:
        logging.error(f"API error: {e}")
        await update.message.reply_text(
            "Something went wrong while fetching the answer. Please try again in a moment."
        )

# ── Main ──────────────────────────────────────────────────
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("about",  about))
    app.add_handler(CommandHandler("tip",    tip))
    app.add_handler(CommandHandler("quiz",   quiz))
    app.add_handler(CommandHandler("answer", answer))
    app.add_handler(CommandHandler("ask",    ask))

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: send_morning(app.bot),
        "cron", hour=8, minute=0
    )
    scheduler.add_job(
        lambda: send_evening(app.bot),
        "cron", hour=20, minute=0
    )
    scheduler.start()

    logging.info("Compie is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
