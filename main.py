"""
RAITHUBADI — God-Tier Backend
Features: F0 F1 F2 F3 F4 F5 F6 F7 F9
Language lock: 3-layer enforcement on every Gemini call.
Hybrid cache: memory (fast) + Supabase (persistent).
"""

import base64, json, io, os, requests
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as Twilio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google import genai
from google.genai import types

# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Raithubadi API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

G   = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or "DUMMY_KEY")
SB  = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
       "Content-Type": "application/json", "Prefer": "return=representation"}

# ── Hybrid Language Cache (memory = O(1), Supabase = persistent) ──────────────
# Format: number → "en" | "te" | "hi" | "pending"
_cache: dict[str, str] = {}

# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _get(table: str, params: dict) -> list:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{SB}/rest/v1/{table}", headers=HDR, params=params)
        d = r.json()
        return d if isinstance(d, list) else []
    except Exception:
        return []

async def _post(table: str, data: dict, prefer: str = "return=representation") -> list:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(f"{SB}/rest/v1/{table}",
                             headers={**HDR, "Prefer": prefer}, json=data)
        d = r.json()
        return d if isinstance(d, list) else []
    except Exception:
        return []

async def _patch(table: str, match: dict, data: dict) -> None:
    try:
        p = {k: f"eq.{v}" for k, v in match.items()}
        async with httpx.AsyncClient(timeout=5) as c:
            await c.patch(f"{SB}/rest/v1/{table}", headers=HDR, params=p, json=data)
    except Exception:
        pass

# F3: Farmer identity ──────────────────────────────────────────────────────────

async def farmer_lang(number: str) -> str | None:
    """Returns lang code, 'pending', or None (new farmer). Uses cache first."""
    if number in _cache:
        return _cache[number]
    rows = await _get("farmers", {"whatsapp_number": f"eq.{number}",
                                  "select": "preferred_lang,lang_confirmed"})
    if not rows:
        return None
    val = "pending" if not rows[0]["lang_confirmed"] else rows[0]["preferred_lang"]
    _cache[number] = val
    return val

async def set_farmer_lang(number: str, lang: str, confirmed: bool) -> None:
    """Write-through: update cache + DB atomically."""
    _cache[number] = lang if confirmed else "pending"
    await _post("farmers", {
        "whatsapp_number": number,
        "preferred_lang":  lang,
        "lang_confirmed":  confirmed,
        "last_active":     datetime.now(timezone.utc).isoformat(),
    }, prefer="resolution=merge-duplicates")

# F4: Scan history ─────────────────────────────────────────────────────────────

async def get_history(number: str) -> list:
    return await _get("scans", {
        "whatsapp_number": f"eq.{number}",
        "select": "disease,severity,created_at",
        "order": "created_at.desc",
        "limit": "5",
    })

async def save_scan(number: str, lang: str, text: str, disease: str,
                    severity: str, treatment: str, dose: str,
                    cost: int, channel: str, district: str = "") -> str:
    rows = await _post("scans", {
        "whatsapp_number": number, "lang": lang, "input_text": text,
        "disease": disease, "severity": severity, "treatment": treatment,
        "dose": dose, "cost_saved_inr": cost, "channel": channel,
        "district": district, "feedback_sent": False,
    })
    return rows[0].get("id", "") if rows else ""

def fmt_history(scans: list) -> str:
    if not scans:
        return "First scan — no history yet."
    lines = []
    for s in scans:
        try:
            dt  = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
            ago = (datetime.now(timezone.utc) - dt).days
            when = f"{ago}d ago" if ago > 1 else "today"
        except Exception:
            when = "recently"
        lines.append(f"- {when}: {s['disease']} ({s['severity']})")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# ███  LANGUAGE SYSTEM  ███████████████████████████████████████████████████████
# F0: Selection  F1: Lock  F2: Switch
# ─────────────────────────────────────────────────────────────────────────────

