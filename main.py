from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
import google.generativeai as genai
import requests
import os

app = FastAPI()

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

PROMPT = """మీరు రైతుబాడి AI — భారతీయ రైతులకు సహాయం చేసే నిపుణుడు.
You are Raithubadi AI, a crop disease expert for Indian farmers.

Rules:
- Always reply in Telugu first, then English
- Speak like a warm, knowledgeable village elder
- Never use technical jargon
- Always mention exact dose per acre
- Always mention money saved vs blanket spraying
- Organic treatment first, chemical only if necessary

Format every reply exactly like this:

🌾 వ్యాధి: [disease name in Telugu]
⚠️ తీవ్రత: [తక్కువ / మధ్యమ / అధికం]
💊 చికిత్స: [treatment in Telugu — organic first]
💰 మోతాదు: [exact dose per acre in Telugu]
💵 ఖర్చు ఆదా: ₹[amount saved vs blanket spray]
📅 తిరిగి చూడండి: [days]

---
🌾 Disease: [English]
⚠️ Severity: [Low/Medium/High]
💊 Treatment: [English]
💰 Dose: [per acre]
💵 Cost saved: ₹[amount]
📅 Recheck in: [days]"""

def analyze_image(image_url):
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    
    img = requests.get(image_url, auth=(account_sid, auth_token))
    
    import PIL.Image
    import io
    image = PIL.Image.open(io.BytesIO(img.content))
    
    response = model.generate_content([PROMPT, image])
    return response.text

def analyze_text(message):
    full_prompt = f"{PROMPT}\n\nరైతు చెప్పింది: {message}"
    response = model.generate_content(full_prompt)
    return response.text

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    form_data = await request.form()
    
    body = form_data.get("Body", "")
    num_media = form_data.get("NumMedia", "0")
    media_url = form_data.get("MediaUrl0", "")

    try:
        if int(num_media) > 0 and media_url:
            reply = analyze_image(media_url)
        elif body.strip():
            reply = analyze_text(body.strip())
        else:
            reply = (
                "నమస్కారం! 🌾 రైతుబాడికి స్వాగతం.\n"
                "మీ పంట ఫోటో పంపండి లేదా వ్యాధి గురించి రాయండి.\n\n"
                "Hello! Welcome to Raithubadi.\n"
                "Send a crop photo or describe the disease."
            )

    except Exception as e:
        reply = f"క్షమించండి, తర్వాత మళ్ళీ ప్రయత్నించండి.\nError: {str(e)}"

    twiml = MessagingResponse()
    twiml.message(reply)
    
    return PlainTextResponse(str(twiml), media_type="application/xml")

@app.get("/")
def root():
    return {
        "status": "రైతుబాడి నడుస్తోంది",
        "message": "Raithubadi is running 🌾"
    }
