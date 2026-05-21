# ═══════════════════════════════════════════════════════════════════════════════
# RAITHUBADI — COMPLETE BACKEND  (F0 → F9, all features)
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from google import genai
from google.genai import types
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import requests
import httpx
import base64
import json
import re
import os

# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

gemini = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT
# ─────────────────────────────────────────────────────────────────────────────

SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_KEY        = os.environ.get("SUPABASE_KEY")
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WA_NUMBER    = os.environ.get("TWILIO_WHATSAPP_NUMBER")

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — LANGUAGE CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

LANG_INSTRUCTION = {
    "en": "You MUST respond entirely in English. Not a single word in Telugu or Hindi.",
    "te": "మీరు సంపూర్ణంగా తెలుగులో సమాధానం ఇవ్వాలి. ఇంగ్లీష్ లేదా హిందీ వాడకూడదు.",
    "hi": "आपको पूरी तरह हिंदी में जवाब देना है। अंग्रेज़ी या तेलुगु न लिखें।",
}

ELDER_VOICE = {
    "en": "Speak like a warm, knowledgeable agricultural officer from rural India.",
    "te": "మీ గ్రామ పెద్ద వ్యవసాయ నిపుణుడు లాగా మాట్లాడండి — ఆప్యాయంగా, సరళంగా.",
    "hi": "एक जानकार और गर्मजोशी से भरे गाँव के कृषि विशेषज्ञ की तरह बोलें।",
}

ERROR_MSG = {
    "en": "Sorry, something went wrong. Please try again 🙏",
    "te": "క్షమించండి, తర్వాత మళ్ళీ ప్రయత్నించండి 🙏",
    "hi": "माफ़ करें, कृपया दोबारा कोशिश करें 🙏",
}

WELCOME_MSG = """🌾 Welcome to Raithubadi!
రైతుబాడికి స్వాగతం!
रैतुबाड़ी में आपका स्वागत है!

Please choose your language:
మీ భాష ఎంచుకోండి:
अपनी भाषा चुनें:

1️⃣  English
2️⃣  తెలుగు
3️⃣  हिंदी

Reply with 1, 2, or 3"""

LANG_CONFIRMED = {
    "en": "✅ I will speak English with you from now on.\n\nSend me a photo of your crop or describe the problem. I'll diagnose it in 10 seconds! 🌾",
    "te": "✅ ఇకపై నేను తెలుగులో మాట్లాడతాను.\n\nమీ పంట ఫోటో పంపండి లేదా సమస్య వివరించండి. 10 సెకన్లలో నిర్ధారణ చెప్తాను! 🌾",
    "hi": "✅ अब से मैं हिंदी में बात करूंगा।\n\nअपनी फसल की फोटो भेजें या समस्या बताएं। 10 सेकंड में निदान बताऊंगा! 🌾",
}

LANG_SWITCHED = {
    "en": "✅ Switched to English! Send your crop photo or describe the problem 🌾",
    "te": "✅ తెలుగుకు మారింది! పంట ఫోటో పంపండి లేదా సమస్య చెప్పండి 🌾",
    "hi": "✅ हिंदी में बदल दिया! फसल की फोटो भेजें या समस्या बताएं 🌾",
}

INVALID_CHOICE = (
    "Please reply with 1, 2, or 3 only.\n"
    "దయచేసి 1, 2, లేదా 3 మాత్రమే జవాబివ్వండి.\n"
    "कृपया केवल 1, 2, या 3 जवाब दें।"
)

REMINDER = {
    "en": "Send a photo of your crop or describe the problem. I'm here! 🌾\n\nTip: Register your crop by typing: *crop: cotton 15 may*",
    "te": "మీ పంట ఫోటో పంపండి లేదా సమస్య వివరించండి. నేను ఇక్కడ ఉన్నాను! 🌾\n\nటిప్: పంట నమోదు చేయండి: *పంట: పత్తి 15 మే*",
    "hi": "अपनी फसल की फोटो भेजें या समस्या बताएं। मैं यहाँ हूँ! 🌾\n\nटिप: फसल दर्ज करें: *crop: cotton 15 may*",
}

# F5 — Feedback messages
FEEDBACK_ASK = {
    "en": (
        "🌾 Raithubadi follow-up!\n\n"
        "7 days ago I diagnosed *{disease}* on your crop.\n"
        "How is your crop now?\n\n"
        "1️⃣ Improved\n2️⃣ Same\n3️⃣ Worse"
    ),
    "te": (
        "🌾 రైతుబాడి అనుసరణ!\n\n"
        "7 రోజుల క్రితం మీ పంటకు *{disease}* నిర్ధారించాను.\n"
        "ఇప్పుడు మీ పంట ఎలా ఉంది?\n\n"
        "1️⃣ మెరుగుపడింది\n2️⃣ అదే విధంగా ఉంది\n3️⃣ మరింత దిగజారింది"
    ),
    "hi": (
        "🌾 रैतुबाड़ी का फॉलो-अप!\n\n"
        "7 दिन पहले मैंने आपकी फसल में *{disease}* की पहचान की थी।\n"
        "अब आपकी फसल कैसी है?\n\n"
        "1️⃣ बेहतर हुई\n2️⃣ वैसी ही है\n3️⃣ और खराब हुई"
    ),
}

FEEDBACK_THANKS = {
    "en": {
        "1": "🎉 Great news! Your crop improved. Stay vigilant and check regularly 🌾",
        "2": "🌾 Understood. Try one more spray as advised. Send a photo if it worsens.",
        "3": "⚠️ Sorry to hear that. Send a fresh photo — I'll give updated advice right away.",
    },
    "te": {
        "1": "🎉 చాలా సంతోషం! మీ పంట మెరుగుపడింది. జాగ్రత్తగా ఉండండి 🌾",
        "2": "🌾 అర్థమైంది. సూచించిన విధంగా మరోసారి స్ప్రే చేయండి. మరింత తీవ్రమైతే ఫోటో పంపండి.",
        "3": "⚠️ విన్నందుకు చాలా బాధగా ఉంది. కొత్త ఫోటో పంపండి — తాజా సలహా ఇస్తాను.",
    },
    "hi": {
        "1": "🎉 बहुत अच्छी खबर! आपकी फसल बेहतर हुई। सावधान रहें 🌾",
        "2": "🌾 समझ गया। बताए अनुसार एक बार और छिड़काव करें। खराब हो तो फोटो भेजें।",
        "3": "⚠️ सुनकर दुख हुआ। नई फोटो भेजें — तुरंत ताजा सलाह दूंगा।",
    },
}

