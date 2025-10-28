import os
import base64
import json
import requests
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# ---- CONFIGURACIÓN ----
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ---- AUTENTICACIÓN GMAIL (OAuth de usuario) ----
def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        with open("token.json", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "wb") as token:
            pickle.dump(creds, token)

    service = build("gmail", "v1", credentials=creds)
    return service

# ---- GEMINI (resumen del correo) ----
def resumir_con_gemini(texto):
    url = "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key=" + GEMINI_API_KEY
    body = {"contents": [{"parts": [{"text": f"Resume este correo y destaca tareas y riesgos:\n\n{texto}"}]}]}

    try:
        resp = requests.post(url, json=body)
        data = resp.json()
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print("Respuesta cruda de Gemini:", data)
            return "Sin respuesta válida"
    except Exception as e:
        print("Error al conectar con Gemini:", e)
        return "Error al conectar con Gemini"

# ---- TELEGRAM ----
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
    requests.post(url, json=data)

# ---- PROCESO PRINCIPAL ----
def main():
    print("Iniciando conexión con Gmail...")
    service = get_gmail_service()

    results = service.users().messages().list(userId="me", maxResults=3, q="is:unread").execute()
    messages = results.get("messages", [])

    if not messages:
        print("No hay correos nuevos.")
        return

    for msg in messages:
        m = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        payload = m["payload"]
        headers = payload.get("headers", [])
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(Sin asunto)")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "(Sin remitente)")

        # Extraer cuerpo del correo
        data = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data", "")
                    break
        else:
            data = payload["body"].get("data", "")

        body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        # Llamar a Gemini
        resumen = resumir_con_gemini(body)

        mensaje = f"📧 <b>Nuevo correo recibido</b>\n<b>Asunto:</b> {subject}\n<b>De:</b> {sender}\n\n<b>Resumen:</b>\n{resumen}"
        enviar_telegram(mensaje)

        print(f"Correo enviado a Telegram: {subject}")

if __name__ == "__main__":
    main()
