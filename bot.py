# language: Python 3.11, file: bot.py
# Portcullis — gate group A behind membership in group/channel B.
# deps: pip install "python-telegram-bot>=21.0"
# env: BOT_TOKEN, TARGET_CHAT_ID (group/channel B), GATED_CHAT_IDS (csv, group A ids)

import os
from telegram import (
    Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatMemberUpdated,
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatJoinRequestHandler, ContextTypes, filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
TARGET = int(os.environ["TARGET_CHAT_ID"])
GATED = {int(x) for x in os.environ.get("GATED_CHAT_IDS", "").split(",") if x.strip()}

VERIFIED: set = set()          # user_id cache
MUTED = ChatPermissions.no_permissions()
FREE = ChatPermissions.all_permissions()

# ── membership check ──────────────────────────────────────────────────────
async def is_member(ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if user_id in VERIFIED:
        return True
    try:
        m = await ctx.bot.get_chat_member(TARGET, user_id)
        if m.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.RESTRICTED,   # present but limited (e.g. request approved with restrictions)
        ):
            VERIFIED.add(user_id)
            return True
    except Exception:
        pass
    return False

async def get_invite(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        link = await ctx.bot.create_chat_invite_link(
            TARGET,
            member_limit=1,
            creates_join_request=True,   # works for private AND public with request mode; harmless otherwise
        )
        return link.invite_link
    except Exception:
        try:
            link = await ctx.bot.create_chat_invite_link(TARGET, member_limit=1)
            return link.invite_link
        except Exception:
            return ""

# ── gate message ──────────────────────────────────────────────────────────
def gate_kb(link: str) -> InlineKeyboardMarkup:
    rows = []
    if link:
        rows.append([InlineKeyboardButton("🔗 Join", url=link)])
    rows.append([InlineKeyboardButton("✅ Done — I joined", callback_data="done")])
    return InlineKeyboardMarkup(rows)

async def send_gate(chat_id: int, user, ctx: ContextTypes.DEFAULT_TYPE, delete_msg_id=None):
    if delete_msg_id is not None:
        try:
            await ctx.bot.delete_message(chat_id, delete_msg_id)
        except Exception:
            pass
    link = await get_invite(ctx)
    await ctx.bot.send_message(
        chat_id,
        f"🔒 {user.mention_html()} — join first, then tap ✅ Done.",
        parse_mode=ParseMode.HTML,
        reply_markup=gate_kb(link),
        disable_web_page_preview=True,
    )

# ── handlers ──────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if await is_member(ctx, uid):
        await update.message.reply_text("✅ You're in. Gate open.")
        return
    link = await get_invite(ctx)
    await update.message.reply_text(
        "🔒 Join to unlock.",
        reply_markup=gate_kb(link),
        disable_web_page_preview=True,
    )

async def cmd_gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    m = await ctx.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if m.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return
    GATED.add(update.effective_chat.id)
    await update.message.reply_text("🚪 Gate on.")

async def cmd_ungate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return
    m = await ctx.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if m.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return
    GATED.discard(update.effective_chat.id)
    await update.message.reply_text("🔓 Gate off.")

async def on_new_members(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in GATED:
        return
    for m in update.message.new_chat_members:
        if m.is_bot:
            continue
        if await is_member(ctx, m.id):
            continue
        try:
            await ctx.bot.restrict_chat_member(update.effective_chat.id, m.id, permissions=MUTED)
        except Exception:
            pass
        await send_gate(update.effective_chat.id, m, ctx)

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in GATED:
        return
    if not update.effective_user or update.effective_user.is_bot:
        return
    uid = update.effective_user.id
    if await is_member(ctx, uid):
        return
    try:
        await ctx.bot.restrict_chat_member(update.effective_chat.id, uid, permissions=MUTED)
    except Exception:
        pass
    await send_gate(update.effective_chat.id, update.effective_user, ctx, delete_msg_id=update.message.message_id)

async def on_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    await q.answer("checking…")
    if not await is_member(ctx, uid):
        await q.message.reply_text("❌ Still not a member. Join, then tap Done again.")
        return
    for chat_id in GATED:
        try:
            await ctx.bot.restrict_chat_member(chat_id, uid, permissions=FREE)
        except Exception:
            pass
    await q.message.reply_text(f"✅ {q.from_user.mention_html()} — unlocked.", parse_mode=ParseMode.HTML)

async def on_join_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # approval side belongs to an admin/target bot; Portcullis just caches nothing here.
    # Fires in TARGET so we invalidate nothing; /status on user side re-checks live.
    pass

async def on_my_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # If a user leaves TARGET, drop them from cache so their next message in A re-gates.
    cmu: ChatMemberUpdated = update.my_chat_member or update.chat_member
    if cmu and cmu.chat.id == TARGET:
        new = cmu.new_chat_member
        if new.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            VERIFIED.discard(new.user.id)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("gate", cmd_gate))
    app.add_handler(CommandHandler("ungate", cmd_ungate))
    app.add_handler(CallbackQueryHandler(on_done, pattern="^done$"))
    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))
    app.add_handler(MessageHandler(filters.ChatMemberUpdatedFilter.ANY_CHAT_MEMBER, on_my_chat_member))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.ALL, on_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