# F6 — Crop registration messages
CROP_REGISTERED = {
    "en": (
        "✅ Got it! I've registered your *{crop}* crop sown on {date}.\n\n"
        "I'll send you timely reminders at every growth stage — what to watch, "
        "what to spray, and what's coming next. You won't miss anything. 🌾"
    ),
    "te": (
        "✅ నమోదైంది! మీ *{crop}* పంట {date} నాటికి నమోదు చేశాను.\n\n"
        "ప్రతి పెరుగుదల దశలో సకాలంలో రిమైండర్లు పంపుతాను — ఏం చూడాలి, "
        "ఏం స్ప్రే చేయాలి, తర్వాత ఏం వస్తుంది. మీరు ఏమీ మిస్ చేయరు. 🌾"
    ),
    "hi": (
        "✅ दर्ज हो गया! आपकी *{crop}* फसल {date} को बोई गई — नोट कर लिया।\n\n"
        "हर विकास चरण पर समय पर अनुस्मारक भेजूंगा — क्या देखना है, "
        "क्या छिड़कना है और आगे क्या आने वाला है। कुछ छूटेगा नहीं। 🌾"
    ),
}

STAGE_HEADER = {
    "en": "🌾 *Raithubadi Stage Alert — {stage}* (Day {day})\n\n",
    "te": "🌾 *రైతుబాడి దశ హెచ్చరిక — {stage}* ({day}వ రోజు)\n\n",
    "hi": "🌾 *रैतुबाड़ी चरण अलर्ट — {stage}* (दिन {day})\n\n",
}

# F8 — Monthly wrapped
WRAPPED_HEADER = {
    "en": "🌾 *Your Monthly Farm Report — {month}* 🌾\n\n",
    "te": "🌾 *మీ నెలవారీ పంట నివేదిక — {month}* 🌾\n\n",
    "hi": "🌾 *आपकी मासिक फसल रिपोर्ट — {month}* 🌾\n\n",
}

WRAPPED_STATS = {
    "en": (
        "📊 This month:\n"
        "• Scans done: {scans}\n"
        "• Diseases caught early: {diseases}\n"
        "• Money saved: ₹{saved}\n\n"
        "{summary}\n\n"
        "Keep scanning. Stay ahead of every disease. 💪🌾"
    ),
    "te": (
        "📊 ఈ నెల:\n"
        "• స్కాన్లు చేశాను: {scans}\n"
        "• ముందే గుర్తించిన వ్యాధులు: {diseases}\n"
        "• ఆదా చేసిన మొత్తం: ₹{saved}\n\n"
        "{summary}\n\n"
        "స్కాన్ చేయడం కొనసాగించండి. ప్రతి వ్యాధిని ముందే ఆపండి. 💪🌾"
    ),
    "hi": (
        "📊 इस महीने:\n"
        "• स्कैन किए: {scans}\n"
        "• जल्दी पकड़ी गई बीमारियां: {diseases}\n"
        "• बचाई गई रकम: ₹{saved}\n\n"
        "{summary}\n\n"
        "स्कैन करते रहें। हर बीमारी से आगे रहें। 💪🌾"
    ),
}

