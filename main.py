import os
import re
import logging
import requests
import threading
import xml.etree.ElementTree as ET
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

# ── Environment Variables ─────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROUP_ID  = int(os.environ.get("GROUP_ID"))
API_KEY   = os.environ.get("API_KEY")
API_URL   = os.environ.get("API_URL")

# ── System Prompt ─────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are compie, an AI companion powered by Alpie, built by 169Pi. "
    "You are operating inside a Telegram group. "
    "You have access to real-time web search. "
    "When a user asks about current events, today's news, live weather, "
    "prices, scores, or any time-sensitive information, "
    "you MUST use your web search capability to retrieve up-to-date information. "
    "Never say you cannot access real-time data. "
    "Always provide the most current and accurate answer available. "
    "Keep responses concise and conversational, suitable for a group chat."
)

# ── News RSS Sources ──────────────────────────────────────
# Multiple sources ensure coverage even if one feed is down or stale.
NEWS_SOURCES = [
    {
        "name": "Reuters",
        "url":  "https://feeds.reuters.com/reuters/topNews"
    },
    {
        "name": "BBC News",
        "url":  "https://feeds.bbci.co.uk/news/world/rss.xml"
    },
    {
        "name": "AP News",
        "url":  "https://rsshub.app/apnews/topics/apf-topnews"
    },
    {
        "name": "The Guardian",
        "url":  "https://www.theguardian.com/world/rss"
    },
    {
        "name": "Al Jazeera",
        "url":  "https://www.aljazeera.com/xml/rss/all.xml"
    },
]

# ── Group-Only Guard ──────────────────────────────────────
async def group_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "Hi! I'm compie, a group AI companion.\n\n"
            "I only work inside the group I'm assigned to. "
            "Head over there and use /ask, /tip, or /quiz!"
        )
        return False
    return True

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
        "question":    "What does LLM stand for in the context of AI?",
        "options":     ["A) Large Language Model", "B) Logical Learning Machine", "C) Linear Language Module", "D) Layered Logic Mechanism"],
        "answer":      "A",
        "explanation": "LLM stands for Large Language Model. Examples include GPT-4 and Alpie."
    },
    {
        "question":    "Which company created the GPT series of AI models?",
        "options":     ["A) Google", "B) Meta", "C) OpenAI", "D) Microsoft"],
        "answer":      "C",
        "explanation": "The GPT series was created by OpenAI."
    },
    {
        "question":    "What does API stand for?",
        "options":     ["A) Automated Program Interface", "B) Application Programming Interface", "C) Applied Process Integration", "D) Advanced Protocol Input"],
        "answer":      "B",
        "explanation": "API stands for Application Programming Interface. It allows different software systems to communicate."
    },
]

quiz_index   = [0]
pending_quiz = {}

# ── Flask Keep-Alive ──────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "compie is running.", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

# ── Helper: Fetch Real Headlines via RSS ──────────────────
def fetch_real_headlines(limit: int = 5) -> list:
    """
    Fetches real, date-validated headlines from RSS feeds.
    - Prioritises items published today.
    - Falls back to most recent items if nothing dated today is found.
    - No API key required.
    """
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    headlines = []   # confirmed today's headlines
    fallback  = []   # most recent headlines regardless of date

    request_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; compie-bot/1.0)"
    }

    for source in NEWS_SOURCES:
        if len(headlines) >= limit:
            break

        try:
            resp = requests.get(
                source["url"],
                timeout=10,
                headers=request_headers
            )
            resp.raise_for_status()

            root = ET.fromstring(resp.content)

            for item in root.findall(".//item"):
                title    = item.findtext("title", "").strip()
                pub_date = item.findtext("pubDate", "").strip()

                # Skip empty or junk titles
                if not title or title.lower() in ("rss", "feed"):
                    continue

                formatted    = f"- {title} ({source['name']})"
                date_matched = False

                if pub_date:
                    try:
                        # pubDate format: "Tue, 24 Jun 2026 10:00:00 GMT"
                        parsed_date   = datetime.strptime(
                            pub_date[:16].strip(), "%a, %d %b %Y"
                        )
                        item_date_str = parsed_date.strftime("%Y-%m-%d")
                        date_matched  = (item_date_str == today_str)

                        if not date_matched:
                            logging.info(
                                f"Skipping old headline ({item_date_str}): {title[:60]}"
                            )
                    except ValueError:
                        # Date parse failed — include it rather than discard
                        date_matched = True

                else:
                    # No pubDate available — include it rather than discard
                    date_matched = True

                if date_matched and len(headlines) < limit:
                    headlines.append(formatted)
                elif len(fallback) < limit:
                    fallback.append(formatted)

        except Exception as e:
            logging.warning(f"RSS fetch failed for {source['name']}: {e}")
            continue

    # Return today's headlines if found, otherwise fall back to most recent
    result = headlines if headlines else fallback
    logging.info(
        f"fetch_real_headlines: {len(result)} items returned "
        f"({'today' if headlines else 'fallback'})"
    )
    return result

