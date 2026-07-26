import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚾ MLB Live Bets\n\n"
        "Bot iniciado correctamente.\n\n"
        "Próximamente:\n"
        "• Seguimiento de apuestas\n"
        "• MLB en vivo\n"
        "• OCR de Stake\n"
        "• Análisis con IA"
    )

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos disponibles:\n"
        "/start\n"
        "/help"
    )

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))

    print("MLB Live Bets iniciado...")

    app.run_polling()

if __name__ == "__main__":
    main()
