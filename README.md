# Portcullis

Telegram bot that gates a public group behind membership in a private one.

## Env
- `BOT_TOKEN` — from @BotFather
- `PRIVATE_CHAT_ID` — target private group id (e.g. `-100...`)
- `GATED_CHAT_IDS` — comma-separated public chat ids the bot watches

## Deploy
Koyeb or Railway, connect repo, set env, run `python bot.py`.

## Commands
- `/start` — check your gate status + get invite link
- `/status` — re-check
- `/gate` (admin) — enable gating in this chat
- `/ungate` (admin) — disable
