import os
import smtplib
import requests
import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")
PORT = int(os.getenv("PORT", 5000))


def get_trait(traits, key):
    value = traits.get(key)
    return value if value not in (None, "", []) else "N/A"


def build_html_table(customer, message):
    traits = customer.get("traits", {})
    customer_name = get_trait(traits, "name")
    phone_number = customer.get("phone_number") or "N/A"
    msg_text = message.get("message") or "N/A"
    received_at = message.get("received_at_utc") or "N/A"
    campaign_name = message.get("campaign_name") or "N/A"

    rows = [
        ("Customer Name",       customer_name),
        ("Phone Number",        phone_number),
        ("Message",             msg_text),
        ("Received At (UTC)",   received_at),
        ("Campaign Name",       campaign_name),
        ("Student Name",        get_trait(traits, "Student Name")),
        ("EMI Amount",          get_trait(traits, "EMI Amount")),
        ("Lender Name",         get_trait(traits, "Lender Name")),
        ("Application No",      get_trait(traits, "Application Number")),
        ("Balance Outstanding", get_trait(traits, "Balance Outstanding")),
        ("Recovery Number",     get_trait(traits, "Recovery Number")),
        ("Institute Name",      get_trait(traits, "Institute Name")),
        ("Loan Amount",         get_trait(traits, "Loan Amount")),
    ]

    table_rows = ""
    for i, (label, value) in enumerate(rows):
        bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
        table_rows += f"""
        <tr style="background-color:{bg};">
            <td style="padding:8px 12px;font-weight:bold;color:#333;border:1px solid #ddd;width:40%;">{label}</td>
            <td style="padding:8px 12px;color:#555;border:1px solid #ddd;">{value}</td>
        </tr>"""

    html = f"""
    <html><body>
    <p style="font-family:Arial,sans-serif;color:#333;">
        A new WhatsApp reply has been received. Details below:
    </p>
    <table style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;width:100%;max-width:600px;">
        {table_rows}
    </table>
    </body></html>
    """
    return html, customer_name


def download_image(media_url):
    """Download image to a temp file. Returns (file_path, filename) or (None, None)."""
    try:
        print(f"[INFO] Downloading image from: {media_url}")
        response = requests.get(media_url, timeout=15)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "image/jpeg")
        ext = content_type.split("/")[-1].split(";")[0].strip() or "jpg"
        filename = f"whatsapp_image.{ext}"

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
        tmp.write(response.content)
        tmp.close()
        print(f"[INFO] Image saved to temp file: {tmp.name}")
        return tmp.name, filename
    except Exception as e:
        print(f"[ERROR] Failed to download image: {e}")
        return None, None


def send_email(subject, html_body, attachment_path=None, attachment_name=None):
    msg = MIMEMultipart("mixed")
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html"))

    if attachment_path and attachment_name:
        try:
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
            msg.attach(part)
            print(f"[INFO] Attached image: {attachment_name}")
        except Exception as e:
            print(f"[ERROR] Failed to attach image: {e}")

    try:
        print(f"[INFO] Sending email to {RECIPIENT_EMAIL} ...")
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print("[INFO] Email sent successfully.")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"[ERROR] SMTP Auth failed: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to send email ({type(e).__name__}): {e}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True)
    if not payload:
        print("[WARN] Empty or non-JSON payload received.")
        return jsonify({"status": "ignored", "reason": "no payload"}), 200

    print(f"[INFO] Webhook received: {payload}")

    data = payload.get("data", {})
    customer = data.get("customer", {})
    message = data.get("message", {})

    chat_message_type = message.get("chat_message_type", "")
    if chat_message_type != "CustomerMessage":
        print(f"[INFO] Ignoring message type: {chat_message_type}")
        return jsonify({"status": "ignored", "reason": "not a CustomerMessage"}), 200

    print("[INFO] CustomerMessage detected. Processing...")

    html_body, customer_name = build_html_table(customer, message)
    subject = f"WhatsApp Reply Received - {customer_name}"
    content_type = message.get("message_content_type", "")

    if content_type == "Image":
        media_url = message.get("media_url", "")
        attachment_path, attachment_name = download_image(media_url)
        success = send_email(subject, html_body, attachment_path, attachment_name)

        if attachment_path:
            try:
                os.remove(attachment_path)
            except Exception:
                pass
    else:
        print(f"[INFO] Content type '{content_type}' — sending email without attachment.")
        success = send_email(subject, html_body)

    if success:
        return jsonify({"status": "ok", "message": "Email sent"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to send email"}), 500


if __name__ == "__main__":
    print(f"[INFO] Starting GrayQuest WhatsApp Webhook Server on port {PORT} ...")
    app.run(host="0.0.0.0", port=PORT, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
