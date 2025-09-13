from flask import Flask, render_template, request, redirect, url_for, session, jsonify  # type: ignore
from werkzeug.security import generate_password_hash, check_password_hash  # type: ignore
from flask_session import Session
import mysql.connector.pooling  # ✅ pooling
import google.generativeai as genai  # type: ignore
import markdown  # type: ignore
import requests  # type: ignore

# -------------------
# App configuration
# -------------------
app = Flask(__name__)
app.secret_key = "your-secret-key"

# Sessions
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# -------------------
# MySQL Connection Pool
# -------------------
dbconfig = {
    "host": "localhost",
    "user": "root",
    "password": "password",
    "database": "trekking",
    "autocommit": True,
    "ssl_disabled": True
}

pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="mypool",
    pool_size=5,       # allow up to 5 simultaneous connections
    **dbconfig
)

def get_conn():
    return pool.get_connection()

# -------------------
# Helper functions
# -------------------
def fetch_one(query, params=()):
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

def fetch_all(query, params=()):
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def execute_query(query, params=()):
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    conn.commit()
    last_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return last_id

# -------------------
# Create users table if not exists
# -------------------
def create_users_table():
    conn = get_conn()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) NOT NULL UNIQUE,
            email VARCHAR(120) NOT NULL UNIQUE,
            password_hash VARCHAR(200) NOT NULL,
            number VARCHAR(20) NOT NULL,
            last_lat FLOAT NULL,
            last_lon FLOAT NULL
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

create_users_table()

# -------------------
# Google Gemini API
# -------------------
genai.configure(api_key="GEMINI_API_KEY")  # replace with your real key

# -------------------
# Routes
# -------------------
@app.route("/")
def home():
    return render_template("home.html")

# -------------------
# Login
# -------------------
@app.route("/auth/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = fetch_one("SELECT * FROM users WHERE username=%s", (username,))
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid username or password"
    return render_template("login.html", error=error)

# -------------------
# Signup
# -------------------
@app.route("/auth/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        confirm = request.form["confirmPassword"]
        number = request.form["number"]

        if password != confirm:
            error = "Passwords do not match"
        elif fetch_one("SELECT * FROM users WHERE username=%s OR email=%s", (username, email)):
            error = "User already exists"
        else:
            password_hash = generate_password_hash(password)
            execute_query(
                "INSERT INTO users (username, email, password_hash, number) VALUES (%s, %s, %s, %s)",
                (username, email, password_hash, number)
            )
            return redirect(url_for("login"))

    return render_template("signup.html", error=error)

# -------------------
# Dashboard
# -------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html")

@app.route("/dashboard/btn-page")
def button_page():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("button.html")

# -------------------
# SOS Button Route
# -------------------
@app.route("/dashboard/action/SOS")
def sos_action():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = fetch_one("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    if not user:
        return jsonify({"status": "error", "message": "User not found"})

    phone_number = user["number"]
    message = "🚨 HELP I AM IN TROUBLE 🚨\n 🏃🏻‍♂️ Message from Trekking Club 🏃🏻‍♂️"

    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = {"message": message, "language": "english", "route": "q", "numbers": phone_number}
    headers = {
        "authorization": "FAST2SMS_API_KEY",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cache-Control": "no-cache"
    }

    try:
        response = requests.post(url, data=payload, headers=headers)
        if response.status_code == 200:
            return jsonify({"status": "success", "message": "SOS sent successfully"})
        else:
            return jsonify({"status": "fail", "error": response.text})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

# -------------------
# TRACK Button Route
# -------------------
@app.route("/dashboard/action/TRACK", methods=["POST"])
def track_action():
    print("TRACK endpoint called. session user_id:", session.get("user_id"))

    if "user_id" not in session:
        return jsonify({"status": "error", "message": "Not logged in"}), 401

    data = request.get_json(force=True, silent=True)
    print("TRACK payload:", data)

    if not data:
        return jsonify({"status": "error", "message": "No JSON body received"}), 400

    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        return jsonify({"status": "error", "message": "Missing lat or lon"}), 400

    user = fetch_one("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Invalid lat/lon: {e}"}), 400

    try:
        execute_query("UPDATE users SET last_lat=%s, last_lon=%s WHERE id=%s", (lat_f, lon_f, user["id"]))
        print(f"Updated DB for user {user['id']} -> {lat_f}, {lon_f}")
    except Exception as e:
        print("DB update error:", e)
        return jsonify({"status": "error", "message": f"DB update error: {e}"}), 500

    # Generate two links
    live_page_link = url_for("public_track", user_id=user["id"], _external=True)
    google_maps_link = f"https://www.google.com/maps?q={lat_f},{lon_f}"

    # Send SMS on first request
    if request.args.get("send_sms") == "true":
        phone_number = user["number"]
        message = (
            f"📍 My Location Update:\n"
            f"Google Maps: {google_maps_link}\n"
            f"Live Tracking: {live_page_link}"
        )

        sms_url = "https://www.fast2sms.com/dev/bulkV2"
        payload = {"message": message, "language": "english", "route": "q", "numbers": phone_number}
        headers = {
            "authorization": "FAST2SMS_API_KEY",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache"
        }

        try:
            sms_resp = requests.post(sms_url, data=payload, headers=headers, timeout=15)
            print("Fast2SMS response:", sms_resp.status_code, sms_resp.text)
            if sms_resp.status_code == 200:
                return jsonify({
                    "status": "success",
                    "google_maps_link": google_maps_link,
                    "live_page_link": live_page_link
                })
            else:
                return jsonify({"status": "fail", "error": sms_resp.text}), 502
        except Exception as e:
            print("Fast2SMS exception:", e)
            return jsonify({"status": "error", "error": str(e)}), 500

    # Normal update (no SMS)
    return jsonify({
        "status": "success",
        "google_maps_link": google_maps_link,
        "live_page_link": live_page_link
    })

# -------------------
# JSON endpoint for public map
# -------------------
@app.route("/track-data/<int:user_id>")
def track_data(user_id):
    user = fetch_one("SELECT last_lat, last_lon FROM users WHERE id=%s", (user_id,))
    if not user or user["last_lat"] is None or user["last_lon"] is None:
        return jsonify({"status": "error", "message": "Location not available"}), 404
    return jsonify({"status": "success", "lat": float(user["last_lat"]), "lon": float(user["last_lon"])})

# -------------------
# Public Tracking Page
# -------------------
@app.route("/track/<int:user_id>")
def public_track(user_id):
    return render_template("track.html", user_id=user_id)

# -------------------
# Chat with Gemini
# -------------------
@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        msg = request.json.get("message")
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(msg)
            reply = markdown.markdown(response.text)
        except Exception as e:
            reply = f"<p style='color:red'>AI Error: {str(e)}</p>"
        return jsonify({"reply": reply})

    return render_template("chat.html")

# -------------------
# List Models
# -------------------
@app.route("/list-models")
def list_models():
    try:
        models = genai.list_models()
        model_names = [m.name for m in models]
        return jsonify({"available_models": model_names})
    except Exception as e:
        return jsonify({"error": str(e)})

# -------------------
# Logout
# -------------------
@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("home"))

# -------------------
# Run the app
# -------------------
if __name__ == "__main__":
    app.run(debug=True, port=3000)
