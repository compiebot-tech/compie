import os
import re
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

# ── System Prompt ─────────────────────────────────────────
# This tells Alpie to behave as a live, real-time assistant
# and unlocks web search for time-sensitive queries like weather

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
    "If an answer feels too short or surface level, just follow up with 'can you go deeper on that?' or 'give me an example.'
