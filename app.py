import os
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change_this_secret_key")

# Local uploads (optional)
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "docx"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25MB

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# Mail setup
from flask_mail import Mail, Message
app.config.update(
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
    MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "true").lower() == "true",
    MAIL_USE_SSL=os.getenv("MAIL_USE_SSL", "false").lower() == "true",
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME"),
)
mail = Mail(app)

def send_email(subject: str, recipients: list, body_text: str):
    msg = Message(subject=subject, recipients=recipients, body=body_text)
    mail.send(msg)

# Cloudinary setup
import cloudinary
import cloudinary.uploader
CLOUDINARY_URL = (os.getenv("CLOUDINARY_URL") or "").strip()
cloudinary.config(cloudinary_url=CLOUDINARY_URL, secure=True)

def upload_to_cloudinary(local_path: str, public_id: str | None = None, resource_type: str = "raw"):
    """
    Upload PDFs/DOCX to Cloudinary as resource_type='raw' and return (secure_url, public_id).
    """
    options = {
        "resource_type": resource_type,
        "unique_filename": True,
        "use_filename": True,
        "overwrite": False,
    }
    if public_id:
        options["public_id"] = public_id
    result = cloudinary.uploader.upload(local_path, **options)
    return result.get("secure_url"), result.get("public_id")

# UNID mapping
EMAIL_UNID_MAP = {
    "indira2005bhattacharjee@gmail.com": "E2R/INT/2025/08/001",
    "shwetpurwar0911@gmail.com": "E2R/INT/2025/08/002",
    "info@e2r-online.com": "E2R-HR",
    "kumar07shashank@gmail.com":"-INSIDER",
    "purwar07khushboo@gmail.com":"-INSIDER",
}

def derive_unid_from_email(email: str) -> str:
    e = (email or "").strip().lower()
    return EMAIL_UNID_MAP.get(e, "")

# Attendance from CSVs
import pandas as pd

JUNE_CSV = Path(__file__).with_name("EGS-ATTENDENCE-INTERNS-Honour-Score-June.csv")
JULY_CSV = Path(__file__).with_name("EGS-ATTENDENCE-INTERNS-Honour-Score-July.csv")

def read_month_csv(month: str, person: str):
    csv_path = JUNE_CSV if month == "June" else JULY_CSV
    if not csv_path.exists():
        return {"rows": [], "totals": {"working_days": None, "attended_days": None, "final_honour_score": ""}}

    try:
        # Skip first 3 rows (banner + empty)
        df = pd.read_csv(csv_path, skiprows=3, dtype=str, keep_default_na=False)
        # Drop unnamed first column if it's empty
        if df.columns[0].strip() == "" or df.columns[0].lower().startswith("unnamed"):
            df.drop(df.columns[0], axis=1, inplace=True)
        # Strip spaces from column names
        df.columns = [c.strip() for c in df.columns]
    except Exception:
        return {"rows": [], "totals": {"working_days": None, "attended_days": None, "final_honour_score": ""}}

    # Map columns
    def get_col(name):
        for col in df.columns:
            if col.lower() == name.lower():
                return col
        return None

    date_col = get_col("Date")
    if person == "Indira":
        att_col = get_col("Indira Attendance")
        honor_col = get_col("Indira Honour Score")
    else:
        att_col = get_col("Shwet Attendance")
        honor_col = get_col("Shwet Honour Score")

    minutes_col = None
    for col in df.columns:
        if "minutes" in col.lower():
            minutes_col = col
            break

    if date_col is None or att_col is None:
        return {"rows": [], "totals": {"working_days": None, "attended_days": None, "final_honour_score": ""}}

    rows = []
    total_row = None
    for _, r in df.iterrows():
        date_val = (r.get(date_col) or "").strip()
        if not date_val:
            continue
        if "total" in date_val.lower() and "day" in date_val.lower():
            total_row = r
            continue
        att_val = (r.get(att_col) or "").strip()
        try:
            present_int = int(float(att_val)) if att_val else 0
        except:
            present_int = 0
        minutes_val = r.get(minutes_col, "").strip() if minutes_col else ""
        rows.append({
            "date": date_val,
            "present_status": "Yes" if present_int == 1 else "No",
            "minutes": minutes_val
        })

    working_days = attended_days = None
    final_honour_score = ""
    if total_row is not None:
        m = re.search(r"(\d+)\s*Days?", (total_row.get(date_col) or ""), re.IGNORECASE)
        if m:
            working_days = int(m.group(1))
        try:
            attended_days = int(float(total_row.get(att_col) or 0))
        except:
            attended_days = None
        final_honour_score = (total_row.get(honor_col) or "").strip()

    return {
        "rows": rows,
        "totals": {
            "working_days": working_days,
            "attended_days": attended_days,
            "final_honour_score": final_honour_score
        }
    }


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/get-unid", methods=["POST"])
def get_unid():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    unid = derive_unid_from_email(email)
    return jsonify({"unid": unid})