# Layer 1 — injected at START of every Gemini prompt
LOCK = {
    "en": ("ABSOLUTE REQUIREMENT: Write your ENTIRE response in English only. "
           "Every word must be English. Zero Telugu or Hindi characters. "
           "Even if the farmer wrote in Telugu or Hindi — reply in English. Non-negotiable."),
    "te": ("అత్యంత కట్టుబాటు: మీరు మొత్తం సమాధానం తెలుగులో మాత్రమే రాయాలి. "
           "ప్రతి పదం తెలుగులో ఉండాలి. ఇంగ్లీష్ లేదా హిందీ ఒక్క అక్షరం కూడా వద్దు. "
           "రైతు ఇంగ్లీష్లో రాసినా — సమాధానం తెలుగులోనే. ఇది అనివార్యం."),
    "hi": ("पूर्ण आवश्यकता: अपना पूरा जवाब केवल हिंदी में लिखें। "
           "हर शब्द हिंदी में हो। तेलुगु या अंग्रेज़ी का एक अक्षर भी नहीं। "
           "किसान ने तेलुगु या अंग्रेज़ी में लिखा हो — जवाब फिर भी हिंदी में। अनिवार्य।"),
}

ELDER = {
    "en": "Speak like a warm, wise agricultural officer from rural India who genuinely cares.",
    "te": "ఆప్యాయంగా పట్టించుకునే గ్రామ పెద్ద వ్యవసాయ నిపుణుడి లాగా మాట్లాడండి.",
    "hi": "एक ऐसे जानकार गाँव के बुज़ुर्ग की तरह बोलें जो सच में परवाह करता है।",
}

ERR = {
    "en": "Sorry, something went wrong. Please try again 🙏",
    "te": "క్షమించండి, తర్వాత మళ్ళీ ప్రయత్నించండి 🙏",
    "hi": "माफ़ करें, कृपया दोबारा कोशिश करें 🙏",
}

# Layer 2 — script validator
def wrong_lang(text: str, lang: str) -> bool:
    te = any('\u0C00' <= c <= '\u0C7F' for c in text)
    hi = any('\u0900' <= c <= '\u097F' for c in text)
    if lang == "en" and (te or hi): return True
    if lang == "te" and hi:         return True
    if lang == "hi" and te:         return True
    return False

# Layer 3 — retry with amplified lock
async def gemini(prompt: str, lang: str,
                 audio: bytes = None, img: bytes = None,
                 mime: str = "image/jpeg") -> str:
    parts = []
    if img:
        parts.append(types.Part.from_bytes(data=img, mime_type=mime))
    if audio:
        parts.append(types.Part.from_bytes(data=audio, mime_type=mime))
    parts.append(types.Part.from_text(text=prompt))

    r = G.models.generate_content(model="gemini-2.5-flash",
                                   contents=parts if len(parts) > 1 else prompt)
    text = r.text.strip()

    if wrong_lang(text, lang):          # Layer 3: retry once
        strong = f"{LOCK[lang]}\nREPEAT: Answer in {lang} ONLY.\n\n{prompt}"
        parts2 = []
        if img:
            parts2.append(types.Part.from_bytes(data=img, mime_type=mime))
        if audio:
            parts2.append(types.Part.from_bytes(data=audio, mime_type=mime))
        parts2.append(types.Part.from_text(text=strong))
        r2 = G.models.generate_content(model="gemini-2.5-flash",
                                        contents=parts2 if len(parts2) > 1 else strong)
        text = r2.text.strip()

    return text

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def wa_prompt(lang: str, problem: str, history: str) -> str:
    return f"""{LOCK[lang]}
{ELDER[lang]}

You are Raithubadi AI — India's most trusted crop disease expert for farmers.

FARMER'S HISTORY:
{history}

INSTRUCTIONS:
- Every single word in {lang} only.
- If SAME disease appears in history → open with urgent warning.
- Organic / natural remedy FIRST. Chemical only if truly needed.
- Give exact dose per acre in simple terms.
- State rupees saved vs spraying entire field blindly.
- No scientific jargon. Speak as if talking to your own family farmer.
- Maximum 280 characters. End with one warm, encouraging line.

Farmer says: {problem}

Plain text reply only. No JSON, no bullet symbols, no markdown."""


