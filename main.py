from fastapi import FastAPI, Form, Request
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import requests
import base64
import os

app = FastAPI()
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """మీరు రైతుబాడి AI — భారతీయ రైతులకు సహాయం చేసే నిపుణుడు.
You are Raitubadi AI, a crop disease expert for Indian farmers.
Always reply in Telugu first, then English below.
Be warm, respectful. Speak like a knowledgeable village elder.
Never use technical jargon. Always mention cost saved vs blanket spraying.

Format every reply exactly like this:
🌾 వ్యాధి: [disease name in Telugu]
⚠️ తీవ్రత: [తక్కువ/మధ్యమ/అధికం]
💊 చికిత్స: [treatment in Telugu — organic first]
💰 మోతాదు: [exact dose per acre]
💵 ఖర్చు ఆదా: ₹[amount saved vs blanket spray]
📅 తిరిగి చూడండి: [days to recheck]

---
🌾 Disease: [English name]
⚠️ Severity: [Low/Medium/High]
💊 Treatment: [English treatment]
💰 Dose: [dose per acre]
💵 Cost saved: ₹[amount]
📅 Recheck in: [days]"""

def analyze_image(image_url: str, account_sid: str, auth_token: str) -> str:
    response = requests.get(image_url, auth=(account_sid, auth_token))
    image_data = base64.b64encode(response.content).decode("utf-8")
    content_type = response.headers.get("Content-Type", "image/jpeg")

    result = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": "ఈ పంట ఫోటో చూసి వ్యాధిని గుర్తించండి. Analyze this crop photo and identify the disease."
                }
            ]
        }]
    )
    return result.content[0].text

def analyze_text(message: str) -> str:
    result = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"రైతు చెప్పింది: {message}\nFarmer says: {message}\nAdvise them on crop disease and treatment."
        }]
    )
    return result.content[0].text

@app.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(default=""),
    NumMedia: str = Form(default="0"),
    MediaUrl0: str = Form(default=""),
    MediaContentType0: str = Form(default="")
):
    response = MessagingResponse()
    msg = response.message()

    try:
        if NumMedia and int(NumMedia) > 0 and MediaUrl0:
            account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
            auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
            reply = analyze_image(MediaUrl0, account_sid, auth_token)
        elif Body.strip():
            reply = analyze_text(Body.strip())
        else:
            reply = "నమస్కారం! 🌾 రైతుబాడికి స్వాగతం.\nHello! Welcome to Raitubadi.\n\nమీ పంట ఫోటో పంపండి లేదా వ్యాధి గురించి రాయండి.\nSend a photo of your crop or describe the disease."

        msg.body(reply)

    except Exception as e:
        msg.body("క్షమించండి, తర్వాత మళ్ళీ ప్రయత్నించండి. Sorry, please try again.")

    return response.to_xml()

@app.get("/")
def root():
    return {"status": "రైతుబాడి నడుస్తోంది", "message": "Raitubadi is running 🌾"}