# ── Helper: Detect News/Headlines Intent ──────────────────
def is_news_question(question: str) -> bool:
    """Returns True if the user is asking for news or headlines."""
    keywords = [
        "news", "headline", "headlines", "today's news",
        "latest news", "what happened", "current events",
        "top stories", "breaking", "update", "updates",
        "what's happening", "whats happening",
    ]
    q_lower = question.lower()
    return any(kw in q_lower for kw in keywords)

# ── Helper: Strip <think> blocks from API response ────────
def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"^.*?</think>",       "", text, flags=re.DOTALL)
    return text.strip()

# ── Helper: Strip echoed system prompt ────────────────────
def strip_system_echo(text: str, prompt: str) -> str:
    if text.startswith(prompt):
        text = text[len(prompt):]
    text = re.sub(r"^.*?User question:.*?\n", "", text, flags=re.DOTALL)
    return text.strip()

# ── Helper: Detect platform-level system prompt echo ──────
SYSTEM_ECHO_MARKERS = [
    "Memory Usage Policy",
    "INTENT DETECTION",
    "Greeting Personalization Rule",
    "Memory Commitment Rule",
    "Follow-Up Resolution Rule",
    "### System Role",
    "You are **Alpie**",
    "Response Rules",
    "Formatting Rules",
]

def is_system_echo(text: str) -> bool:
    return any(marker in text for marker in SYSTEM_ECHO_MARKERS)

# ── Helper: Split long messages for Telegram's 4096 limit ─
def split_message(text: str, limit: int = 4000) -> list:
    parts   = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit:
            if current:
                parts.append(current.strip())
            current = line
        else:
            current += line
    if current.strip():
        parts.append(current.strip())
    return parts

# ── Scheduled Messages ────────────────────────────────────
def send_morning(bot):
    import asyncio
    message = (
        "Good morning, everyone!\n\n"
        "I'm compie, your AI companion in this group, powered by Alpie by 169Pi.\n\n"
        "Here's a quick reminder of what I can do for you right here in this group:\n\n"
        "- /ask [your question] — Ask me anything\n"
        "- /about — Learn what Alpie and 169Pi are all about\n"
        "- /tip — Get a quick AI or prompt engineering tip\n"
        "- /quiz — Test your AI knowledge\n\n"
        "What is Alpie?\n"
        "Alpie is an AI assistant built by 169Pi. It is designed to be conversational, "
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
        "and give you answers that are actually useful — whether you are curious about AI, exploring what "
        "169Pi offers, or trying to build something new.\n\n"
        "The best way to understand what Alpie can do is simply to try it.\n\n"
        "Type /ask followed by any question, right here in this group, and see for yourself.\n\n"
        "See you tomorrow morning."
    )
    asyncio.run(bot.send_message(chat_id=GROUP_ID, text=message))