def web_prompt(lang: str, problem: str, history: str) -> str:
    return f"""{LOCK[lang]}
{ELDER[lang]}

You are Raithubadi AI — India's most trusted crop disease expert for farmers.

FARMER'S HISTORY:
{history}

INSTRUCTIONS:
- Every single word in {lang} only — no exceptions.
- If SAME disease in history → warn urgently in speak_text.
- Organic / natural remedy FIRST. Chemical only if needed.
- Exact dose per acre. Calculate rupees saved vs blanket spraying.
- Speak like a caring village elder, not a textbook.

Farmer's problem: {problem}

Respond ONLY with valid JSON (no markdown, nothing outside braces):
{{
  "disease":        "<disease name in {lang}>",
  "severity":       "<low|medium|high>",
  "cause":          "<simple root cause in {lang}>",
  "treatment":      "<organic treatment first, chemical if needed — in {lang}>",
  "dose":           "<exact dose per acre in {lang}>",
  "recheck_days":   <integer days>,
  "cost_saved_inr": <integer rupees saved>,
  "speak_text":     "<warm, spoken 4-6 sentence diagnosis in {lang}, village elder tone>"
}}"""


def extract_prompt(reply: str) -> str:
    return f"""From this crop diagnosis reply extract fields.
Return ONLY valid JSON, values in English:
{{"disease":"<name>","severity":"<low|medium|high>","treatment":"<1 line>","dose":"<dose>","cost_saved_inr":<int>}}
Reply: {reply}"""

# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP STATIC STRINGS
# ─────────────────────────────────────────────────────────────────────────────

WELCOME = """\
🌾 *Welcome to Raithubadi!*
రైతుబాడికి స్వాగతం!
रैतुबाड़ी में आपका स्वागत है!

Please choose your language:
మీ భాష ఎంచుకోండి:
अपनी भाषा चुनें:

1️⃣  English
2️⃣  తెలుగు
3️⃣  हिंदी

Reply with *1*, *2*, or *3*"""

LANG_OK = {
    "en": "✅ *English selected.*\n\nSend a photo of your crop or describe the problem. I'll diagnose it in 10 seconds! 🌾",
    "te": "✅ *తెలుగు ఎంచుకున్నారు.*\n\nమీ పంట ఫోటో పంపండి లేదా సమస్య వివరించండి. 10 సెకన్లలో నిర్ధారణ! 🌾",
    "hi": "✅ *हिंदी चुनी।*\n\nफसल की फोटो भेजें या समस्या बताएं। 10 सेकंड में निदान! 🌾",
}

LANG_SWITCHED = {
    "en": "✅ Switched to *English*. All replies now in English. Send your crop problem anytime 🌾",
    "te": "✅ *తెలుగు*కు మారింది. ఇకపై అన్ని జవాబులు తెలుగులో. మీ పంట సమస్య ఎప్పుడైనా పంపండి 🌾",
    "hi": "✅ *हिंदी* में बदल दिया। अब सभी जवाब हिंदी में। कभी भी फसल की समस्या भेजें 🌾",
}

INVALID = "⚠️ Reply *1*, *2*, or *3* only.\n1, 2, లేదా 3 మాత్రమే.\nकेवल 1, 2, या 3।"

REMINDER = {
    "en": "Send a crop photo or describe the problem 🌾",
    "te": "పంట ఫోటో పంపండి లేదా సమస్య వివరించండి 🌾",
    "hi": "फसल फोटो भेजें या समस्या बताएं 🌾",
}

# Selection map — F0
SEL = {
    "1":"en","english":"en",
    "2":"te","telugu":"te","తెలుగు":"te",
    "3":"hi","hindi":"hi","हिंदी":"hi",
}
# Switch map — F2
SWI = {
    "language: english":"en","switch to english":"en","change to english":"en","language english":"en",
    "language: telugu":"te","switch to telugu":"te","change to telugu":"te","language telugu":"te",
    "భాష: తెలుగు":"te","భాష తెలుగు":"te","తెలుగులో మాట్లాడు":"te",
    "language: hindi":"hi","switch to hindi":"hi","change to hindi":"hi","language hindi":"hi",
    "भाषा: हिंदी":"hi","भाषा हिंदी":"hi","हिंदी में बात करो":"hi",
}

