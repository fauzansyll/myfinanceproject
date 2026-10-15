import os
import json
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO)

# 1. Environment Setup
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GCP_CREDS_JSON = os.environ.get("GCP_CREDS_JSON")  # Store full JSON string in ENV

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

# Configure Google Sheets
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds_dict = json.loads(GCP_CREDS_JSON)
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID).sheet1

# 2. Define Gemini Tool Schema
add_expense_tool = {
    "name": "add_expense",
    "description": "Extract expense info from user message and provide a brief feedback insight.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "amount": {"type": "NUMBER", "description": "Numeric expense amount"},
            "category": {"type": "STRING", "description": "e.g., Food, Transport, Coffee, Gaming, Repairs, Bills"},
            "description": {"type": "STRING", "description": "Short summary of item/place"},
            "payment_method": {"type": "STRING", "description": "e.g., GoPay, QRIS, Cash, Card"},
            "brief_insight": {"type": "STRING", "description": "A brief 1-sentence reaction or spend advice (under 20 words)."}
        },
        "required": ["amount", "category", "description", "payment_method", "brief_insight"]
    }
}

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    tools=[add_expense_tool]
)

# 3. Message Processing Logic
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # Fast extraction via Gemini Tool Call
    prompt = f"Parse this expense and provide insight: {user_text}"
    response = model.generate_content(
        prompt,
        generation_config={"max_output_tokens": 150}
    )
    
    try:
        tool_call = response.candidates[0].content.parts[0].function_call
        if tool_call.name == "add_expense":
            args = tool_call.args
            
            # Format row data
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            
            amount = float(args["amount"])
            category = str(args["category"])
            desc = str(args["description"])
            payment = str(args["payment_method"])
            insight = str(args["brief_insight"])
            
            # Append row to Google Sheet
            new_row = [today, category, desc, amount, payment]
            sheet.append_row(new_row)
            
            # Formulate response back to Telegram
            reply_msg = (
                f"✅ **Recorded!**\n"
                f"• **Item:** {desc}\n"
                f"• **Amount:** {amount:,.0f}\n"
                f"• **Category:** {category}\n"
                f"• **Paid via:** {payment}\n\n"
                f"💡 *Insight:* {insight}"
            )
            await update.message.reply_text(reply_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error processing: {e}")
        await update.message.reply_text("Could not parse that clearly. Try: 'Spent 45k on lunch using GoPay'")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me any expense like 'Spent 20k on coffee with QRIS' and I'll update your sheet!")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()