@app.route("/progress", methods=["POST"])
def progress():
    email = (request.form.get("p_email") or "").strip()
    unid = (request.form.get("p_unid") or "").strip()
    month = (request.form.get("p_month") or "").strip()

    expected_unid = derive_unid_from_email(email)
    if not expected_unid or expected_unid != unid:
        flash("Invalid email and UNID combination.", "error")
        return redirect(url_for("home") + "#progress")

    person = "Indira" if expected_unid.endswith("001") else "Shwet"

    if month in ("June", "July"):
        return redirect(url_for("attendance_page", month=month, person=person))
    elif month == "Final Evaluation (combined)":
        return redirect(url_for("final_evaluation_page"))
    else:
        flash("Please select a valid option.", "error")
        return redirect(url_for("home") + "#progress")

@app.route("/attendance", methods=["GET"])
def attendance_page():
    month = request.args.get("month", "").strip()
    person = request.args.get("person", "").strip()
    if month not in ("June", "July") or person not in ("Indira", "Shwet"):
        flash("Invalid attendance request.", "error")
        return redirect(url_for("home") + "#progress")

    data = read_month_csv(month, person)
    return render_template("attendance.html", person=person, month=month, rows=data["rows"], totals=data["totals"])

@app.route("/final-evaluation", methods=["GET"])
def final_evaluation_page():
    indira = {"title": "EGS Internship June–July", "name": "Indira Bhattacharjee", "code": "INT/001", "assignment": 10.0, "punctuality": 10.0, "attendance": 10.0, "problem_solving": 9.6, "presentation": 9.2, "total": 9.76, "grade": "A*", "remark": "Excellent Performer."}
    shwet = {"title": "EGS Internship June–July", "name": "Shwet Purwar", "code": "INT/002", "assignment": 7.0, "punctuality": 7.4, "attendance": 8.3, "problem_solving": 9.0, "presentation": 7.1, "total": 7.76, "grade": "B+", "remark": "Could be better."}
    return render_template("final_evaluation.html", indira=indira, shwet=shwet)

@app.route("/submit", methods=["POST"])
def submit():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    state = request.form.get("state", "").strip()
    district = request.form.get("district", "").strip()
    town = request.form.get("town", "").strip()
    role = request.form.get("role", "").strip()
    organization = request.form.get("organization", "").strip()
    journey = request.form.get("journey", "").strip()
    challenges = request.form.get("challenges", "").strip()
    work_again = request.form.get("work_again", "").strip()
    learnings = request.form.get("learnings", "").strip()
    unid = derive_unid_from_email(email)
    report = request.files.get("report")

    errors = []
    if not name: errors.append("Please provide your full name.")
    if not email: errors.append("Please provide your email address.")
    if not state: errors.append("Please select your state.")
    if not district: errors.append("Please enter your district.")
    if not town: errors.append("Please enter your town/city.")
    if not role: errors.append("Please indicate whether you are a student or a professional.")
    if not organization: errors.append("Please enter your organization name.")
    if not journey: errors.append("Please share your journey with E2R.")
    if not challenges: errors.append("Please describe the challenges you faced.")
    if not work_again: errors.append("Please select if you would like to work with us again.")
    if not learnings: errors.append("Please share what you learned during the internship.")
    if not report or report.filename == "":
        errors.append("Please upload your report in PDF or DOCX format.")
    elif not allowed_file(report.filename):
        errors.append("Only PDF or DOCX files are accepted.")
    if not CLOUDINARY_URL:
        errors.append("Cloud storage is not configured. Set CLOUDINARY_URL in .env.")

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("home") + "#submit")

    base = secure_filename(report.filename)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    safe_name = f"{stamp}_{base}"
    local_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
    report.save(local_path)

    try:
        cloud_url, _ = upload_to_cloudinary(local_path, public_id=None, resource_type="raw")
    except Exception as e:
        flash(f"File saved locally, but Cloudinary upload failed: {e}", "error")
        return redirect(url_for("home") + "#submit")

    body = (
        f"New End Intern Submission\n\n"
        f"Timestamp (UTC): {datetime.utcnow().isoformat()}Z\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"UNID: {unid or '(auto-map not found)'}\n"
        f"State: {state}\n"
        f"District: {district}\n"
        f"Town/City: {town}\n"
        f"Role: {role}\n"
        f"Organization: {organization}\n"
        f"Would work again: {work_again}\n\n"
        f"Journey with E2R:\n{journey}\n\n"
        f"Challenges faced:\n{challenges}\n\n"
        f"Key learnings:\n{learnings}\n\n"
        f"Media uploaded (Cloudinary): {cloud_url}\n"
    )

    try:
        send_email("E2R End Intern Submission (Cloud link + UNID)",[
        "shwetpurwar0911@gmail.com",
        "info@e2r-online.com",
        "kumar07shashank@gmail.com",
        "purwar07khushboo@gmail.com"],body)

        flash("Submission received and uploaded to cloud. Note: once submitted, it cannot be changed.", "success")
    except Exception as e:
        flash(f"Uploaded to cloud, but email failed: {e}", "error")

    return redirect(url_for("home") + "#submit")

if __name__ == "__main__":
    app.run(debug=True)