def pick_sel(t: str) -> str | None: return SEL.get(t.strip().lower())
def pick_swi(t: str) -> str | None: return SWI.get(t.strip().lower())

# ─────────────────────────────────────────────────────────────────────────────
# F5 — 7-DAY FEEDBACK LOOP
# ─────────────────────────────────────────────────────────────────────────────

FB_ASK = {
    "en": "🌾 *Raithubadi follow-up*\n\n7 days ago: *{d}*\n\nHow is your crop now?\n1️⃣ Improved ✅\n2️⃣ Same 🔄\n3️⃣ Worse ⚠️\n\nReply 1, 2, or 3",
    "te": "🌾 *రైతుబాడి అనుసరణ*\n\n7 రోజుల క్రితం: *{d}*\n\nఇప్పుడు పంట ఎలా ఉంది?\n1️⃣ మెరుగుపడింది ✅\n2️⃣ అదే విధంగా 🔄\n3️⃣ మరింత దిగజారింది ⚠️\n\n1, 2, లేదా 3 జవాబివ్వండి",
    "hi": "🌾 *रैतुबाड़ी फॉलो-अप*\n\n7 दिन पहले: *{d}*\n\nअब फसल कैसी है?\n1️⃣ बेहतर ✅\n2️⃣ वैसी ही 🔄\n3️⃣ और खराब ⚠️\n\n1, 2, या 3 जवाब दें",
}

FB_THANKS = {
    "en": {
        "1": "🎉 *Wonderful!* Your crop recovered. Keep monitoring every few days. You're a great farmer 🌾",
        "2": "🌾 *Understood.* Try the recommended treatment one more time. If no change in 3 days, send a fresh photo and I'll give updated advice.",
        "3": "⚠️ *I'm sorry to hear that.* Please send a fresh photo of your crop right now — I'll give you an updated, stronger treatment plan immediately.",
    },
    "te": {
        "1": "🎉 *అద్భుతం!* మీ పంట కోలుకుంది. కొన్ని రోజులకు ఒకసారి చూస్తూ ఉండండి. మీరు గొప్ప రైతు 🌾",
        "2": "🌾 *అర్థమైంది.* సూచించిన చికిత్స మరోసారి ప్రయత్నించండి. 3 రోజులలో మార్పు లేకపోతే కొత్త ఫోటో పంపండి.",
        "3": "⚠️ *చాలా బాధగా ఉంది.* ఇప్పుడే మీ పంట కొత్త ఫోటో పంపండి — నేను వెంటనే మెరుగైన చికిత్స ప్లాన్ ఇస్తాను.",
    },
    "hi": {
        "1": "🎉 *बहुत अच्छा!* आपकी फसल ठीक हो गई। कुछ दिनों में एक बार जाँचते रहें। आप एक अच्छे किसान हैं 🌾",
        "2": "🌾 *समझ गया।* बताया गया उपचार एक बार और आज़माएं। 3 दिन में फर्क न पड़े तो नई फोटो भेजें।",
        "3": "⚠️ *सुनकर दुख हुआ।* अभी अपनी फसल की नई फोटो भेजें — मैं तुरंत बेहतर उपचार योजना दूंगा।",
    },
}

_pending_fb: dict[str, str] = {}   # number → scan_id

async def run_feedback():
    tw  = Twilio(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))
    cut = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    rows = await _get("scans", {
        "feedback_sent": "eq.false",
        "created_at":    f"gte.{cut}T00:00:00Z",
        "select": "id,whatsapp_number,disease,lang",
        "limit": "100",
    })
    for s in rows:
        try:
            lang = s.get("lang", "en")
            body = FB_ASK[lang].format(d=s.get("disease", "the disease"))
            tw.messages.create(
                from_=os.environ.get("TWILIO_WHATSAPP_NUMBER"),
                to=s["whatsapp_number"], body=body)
            await _patch("scans", {"id": s["id"]}, {
                "feedback_sent":    True,
                "feedback_sent_at": datetime.now(timezone.utc).isoformat(),
            })
            _pending_fb[s["whatsapp_number"]] = s["id"]
        except Exception:
            continue

