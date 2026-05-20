from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import requests
import base64
import os

app = FastAPI()

SYSTEM_PROMPT = """You are Raithubadi AI — a crop disease expert for Indian farmers.
Always reply in Telugu first, then English below.
Be warm, respectful. Speak like a knowledgeable village elder.
Never use technical jargon. Always mention cost saved vs blanket spraying.

Format every reply exactly like this:
🌾 వ్యాధి: [disease name in Telugu]
⚠️ తీవ్రత: [తక్కువ/మధ్యమ/అధికం]
💊 చికిత్స: [treatment in Telugu]
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

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    form_data = await request.form()
    
    body = form_data.get("Body", "")
    num_media = form_data.get("NumMedia", "0")
    media_url = form_data.get("MediaUrl0", "")

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    try:
        if int(num_media) > 0 and media_url:
            account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
            auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
            
            img_response = requests.get(
                media_url, 
                auth=(account_sid, auth_token)
            )
            image_data = base64.b64encode(
                img_response.content
            ).decode("utf-8")
            content_type = img_response.headers.get(
                "Content-Type", "image/jpeg"
            )

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
                            "text": "ఈ పంట ఫోటో చూసి వ్యాధిని గుర్తించండి."
                        }
                    ]
                }]
            )
            reply = result.content[0].text

        elif body.strip():
            result = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"రైతు చెప్పింది: {body}"
                }]
            )
            reply = result.content[0].text

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
    
    return PlainTextResponse(
        str(twiml), 
        media_type="application/xml"
    )

@app.get("/")
def root():
    return {
        "status": "రైతుబాడి నడుస్తోంది", 
        "message": "Raithubadi is running 🌾"
    }