# ── Command Handlers ──────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update, context):
        return
    await update.message.reply_text(
        "Hey! I'm compie, an AI companion built by a community member to bring Alpie's intelligence right into this group.\n\n"
        "Alpie is the AI behind compie, developed by 169Pi. I'm an independent project, "
        "not an official 169Pi product, but I'm powered by Alpie-Core API.\n\n"
        "Here's what I can do:\n"
        "- /ask [question] — Ask me anything\n"
        "- /about — Learn about Alpie and 169Pi\n"
        "- /tip — Get a prompt engineering tip\n"
        "- /quiz — Test your AI knowledge\n\n"
        "Try it now. Type /ask followed by any question."
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update, context):
        return
    await update.message.reply_text(
        "Alpie is an AI assistant built by 169Pi.\n\n"
        "It is designed to be conversational, knowledgeable, and helpful across a wide range of topics "
        "including science, technology, business, education, health, and more.\n\n"
        "169Pi built Alpie and provides API access so developers and communities can "
        "integrate Alpie's intelligence into their own platforms and projects.\n\n"
        "This group exists to explore, learn, and make the most of what Alpie and 169Pi have to offer.\n\n"
        "Want to try Alpie right now? Type /ask followed by your question."
    )

async def tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update, context):
        return
    current_tip = TIPS[tip_index[0] % len(TIPS)]
    tip_index[0] += 1
    await update.message.reply_text(f"Tip of the moment:\n\n{current_tip}")

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update, context):
        return
    q = QUIZ_BANK[quiz_index[0] % len(QUIZ_BANK)]
    quiz_index[0] += 1
    pending_quiz[update.effective_user.id] = q["answer"]
    options_text = "\n".join(q["options"])
    await update.message.reply_text(
        f"AI Quiz Time!\n\n{q['question']}\n\n{options_text}\n\n"
        f"Reply with A, B, C, or D.\n"
        f"Type /answer [your choice] when ready."
    )

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update, context):
        return
    user_id = update.effective_user.id
    if user_id not in pending_quiz:
        await update.message.reply_text(
            "No active quiz found. Type /quiz to start one."
        )
        return
    if not context.args:
        await update.message.reply_text(
            "Please type /answer followed by A, B, C, or D."
        )
        return
    user_answer = context.args[0].upper()
    correct     = pending_quiz.pop(user_id)
    q_data      = next((q for q in QUIZ_BANK if q["answer"] == correct), None)
    if user_answer == correct:
        await update.message.reply_text(
            f"Correct! Well done.\n\n{q_data['explanation'] if q_data else ''}"
        )
    else:
        await update.message.reply_text(
            f"Not quite. The correct answer is {correct}.\n\n"
            f"{q_data['explanation'] if q_data else ''}"
        )