MONTH_NAMES = {
    "en": ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "te": ["", "జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్",
           "జులై", "ఆగస్టు", "సెప్టెంబర్", "అక్టోబర్", "నవంబర్", "డిసెంబర్"],
    "hi": ["", "जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून",
           "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
}

# F9 — Outbreak alert
OUTBREAK_THRESHOLD = 3

OUTBREAK_ALERT = {
    "en": (
        "⚠️ *CROP OUTBREAK ALERT* ⚠️\n\n"
        "*{disease}* has been reported by {count} farmers in your region "
        "in the last 7 days.\n\n"
        "✅ What to do RIGHT NOW:\n{action}\n\n"
        "Don't wait. Act before it reaches your field. 🌾"
    ),
    "te": (
        "⚠️ *పంట వ్యాధి హెచ్చరిక* ⚠️\n\n"
        "మీ ప్రాంతంలో గత 7 రోజులలో {count} మంది రైతులు "
        "*{disease}* వ్యాధి నివేదించారు.\n\n"
        "✅ ఇప్పుడే చేయవలసినవి:\n{action}\n\n"
        "ఆలస్యం చేయకండి. మీ పంటకు చేరకముందే చర్యలు తీసుకోండి. 🌾"
    ),
    "hi": (
        "⚠️ *फसल प्रकोप चेतावनी* ⚠️\n\n"
        "आपके क्षेत्र में पिछले 7 दिनों में {count} किसानों ने "
        "*{disease}* की सूचना दी है।\n\n"
        "✅ अभी क्या करें:\n{action}\n\n"
        "देर मत करें। फसल तक पहुंचने से पहले कार्रवाई करें। 🌾"
    ),
}

# Language routing maps
SELECTION_MAP: dict[str, str] = {
    "1": "en", "english": "en",
    "2": "te", "telugu": "te", "తెలుగు": "te",
    "3": "hi", "hindi": "hi", "हिंदी": "hi",
}

SWITCH_KEYWORDS: dict[str, str] = {
    "language: english": "en", "switch to english": "en",
    "change to english": "en", "language english":  "en",
    "language: telugu":  "te", "switch to telugu":  "te",
    "change to telugu":  "te", "language telugu":   "te",
    "భాష: తెలుగు": "te",       "భాష తెలుగు": "te",
    "తెలుగులో మాట్లాడు": "te",
    "language: hindi":   "hi", "switch to hindi":   "hi",
    "change to hindi":   "hi", "language hindi":    "hi",
    "भाषा: हिंदी": "hi",        "भाषा हिंदी": "hi",
    "हिंदी में बात करो": "hi",
}

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — F6 CROP STAGE DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

CROP_STAGES: dict[str, list[dict]] = {

    "cotton": [
        {"day":  10, "stage": "Germination",
         "en": "🌱 Cotton is sprouting! Watch for damping-off disease (black stem at soil level). Ensure drainage. No waterlogging.",
         "te": "🌱 పత్తి మొలకెత్తుతోంది! నల్ల కాండం వ్యాధి చూడండి. నీరు నిలవకుండా చూసుకోండి.",
         "hi": "🌱 कपास अंकुरित हो रहा है! काले तने की बीमारी देखें। पानी जमा न होने दें।"},
        {"day":  30, "stage": "Vegetative",
         "en": "🌿 Cotton at 30 days. Thrips attack likely — check leaf undersides for silver patches. Spray neem oil 5ml/L if spotted.",
         "te": "🌿 పత్తి 30 రోజులు. నిమ్మ నూనె 5ml/L స్ప్రే చేయండి — తెల్ల మచ్చల కోసం ఆకు అడుగు భాగం చూడండి.",
         "hi": "🌿 कपास 30 दिन का। थ्रिप्स की संभावना — पत्तियों के नीचे चांदी के धब्बे देखें। नीम तेल 5ml/L छिड़कें।"},
        {"day":  55, "stage": "Flowering",
         "en": "🌸 Cotton flowering! Critical stage. Pink bollworm risk is HIGH. Check squares for entry holes. Don't skip this check.",
         "te": "🌸 పత్తి పూచింది! కీలక దశ. గులాబీ పురుగు ప్రమాదం అధికం. చదరపు పూవులలో రంధ్రాలు చూడండి.",
         "hi": "🌸 कपास में फूल आए! महत्वपूर्ण चरण। गुलाबी सुंडी का खतरा अधिक है। कलियों में छेद देखें।"},
        {"day":  80, "stage": "Boll Development",
         "en": "🫚 Bolls forming. Boll rot is your enemy now — check for brown soft bolls. Reduce irrigation slightly.",
         "te": "🫚 కాయలు ఏర్పడుతున్నాయి. కాయ కుళ్ళు వ్యాధి జాగ్రత్త — గోధుమ రంగు మెత్తటి కాయలు చూడండి. నీరు తగ్గించండి.",
         "hi": "🫚 टिंडे बन रहे हैं। टिंडा सड़न का खतरा — भूरे नरम टिंडे देखें। सिंचाई थोड़ी कम करें।"},
        {"day": 130, "stage": "Pre-harvest",
         "en": "🏁 Cotton almost ready! Stop all spraying now — 2 weeks before picking. Let the crop finish naturally. 🌾",
         "te": "🏁 పత్తి దాదాపు సిద్ధం! ఇప్పుడు స్ప్రే ఆపండి — కోతకు 2 వారాల ముందు. పంట సహజంగా పూర్తవ్వనివ్వండి. 🌾",
         "hi": "🏁 कपास लगभग तैयार! अब छिड़काव बंद करें — चुनाई से 2 हफ्ते पहले। फसल को प्राकृतिक रूप से पकने दें। 🌾"},
    ],

    "rice": [
        {"day":  7,  "stage": "Nursery",
         "en": "🌱 Rice seedlings up! Check for yellow leaf color — may be nitrogen deficiency. Ensure flooded nursery bed.",
         "te": "🌱 వరి మొలకలు వచ్చాయి! పసుపు ఆకు రంగు చూడండి — నత్రజని లోపం కావచ్చు. నర్సరీ మడి నీటితో నిండేలా చూడండి.",
         "hi": "🌱 चावल के पौधे निकले! पीले पत्तों की जांच करें — नाइट्रोजन की कमी हो सकती है। नर्सरी में पानी भरा रखें।"},
        {"day":  25, "stage": "Transplanting",
         "en": "🌾 Time to transplant! After planting — watch for blast disease (grey spots on leaves) in first 2 weeks.",
         "te": "🌾 నాటే సమయం! నాటిన తర్వాత — మొదటి 2 వారాలలో బ్లాస్ట్ వ్యాధి (ఆకులపై బూడిద మచ్చలు) చూడండి.",
         "hi": "🌾 रोपाई का समय! रोपण के बाद — पहले 2 हफ्तों में ब्लास्ट रोग (पत्तियों पर भूरे धब्बे) देखें।"},
        {"day":  50, "stage": "Tillering",
         "en": "🌿 Rice tillering. Stem borer is active now — dead heart symptom means larvae inside. Check 5 plants per row.",
         "te": "🌿 వరి పిలకలు వేస్తోంది. కాండం తొలుచే పురుగు చురుగ్గా ఉంది — చనిపోయిన గుండె లక్షణం లార్వా సూచిస్తుంది.",
         "hi": "🌿 चावल में कल्ले। तना छेदक सक्रिय है — मृत हृदय लक्षण का मतलब अंदर लार्वा। प्रति पंक्ति 5 पौधे जांचें।"},
        {"day":  75, "stage": "Panicle Initiation",
         "en": "🌾 Panicle forming — most critical stage! Sheath blight risk high. Check base of stems for white-brown lesions.",
         "te": "🌾 గుత్తి ఏర్పడుతోంది — అత్యంత కీలక దశ! కాండం తొడుపు తెగులు ప్రమాదం అధికం. కాండం అడుగు భాగంలో తెల్ల-గోధుమ గాయాలు చూడండి.",
         "hi": "🌾 बाली बन रही है — सबसे महत्वपूर्ण चरण! शीथ ब्लाइट का खतरा। तने के आधार पर सफेद-भूरे घाव देखें।"},
        {"day": 110, "stage": "Pre-harvest",
         "en": "🏁 Rice nearly ready! Drain water 10 days before harvest. Stop all chemicals now. Golden fields coming 🌾",
         "te": "🏁 వరి దాదాపు సిద్ధం! కోత కంటే 10 రోజుల ముందు నీరు తీయండి. ఇప్పుడు అన్ని రసాయనాలు ఆపండి. 🌾",
         "hi": "🏁 चावल लगभग तैयार! कटाई से 10 दिन पहले पानी निकालें। अब सभी रसायन बंद करें। 🌾"},
    ],

    "chilli": [
        {"day":  10, "stage": "Germination",
         "en": "🌶 Chilli sprouting. Damping off kills seedlings fast — avoid overwatering. Good airflow around plants.",
         "te": "🌶 మిర్చి మొలకెత్తుతోంది. అతిగా నీరు పోయకండి — మొలక కుళ్ళు వ్యాధి వస్తుంది. మొక్కల చుట్టూ గాలి చలనం బాగుండాలి.",
         "hi": "🌶 मिर्च अंकुरित हो रही है। ज़्यादा पानी न दें — डैम्पिंग ऑफ़ बीमारी होगी। पौधों के आसपास हवा का प्रवाह रखें।"},
        {"day":  35, "stage": "Vegetative",
         "en": "🌿 Chilli growing. Thrips and mites appear now. Tap a branch over white paper — tiny moving dots = mites. Act early.",
         "te": "🌿 మిర్చి పెరుగుతోంది. థ్రిప్స్ మరియు పురుగులు ఇప్పుడు కనిపిస్తాయి. తెల్ల కాగితంపై కొమ్మ తట్టండి — కదిలే చిన్న చుక్కలు = పురుగులు.",
         "hi": "🌿 मिर्च बढ़ रही है। थ्रिप्स और माइट्स अब आते हैं। सफेद कागज पर टहनी थपथपाएं — हिलते बिंदु = माइट्स।"},
        {"day":  60, "stage": "Flowering",
         "en": "🌸 Chilli flowering! Flower drop is common — caused by extreme heat or thrips. Spray 1% KNO3 to set more fruit.",
         "te": "🌸 మిర్చి పూచింది! పూల రాలడం సాధారణం — అధిక వేడి లేదా థ్రిప్స్ వల్ల. 1% KNO3 స్ప్రే చేస్తే పండ్లు ఎక్కువగా కట్టుకుంటాయి.",
         "hi": "🌸 मिर्च में फूल! फूल गिरना आम — तेज गर्मी या थ्रिप्स से। 1% KNO3 छिड़कें — ज़्यादा फल लगेंगे।"},
        {"day":  90, "stage": "Fruit Development",
         "en": "🫑 Fruits developing! Anthracnose (black spots on fruit) is your main threat now. Pick and destroy any infected fruit immediately.",
         "te": "🫑 పండ్లు పెరుగుతున్నాయి! ఆంత్రాక్నోస్ (పండులపై నల్ల మచ్చలు) ఇప్పుడు ప్రధాన ముప్పు. సోకిన పండ్లు వెంటనే తీసి నాశనం చేయండి.",
         "hi": "🫑 फल बढ़ रहे हैं! एंथ्रेक्नोज़ (फल पर काले धब्बे) मुख्य खतरा। संक्रमित फल तुरंत तोड़कर नष्ट करें।"},
        {"day": 120, "stage": "Pre-harvest",
         "en": "🏁 Chilli nearly ready for picking! First red fruits appear. Stop all sprays 15 days before. 🌾",
         "te": "🏁 మిర్చి కోత దగ్గరలో ఉంది! మొదటి ఎర్ర పండ్లు వస్తున్నాయి. 15 రోజుల ముందు స్ప్రే ఆపండి. 🌾",
         "hi": "🏁 मिर्च चुनाई के पास! पहले लाल फल आ रहे हैं। 15 दिन पहले छिड़काव बंद करें। 🌾"},
    ],

    "default": [
        {"day":  14, "stage": "Early Growth",
         "en": "🌱 Your crop is in early growth. Watch for yellowing leaves (nutrient deficiency) or wilting (root rot). Send a photo if anything looks wrong.",
         "te": "🌱 మీ పంట ప్రారంభ దశలో ఉంది. పసుపు ఆకులు (పోషక లోపం) లేదా వాడటం (వేర్ల కుళ్ళు) చూడండి. ఏదైనా తప్పుగా కనిపిస్తే ఫోటో పంపండి.",
         "hi": "🌱 आपकी फसल शुरुआती विकास में है। पीले पत्ते या मुरझाना देखें। कुछ गलत लगे तो फोटो भेजें।"},
        {"day":  45, "stage": "Vegetative",
         "en": "🌿 Crop is growing! This is when most fungal diseases start. Check 10 random plants today. Photo me if unsure.",
         "te": "🌿 పంట పెరుగుతోంది! చాలా శిలీంద్ర వ్యాధులు ఇప్పుడే మొదలవుతాయి. నేడు 10 మొక్కలు తనిఖీ చేయండి.",
         "hi": "🌿 फसल बढ़ रही है! अधिकांश फफूंद रोग अब शुरू होते हैं। आज 10 पौधे जांचें।"},
        {"day":  90, "stage": "Flowering/Fruiting",
         "en": "🌸 Your crop should be near flowering. Most important stage — any disease now costs you yield. Check daily if possible.",
         "te": "🌸 మీ పంట పూత దశకు చేరుకుంటోంది. అత్యంత కీలక దశ — ఇప్పుడు వ్యాధి వస్తే దిగుబడి తగ్గుతుంది. రోజూ తనిఖీ చేయండి.",
         "hi": "🌸 आपकी फसल फूल के पास होगी। सबसे महत्वपूर्ण चरण — अभी बीमारी से उपज कम होती है। रोज़ जांचें।"},
    ],
}

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SUPABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_farmer_lang(number: str) -> str | None:
    async with httpx.AsyncClient() as c:
        res = await c.get(
            f"{SUPABASE_URL}/rest/v1/farmers",
            headers=SB_HEADERS,
            params={"whatsapp_number": f"eq.{number}",
                    "select": "preferred_lang,lang_confirmed"},
        )
    rows = res.json()
    if not rows:
        return None
    row = rows[0]
    return "pending" if not row["lang_confirmed"] else row["preferred_lang"]


async def upsert_farmer(number: str, lang: str, confirmed: bool) -> None:
    async with httpx.AsyncClient() as c:
        await c.post(
            f"{SUPABASE_URL}/rest/v1/farmers",
            headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates"},
            json={
                "whatsapp_number": number,
                "preferred_lang":  lang,
                "lang_confirmed":  confirmed,
                "last_active":     datetime.now(timezone.utc).isoformat(),
            },
        )


async def save_scan(
    number: str, lang: str, input_text: str,
    disease: str, severity: str, treatment: str,
    dose: str, cost_saved: int, channel: str = "whatsapp",
) -> None:
    async with httpx.AsyncClient() as c:
        await c.post(
            f"{SUPABASE_URL}/rest/v1/scans",
            headers=SB_HEADERS,
            json={
                "whatsapp_number": number,
                "lang":            lang,
                "input_text":      input_text,
                "disease":         disease,
                "severity":        severity,
                "treatment":       treatment,
                "dose":            dose,
                "cost_saved_inr":  cost_saved,
                "channel":         channel,
            },
        )


async def get_scan_history(number: str) -> list[dict]:
    try:
        async with httpx.AsyncClient() as c:
            res = await c.get(
                f"{SUPABASE_URL}/rest/v1/scans",
                headers=SB_HEADERS,
                params={
                    "whatsapp_number": f"eq.{number}",
                    "select":          "disease,severity,treatment,created_at",
                    "order":           "created_at.desc",
                    "limit":           "5",
                },
            )
        return res.json() if isinstance(res.json(), list) else []
    except Exception:
        return []


def format_history(scans: list[dict], lang: str) -> str:
    if not scans:
        return "No previous scans. This is the farmer's first diagnosis."
    lines = []
    for s in scans:
        try:
            dt  = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
            ago = (datetime.now(timezone.utc) - dt).days
            when = f"{ago} days ago" if ago > 1 else "today"
        except Exception:
            when = "recently"
        lines.append(f"- {when}: {s['disease']} ({s['severity']} severity)")
    return "\n".join(lines)


async def get_scans_needing_feedback() -> list[dict]:
    try:
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        async with httpx.AsyncClient() as c:
            res = await c.get(
                f"{SUPABASE_URL}/rest/v1/scans",
                headers=SB_HEADERS,
                params={
                    "feedback_sent": "eq.false",
                    "created_at":    f"gte.{seven_days_ago}T00:00:00Z",
                    "select":        "id,whatsapp_number,disease,lang",
                    "limit":         "50",
                },
            )
        return res.json() if isinstance(res.json(), list) else []
    except Exception:
        return []


async def mark_feedback_sent(scan_id: str) -> None:
    async with httpx.AsyncClient() as c:
        await c.patch(
            f"{SUPABASE_URL}/rest/v1/scans",
            headers=SB_HEADERS,
            params={"id": f"eq.{scan_id}"},
            json={"feedback_sent": True},
        )


async def save_feedback_reply(scan_id: str, outcome: str) -> None:
    outcome_map = {"1": "improved", "2": "same", "3": "worse"}
    async with httpx.AsyncClient() as c:
        await c.patch(
            f"{SUPABASE_URL}/rest/v1/scans",
            headers=SB_HEADERS,
            params={"id": f"eq.{scan_id}"},
            json={"feedback_reply": outcome_map.get(outcome, outcome)},
        )


# F6 — crop registration helpers
async def register_crop(number: str, crop: str, sowing_date: str, lang: str) -> None:
    async with httpx.AsyncClient() as c:
        await c.patch(
            f"{SUPABASE_URL}/rest/v1/farmer_crops",
            headers=SB_HEADERS,
            params={"whatsapp_number": f"eq.{number}", "active": "eq.true"},
            json={"active": False},
        )
        await c.post(
            f"{SUPABASE_URL}/rest/v1/farmer_crops",
            headers=SB_HEADERS,
            json={
                "whatsapp_number": number,
                "crop_name":       crop.lower().strip(),
                "crop_name_raw":   crop.strip(),
                "sowing_date":     sowing_date,
                "stage_index":     0,
                "active":          True,
                "lang":            lang,
            },
        )


async def get_active_crops_due_reminder() -> list[dict]:
    try:
        today = datetime.now(timezone.utc).date()
        async with httpx.AsyncClient() as c:
            res = await c.get(
                f"{SUPABASE_URL}/rest/v1/farmer_crops",
                headers=SB_HEADERS,
                params={"active": "eq.true",
                        "select": "id,whatsapp_number,crop_name,sowing_date,stage_index,lang"},
            )
        crops = res.json() if isinstance(res.json(), list) else []
        due   = []
        for crop in crops:
            try:
                sown   = datetime.strptime(crop["sowing_date"], "%Y-%m-%d").date()
                days   = (today - sown).days
                stages = CROP_STAGES.get(crop["crop_name"], CROP_STAGES["default"])
                idx    = crop["stage_index"]
                if idx < len(stages) and days >= stages[idx]["day"]:
                    crop["days_since_sowing"] = days
                    crop["stage"]             = stages[idx]
                    due.append(crop)
            except Exception:
                continue
        return due
    except Exception:
        return []


async def advance_stage(crop_id: str, next_index: int) -> None:
    async with httpx.AsyncClient() as c:
        await c.patch(
            f"{SUPABASE_URL}/rest/v1/farmer_crops",
            headers=SB_HEADERS,
            params={"id": f"eq.{crop_id}"},
            json={"stage_index": next_index},
        )


# F8 — all farmers + monthly scans
async def get_all_active_farmers() -> list[dict]:
    try:
        async with httpx.AsyncClient() as c:
            res = await c.get(
                f"{SUPABASE_URL}/rest/v1/farmers",
                headers=SB_HEADERS,
                params={"lang_confirmed": "eq.true",
                        "select": "whatsapp_number,preferred_lang"},
            )
        return res.json() if isinstance(res.json(), list) else []
    except Exception:
        return []


async def get_monthly_scans(number: str, year: int, month: int) -> list[dict]:
    start = f"{year}-{month:02d}-01T00:00:00Z"
    if month == 12:
        end = f"{year + 1}-01-01T00:00:00Z"
    else:
        end = f"{year}-{month + 1:02d}-01T00:00:00Z"
    try:
        async with httpx.AsyncClient() as c:
            res = await c.get(
                f"{SUPABASE_URL}/rest/v1/scans",
                headers=SB_HEADERS,
                params={
                    "whatsapp_number": f"eq.{number}",
                    "created_at":      f"gte.{start}",
                    "select":          "disease,cost_saved_inr",
                    "limit":           "200",
                },
            )
        return res.json() if isinstance(res.json(), list) else []
    except Exception:
        return []

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — PARSERS
# ═══════════════════════════════════════════════════════════════════════════════

def parse_lang_choice(text: str) -> str | None:
    return SELECTION_MAP.get(text.strip().lower())

def parse_switch_command(text: str) -> str | None:
    return SWITCH_KEYWORDS.get(text.strip().lower())


# F6 — crop registration parser
MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "జనవరి": "01", "ఫిబ్రవరి": "02", "మార్చి": "03", "ఏప్రిల్": "04",
    "మే": "05", "జూన్": "06", "జులై": "07", "ఆగస్టు": "08",
    "సెప్టెంబర్": "09", "అక్టోబర్": "10", "నవంబర్": "11", "డిసెంబర్": "12",
}