# ─────────────────────────────────────────────────────────────────────────────
# F6 — CROP STAGE REMINDERS
# ─────────────────────────────────────────────────────────────────────────────

REG_OK = {
    "en": "✅ *Crop registered!* I'll send you WhatsApp tips at key growth stages (day 7, 14, 21, 30, 45, 60, 90). You can also send crop photos anytime for diagnosis 🌾",
    "te": "✅ *పంట నమోదు అయింది!* కీలక వ్యవసాయ దశలలో (7, 14, 21, 30, 45, 60, 90 రోజులకు) WhatsApp సలహాలు పంపిస్తాను 🌾",
    "hi": "✅ *फसल दर्ज हुई!* मुख्य विकास चरणों (दिन 7, 14, 21, 30, 45, 60, 90) पर WhatsApp सुझाव भेजूंगा 🌾",
}

MILESTONES = {7, 14, 21, 30, 45, 60, 90}
REG_KEYS   = ("register:", "crop:", "పంట:", "फसल:", "register :")

def is_reg(t: str) -> bool:
    return any(t.lower().startswith(k) for k in REG_KEYS)

async def register_crop_wa(number: str, lang: str, cmd: str):
    p = (f"Extract crop name and planting date from this text. "
         f"JSON only, values in English: "
         f'{{ "crop": "<name>", "planted_date": "<YYYY-MM-DD or null>" }}\n'
         f"Text: {cmd}")
    try:
        r    = G.models.generate_content(model="gemini-2.5-flash", contents=p)
        data = json.loads(r.text.strip().replace("```json","").replace("```",""))
        await _post("crop_registrations", {
            "whatsapp_number": number, "lang": lang,
            "crop":            data.get("crop", "crop"),
            "planted_date":    data.get("planted_date") or datetime.now(timezone.utc).date().isoformat(),
        }, prefer="resolution=merge-duplicates")
    except Exception:
        pass

async def run_reminders():
    tw   = Twilio(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))
    rows = await _get("crop_registrations", {
        "active": "eq.true",
        "select": "whatsapp_number,lang,crop,planted_date",
        "limit":  "500",
    })
    today = datetime.now(timezone.utc).date()
    for r in rows:
        try:
            planted  = datetime.fromisoformat(r["planted_date"]).date()
            days_old = (today - planted).days
            if days_old not in MILESTONES:
                continue
            lang = r.get("lang", "en")
            crop = r.get("crop", "crop")
            p = (f"{LOCK[lang]}\n{ELDER[lang]}\n\n"
                 f"The farmer's {crop} crop is exactly {days_old} days old today.\n"
                 f"Give ONE specific, actionable care tip for this exact growth stage.\n"
                 f"Max 200 characters. Warm, practical, no jargon. 100% in {lang}.")
            tip = await gemini(p, lang)
            pfx = {
                "en": f"🌾 Day {days_old} — {crop}:",
                "te": f"🌾 {days_old}వ రోజు — {crop}:",
                "hi": f"🌾 दिन {days_old} — {crop}:",
            }
            tw.messages.create(
                from_=os.environ.get("TWILIO_WHATSAPP_NUMBER"),
                to=r["whatsapp_number"],
                body=f"{pfx[lang]}\n\n{tip}")
        except Exception:
            continue

# ─────────────────────────────────────────────────────────────────────────────
# F7 — VOICE NOTE (WhatsApp OGG audio → Gemini → diagnosis in farmer's language)
# ─────────────────────────────────────────────────────────────────────────────

