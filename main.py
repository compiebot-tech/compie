import os
import logging
import random
import requests
from datetime import datetime
from collections import defaultdict
from threading import Thread

from flask import Flask
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ── Load environment variables ──────────────────────────────────────────────
load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN")
API_KEY     = os.getenv("API_KEY")          # Your 169pi API key
GROUP_ID    = int(os.getenv("GROUP_ID"))    # e.g. -1001234567890
API_URL     = os.getenv("API_URL")          # 169pi API endpoint

# ── Logging setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Rate limiting storage ────────────────────────────────────────────────────
# { user_id: { "date": "2026-06-19", "count": 2 } }
user_ask_log: dict = defaultdict(lambda: {"date": "", "count": 0})
DAILY_LIMIT = 3

# ── Static content ───────────────────────────────────────────────────────────
TIPS = [
    (
        "💡 *Tip of the moment:*\n\n"
        "Be specific in your prompts. Instead of asking 'explain AI', try "
        "'explain how a large language model processes a question in simple terms.' "
        "The more context you give, the better the answer."
    ),
    (
        "💡 *Tip of the moment:*\n\n"
        "Give Alpie a role. Try starting your question with 'As a financial advisor...' "
        "or 'As a teacher explaining to a 10 year old...' and watch how the response "
        "shifts in tone and depth."
    ),
    (
        "💡 *Tip of the moment:*\n\n"
        "If an answer feels too short or surface level, just follow up with "
        "'can you go deeper on that?' or 'give me an example.' "
        "Alpie responds well to follow-ups."
    ),
    (
        "💡 *Tip of the moment:*\n\n"
        "Use constraints to sharpen answers. Try 'explain this in under 100 words' "
        "or 'give me 3 bullet points only.' Constraints produce clarity."
    ),
    (
        "💡 *Tip of the moment:*\n\n"
        "Ask Alpie to compare things. 'What is the difference between X and Y, "
        "and when should I use each?' is one of the most powerful question formats."
    ),
]

QUIZ_BANK = [
    {
        "question": (
            "🧠 *AI Quiz Time!*\n\n"
            "What does LLM stand for in the context of AI?\n\n"
            "A) Large Language Model\n"
            "B) Logical Learning Machine\n"
            "C) Linear Language Module\n"
            "D) Layered Logic Mechanism\n\n"
            "Reply with A, B, C, or D."
        ),
        "answer": "A",
        "explanation": "✅ *Answer: A — Large Language Model*\n\nLLMs are AI models trained on massive text datasets to understand and generate human language. Alpie is powered by one!"
    },
    {
        "question": (
            "🧠 *AI Quiz Time!*\n\n"
            "What is a 'prompt' in the context of AI?\n\n"
            "A) A memory chip inside the AI\n"
            "B) The input or instruction you give to an AI model\n"
            "C) A type of neural network layer\n"
            "D) The AI's training dataset\n\n"
            "Reply with A, B, C, or D."
        ),
        "answer": "B",
        "explanation": "✅ *Answer: B — The input or instruction you give to an AI model*\n\nA prompt is simply what you type or say to the AI. The quality of your prompt directly affects the quality of the response."
    },
    {
        "question": (
            "🧠 *AI Quiz Time!*\n\n"
            "What does 'GPT' stand for?\n\n"
            "A) General Processing Technology\n"
            "B) Generative Pre-trained Transformer\n"
            "C) Global Prediction Tool\n"
            "D) Gradient Processing Tree\n\n"
            "Reply with A, B, C, or D."
        ),
        "answer": "B",
        "explanation": "✅ *Answer: B — Generative Pre-trained Transformer*\n\nGPT models are a family of LLMs that use the Transformer architecture and are pre-trained on large text corpora before being fine-tuned."
    },
]