KNOWN_CROPS = {
    "cotton": "cotton", "rice": "rice", "chilli": "chilli", "chili": "chilli",
    "maize": "maize",   "corn": "maize", "wheat": "wheat",
    "groundnut": "groundnut", "peanut": "groundnut",
    "tomato": "tomato", "onion": "onion",
    "sugarcane": "sugarcane", "soybean": "soybean", "soya": "soybean",
    "patti": "cotton",  "vari": "rice",  "mirchi": "chilli", "mirapa": "chilli",
    "maka": "maize",    "goduma": "wheat", "pallilu": "groundnut",
    "ullipaya": "onion", "cheruku": "sugarcane",
}

CROP_REGISTER_TRIGGERS = [
    "crop:", "my crop:", "i planted", "i sowed", "sowing date",
    "పంట:", "నేను నాటాను", "నేను విత్తాను",
    "फसल:", "मैंने बोया", "मैंने लगाया",
]

def parse_crop_registration(text: str) -> dict | None:
    lower = text.lower().strip()
    if not any(t in lower for t in CROP_REGISTER_TRIGGERS):
        return None
    crop = None
    for key, val in KNOWN_CROPS.items():
        if key in lower:
            crop = val
            break
    if not crop:
        return None
    today = datetime.now(timezone.utc).date()
    year  = today.year
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return {"crop": crop, "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}"}
    m = re.search(r"(\d{1,2})\s+([a-zA-Z]+)", lower)
    if m:
        day = m.group(1).zfill(2)
        mon = MONTH_MAP.get(m.group(2)[:3].lower())
        if mon:
            return {"crop": crop, "date": f"{year}-{mon}-{day}"}
    m = re.search(r"([a-zA-Z]+)\s+(\d{1,2})", lower)
    if m:
        mon = MONTH_MAP.get(m.group(1)[:3].lower())
        day = m.group(2).zfill(2)
        if mon:
            return {"crop": crop, "date": f"{year}-{mon}-{day}"}
    return {"crop": crop, "date": today.isoformat()}

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — GEMINI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_whatsapp_prompt(lang: str, input_text: str, history: str) -> str:
    return f"""{LANG_INSTRUCTION[lang]}
{ELDER_VOICE[lang]}

You are Raithubadi AI — a crop disease expert for Indian farmers.

FARMER'S PAST SCAN HISTORY:
{history}

RULES:
- Respond 100% in {lang}. Zero words from any other language.
- If history shows the SAME disease repeating — warn the farmer urgently.
- Organic treatment FIRST. Chemical only if organic is not enough.
- Exact dose per acre. Rupees saved vs blanket spraying.
- Simple words. No jargon. Max 300 characters total.
- End with one warm encouraging line.

Current problem: {input_text}

Reply in plain text only. No JSON. No bullet points."""