async def diagnose_audio(lang: str, audio_bytes: bytes, mime: str, history: str) -> str:
    p = (f"{LOCK[lang]}\n{ELDER[lang]}\n\n"
         f"FARMER HISTORY:\n{history}\n\n"
         f"A farmer just sent you a voice note describing their crop problem.\n"
         f"Listen to the audio, understand the problem described, and give a full crop diagnosis.\n"
         f"If same disease appears in history → warn urgently.\n"
         f"Organic first. Exact dose per acre. Rupees saved.\n"
         f"Max 280 characters. Warm, plain text. 100% in {lang}.")
    return await gemini(p, lang, audio=audio_bytes, mime=mime)

# ─────────────────────────────────────────────────────────────────────────────
# F9 — WAZE FOR CROPS (Outbreak Warning)
# ─────────────────────────────────────────────────────────────────────────────

OUTBREAK_ALERT = {
    "en": ("⚠️ *DISEASE ALERT — {district}*\n\n"
           "*{disease}* is spreading in your area.\n"
           "{count} farmers reported it this week.\n\n"
           "🔍 Check your crop *right now* and send a photo if you see anything unusual."),
    "te": ("⚠️ *వ్యాధి హెచ్చరిక — {district}*\n\n"
           "*{disease}* మీ ప్రాంతంలో వ్యాప్తి చెందుతోంది.\n"
           "ఈ వారం {count} రైతులు నివేదించారు.\n\n"
           "🔍 *ఇప్పుడే* మీ పంట చూడండి — ఏదైనా అసాధారణంగా కనిపిస్తే ఫోటో పంపండి."),
    "hi": ("⚠️ *रोग चेतावनी — {district}*\n\n"
           "*{disease}* आपके क्षेत्र में फैल रहा है।\n"
           "इस हफ्ते {count} किसानों ने रिपोर्ट किया।\n\n"
           "🔍 *अभी* अपनी फसल जाँचें — कुछ असामान्य दिखे तो फोटो भेजें।"),
}

async def update_outbreak(district: str, disease: str):
    if not district or not disease:
        return
    week = datetime.now(timezone.utc).strftime("%Y-W%W")
    rows = await _get("outbreaks", {
        "district": f"eq.{district}", "disease": f"eq.{disease}",
        "week": f"eq.{week}", "select": "id,report_count",
    })
    if rows:
        await _patch("outbreaks", {"id": rows[0]["id"]},
                     {"report_count": rows[0]["report_count"] + 1})
    else:
        await _post("outbreaks", {
            "district": district, "disease": disease,
            "week": week, "report_count": 1, "alerted": False,
        })

async def run_outbreak_check():
    tw   = Twilio(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))
    week = datetime.now(timezone.utc).strftime("%Y-W%W")
    hot  = await _get("outbreaks", {
        "week": f"eq.{week}", "alerted": "eq.false",
        "report_count": "gte.5",
        "select": "id,district,disease,report_count",
    })
    for ob in hot:
        try:
            district = ob["district"]
            disease  = ob["disease"]
            count    = ob["report_count"]
            # Get all unique farmers who scanned from this district
            farmers  = await _get("scans", {
                "district": f"eq.{district}",
                "select": "whatsapp_number",
                "limit": "500",
            })
            seen = set()
            for f in farmers:
                n = f["whatsapp_number"]
                if n in seen:
                    continue
                seen.add(n)
                try:
                    lang = await farmer_lang(n) or "en"
                    if lang in ("pending", None):
                        lang = "en"
                    body = OUTBREAK_ALERT[lang].format(
                        district=district, disease=disease, count=count)
                    tw.messages.create(
                        from_=os.environ.get("TWILIO_WHATSAPP_NUMBER"),
                        to=n, body=body)
                except Exception:
                    continue
            await _patch("outbreaks", {"id": ob["id"]}, {"alerted": True})
        except Exception:
            continue

# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def start():
    s = AsyncIOScheduler()
    s.add_job(run_feedback,       "interval", hours=1,   id="feedback")
    s.add_job(run_reminders,      "cron",     hour=7,    id="reminders")
    s.add_job(run_outbreak_check, "cron",     hour=6,    id="outbreak")
    s.start()