MORNING_MESSAGE = (
    "☀️ *Good morning, everyone!*\n\n"
    "I'm Compie, your AI companion in this group, powered by Alpie and the 169pi team.\n\n"
    "Here's a quick reminder of what I can do for you right here in this group:\n\n"
    "• /ask \\[your question\\] — Ask me anything, I'll answer using Alpie's intelligence\n"
    "• /about — Learn what Alpie and 169pi are all about\n"
    "• /tip — Get a quick AI or prompt engineering tip\n"
    "• /quiz — Test your AI knowledge\n\n"
    "*What is Alpie?*\n"
    "Alpie is an AI assistant built by the 169pi team. It is designed to be conversational, "
    "deeply knowledgeable, and genuinely useful across almost any topic you can think of.\n\n"
    "*What is 169pi?*\n"
    "169pi is the team behind Alpie. They build AI-powered tools and provide API access so "
    "developers, communities, and businesses can plug Alpie's intelligence directly into their own projects.\n\n"
    "Start your day with a good question. I'm here. 🤖"
)

EVENING_MESSAGE = (
    "🌙 *Good evening, everyone!*\n\n"
    "Before the day wraps up, here's something worth thinking about:\n\n"
    "Alpie is not just a chatbot. It is built to work through complex questions, explain ideas clearly, "
    "and give you answers that are actually useful — whether you are curious about AI, exploring what "
    "169pi offers, or trying to build something new.\n\n"
    "The best way to understand what Alpie can do is simply to try it.\n\n"
    "Type /ask followed by any question, right here in the group, and see for yourself.\n\n"
    "See you tomorrow morning. 👋"
)

# ── Rate limit checker ───────────────────────────────────────────────────────
def check_rate_limit(user_id: int) -> bool:
    """Returns True if user is allowed to ask, False if limit reached."""
    today = datetime.now().strftime("%Y-%m-%d")
    record = user_ask_log[user_id]

    # Reset count if it's a new day
    if record["date"] != today:
        user_ask_log[user_id] = {"date": today, "count": 0}

    if user_ask_log[user_id]["count"] >= DAILY_LIMIT:
        return False

    user_ask_log[user_id]["count"] += 1
    return True

# ── 169pi API call ───────────────────────────────────────────────────────────
def call_alpie(question: str) -> str:
    """Send question to 169pi API and return Alpie's response."""
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "alpie",           # adjust to actual model name from 169pi
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Alpie, a helpful AI assistant built by the 169pi team. "
                        "You are responding inside a Telegram group called Compie. "
                        "Be warm, clear, and concise."
                    )
                },
                {"role": "user", "content": question}
            ]
        }
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Adjust key path to match 169pi's actual response format
        return data["choices"][0]["message"]["content"]

    except requests.exceptions.Timeout:
        return "Alpie is taking a moment to think. Please try again shortly."
    except requests.exceptions.RequestException as e:
        logger.error(f"API error: {e}")
        return "I couldn't reach Alpie right now. Please try again in a moment."

# ── Command handlers ─────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "👋 *Hey there! I'm Compie.*\n\n"
        "Your friendly AI companion in this group, powered by Alpie and the 169pi team.\n\n"
        "Here's what I can do:\n\n"
        "• /ask \\[question\\] — Ask Alpie anything\n"
        "• /about — Learn about Alpie and 169pi\n"
        "• /tip — Get a prompt engineering tip\n"
        "• /quiz — Test your AI knowledge\n\n"
        "Go ahead, ask me something! 🤖",
        parse_mode="MarkdownV2"
    )