def build_web_prompt(lang: str, input_text: str, history: str) -> str:
    return f"""{LANG_INSTRUCTION[lang]}
{ELDER_VOICE[lang]}

You are Raithubadi AI — a crop disease expert for Indian farmers.

FARMER'S PAST SCAN HISTORY:
{history}

RULES:
- Respond 100% in {lang}. Zero words from any other language.
- Organic treatment FIRST. Chemical only if organic is not enough.
- Exact dose per acre. Calculate rupees saved vs blanket spraying.
- Simple words. No jargon.

Current problem: {input_text}

Respond ONLY in valid JSON. No markdown. No text outside JSON:
{{
  "disease": "<disease name in {lang}>",
  "severity": "<low|medium|high>",
  "cause": "<simple cause in {lang}>",
  "treatment": "<organic first then chemical in {lang}>",
  "dose": "<exact dose per acre in {lang}>",
  "recheck_days": <integer>,
  "cost_saved_inr": <integer>,
  "speak_text": "<full spoken diagnosis in {lang}, warm like a village elder, 4-6 sentences>"
}}"""


def gemini_text(prompt: str) -> str:
    r = gemini.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return r.text.strip()


def gemini_image(prompt: str, image_bytes: bytes, mime_type: str) -> str:
    r = gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            types.Part.from_text(text=prompt),
        ]
    )
    return r.text.strip()