# ─────────────────────────────────────────────────────────────────────────────
# WEB — POST /analyze  (F1 security + F4 memory + F9 outbreak)
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzeReq(BaseModel):
    lang:         str = "en"
    text:         str = ""
    image_b64:    str = ""
    image_mime:   str = "image/jpeg"
    phone_number: str = ""
    district:     str = ""

@app.post("/analyze")
async def analyze(req: AnalyzeReq):
    lang = req.lang if req.lang in ("en", "te", "hi") else "en"
    try:
        history = fmt_history(
            await get_history(req.phone_number) if req.phone_number else []
        )
        prompt = web_prompt(lang, req.text or "See the uploaded image", history)

        img_bytes = base64.b64decode(req.image_b64) if req.image_b64 else None
        raw = await gemini(prompt, lang, img=img_bytes, mime=req.image_mime)

        clean  = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        result["lang"] = lang

        if req.phone_number:
            await save_scan(
                req.phone_number, lang, req.text,
                result.get("disease", "unknown"),
                result.get("severity", "medium"),
                result.get("treatment", ""),
                result.get("dose", ""),
                int(result.get("cost_saved_inr", 0)),
                "web", req.district,
            )
            if req.district:
                await update_outbreak(req.district, result.get("disease", ""))

        return JSONResponse(content=result)

    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"error": ERR.get(lang, ERR["en"])})

# ─────────────────────────────────────────────────────────────────────────────
# WEB — POST /register-crop  (F6 web)
# ─────────────────────────────────────────────────────────────────────────────

class RegReq(BaseModel):
    phone_number: str
    lang:         str = "en"
    crop:         str
    planted_date: str

@app.post("/register-crop")
async def register_crop_web(req: RegReq):
    lang = req.lang if req.lang in ("en", "te", "hi") else "en"
    try:
        fl = await farmer_lang(req.phone_number)
        if fl is None:
            await set_farmer_lang(req.phone_number, lang, True)
        await _post("crop_registrations", {
            "whatsapp_number": req.phone_number, "lang": lang,
            "crop": req.crop, "planted_date": req.planted_date,
        }, prefer="resolution=merge-duplicates")
        ok = {
            "en": f"✅ {req.crop} registered! Weekly growth-stage tips coming to your WhatsApp 🌾",
            "te": f"✅ {req.crop} నమోదు అయింది! వారంవారం WhatsApp సలహాలు వస్తాయి 🌾",
            "hi": f"✅ {req.crop} दर्ज हुई! साप्ताहिक WhatsApp सुझाव आएंगे 🌾",
        }
        return JSONResponse(content={"message": ok[lang]})
    except Exception:
        return JSONResponse(status_code=500, content={"error": ERR[lang]})

# ─────────────────────────────────────────────────────────────────────────────
# WEB — GET /outbreak-alerts  (F9 web display)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/outbreak-alerts")
async def outbreak_alerts():
    week = datetime.now(timezone.utc).strftime("%Y-W%W")
    rows = await _get("outbreaks", {
        "week": f"eq.{week}", "report_count": "gte.3",
        "select": "district,disease,report_count,alerted,created_at",
        "order": "report_count.desc", "limit": "20",
    })
    return JSONResponse(content={"alerts": rows})

# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP WEBHOOK  (F0 F2 F3 F4 F5 F6 F7 F9)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/whatsapp")
async def whatsapp(request: Request):
    form       = await request.form()
    sender     = form.get("From", "")
    body       = form.get("Body", "").strip()
    num_media  = int(form.get("NumMedia", "0"))
    media_url  = form.get("MediaUrl0", "")
    media_type = form.get("MediaContentType0", "image/jpeg")

    twiml = MessagingResponse()
    msg   = twiml.message()

    try:
        lang_state = await farmer_lang(sender)

        # ── F3 + F0: New farmer ───────────────────────────────────────────
        if lang_state is None:
            await set_farmer_lang(sender, "en", False)
            msg.body(WELCOME)
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── F0: Language selection pending ────────────────────────────────
        if lang_state == "pending":
            chosen = pick_sel(body)
            if chosen:
                await set_farmer_lang(sender, chosen, True)
                msg.body(LANG_OK[chosen])
            else:
                msg.body(INVALID)
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # Language confirmed from here — LOCKED
        lang = lang_state

        # ── F2: Language switch ───────────────────────────────────────────
        sw = pick_swi(body)
        if sw:
            await set_farmer_lang(sender, sw, True)
            msg.body(LANG_SWITCHED[sw])
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── F5: Feedback reply ────────────────────────────────────────────
        if sender in _pending_fb and body in ("1", "2", "3"):
            scan_id = _pending_fb.pop(sender)
            outcome = {"1": "improved", "2": "same", "3": "worse"}[body]
            await _patch("scans", {"id": scan_id}, {"feedback_reply": outcome})
            msg.body(FB_THANKS[lang][body])
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── F6: Crop registration ─────────────────────────────────────────
        if is_reg(body):
            await register_crop_wa(sender, lang, body)
            msg.body(REG_OK[lang])
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── F4: Load history before every diagnosis ───────────────────────
        history = fmt_history(await get_history(sender))

        # ── F7: Voice note (OGG audio) ────────────────────────────────────
        if num_media > 0 and "audio" in media_type:
            sid = os.environ.get("TWILIO_ACCOUNT_SID")
            tok = os.environ.get("TWILIO_AUTH_TOKEN")
            aud = requests.get(media_url, auth=(sid, tok), timeout=15)
            reply = await diagnose_audio(lang, aud.content, media_type, history)

        # ── Image diagnosis ───────────────────────────────────────────────
        elif num_media > 0 and media_url:
            sid = os.environ.get("TWILIO_ACCOUNT_SID")
            tok = os.environ.get("TWILIO_AUTH_TOKEN")
            im  = requests.get(media_url, auth=(sid, tok), timeout=15)
            p   = wa_prompt(lang, body or "Diagnose this crop photo.", history)
            reply = await gemini(p, lang, img=im.content,
                                 mime=im.headers.get("Content-Type", "image/jpeg"))

        # ── Text diagnosis ────────────────────────────────────────────────
        elif body:
            p     = wa_prompt(lang, body, history)
            reply = await gemini(p, lang)

        else:
            msg.body(REMINDER[lang])
            return PlainTextResponse(str(twiml), media_type="text/xml")

        msg.body(reply)

        # ── F4 + F9: Save scan silently ───────────────────────────────────
        try:
            ep  = extract_prompt(reply)
            r   = G.models.generate_content(model="gemini-2.5-flash", contents=ep)
            d   = json.loads(r.text.strip().replace("```json","").replace("```",""))
            await save_scan(sender, lang, body,
                            d.get("disease","unknown"), d.get("severity","medium"),
                            d.get("treatment",""), d.get("dose",""),
                            int(d.get("cost_saved_inr",0)), "whatsapp", "")
        except Exception:
            pass

    except Exception:
        lang = "en"
        try:
            s = await farmer_lang(sender)
            if s and s not in ("pending", None):
                lang = s
        except Exception:
            pass
        msg.body(ERR[lang])

    return PlainTextResponse(str(twiml), media_type="text/xml")

# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    farmers = scans = 0
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r1 = await c.get(f"{SB}/rest/v1/farmers",
                             headers=HDR, params={"lang_confirmed":"eq.true","select":"id"})
            r2 = await c.get(f"{SB}/rest/v1/scans",
                             headers={**HDR,"Prefer":"count=exact"},
                             params={"select":"id"})
        farmers = len(r1.json())
        scans   = int(r2.headers.get("content-range","0/0").split("/")[-1])
    except Exception:
        pass
    return {
        "status":         "రైతుబాడి నడుస్తోంది 🌾",
        "active_farmers": farmers,
        "total_scans":    scans,
        "features":       ["F0","F1","F2","F3","F4","F5","F6","F7","F9"],
    }

@app.get("/", response_class=HTMLResponse)
async def root():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>రైతుబాడి API is running 🌾</h1>")