async def ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ask command — the only paid call."""
    user_id   = update.effective_user.id
    user_name = update.effective_user.first_name

    # Extract question from message
    question = " ".join(context.args).strip() if context.args else ""

    if not question:
        await update.message.reply_text(
            "Please include your question after the command.\n\n"
            "Example: `/ask What is machine learning?`",
            parse_mode="Markdown"
        )
        return

    # Check rate limit
    if not check_rate_limit(user_id):
        await update.message.reply_text(
            "You have reached today's limit for questions. "
            "Come back tomorrow and ask away again.\n\n"
            "In the meantime, try /tip or /quiz — both are unlimited and always ready."
        )
        return

    # Show typing indicator while waiting for API
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    # Call Alpie
    response = call_alpie(question)

    remaining = DAILY_LIMIT - user_ask_log[user_id]["count"]
    await update.message.reply_text(
        f"🤖 *Alpie says:*\n\n{response}\n\n"
        f"_{user_name}, you have {remaining} question(s) left today._",
        parse_mode="Markdown"
    )


async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /about command — static, no API cost."""
    await update.message.reply_text(
        "🔍 *About Alpie & 169pi*\n\n"
        "Alpie is an AI assistant built by the 169pi team.\n\n"
        "It is designed to be conversational, knowledgeable, and helpful across a wide range "
        "of topics including science, technology, business, education, health, and more.\n\n"
        "169pi is the team that built Alpie. They provide API access so developers and communities "
        "can integrate Alpie's intelligence into their own platforms and projects.\n\n"
        "This group exists to explore, learn, and make the most of what Alpie and 169pi have to offer.\n\n"
        "Want to try Alpie right now?\nType `/ask` followed by your question.",
        parse_mode="Markdown"
    )


async def tip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tip command — rotates through local tips, no API cost."""
    tip = random.choice(TIPS)
    await update.message.reply_text(tip, parse_mode="Markdown")


# Track last quiz shown per chat for /answer command
last_quiz: dict = {}

async def quiz_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quiz command — local question bank, no API cost."""
    chat_id = update.effective_chat.id
    question_data = random.choice(QUIZ_BANK)
    last_quiz[chat_id] = question_data
    await update.message.reply_text(question_data["question"], parse_mode="Markdown")


async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /answer command — reveals quiz answer."""
    chat_id = update.effective_chat.id
    if chat_id not in last_quiz:
        await update.message.reply_text(
            "No active quiz found. Type /quiz to start one!"
        )
        return
    await update.message.reply_text(
        last_quiz[chat_id]["explanation"],
        parse_mode="Markdown"
    )
    del last_quiz[chat_id]

# ── Scheduled message senders ────────────────────────────────────────────────
def send_morning_message(bot):
    """Send morning message to group — called by scheduler."""
    import asyncio
    asyncio.run(bot.send_message(
        chat_id=GROUP_ID,
        text=MORNING_MESSAGE,
        parse_mode="Markdown"
    ))
    logger.info("Morning message sent.")


def send_evening_message(bot):
    """Send evening message to group — called by scheduler."""
    import asyncio
    asyncio.run(bot.send_message(
        chat_id=GROUP_ID,
        text=EVENING_MESSAGE,
        parse_mode="Markdown"
    ))
    logger.info("Evening message sent.")

# ── Flask keep-alive server ──────────────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def health_check():
    """UptimeRobot will ping this endpoint to keep Render awake."""
    return "Compie is alive! 🤖", 200

def run_flask():
    """Run Flask in a separate thread."""
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

# ── Main entry point ─────────────────────────────────────────────────────────
def main():
    # Start Flask in background thread for UptimeRobot pings
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask keep-alive server started.")

    # Build the Telegram bot application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start",  start_handler))
    app.add_handler(CommandHandler("ask",    ask_handler))
    app.add_handler(CommandHandler("about",  about_handler))
    app.add_handler(CommandHandler("tip",    tip_handler))
    app.add_handler(CommandHandler("quiz",   quiz_handler))
    app.add_handler(CommandHandler("answer", answer_handler))

    # Set up APScheduler for daily messages (UTC timezone)
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        send_morning_message,
        trigger="cron",
        hour=8, minute=0,           # 8:00 AM UTC — adjust to your timezone
        args=[app.bot]
    )
    scheduler.add_job(
        send_evening_message,
        trigger="cron",
        hour=20, minute=0,          # 8:00 PM UTC — adjust to your timezone
        args=[app.bot]
        )
    scheduler.start()
    logger.info("Scheduler started. Morning at 08:00 UTC, Evening at 20:00 UTC.")

    # Start polling
    logger.info("Compie is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