# F7 — voice note
def is_voice_note(content_type: str) -> bool:
    return content_type.lower().split(";")[0].strip().startswith("audio/")


async def diagnose_voice(lang: str, audio_bytes: bytes, mime_type: str, history: str) -> str:
    prompt = f"""{LANG_INSTRUCTION[lang]}
{ELDER_VOICE[lang]}

You are Raithubadi AI — a crop disease expert for Indian farmers.

FARMER'S PAST SCAN HISTORY:
{history}

A farmer has sent you a voice note describing their crop problem.
Listen to the audio, understand what they said, and diagnose the disease.

RULES:
- Internally transcribe what the farmer said (do not show transcription).
- Then respond ONLY with your diagnosis in {lang}.
- Respond 100% in {lang}. Zero words from any other language.
- Organic treatment FIRST. Chemical only if needed.
- Exact dose per acre. Rupees saved vs blanket spray.
- Simple words. No jargon. Max 350 characters.
- Start with one line acknowledging what the farmer said (in {lang}).
- End with one warm encouraging line."""
    clean_mime = mime_type.split(";")[0].strip()
    if clean_mime not in ("audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav"):
        clean_mime = "audio/ogg"
    r = gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=clean_mime),
            types.Part.from_text(text=prompt),
        ]
    )
    return r.text.strip()