# ── Main Command: /ask ────────────────────────────────────
async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update, context):
        return

    user_id     = update.effective_user.id
    today_str   = datetime.utcnow().strftime("%Y-%m-%d")
    today_human = datetime.utcnow().strftime("%B %d, %Y")

    # ── Rate limit: 3 questions per user per day ──────────
    if user_id in ask_usage:
        if ask_usage[user_id]["date"] == today_str:
            if ask_usage[user_id]["count"] >= 3:
                await update.message.reply_text(
                    "You have reached today's limit of 3 questions. "
                    "Come back tomorrow and ask away again.\n\n"
                    "In the meantime, try /tip or /quiz — both are unlimited."
                )
                return
        else:
            # New day — reset counter
            ask_usage[user_id] = {"date": today_str, "count": 0}
    else:
        ask_usage[user_id] = {"date": today_str, "count": 0}

    if not context.args:
        await update.message.reply_text(
            "Please type /ask followed by your question."
        )
        return

    question = " ".join(context.args)
    await update.message.reply_text("Let me check on that...")

    # ════════════════════════════════════════════════════════
    # NEWS PATH
    # Triggered when user asks for news or headlines.
    # Strategy:
    #   1. Fetch real headlines from RSS feeds (date-validated)
    #   2. Pass verified headlines to Alpie for formatting only
    #   3. search=False so Alpie cannot override facts with hallucinations
    #   4. If Alpie fails or echoes, send raw headlines directly
    # This eliminates political hallucinations completely because
    # Alpie never generates the facts — it only formats them.
    # ════════════════════════════════════════════════════════
    if is_news_question(question):
        headlines = fetch_real_headlines(limit=5)

        if not headlines:
            await update.message.reply_text(
                "I wasn't able to fetch live headlines right now. "
                "Please try again in a moment."
            )
            return

        headlines_text = "\n".join(headlines)

        # Ask Alpie to format the real headlines — not to generate them
        try:
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            }

            formatting_prompt = (
                f"You are compie, a Telegram group AI companion. "
                f"Today is {today_human}. "
                f"Below are real, verified news headlines fetched live from trusted sources right now. "
                f"Present them clearly and conversationally for a group chat. "
                f"Do NOT add, remove, change, invent, or assume any information beyond what is given. "
                f"Do not add context, background, or commentary about any headline. "
                f"Only format and present exactly what is listed below.\n\n"
                f"Headlines:\n{headlines_text}"
            )

            payload = {
                "model":      "alpie-32b",
                "search":     False,        # OFF — facts already provided, no hallucination allowed
                "max_tokens": 1024,
                "messages": [
                    {
                        "role":    "user",
                        "content": formatting_prompt
                    }
                ]
            }

            response = requests.post(
                API_URL,
                json=payload,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()

            data  = response.json()
            reply = data["choices"][0]["message"]["content"]
            reply = strip_thinking(reply)

            # If Alpie echoes system prompt instead of formatting, fall back to raw
            if is_system_echo(reply):
                logging.warning("System echo on news response — using raw headlines.")
                reply = (
                    f"Here are the latest headlines ({today_human}):\n\n"
                    f"{headlines_text}"
                )

        except Exception as e:
            # If Alpie call fails for any reason, send raw headlines — user still gets real data
            logging.error(f"Alpie formatting failed for news: {e} — sending raw headlines.")
            reply = (
                f"Here are the latest headlines ({today_human}):\n\n"
                f"{headlines_text}"
            )

        ask_usage[user_id]["count"] += 1
        chunks = split_message(reply)
        for chunk in chunks:
            await update.message.reply_text(chunk)
        return

    # ════════════════════════════════════════════════════════
    # GENERAL PATH
    # All non-news questions go here.
    # search=True allows Alpie to retrieve live data (weather,
    # sports, prices, general knowledge, etc.)
    # ════════════════════════════════════════════════════════
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }

        dated_system_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"Today's date is {today_human}. "
            f"When searching for sports scores, weather, prices, "
            f"or any current events, always retrieve results specifically "
            f"dated {today_human}. "
            f"Never return information from previous days. "
            f"If search results do not clearly match today's date, "
            f"explicitly state that and provide the most recent available.\n\n"
            f"CRITICAL: Never fabricate, invent, or assume facts. "
            f"Every score, result, statistic, or named event you report "
            f"MUST come directly from your web search results. "
            f"If you cannot find verified information for a specific item, "
            f"say so clearly instead of generating a plausible-sounding answer. "
            f"Do not fill gaps with assumed or historically expected outcomes."
        )

        payload = {
            "model":      "alpie-32b",
            "search":     True,
            "max_tokens": 2048,
            "messages": [
                {
                    "role":    "user",
                    "content": (
                        f"{dated_system_prompt}\n\n"
                        f"User question: {question}"
                    )
                }
            ]
        }

        response = requests.post(
            API_URL,
            json=payload,
            headers=headers,
            timeout=60
        )
        response.raise_for_status()

        data  = response.json()
        reply = data["choices"][0]["message"]["content"]

        reply = strip_thinking(reply)
        reply = strip_system_echo(reply, dated_system_prompt)

        # Catch platform-level system prompt echo
        if is_system_echo(reply):
            logging.warning("System prompt echo detected — suppressing response.")
            reply = (
                "I ran into an issue retrieving that answer. "
                "Please try again in a moment."
            )

        ask_usage[user_id]["count"] += 1

        chunks = split_message(reply)
        for chunk in chunks:
            await update.message.reply_text(chunk)

    except requests.exceptions.Timeout:
        logging.error("Request timed out.")
        await update.message.reply_text(
            "The request timed out. Please try again in a moment."
        )
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error: {e}")
        await update.message.reply_text(
            "There was a problem reaching the AI service. Please try again shortly."
        )
    except Exception as e:
        logging.error(f"Unexpected error in /ask: {e}")
        await update.message.reply_text(
            "Something went wrong while fetching the answer. Please try again in a moment."
        )

# ── Entry Point ───────────────────────────────────────────
def main():
    # Start Flask keep-alive in background thread
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
        "cron", hour=4, minute=0
    )
    scheduler.add_job(
        lambda: send_evening(app.bot),
        "cron", hour=16, minute=0
    )
    scheduler.start()

    logging.info("compie is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
