import os
import json
import base64
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ================== CONFIG ==================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LABEL_IN = "IA_Pendiente"
LABEL_DONE = "IA_Procesado"

# ============================================

def gmail_service():
    creds = service_account.Credentials.from_service_account_file(
        "service_account.json",
        scopes=["https://www.googleapis.com/auth/gmail.modify"]
    )
    return build("gmail", "v1", credentials=creds)

def get_messages(service, label):
    results = service.users().messages().list(userId="me", labelIds=[label]).execute()
    return results.get("messages", [])

def get_message_content(service, msg_id):
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    body = ""
    if "data" in msg["payload"]["body"]:
        body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8", errors="ignore")
    elif "parts" in msg["payload"]:
        for part in msg["payload"]["parts"]:
            if part["mimeType"] == "text/plain" and "data" in part["body"]:
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                break
    return {
        "id": msg_id,
        "asunto": headers.get("Subject", ""),
        "remitente": headers.get("From", ""),
        "cuerpo": body
    }

def resume_con_gemini(email):
    prompt = f"""
Eres un analista experto que resume correos para decisiones rápidas.
Devuélveme SOLO un JSON válido con esta forma exacta:

{{
  "asunto": "...",
  "remitente": "...",
  "resumen_breve": "...",
  "tareas_concretas": ["..."],
  "prioridad": "alta|media|baja",
  "riesgos_alertas": ["..."],
  "sentimiento": "positivo|neutral|negativo"
}}

Entrada:
Asunto: {email['asunto']}
Remitente: {email['remitente']}
Cuerpo: {email['cuerpo'][:10000]}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
    }
    res = requests.post(url, json=payload)
    try:
        data = res.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text.strip().replace("```json", "").replace("```", ""))
    except Exception as e:
        print("Error Gemini:", e, res.text)
        return {"resumen_breve": "No se pudo generar resumen"}

def enviar_a_telegram(r):
    text = f"""🔔 *Alerta de correo analizado*
*Asunto:* {r.get('asunto','—')}
*De:* {r.get('remitente','—')}
*Prioridad:* {r.get('prioridad','—')}
*Resumen:* {r.get('resumen_breve','—')}
*Tareas:*
{chr(10).join('• '+t for t in r.get('tareas_concretas',[]) or ['—'])}
*Riesgos:*
{chr(10).join('• '+t for t in r.get('riesgos_alertas',[]) or ['—'])}
*Sentimiento:* {r.get('sentimiento','—')}"""
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                  json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})

def main():
    service = gmail_service()
    label_list = service.users().labels().list(userId="me").execute().get("labels", [])
    label_ids = {l["name"]: l["id"] for l in label_list}
    if LABEL_IN not in label_ids:
        print("No existe la etiqueta IA_Pendiente.")
        return
    mensajes = get_messages(service, label_ids[LABEL_IN])
    for m in mensajes:
        email = get_message_content(service, m["id"])
        resumen = resume_con_gemini(email)
        enviar_a_telegram(resumen)
        # mover a IA_Procesado
        if LABEL_DONE in label_ids:
            service.users().messages().modify(
                userId="me", id=m["id"],
                body={"removeLabelIds": [label_ids[LABEL_IN]], "addLabelIds": [label_ids[LABEL_DONE]]}
            ).execute()
    print("Ejecución completada.")

if __name__ == "__main__":
    main()
