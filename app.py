import base64
from datetime import datetime
from functools import wraps
import html
from io import BytesIO
import json
import os
import sqlite3
import urllib.parse
import urllib.request
import urllib.error

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import qrcode
from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify
from werkzeug.security import check_password_hash, generate_password_hash


def load_local_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()


load_local_env()

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-before-deployment"
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
DATABASE = "smarthostel.db"


@app.context_processor
def inject_asset_version():
    return {"asset_version": os.getenv("RENDER_GIT_COMMIT", datetime.now().strftime("%Y%m%d%H%M"))}


@app.after_request
def add_no_cache_headers(response):
    if request.endpoint == "static":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

def get_db():
    db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    return db


def column_exists(db, table, column):
    columns = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in columns)


def add_column_if_missing(db, table, column, definition):
    if not column_exists(db, table, column):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with get_db() as db:
        # Create Tables
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                password TEXT NOT NULL,
                failed_attempts INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                phone TEXT,
                dob TEXT NOT NULL,
                gender TEXT NOT NULL,
                degree TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block TEXT NOT NULL,
                floor INTEGER NOT NULL,
                room_number INTEGER NOT NULL,
                type TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                occupied INTEGER DEFAULT 0,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pass_sequence (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_email TEXT UNIQUE NOT NULL,
                room_id INTEGER NOT NULL,
                pass_id TEXT NOT NULL,
                allocated_at TEXT NOT NULL,
                FOREIGN KEY (room_id) REFERENCES rooms (id)
            );
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_email TEXT UNIQUE NOT NULL,
                room_type TEXT NOT NULL,
                floor INTEGER,
                request_type TEXT DEFAULT 'Allocation',
                reason TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_email TEXT NOT NULL,
                channel TEXT NOT NULL,
                recipient TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                provider TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_email TEXT NOT NULL,
                text TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                event TEXT NOT NULL,
                risk TEXT NOT NULL
            );
        """)

        add_column_if_missing(db, "students", "phone", "TEXT")
        add_column_if_missing(db, "requests", "request_type", "TEXT DEFAULT 'Allocation'")
        add_column_if_missing(db, "requests", "reason", "TEXT")
        
        # Initialize pass sequence if not exists
        seq = db.execute("SELECT last_id FROM pass_sequence WHERE id = 1").fetchone()
        if not seq:
            db.execute("INSERT INTO pass_sequence (id, last_id) VALUES (1, 1110)")
            db.commit()

        # Seed Admins if not exists
        admin = db.execute("SELECT * FROM users WHERE email = 'admin@smarthostel.ai'").fetchone()
        if not admin:
            db.execute(
                "INSERT INTO users (email, name, role, password) VALUES (?, ?, ?, ?)",
                ("admin@smarthostel.ai", "Chief Warden", "admin", generate_password_hash("admin123"))
            )
            db.execute(
                "INSERT INTO users (email, name, role, password) VALUES (?, ?, ?, ?)",
                ("maleadmin@hostel.com", "Male Admin", "admin", generate_password_hash("Male@123"))
            )
            db.execute(
                "INSERT INTO users (email, name, role, password) VALUES (?, ?, ?, ?)",
                ("femaleadmin@hostel.com", "Female Admin", "admin", generate_password_hash("Female@123"))
            )
            db.commit()

        # Seed Rooms if empty
        room_count = db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        if room_count == 0:
            for block, start in (("A", 100), ("B", 200)):
                floor = start // 100
                for offset in range(100):
                    room_id = start + offset
                    if offset % 10 == 4:
                        room_type = "Single"
                        capacity = 1
                    elif offset % 3 == 0:
                        room_type = "3 Sharing"
                        capacity = 3
                    elif offset % 5 == 0:
                        room_type = "4 Sharing"
                        capacity = 4
                    else:
                        room_type = "2 Sharing"
                        capacity = 2

                    occupied = 0
                    status = "Available"
                    if offset in {1, 8, 14, 21, 55, 77, 88}:
                        occupied = capacity
                        status = "Full"
                    elif offset in {6, 18, 44, 99}:
                        status = "Maintenance"
                    elif offset in {0, 5, 11, 17, 23, 66}:
                        occupied = max(1, capacity - 1)

                    db.execute(
                        "INSERT INTO rooms (block, floor, room_number, type, capacity, occupied, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (block, floor, room_id, room_type, capacity, occupied, status)
                    )
            db.commit()

# Delete DB in development mode to refresh schema if needed
if os.environ.get("FLASK_ENV") == "development":
    if os.path.exists(DATABASE):
        os.remove(DATABASE)

init_db()


def get_admin_scope(email):
    if email == "maleadmin@hostel.com":
        return {"block": "A", "gender": "Male", "label": "Male Admin Dashboard", "audience": "Boys Hostel"}
    if email == "femaleadmin@hostel.com":
        return {"block": "B", "gender": "Female", "label": "Female Admin Dashboard", "audience": "Girls Hostel"}
    return {"block": None, "gender": None, "label": "Chief Admin Dashboard", "audience": "All Hostels"}


def student_block(gender):
    return "A" if gender == "Male" else "B"


def fee_amount_for_room(room_type):
    if not room_type:
        return 0
    if "Single" in room_type or "1 Sharing" in room_type:
        return 144000
    if "2 Sharing" in room_type:
        return 90000
    if "3 Sharing" in room_type:
        return 80000
    if "4 Sharing" in room_type:
        return 70000
    return 0


def log_notification(student_email, channel, recipient, message, status, provider):
    with get_db() as db:
        db.execute(
            "INSERT INTO notification_logs (student_email, channel, recipient, message, status, provider, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (student_email, channel, recipient, message, status, provider, datetime.now().strftime("%d %b %Y, %I:%M %p"))
        )
        db.commit()

def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "user_email" not in session:
                flash("Please login to continue.", "warning")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped_view
    return decorator


def classify_complaint(text):
    lowered = text.lower()
    categories = {
        "Electrical": ["power", "electric", "fan", "light", "switch"],
        "Plumbing": ["water", "tap", "leak", "bathroom", "pipe"],
        "Network": ["wifi", "wi-fi", "internet", "network"],
        "Security": ["theft", "unknown", "unsafe", "fight", "emergency"],
        "Hygiene": ["clean", "dirty", "dust", "garbage", "smell"],
    }

    category = "General"
    for label, keywords in categories.items():
        if any(keyword in lowered for keyword in keywords):
            category = label
            break

    urgent_words = ["emergency", "unsafe", "fire", "leak", "theft", "no water", "spark"]
    priority = "Critical" if any(word in lowered for word in urgent_words) else "Medium"
    if category in {"Security", "Electrical"} and priority != "Critical":
        priority = "High"

    sentiment = "Urgent" if priority == "Critical" else "Concerned"
    return category, priority, sentiment


def build_qr_payload(allocation, user_name):
    return (
        f"SmartHostel AI Pass\n"
        f"Pass ID: {allocation['pass_id']}\n"
        f"Student: {user_name}\n"
        f"Room: {allocation['block']}-{allocation['room_number']}\n"
        f"Allocated: {allocation['allocated_at']}"
    )


def build_allocation_email_body(allocation, user_name):
    return (
        f"Hello {user_name},\n\n"
        "Your hostel room has been successfully allocated.\n\n"
        f"Room: {allocation['block']}-{allocation['room_number']}\n"
        f"Floor: {allocation['floor']}\n"
        f"Room Type: {allocation['type']}\n"
        f"Pass ID: {allocation['pass_id']}\n"
        f"Allocated At: {allocation['allocated_at']}\n\n"
        "You can now log in to view details and access your QR pass.\n\n"
        "This is an automated SmartHostelAI message.\n"
    )


def build_allocation_email_html(allocation, user_name):
    safe_name = html.escape(str(user_name))
    room_label = html.escape(f"{allocation['block']}-{allocation['room_number']}")
    floor = html.escape(str(allocation["floor"]))
    room_type = html.escape(str(allocation["type"]))
    pass_id = html.escape(str(allocation["pass_id"]))
    allocated_at = html.escape(str(allocation["allocated_at"]))
    return f"""
    <div style="margin:0;padding:0;background:#f6f7fb;font-family:Inter,Arial,sans-serif;color:#111827;">
      <div style="max-width:640px;margin:0 auto;padding:32px 20px;">
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;overflow:hidden;">
          <div style="padding:28px 30px;background:#111827;color:#ffffff;">
            <div style="font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#c4b5fd;font-weight:700;">SmartHostelAI</div>
            <h1 style="margin:10px 0 0;font-size:26px;line-height:1.25;">Room allocation confirmed</h1>
          </div>
          <div style="padding:30px;">
            <p style="margin:0 0 18px;font-size:16px;line-height:1.6;">Hello {safe_name},</p>
            <p style="margin:0 0 24px;font-size:16px;line-height:1.6;">Your hostel room has been successfully allocated. Your QR pass is attached to this email.</p>
            <table style="width:100%;border-collapse:collapse;margin:0 0 26px;">
              <tr><td style="padding:12px;border-bottom:1px solid #eef2f7;color:#6b7280;">Room</td><td style="padding:12px;border-bottom:1px solid #eef2f7;font-weight:700;">{room_label}</td></tr>
              <tr><td style="padding:12px;border-bottom:1px solid #eef2f7;color:#6b7280;">Floor</td><td style="padding:12px;border-bottom:1px solid #eef2f7;font-weight:700;">{floor}</td></tr>
              <tr><td style="padding:12px;border-bottom:1px solid #eef2f7;color:#6b7280;">Room Type</td><td style="padding:12px;border-bottom:1px solid #eef2f7;font-weight:700;">{room_type}</td></tr>
              <tr><td style="padding:12px;border-bottom:1px solid #eef2f7;color:#6b7280;">Pass ID</td><td style="padding:12px;border-bottom:1px solid #eef2f7;font-weight:700;">{pass_id}</td></tr>
              <tr><td style="padding:12px;color:#6b7280;">Allocated At</td><td style="padding:12px;font-weight:700;">{allocated_at}</td></tr>
            </table>
            <a href="{os.getenv('SMART_HOSTEL_APP_URL', '#')}" style="display:inline-block;background:#111827;color:#ffffff;text-decoration:none;padding:13px 18px;border-radius:999px;font-weight:700;">Login to SmartHostelAI</a>
            <p style="margin:26px 0 0;color:#6b7280;font-size:13px;line-height:1.6;">Need help? Contact your hostel office and share your Pass ID. This is an automated message.</p>
          </div>
        </div>
      </div>
    </div>
    """


def build_qr_png(allocation, user_name):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(build_qr_payload(allocation, user_name))
    qr.make(fit=True)
    image = qr.make_image(fill_color="#050914", back_color="#f4fbff")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_qr_data_uri(allocation, user_name):
    encoded = base64.b64encode(build_qr_png(allocation, user_name)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_qr_attachment(allocation, user_name):
    qr_png = build_qr_png(allocation, user_name)
    return {
        "filename": f"{allocation['pass_id']}_QR_Pass.png",
        "content": base64.b64encode(qr_png).decode("ascii"),
    }


def get_resend_api_key():
    key = os.getenv("SMART_HOSTEL_RESEND_API_KEY") or os.getenv("RESEND_API_KEY")
    return key.strip() if key else None


def is_resend_configured():
    return bool(get_resend_api_key())


def send_allocation_email(allocation, user_name, user_email):
    api_key = get_resend_api_key()
    smtp_pass = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMART_HOSTEL_MAIL_FROM", "SmartHostel AI <onboarding@resend.dev>")

    if not api_key and not smtp_pass:
        return {"sent": False, "provider": "none", "reason": "Set RESEND_API_KEY or SMTP_PASSWORD in environment variables"}

    subject = "Room Allocation - SmartHostelAI"
    body = build_allocation_email_body(allocation, user_name)
    html_body = build_allocation_email_html(allocation, user_name)
    
    if smtp_pass:
        # Use SMTP
        smtp_user = os.getenv("SMTP_USER", sender)
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "465"))
        
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = sender if ' ' not in sender else f"{sender.split('<')[0].strip()} <{smtp_user}>"
        msg['To'] = user_email
        
        msg.attach(MIMEText(body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        qr_png = build_qr_png(allocation, user_name)
        img = MIMEImage(qr_png, name=f"{allocation['pass_id']}_QR_Pass.png")
        msg.attach(img)
        
        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()
            return {"sent": True, "reason": "Email sent via SMTP", "provider": "smtp", "message_id": "smtp-success"}
        except Exception as exc:
            print(f"SMTP Error: {exc}")
            return {"sent": False, "provider": "smtp", "reason": str(exc)}

    # Fallback to Resend API
    qr_attachment = build_qr_attachment(allocation, user_name)
    payload = {
        "from": sender,
        "to": [user_email],
        "subject": subject,
        "text": body,
        "html": html_body,
        "attachments": [qr_attachment],
    }

    try:
        request_payload = json.dumps(payload).encode("utf-8")
        resend_request = urllib.request.Request(
            "https://api.resend.com/emails",
            data=request_payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "SmartHostelAI/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(resend_request, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            response_data = json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as exc:
        error_detail = exc.read().decode("utf-8", errors="replace") or str(exc)
        print(f"Resend Error: {error_detail}")
        return {"sent": False, "provider": "resend", "reason": error_detail}
    except urllib.error.URLError as exc:
        print(f"Resend Error: {exc}")
        return {"sent": False, "provider": "resend", "reason": str(exc)}
    except Exception as exc:
        print(f"Email Error: {exc}")
        return {"sent": False, "provider": "resend", "reason": str(exc)}

    return {"sent": True, "reason": "Email sent via Resend", "provider": "resend", "message_id": response_data.get("id", "")}


def build_whatsapp_allocation_message(allocation, user_name):
    return (
        f"SmartHostelAI room allocation update\n"
        f"Hello {user_name}, your hostel room has been allocated.\n"
        f"Room: Block {allocation['block']}, Room {allocation['room_number']}\n"
        f"Floor: {allocation['floor']}\n"
        f"Room Type: {allocation['type']}\n"
        f"Pass ID: {allocation['pass_id']}\n"
        f"Allocated At: {allocation['allocated_at']}\n\n"
        "Reply HELP for commands, ROOM for room details, FEES for fee status, NOTICE for latest notice, or COMPLAINT followed by your issue."
    )


def send_whatsapp_message(student_email, phone, message):
    if not phone:
        return {"sent": False, "provider": "twilio", "reason": "Phone number not available", "skipped": True}

    sid = os.getenv("SMART_HOSTEL_TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("SMART_HOSTEL_TWILIO_AUTH_TOKEN", "").strip()
    sender = os.getenv("SMART_HOSTEL_TWILIO_WHATSAPP_FROM", "").strip()

    if not sid or not token or not sender:
        return {"sent": False, "provider": "twilio", "reason": "WhatsApp not configured", "skipped": True}

    destination = phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"
    data = urllib.parse.urlencode({"From": sender, "To": destination, "Body": message}).encode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    request_data = urllib.request.Request(url, data=data)
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    request_data.add_header("Authorization", f"Basic {auth}")

    try:
        with urllib.request.urlopen(request_data, timeout=15) as response:
            response.read()
    except Exception as exc:
        log_notification(student_email, "WhatsApp", phone, message, f"Failed: {exc}", "twilio")
        return {"sent": False, "provider": "twilio", "reason": str(exc)}

    log_notification(student_email, "WhatsApp", phone, message, "Sent", "twilio")
    return {"sent": True, "provider": "twilio", "reason": "WhatsApp sent"}


def can_admin_manage_student(admin_email, student_gender):
    admin_scope = get_admin_scope(admin_email)
    return not admin_scope["gender"] or admin_scope["gender"] == student_gender


@app.route("/")
def index():
    with get_db() as db:
        total_capacity = db.execute("SELECT SUM(capacity) FROM rooms").fetchone()[0] or 0
        occupied = db.execute("SELECT SUM(occupied) FROM rooms").fetchone()[0] or 0
        open_complaints = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Open'").fetchone()[0] or 0
        threat_count = db.execute("SELECT COUNT(*) FROM audit_logs WHERE risk='High'").fetchone()[0] or 0
        
    return render_template(
        "index.html",
        total_capacity=total_capacity,
        occupied=occupied,
        open_complaints=open_complaints,
        threat_count=threat_count,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if not user or not check_password_hash(user["password"], password):
                if user:
                    db.execute("UPDATE users SET failed_attempts = failed_attempts + 1 WHERE email = ?", (email,))
                    db.commit()
                flash("Invalid credentials.", "danger")
                return redirect(url_for("login"))

            db.execute("UPDATE users SET failed_attempts = 0 WHERE email = ?", (email,))
            db.execute("INSERT INTO audit_logs (time, event, risk) VALUES (?, ?, ?)", 
                      (datetime.now().strftime("%H:%M"), f"{user['role'].title()} login successful", "Low"))
            db.commit()
            
            session["user_email"] = user["email"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        dob = request.form.get("dob", "").strip()
        gender = request.form.get("gender", "").strip()
        degree = request.form.get("degree", "").strip()

        if gender not in {"Male", "Female"}:
            flash("Please select Male or Female for hostel allocation.", "warning")
            return redirect(url_for("register"))

        if not name or not email or not password or not phone or not dob or not gender or not degree:
            flash("All fields (Name, Email, Phone, Password, DOB, Gender, Degree) are required.", "warning")
            return redirect(url_for("register"))
            
        import re
        if len(password) < 6 or not re.search(r"[A-Z]", password) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            flash("Password must be at least 6 characters, include 1 uppercase and 1 special character.", "warning")
            return redirect(url_for("register"))

        with get_db() as db:
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                flash("This email is already registered. Please login.", "warning")
                return redirect(url_for("login"))

            db.execute("INSERT INTO users (email, name, role, password) VALUES (?, ?, ?, ?)",
                       (email, name, "student", generate_password_hash(password)))
            db.execute("INSERT INTO students (email, password, phone, dob, gender, degree) VALUES (?, ?, ?, ?, ?, ?)",
                       (email, generate_password_hash(password), phone, dob, gender, degree))
            db.execute("INSERT INTO audit_logs (time, event, risk) VALUES (?, ?, ?)", 
                      (datetime.now().strftime("%H:%M"), f"New student registered: {name}", "Low"))
            db.commit()
            
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out securely.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required()
def dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("student_dashboard"))


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    with get_db() as db:
        admin_email = session.get("user_email")
        admin_scope = get_admin_scope(admin_email)
        block_filter = admin_scope["block"]

        if block_filter:
            rooms = db.execute("SELECT * FROM rooms WHERE block = ?", (block_filter,)).fetchall()
            students_count = db.execute("SELECT COUNT(*) FROM allocations a JOIN students s ON a.student_email = s.email WHERE s.gender = ?", (admin_scope["gender"],)).fetchone()[0]
            requests_query = db.execute("""
                SELECT r.*, u.name, s.gender, s.phone
                FROM requests r 
                JOIN users u ON r.student_email = u.email 
                JOIN students s ON u.email = s.email
                WHERE r.status = 'Pending' AND s.gender = ?
            """, (admin_scope["gender"],)).fetchall()
            open_complaints = db.execute("""
                SELECT c.* FROM complaints c
                JOIN students s ON c.student_email = s.email
                WHERE c.status = 'Open' AND s.gender = ?
                ORDER BY c.id DESC
            """, (admin_scope["gender"],)).fetchall()
            allocations = db.execute("""
                SELECT a.id, a.student_email, a.pass_id, a.allocated_at, u.name, s.gender, r.block, r.floor, r.room_number, r.type
                FROM allocations a
                JOIN users u ON a.student_email = u.email
                JOIN students s ON a.student_email = s.email
                JOIN rooms r ON a.room_id = r.id
                WHERE s.gender = ?
                ORDER BY a.id DESC
                LIMIT 8
            """, (admin_scope["gender"],)).fetchall()
        else:
            rooms = db.execute("SELECT * FROM rooms").fetchall()
            students_count = db.execute("SELECT COUNT(*) FROM allocations").fetchone()[0]
            requests_query = db.execute("""
                SELECT r.*, u.name, s.gender, s.phone
                FROM requests r 
                JOIN users u ON r.student_email = u.email 
                JOIN students s ON u.email = s.email
                WHERE r.status = 'Pending'
            """).fetchall()
            open_complaints = db.execute("SELECT * FROM complaints WHERE status = 'Open' ORDER BY id DESC").fetchall()
            allocations = db.execute("""
                SELECT a.id, a.student_email, a.pass_id, a.allocated_at, u.name, s.gender, r.block, r.floor, r.room_number, r.type
                FROM allocations a
                JOIN users u ON a.student_email = u.email
                JOIN students s ON a.student_email = s.email
                JOIN rooms r ON a.room_id = r.id
                ORDER BY a.id DESC
                LIMIT 8
            """).fetchall()

        total_capacity = sum(r["capacity"] for r in rooms)
        occupied_beds = sum(r["occupied"] for r in rooms)
        occupancy_rate = round((occupied_beds / total_capacity * 100), 1) if total_capacity else 0
        
        available = sum(1 for r in rooms if r["status"] == "Available")
        full = sum(1 for r in rooms if r["status"] == "Full")
        maintenance = sum(1 for r in rooms if r["status"] == "Maintenance")
        
        audit_logs = db.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 5").fetchall()
        notification_filter = request.args.get("notification_filter", "All")
        allowed_filters = {"All", "Email", "Failed", "Sent"}
        if notification_filter not in allowed_filters:
            notification_filter = "All"

        notification_sql = """
            SELECT n.* 
            FROM notification_logs n
            LEFT JOIN students s ON n.student_email = s.email
            WHERE NOT (n.channel = ? AND n.provider = ?)
        """
        notification_params = ["WhatsApp", "mock"]
        
        if block_filter:
            notification_sql += " AND s.gender = ?"
            notification_params.append(admin_scope["gender"])

        notification_conditions = []
        notification_extra_params = []
        if notification_filter == "Email":
            notification_conditions.append("n.channel = ?")
            notification_extra_params.append(notification_filter)
        elif notification_filter == "Failed":
            notification_conditions.append("n.status LIKE ?")
            notification_extra_params.append("Failed%")
        elif notification_filter == "Sent":
            notification_conditions.append("(n.status LIKE ? OR n.status LIKE ?)")
            notification_extra_params.extend(["Sent%", "Resent%"])
            
        if notification_conditions:
            notification_sql += " AND " + " AND ".join(notification_conditions)
            
        notification_params.extend(notification_extra_params)
        notification_sql += " ORDER BY n.id DESC LIMIT 8"
        notification_logs = db.execute(notification_sql, notification_params).fetchall()

    return render_template(
        "admin_dashboard.html",
        admin_scope=admin_scope,
        rooms=rooms,
        available=available,
        full=full,
        maintenance=maintenance,
        room_requests=requests_query,
        allocations=allocations,
        complaints=open_complaints,
        audit_logs=audit_logs,
        notification_logs=notification_logs,
        notification_filter=notification_filter,
        mail_configured=is_resend_configured() or bool(os.getenv("SMTP_PASSWORD")),
        analytics={
            "occupancy_rate": occupancy_rate,
            "total_students": students_count,
            "available_rooms": available,
            "open_complaints": len(open_complaints)
        }
    )


def get_student_allocation(student_email):
    with get_db() as db:
        return db.execute("""
            SELECT a.*, r.block, r.floor, r.room_number, r.type
            FROM allocations a
            JOIN rooms r ON a.room_id = r.id
            WHERE a.student_email = ?
        """, (student_email,)).fetchone()


@app.route("/student/pass")
@login_required("student")
def room_pass_page():
    allocation = get_student_allocation(session["user_email"])

    if not allocation:
        flash("No active room pass is available yet.", "warning")
        return redirect(url_for("student_dashboard"))

    alloc_dict = dict(allocation)
    qr_data_uri = build_qr_data_uri(alloc_dict, session["name"])
    return render_template("room_pass.html", allocation=allocation, qr_data_uri=qr_data_uri)


@app.route("/student/qr-pass")
@login_required("student")
def download_qr_pass():
    allocation = get_student_allocation(session["user_email"])

    if not allocation:
        flash("No active QR pass is available yet.", "warning")
        return redirect(url_for("student_dashboard"))

    qr_png = build_qr_png(dict(allocation), session["name"])
    response = app.response_class(qr_png, mimetype="image/png")
    response.headers["Content-Disposition"] = f"attachment; filename={allocation['pass_id']}_QR_Pass.png"
    return response


@app.route("/student")
@login_required("student")
def student_dashboard():
    with get_db() as db:
        allocation = get_student_allocation(session["user_email"])
        pending_request = db.execute(
            "SELECT * FROM requests WHERE student_email = ? AND status = 'Pending'",
            (session["user_email"],)
        ).fetchone()
        
        qr_data_uri = None
        if allocation:
            # We need to construct a dict for the QR builder
            alloc_dict = dict(allocation)
            qr_data_uri = build_qr_data_uri(alloc_dict, session["name"])

    return render_template(
        "student_dashboard.html",
        allocation=allocation,
        pending_request=pending_request,
        qr_data_uri=qr_data_uri
    )

@app.route("/notice_board")
@login_required("student")
def notice_board_page():
    with get_db() as db:
        notices = db.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()
    return render_template("notice_board.html", notices=notices)

@app.route("/room_change", methods=["GET"])
@login_required("student")
def room_change_page():
    with get_db() as db:
        allocation = db.execute("""
            SELECT a.*, r.block, r.floor, r.room_number, r.type
            FROM allocations a
            JOIN rooms r ON a.room_id = r.id
            WHERE a.student_email = ?
        """, (session["user_email"],)).fetchone()
    return render_template("room_change.html", allocation=allocation)


@app.route("/api/rooms")
def api_rooms():
    with get_db() as db:
        admin_email = session.get("user_email")
        block_filter = None
        if session.get("role") == "admin":
            block_filter = get_admin_scope(admin_email)["block"]
        elif session.get("role") == "student":
            student = db.execute("SELECT gender FROM students WHERE email = ?", (session["user_email"],)).fetchone()
            if student:
                block_filter = student_block(student["gender"])
        
        if block_filter:
            rooms = db.execute("SELECT id, block, room_number as id_display, type, capacity, occupied, status FROM rooms WHERE block = ?", (block_filter,)).fetchall()
        else:
            rooms = db.execute("SELECT id, block, room_number as id_display, type, capacity, occupied, status FROM rooms").fetchall()
            
        rooms_list = [dict(r) for r in rooms]
        for r in rooms_list:
            r['room_id_display'] = r['id_display']
    response = jsonify({"rooms": rooms_list})
    response.headers["Cache-Control"] = "no-store"
    return response

@app.route("/api/request-room", methods=["POST"])
@login_required("student")
def api_request_room():
    data = request.json
    room_type = data.get("room_type")
    floor = data.get("floor")
    
    with get_db() as db:
        # Check if already has a pending request
        existing = db.execute("SELECT id FROM requests WHERE student_email = ? AND status = 'Pending'", (session["user_email"],)).fetchone()
        if existing:
            return jsonify({"success": False, "message": "You already have a pending room request."})

        existing_request = db.execute("SELECT id FROM requests WHERE student_email = ?", (session["user_email"],)).fetchone()
        if existing_request:
            db.execute(
                "UPDATE requests SET room_type = ?, floor = ?, request_type = ?, reason = ?, status = ?, created_at = ? WHERE id = ?",
                (room_type, floor, "Allocation", None, "Pending", datetime.now().strftime("%d %b %Y"), existing_request["id"])
            )
        else:
            db.execute("INSERT INTO requests (student_email, room_type, floor, request_type, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (session["user_email"], room_type, floor, "Allocation", None, "Pending", datetime.now().strftime("%d %b %Y")))
            
        db.execute("INSERT INTO audit_logs (time, event, risk) VALUES (?, ?, ?)", 
                  (datetime.now().strftime("%H:%M"), f"Room request from {session['name']}", "Low"))
        db.commit()
        
    return jsonify({"success": True})


@app.route("/api/room-change", methods=["POST"])
@login_required("student")
def api_room_change():
    data = request.json
    room_type = data.get("room_type")
    floor = data.get("floor")
    reason = (data.get("reason") or "").strip()
    
    with get_db() as db:
        allocation = db.execute("SELECT id FROM allocations WHERE student_email = ?", (session["user_email"],)).fetchone()
        request_type = "Room Change" if allocation else "Allocation"
        if request_type == "Room Change" and not reason:
            return jsonify({"success": False, "message": "Please enter a reason for the room change."})
        if request_type == "Room Change" and len(reason) < 12:
            return jsonify({"success": False, "message": "Please write a clearer reason for the room change."})

        existing = db.execute("SELECT id FROM requests WHERE student_email = ? AND status = 'Pending'", (session["user_email"],)).fetchone()
        if existing:
            return jsonify({"success": False, "message": "You already have a pending room request."})

        existing_request = db.execute("SELECT id FROM requests WHERE student_email = ?", (session["user_email"],)).fetchone()
        if existing_request:
            db.execute(
                "UPDATE requests SET room_type = ?, floor = ?, request_type = ?, reason = ?, status = ?, created_at = ? WHERE id = ?",
                (room_type, floor, request_type, reason or None, "Pending", datetime.now().strftime("%d %b %Y"), existing_request["id"])
            )
        else:
            db.execute("INSERT INTO requests (student_email, room_type, floor, request_type, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (session["user_email"], room_type, floor, request_type, reason or None, "Pending", datetime.now().strftime("%d %b %Y")))
        db.execute("INSERT INTO audit_logs (time, event, risk) VALUES (?, ?, ?)", 
                  (datetime.now().strftime("%H:%M"), f"{request_type} request from {session['name']}: {reason or 'No reason required'}", "Low"))
        db.commit()
        
    return jsonify({"success": True, "message": "Your request has been submitted. Waiting for admin approval."})


@app.route("/api/approve-request/<int:req_id>", methods=["POST"])
@login_required("admin")
def api_approve_request(req_id):
    with get_db() as db:
        req = db.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
        if not req:
            return jsonify({"success": False, "message": "Request not found"})
            
        if req["status"] != "Pending":
            return jsonify({"success": False, "message": "Request already processed"})
            
        # Get student gender to enforce block rules
        student = db.execute("SELECT gender, phone FROM students WHERE email = ?", (req["student_email"],)).fetchone()
        if not student:
            return jsonify({"success": False, "message": "Student record not found."})

        admin_scope = get_admin_scope(session.get("user_email"))
        if admin_scope["gender"] and admin_scope["gender"] != student["gender"]:
            flash("This request belongs to another hostel block.", "danger")
            return redirect(url_for("admin_dashboard"))
            
        target_block = student_block(student["gender"])
        
        # Find best room
        rooms = db.execute("SELECT * FROM rooms WHERE status = 'Available' AND occupied < capacity AND block = ?", (target_block,)).fetchall()
        best_room = None
        best_score = -1
        
        for room in rooms:
            score = 0
            if room["type"] == req["room_type"]: score += 50
            if req["floor"] and str(room["floor"]) == str(req["floor"]): score += 30
            if room["occupied"] == 0: score += 10
            
            if score > best_score:
                best_score = score
                best_room = room
                
        if not best_room:
            flash(f"No suitable room available in Block {target_block} to approve this request.", "warning")
            return redirect(url_for("admin_dashboard"))
            
        existing_allocation = db.execute("SELECT room_id FROM allocations WHERE student_email = ?", (req["student_email"],)).fetchone()
        if existing_allocation and existing_allocation["room_id"] != best_room["id"]:
            old_room = db.execute("SELECT occupied FROM rooms WHERE id = ?", (existing_allocation["room_id"],)).fetchone()
            if old_room:
                old_occupied = max(0, old_room["occupied"] - 1)
                old_status = "Available"
                db.execute("UPDATE rooms SET occupied = ?, status = ? WHERE id = ?", (old_occupied, old_status, existing_allocation["room_id"]))

        same_room_reassignment = existing_allocation and existing_allocation["room_id"] == best_room["id"]

        # Allocate Room
        new_occupied = best_room["occupied"] if same_room_reassignment else best_room["occupied"] + 1
        new_status = "Full" if new_occupied >= best_room["capacity"] else "Available"
        
        db.execute("UPDATE rooms SET occupied = ?, status = ? WHERE id = ?", (new_occupied, new_status, best_room["id"]))
        
        # Safe Sequential Pass ID
        seq = db.execute("SELECT last_id FROM pass_sequence WHERE id = 1").fetchone()
        new_pass_id = seq["last_id"] + 1
        db.execute("UPDATE pass_sequence SET last_id = ? WHERE id = 1", (new_pass_id,))
        
        pass_id = str(new_pass_id)
        allocated_at = datetime.now().strftime("%d %b %Y, %I:%M %p")
        
        # Ensure no existing allocation for this student (if room change, we would handle it, but here just insert/update)
        db.execute("DELETE FROM allocations WHERE student_email = ?", (req["student_email"],))
        db.execute("INSERT INTO allocations (student_email, room_id, pass_id, allocated_at) VALUES (?, ?, ?, ?)",
                   (req["student_email"], best_room["id"], pass_id, allocated_at))
                   
        db.execute("UPDATE requests SET status = 'Approved' WHERE id = ?", (req_id,))
        db.execute("INSERT INTO audit_logs (time, event, risk) VALUES (?, ?, ?)", 
                  (datetime.now().strftime("%H:%M"), f"Room {best_room['block']}-{best_room['room_number']} allocated to {req['student_email']}", "Low"))
        db.commit()

        # Send email
        user = db.execute("SELECT name FROM users WHERE email = ?", (req["student_email"],)).fetchone()
        
        allocation_dict = {
            "pass_id": pass_id,
            "block": best_room["block"],
            "floor": best_room["floor"],
            "room_number": best_room["room_number"],
            "type": best_room["type"],
            "allocated_at": allocated_at
        }
        
        mail_status = send_allocation_email(allocation_dict, user["name"], req["student_email"])
        mail_log_status = "Sent"
        if mail_status.get("message_id"):
            mail_log_status = f"Sent: {mail_status['message_id']}"
        elif not mail_status["sent"]:
            mail_log_status = f"Failed: {mail_status['reason']}"
        log_notification(
            req["student_email"],
            "Email",
            req["student_email"],
            build_allocation_email_body(allocation_dict, user["name"]),
            mail_log_status,
            mail_status.get("provider", "resend"),
        )
        whatsapp_message = build_whatsapp_allocation_message(allocation_dict, user["name"])
        whatsapp_status = send_whatsapp_message(req["student_email"], student["phone"], whatsapp_message)
        
    if mail_status["sent"]:
        flash("Request approved! Allocation email sent with a fresh QR pass.", "success")
    else:
        flash(f"Request approved, but email was not sent: {mail_status['reason']}", "warning")
        
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/reject_request/<int:req_id>", methods=["POST"])
@login_required("admin")
def reject_request(req_id):
    with get_db() as db:
        db.execute("UPDATE requests SET status = 'Rejected' WHERE id = ?", (req_id,))
        db.commit()
    flash("Room request rejected.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/resend-allocation-email/<int:allocation_id>", methods=["POST"])
@login_required("admin")
def resend_allocation_email(allocation_id):
    with get_db() as db:
        allocation = db.execute("""
            SELECT a.*, u.name, s.gender, r.block, r.floor, r.room_number, r.type
            FROM allocations a
            JOIN users u ON a.student_email = u.email
            JOIN students s ON a.student_email = s.email
            JOIN rooms r ON a.room_id = r.id
            WHERE a.id = ?
        """, (allocation_id,)).fetchone()

        if not allocation:
            flash("Allocation not found.", "warning")
            return redirect(url_for("admin_dashboard"))

        if not can_admin_manage_student(session.get("user_email"), allocation["gender"]):
            flash("This allocation belongs to another hostel block.", "danger")
            return redirect(url_for("admin_dashboard"))

        allocation_dict = {
            "pass_id": allocation["pass_id"],
            "block": allocation["block"],
            "floor": allocation["floor"],
            "room_number": allocation["room_number"],
            "type": allocation["type"],
            "allocated_at": allocation["allocated_at"],
        }
        mail_status = send_allocation_email(allocation_dict, allocation["name"], allocation["student_email"])
        mail_log_status = "Resent"
        if mail_status.get("message_id"):
            mail_log_status = f"Resent: {mail_status['message_id']}"
        elif not mail_status["sent"]:
            mail_log_status = f"Failed: {mail_status['reason']}"
        log_notification(
            allocation["student_email"],
            "Email",
            allocation["student_email"],
            build_allocation_email_body(allocation_dict, allocation["name"]),
            mail_log_status,
            mail_status.get("provider", "resend"),
        )

    if mail_status["sent"]:
        flash("Allocation email resent with a fresh QR pass attachment.", "success")
    else:
        flash(f"Could not resend allocation email: {mail_status['reason']}", "warning")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/broadcast", methods=["POST"])
@login_required("admin")
def broadcast_notice():
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    
    if not title or not content:
        flash("Title and Content are required for broadcast.", "warning")
        return redirect(url_for("admin_dashboard"))
        
    with get_db() as db:
        db.execute("INSERT INTO notices (title, content, date) VALUES (?, ?, ?)",
                   (title, content, datetime.now().strftime("%d %b %Y, %I:%M %p")))
        db.execute("INSERT INTO audit_logs (time, event, risk) VALUES (?, ?, ?)", 
                  (datetime.now().strftime("%H:%M"), f"Admin broadcasted notice: {title}", "Low"))
        db.commit()
        
    flash("Notice broadcasted successfully.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/complaints")
@login_required()
def complaints_page():
    with get_db() as db:
        if session["role"] == "admin":
            scope = get_admin_scope(session["user_email"])
            params = []
            gender_filter = ""
            if scope["gender"]:
                gender_filter = "WHERE s.gender = ?"
                params.append(scope["gender"])
            complaints = db.execute(f"""
                SELECT c.*, u.name as student_name, r.block, r.room_number
                FROM complaints c
                JOIN users u ON c.student_email = u.email
                JOIN students s ON c.student_email = s.email
                LEFT JOIN allocations a ON c.student_email = a.student_email
                LEFT JOIN rooms r ON a.room_id = r.id
                {gender_filter}
                ORDER BY
                    CASE c.priority
                        WHEN 'Critical' THEN 0
                        WHEN 'High' THEN 1
                        WHEN 'Medium' THEN 2
                        WHEN 'Low' THEN 3
                        ELSE 4
                    END, c.id DESC
            """, params).fetchall()
        else:
            complaints = db.execute("SELECT * FROM complaints WHERE student_email = ? ORDER BY id DESC", (session["user_email"],)).fetchall()
    return render_template("complaints.html", complaints=complaints)


@app.route("/complaints", methods=["POST"])
@login_required("student")
def create_complaint():
    text = request.form.get("complaint", "").strip()
    if not text:
        flash("Complaint text cannot be empty.", "warning")
        return redirect(url_for("student_dashboard"))

    category, priority, sentiment = classify_complaint(text)
    
    with get_db() as db:
        db.execute("INSERT INTO complaints (student_email, text, category, priority, sentiment, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (session["user_email"], text, category, priority, sentiment, "Open", datetime.now().strftime("%d %b %Y")))
        db.commit()
        
    flash("AI complaint engine classified and prioritized your issue.", "success")
    return redirect(url_for("complaints_page"))


@app.route("/fees")
@login_required()
def fees_page():
    # Keep fees as a simple dummy representation for now
    fee_records = []
    with get_db() as db:
        params = []
        gender_filter = ""
        if session.get("role") == "admin":
            scope = get_admin_scope(session["user_email"])
            if scope["gender"]:
                gender_filter = "WHERE s.gender = ?"
                params.append(scope["gender"])
        elif session.get("role") == "student":
            gender_filter = "WHERE s.email = ?"
            params.append(session["user_email"])

        students = db.execute(f"""
            SELECT u.name, s.email, s.gender
            FROM students s
            JOIN users u ON s.email = u.email
            {gender_filter}
        """, params).fetchall()
        allocations = {row["student_email"]: row for row in db.execute("SELECT a.student_email, r.block, r.floor, r.room_number, r.type FROM allocations a JOIN rooms r ON a.room_id = r.id").fetchall()}
        
    for student in students:
        email = student["email"]
        alloc = allocations.get(email)
        
        amount = fee_amount_for_room(alloc["type"]) if alloc else 0
                
        paid = 30000 if email == "student@smarthostel.ai" else 0
        fee_records.append(
            {
                "email": email,
                "name": student["name"],
                "room": f"{alloc['block']}-{alloc['room_number']}" if alloc else "Pending",
                "amount": amount,
                "paid": paid,
                "due": amount - paid,
                "status": "Paid" if paid == amount else ("Partial" if paid else "Due"),
            }
        )
        
    return render_template("fees.html", fee_records=fee_records)


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming = (request.form.get("Body") or "").strip()
    from_number = (request.form.get("From") or "").replace("whatsapp:", "").strip()
    command, _, detail = incoming.partition(" ")
    command = command.upper()

    with get_db() as db:
        student = db.execute("SELECT s.*, u.name FROM students s JOIN users u ON s.email = u.email WHERE s.phone = ? OR s.phone = ?", (from_number, f"+{from_number.lstrip('+')}")).fetchone()
        if not student:
            reply = "SmartHostelAI: phone number not found. Please use your registered WhatsApp number."
        elif command == "ROOM":
            allocation = db.execute("""
                SELECT a.pass_id, a.allocated_at, r.block, r.floor, r.room_number, r.type
                FROM allocations a
                JOIN rooms r ON a.room_id = r.id
                WHERE a.student_email = ?
            """, (student["email"],)).fetchone()
            if allocation:
                reply = f"Room: Block {allocation['block']}, Room {allocation['room_number']}, Floor {allocation['floor']}, {allocation['type']}. Pass ID: {allocation['pass_id']}."
            else:
                reply = "SmartHostelAI: your room allocation is still pending."
        elif command == "FEES":
            allocation = db.execute("SELECT r.type FROM allocations a JOIN rooms r ON a.room_id = r.id WHERE a.student_email = ?", (student["email"],)).fetchone()
            amount = fee_amount_for_room(allocation["type"]) if allocation else 0
            paid = 30000 if student["email"] == "student@smarthostel.ai" else 0
            reply = f"Fee status: Total Rs {amount}, Paid Rs {paid}, Due Rs {amount - paid}."
        elif command == "NOTICE":
            notice = db.execute("SELECT title, content FROM notices ORDER BY id DESC LIMIT 1").fetchone()
            reply = f"Latest notice: {notice['title']} - {notice['content']}" if notice else "No active notices right now."
        elif command == "COMPLAINT" and detail.strip():
            category, priority, sentiment = classify_complaint(detail.strip())
            db.execute("INSERT INTO complaints (student_email, text, category, priority, sentiment, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (student["email"], detail.strip(), category, priority, sentiment, "Open", datetime.now().strftime("%d %b %Y")))
            db.commit()
            reply = f"Complaint logged. Category: {category}, Priority: {priority}."
        else:
            reply = "SmartHostelAI commands: ROOM, FEES, NOTICE, COMPLAINT your issue, HELP."

    return f"""<?xml version="1.0" encoding="UTF-8"?><Response><Message>{reply}</Message></Response>""", 200, {"Content-Type": "text/xml"}


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