# F8 — wrapped summary line
async def generate_wrapped_summary(lang: str, scans: int, diseases: list[str], saved: int) -> str:
    if scans == 0:
        fallback = {
            "en": "You didn't scan this month — that's okay. Your farm needs you next month 🌱",
            "te": "ఈ నెల స్కాన్ చేయలేదు — పర్వాలేదు. వచ్చే నెల మీ పంటకు మీరు అవసరం 🌱",
            "hi": "इस महीने स्कैन नहीं किया — कोई बात नहीं। अगले महीने आपकी फसल को आपकी ज़रूरत है 🌱",
        }
        return fallback[lang]
    disease_list = ", ".join(set(diseases)) if diseases else "none"
    prompt = (
        f"{LANG_INSTRUCTION[lang]}\n"
        f"Write ONE warm sentence (max 100 characters) summarising a farmer's month.\n"
        f"Facts: {scans} crop scans done, diseases found: {disease_list}, ₹{saved} saved.\n"
        f"Personal, encouraging, like a proud elder speaking to a young farmer.\n"
        f"Only the sentence. No extra text."
    )
    try:
        return gemini_text(prompt)
    except Exception:
        return ""


# F9 — outbreak check
_outbreak_sent_today: set[str] = set()

async def check_and_broadcast_outbreak(disease: str) -> None:
    if not disease or disease.lower() == "unknown":
        return
    disease_lower = disease.lower().strip()
    today_key     = f"{disease_lower}:{datetime.now(timezone.utc).date()}"
    if today_key in _outbreak_sent_today:
        return
    try:
        seven_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        async with httpx.AsyncClient() as c:
            res = await c.get(
                f"{SUPABASE_URL}/rest/v1/scans",
                headers={**SB_HEADERS, "Prefer": "count=exact"},
                params={
                    "disease":    f"ilike.%{disease_lower}%",
                    "created_at": f"gte.{seven_ago}",
                    "select":     "whatsapp_number",
                },
            )
        total = int(res.headers.get("content-range", "0/0").split("/")[-1])
        if total < OUTBREAK_THRESHOLD:
            return
        _outbreak_sent_today.add(today_key)

        action_en = gemini_text(
            f"Crop disease outbreak: {disease}. "
            f"Give ONE preventive action farmers should take immediately. "
            f"Max 80 characters. Organic first. Plain text only."
        )
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        farmers = await get_all_active_farmers()
        for farmer in farmers:
            try:
                number = farmer["whatsapp_number"]
                lang   = farmer.get("preferred_lang", "en")
                if lang != "en":
                    action = gemini_text(
                        f"{LANG_INSTRUCTION[lang]}\n"
                        f"Translate this crop disease prevention advice "
                        f"to {lang}: {action_en}"
                    )
                else:
                    action = action_en
                text = OUTBREAK_ALERT[lang].format(
                    disease=disease, count=total, action=action
                )
                twilio_client.messages.create(
                    from_=TWILIO_WA_NUMBER,
                    to=number,
                    body=text,
                )
            except Exception:
                continue
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SCAN PARSER + SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════

async def parse_and_save_whatsapp_scan(number, lang, input_text, reply):
    try:
        raw = gemini_text(
            f"""Extract from this crop diagnosis. Respond ONLY valid JSON, no markdown:
{{"disease":"<English>","severity":"<low|medium|high>","treatment":"<one line English>","dose":"<English>","cost_saved_inr":<integer>}}
Diagnosis:
{reply}"""
        )
        data = json.loads(raw.replace("```json", "").replace("```", "").strip())
        await save_scan(
            number=number, lang=lang, input_text=input_text,
            disease=data.get("disease", "unknown"),
            severity=data.get("severity", "medium"),
            treatment=data.get("treatment", ""),
            dose=data.get("dose", ""),
            cost_saved=int(data.get("cost_saved_inr", 0)),
        )
        await check_and_broadcast_outbreak(data.get("disease", ""))
    except Exception:
        pass


pending_feedback: dict[str, str] = {}   # number → scan_id

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — SCHEDULER JOBS (F5 + F6 + F8)
# ═══════════════════════════════════════════════════════════════════════════════

async def send_feedback_requests() -> None:
    """F5 — runs every hour, sends 7-day follow-ups."""
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        scans = await get_scans_needing_feedback()
        for scan in scans:
            try:
                lang    = scan.get("lang", "en")
                disease = scan.get("disease", "the disease")
                number  = scan["whatsapp_number"]
                text    = FEEDBACK_ASK[lang].format(disease=disease)
                twilio_client.messages.create(
                    from_=TWILIO_WA_NUMBER,
                    to=number,
                    body=text,
                )
                await mark_feedback_sent(scan["id"])
                pending_feedback[number] = scan["id"]
            except Exception:
                continue
    except Exception:
        pass


async def send_stage_reminders() -> None:
    """F6 — runs every morning at 8am IST, sends crop stage alerts."""
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        due_crops = await get_active_crops_due_reminder()
        for crop in due_crops:
            try:
                lang      = crop.get("lang", "en")
                stage     = crop["stage"]
                days      = crop["days_since_sowing"]
                number    = crop["whatsapp_number"]
                crop_id   = crop["id"]
                idx       = crop["stage_index"]

                header    = STAGE_HEADER[lang].format(stage=stage["stage"], day=days)
                body_text = header + stage[lang]

                twilio_client.messages.create(
                    from_=TWILIO_WA_NUMBER,
                    to=number,
                    body=body_text,
                )
                await advance_stage(crop_id, idx + 1)
            except Exception:
                continue
    except Exception:
        pass


async def send_monthly_wrapped() -> None:
    """F8 — runs last day of month, sends monthly farm report."""
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        now   = datetime.now(timezone.utc)
        year  = now.year
        month = now.month
        farmers = await get_all_active_farmers()
        for farmer in farmers:
            try:
                number     = farmer["whatsapp_number"]
                lang       = farmer.get("preferred_lang", "en")
                scans      = await get_monthly_scans(number, year, month)
                scan_count = len(scans)
                diseases   = [s.get("disease", "") for s in scans if s.get("disease")]
                total_saved = sum(int(s.get("cost_saved_inr", 0)) for s in scans)
                month_name = MONTH_NAMES[lang][month]
                summary    = await generate_wrapped_summary(lang, scan_count, diseases, total_saved)
                header     = WRAPPED_HEADER[lang].format(month=month_name)
                stats      = WRAPPED_STATS[lang].format(
                    scans=scan_count,
                    diseases=len(set(diseases)),
                    saved=total_saved,
                    summary=summary,
                )
                twilio_client.messages.create(
                    from_=TWILIO_WA_NUMBER,
                    to=number,
                    body=header + stats,
                )
            except Exception:
                continue
    except Exception:
        pass


@app.on_event("startup")
async def start_scheduler():
    scheduler = AsyncIOScheduler()
    # F5: check every hour
    scheduler.add_job(send_feedback_requests, "interval", hours=1)
    # F6: every morning at 8am IST (UTC+5:30 = 02:30 UTC)
    scheduler.add_job(send_stage_reminders, "cron", hour=2, minute=30)
    # F8: last day of each month at 9am IST (03:30 UTC)
    scheduler.add_job(send_monthly_wrapped, "cron", day="last", hour=3, minute=30)
    scheduler.start()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — WEB API  (POST /analyze)
# ═══════════════════════════════════════════════════════════════════════════════

class AnalyzeRequest(BaseModel):
    lang:         str = "en"
    text:         str = ""
    image_b64:    str = ""
    image_mime:   str = "image/jpeg"
    phone_number: str = ""


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    lang = req.lang if req.lang in ("en", "te", "hi") else "en"
    try:
        history = "No previous scans."
        if req.phone_number:
            scans   = await get_scan_history(req.phone_number)
            history = format_history(scans, lang)

        prompt = build_web_prompt(lang, req.text or "See the image provided", history)
        if req.image_b64:
            raw = gemini_image(prompt, base64.b64decode(req.image_b64), req.image_mime)
        else:
            raw = gemini_text(prompt)

        clean  = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        result["lang"] = lang

        if req.phone_number:
            await save_scan(
                number=req.phone_number, lang=lang, input_text=req.text,
                disease=result.get("disease", "unknown"),
                severity=result.get("severity", "medium"),
                treatment=result.get("treatment", ""),
                dose=result.get("dose", ""),
                cost_saved=int(result.get("cost_saved_inr", 0)),
                channel="web",
            )
            await check_and_broadcast_outbreak(result.get("disease", ""))
        return JSONResponse(content=result)
    except Exception:
        return JSONResponse(status_code=500, content={"error": ERROR_MSG.get(lang, ERROR_MSG["en"])})

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — WHATSAPP WEBHOOK  (POST /whatsapp)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    form      = await request.form()
    sender    = form.get("From", "")
    body      = form.get("Body", "").strip()
    num_media = int(form.get("NumMedia", "0"))
    media_url = form.get("MediaUrl0", "")

    twiml = MessagingResponse()
    msg   = twiml.message()

    try:
        current = await get_farmer_lang(sender)

        # ── New farmer ────────────────────────────────────────────────────
        if current is None:
            await upsert_farmer(sender, "en", confirmed=False)
            msg.body(WELCOME_MSG)
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── Language selection pending ────────────────────────────────────
        if current == "pending":
            chosen = parse_lang_choice(body)
            if chosen:
                await upsert_farmer(sender, chosen, confirmed=True)
                msg.body(LANG_CONFIRMED[chosen])
            else:
                msg.body(INVALID_CHOICE)
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── Language switch command ───────────────────────────────────────
        switch_to = parse_switch_command(body)
        if switch_to:
            await upsert_farmer(sender, switch_to, confirmed=True)
            msg.body(LANG_SWITCHED[switch_to])
            return PlainTextResponse(str(twiml), media_type="text/xml")

        lang = current

        # ── F5: Handle feedback reply ─────────────────────────────────────
        if sender in pending_feedback and body in ("1", "2", "3"):
            scan_id = pending_feedback.pop(sender)
            await save_feedback_reply(scan_id, body)
            msg.body(FEEDBACK_THANKS[lang][body])
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── F6: Handle crop registration ──────────────────────────────────
        crop_reg = parse_crop_registration(body)
        if crop_reg:
            await register_crop(
                number=sender,
                crop=crop_reg["crop"],
                sowing_date=crop_reg["date"],
                lang=lang,
            )
            reply = CROP_REGISTERED[lang].format(
                crop=crop_reg["crop"].title(),
                date=crop_reg["date"],
            )
            msg.body(reply)
            return PlainTextResponse(str(twiml), media_type="text/xml")

        # ── F4: Load scan history and diagnose ────────────────────────────
        scans   = await get_scan_history(sender)
        history = format_history(scans, lang)

        if num_media > 0 and media_url:
            media_res = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            mime_type = media_res.headers.get("Content-Type", "image/jpeg")

            # F7: voice note support
            if is_voice_note(mime_type):
                reply = await diagnose_voice(lang, media_res.content, mime_type, history)
            else:
                prompt = build_whatsapp_prompt(lang, "See the crop image", history)
                reply  = gemini_image(prompt, media_res.content, mime_type)

            await parse_and_save_whatsapp_scan(sender, lang, "image/voice", reply)

        elif body:
            prompt = build_whatsapp_prompt(lang, body, history)
            reply  = gemini_text(prompt)
            await parse_and_save_whatsapp_scan(sender, lang, body, reply)

        else:
            reply = REMINDER[lang]

        msg.body(reply)

    except Exception:
        safe_lang = current if current and current != "pending" else "en"
        msg.body(ERROR_MSG.get(safe_lang, ERROR_MSG["en"]))

    return PlainTextResponse(str(twiml), media_type="text/xml")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — ROOT
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "status": "రైతుబాడి నడుస్తోంది",
        "message": "Raithubadi is running 🌾",
        "features": "F0-F9 active",
    }
