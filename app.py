"""
Portus Community — Dashboard Backend (single-collection edition)
-------------------------------------------------------------------
Everything lives in ONE MongoDB collection: PORTUS.USERS

Every member is one document. Two special "system" documents (identified
by USERNAME "_NEWS_BOARD" and "_BADGES_CATALOG") hold organization-wide
data — news posts and the badge catalog — so you never need a second
collection.

Local dev URLs (already wired into the templates):
    Backend:  http://127.0.0.1:5050
    Frontend: http://127.0.0.1:5500/index.html

Document shape (one member):
{
  "USERNAME": "SEA",
  "PASSWORD": "123",              # plaintext to keep manual DB entry easy;
                                   # swap to a hash before going to production
  "ROLE": "admin" | "user",
  "POSITION": "Frontend Lead",
  "IS_ACTIVE": true,
  "JOINED_AT": "12-08-2026 10:00",
  "LAST_ACTIVE": "12-08-2026 10:00",
  "PROFILE": { "BIO": "", "GITHUB": "", "LINKEDIN": "", "WEBSITE": "", "PHONE": "" },
  "ATTENDANCE": { "ATT1": { "SESSION_NAME": "...", "DATE": "...", "STATUS": "Present", "MARKED_BY": "SEA" } },
  "APPLICATION": { "APP1": { "TYPE": "Leave", "SUBJECT": "...", "STATEMENT": "...", "STATUS": "Under Review", "SUBMITTED_AT": "...", "ADMIN_NOTES": "" } },
  "CONTRIBUTIONS": { "C1": { "TITLE": "...", "DESCRIPTION": "...", "LINK": "", "STATUS": "Pending", "SUBMITTED_AT": "..." } },
  "EXPERIENCE": { "TENURE": "6 Months", "ISSUE_DATE": "...", "KEY_ACHIEVEMENTS": ["..."], "VERIFICATION_CODE": "AB12CD" },
  "BADGES": ["Founding Member"],
  "REPORTS": { "R1": { "CATEGORY": "Technical", "DETAILS": "...", "STATUS": "Open", "CREATED_AT": "..." } }
}

System documents:
{ "USERNAME": "_NEWS_BOARD", "POSTS": { "N1": { "TITLE": "...", "CONTENT": "...", "AUTHOR": "SEA", "CREATED_AT": "..." } } }
{ "USERNAME": "_BADGES_CATALOG", "CATALOG": { "Founding Member": "Joined during Portus's early days." } }
"""
import os
from dotenv import load_dotenv
load_dotenv()  # reads backend/.env automatically so MONGO_URI, SECRET_KEY, etc. don't need manual export
import secrets
from datetime import datetime

import flask
from flask import session, request, jsonify, render_template
from flask_cors import CORS
from pymongo import MongoClient
from functools import wraps

app = flask.Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "portus_dev_secret_change_me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_PATH"] = "/"
app.config["SESSION_REFRESH_EACH_REQUEST"] = True

# Local dev: frontend runs on http://127.0.0.1:5500, backend on :5050 — different
# ports count as different origins, so CORS + credentials must be explicit.
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:5500")
API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:5050")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        f"{FRONTEND_ORIGIN},{API_BASE},https://portus-dashboard.netlify.app,https://portus-api-backend.vercel.app",
    ).split(",")
    if origin.strip()
]
CORS(
    app,
    supports_credentials=True,
    origins=ALLOWED_ORIGINS,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)

@app.after_request
def after_request(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(MONGO_URI)
db = client["PORTUS"]
users_col = db["USERS"]

NEWS_DOC_ID = "_NEWS_BOARD"
BADGES_DOC_ID = "_BADGES_CATALOG"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ts():
    return datetime.now().strftime("%d-%m-%Y %H:%M")


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return "<h3>Unauthorized. Please log in first.</h3>", 401
        return view_func(*args, **kwargs)
    return wrapped


def admin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return "<h3>Unauthorized. Please log in first.</h3>", 401
        if session.get("role") != "admin":
            return "<h3>Admins only.</h3>", 403
        return view_func(*args, **kwargs)
    return wrapped


def get_current_user():
    return users_col.find_one({"USERNAME": session.get("username")})


def get_news_doc():
    doc = users_col.find_one({"USERNAME": NEWS_DOC_ID})
    if not doc:
        doc = {"USERNAME": NEWS_DOC_ID, "POSTS": {}}
        users_col.insert_one(doc)
    return doc


def get_badges_doc():
    doc = users_col.find_one({"USERNAME": BADGES_DOC_ID})
    if not doc:
        doc = {"USERNAME": BADGES_DOC_ID, "CATALOG": {}}
        users_col.insert_one(doc)
    return doc


def all_members():
    """Real members only — excludes the two system documents."""
    return list(users_col.find({"USERNAME": {"$nin": [NEWS_DOC_ID, BADGES_DOC_ID]}}))


def nav_context():
    user = get_current_user()
    return {
        "user_name": session.get("username"),
        "role": session.get("role", "user"),
        "position": (user or {}).get("POSITION", "Member"),
        "frontend_origin": FRONTEND_ORIGIN,
        "api_base": API_BASE,
    }


@app.before_request
def track_activity():
    username = session.get("username")
    if username:
        users_col.update_one({"USERNAME": username}, {"$set": {"LAST_ACTIVE": ts()}})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return "Portus API is running."


@app.route("/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS":
        response = app.make_response("")
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", FRONTEND_ORIGIN)
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = users_col.find_one({"USERNAME": username})
    if not user or user.get("PASSWORD") != password or not user.get("IS_ACTIVE", True):
        response = jsonify({"error": "Invalid credentials."})
        response.status_code = 401
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", FRONTEND_ORIGIN)
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    session["username"] = username
    session["role"] = user.get("ROLE", "user")
    users_col.update_one({"USERNAME": username}, {"$set": {"LAST_ACTIVE": ts()}})

    response = jsonify({"success": True, "username": username, "role": session["role"]})
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", FRONTEND_ORIGIN)
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"}), 200


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def render_dashboard():
    user = get_current_user()
    ctx = nav_context()

    att = (user or {}).get("ATTENDANCE", {})
    present = sum(1 for a in att.values() if a.get("STATUS") == "Present")
    total = len(att)
    attendance_rate = round((present / total * 100), 1) if total else 0

    badges_doc = get_badges_doc()
    my_badge_names = (user or {}).get("BADGES", [])
    my_badges = [{"name": n, "description": badges_doc.get("CATALOG", {}).get(n, "")} for n in my_badge_names]

    stats = {
        "attendance_rate": attendance_rate,
        "badge_count": len(my_badge_names),
        "contribution_count": len((user or {}).get("CONTRIBUTIONS", {})),
    }

    admin_stats = None
    if ctx["role"] == "admin":
        members = all_members()
        pending_apps = sum(
            1 for m in members for a in m.get("APPLICATION", {}).values() if a.get("STATUS") == "Under Review"
        )
        open_reports = sum(
            1 for m in members for r in m.get("REPORTS", {}).values() if r.get("STATUS") != "Resolved"
        )
        admin_stats = {
            "total_users": len(members),
            "total_applications": pending_apps,
            "total_reports": open_reports,
        }

    return render_template("dashboard.html", stats=stats, admin_stats=admin_stats, badges=my_badges, **ctx)


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    return render_dashboard()


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
@app.route("/profile", methods=["GET"])
@login_required
def profile():
    ctx = nav_context()
    user = get_current_user()
    members = all_members() if ctx["role"] == "admin" else None
    return render_template("profile.html", profile_user=user, all_users=members, **ctx)


@app.route("/profile/update", methods=["POST"])
@login_required
def profile_update():
    data = request.get_json(silent=True) or {}
    updates = {}
    for field in ["BIO", "GITHUB", "LINKEDIN", "WEBSITE", "PHONE"]:
        key = field.lower()
        if key in data:
            updates[f"PROFILE.{field}"] = data[key]
    if not updates:
        return jsonify({"error": "Nothing to update."}), 400
    users_col.update_one({"USERNAME": session["username"]}, {"$set": updates})
    return jsonify({"success": True}), 200


@app.route("/admin/users/<username>", methods=["POST"])
@admin_required
def admin_update_user(username):
    data = request.get_json(silent=True) or {}
    updates = {}
    if "position" in data:
        updates["POSITION"] = data["position"]
    if "role" in data and data["role"] in ("admin", "user"):
        updates["ROLE"] = data["role"]
    if "new_password" in data and data["new_password"]:
        updates["PASSWORD"] = data["new_password"]
    if not updates:
        return jsonify({"error": "Nothing to update."}), 400
    users_col.update_one({"USERNAME": username}, {"$set": updates})
    return jsonify({"success": True}), 200


@app.route("/admin/users/create", methods=["POST"])
@admin_required
def admin_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or secrets.token_hex(4)
    role = data.get("role") if data.get("role") in ("admin", "user") else "user"
    position = data.get("position") or "Member"

    if not username:
        return jsonify({"error": "Username is required."}), 400
    if users_col.find_one({"USERNAME": username}):
        return jsonify({"error": "That username already exists."}), 400

    doc = {
        "USERNAME": username,
        "PASSWORD": password,
        "ROLE": role,
        "POSITION": position,
        "IS_ACTIVE": True,
        "JOINED_AT": ts(),
        "LAST_ACTIVE": ts(),
        "PROFILE": {"BIO": "", "GITHUB": "", "LINKEDIN": "", "WEBSITE": "", "PHONE": ""},
        "ATTENDANCE": {},
        "APPLICATION": {},
        "CONTRIBUTIONS": {},
        "EXPERIENCE": {},
        "BADGES": [],
        "REPORTS": {},
    }
    users_col.insert_one(doc)
    return jsonify({"success": True, "username": username, "temp_password": password}), 200


@app.route("/admin/users/<username>/delete", methods=["POST"])
@admin_required
def admin_delete_user(username):
    users_col.delete_one({"USERNAME": username})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
@app.route("/attendance", methods=["GET"])
@login_required
def attendance():
    ctx = nav_context()
    if ctx["role"] == "admin":
        records = []
        for m in all_members():
            for key, a in m.get("ATTENDANCE", {}).items():
                records.append({**a, "_key": key, "member_name": m["USERNAME"]})
        records.sort(key=lambda r: r.get("DATE", ""), reverse=True)
        members = all_members()
        return render_template("attendance.html", records=records, all_users=members, **ctx)
    else:
        user = get_current_user()
        att = (user or {}).get("ATTENDANCE", {})
        records = [{**a, "_key": k} for k, a in att.items()]
        records.sort(key=lambda r: r.get("DATE", ""), reverse=True)
        present = sum(1 for r in records if r.get("STATUS") == "Present")
        rate = round((present / len(records) * 100), 1) if records else 0
        return render_template("attendance.html", records=records, attendance_rate=rate, **ctx)


@app.route("/attendance/mark", methods=["POST"])
@admin_required
def attendance_mark():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    status = data.get("status")
    session_name = (data.get("session_name") or "").strip()

    if not username or status not in ("Present", "Absent", "Excused") or not session_name:
        return jsonify({"error": "username, valid status, and session_name are required."}), 400

    user = users_col.find_one({"USERNAME": username})
    if not user:
        return jsonify({"error": "Unknown member."}), 404

    att = user.get("ATTENDANCE", {})
    key = f"ATT{len(att) + 1}"
    entry = {"SESSION_NAME": session_name, "DATE": ts(), "STATUS": status, "MARKED_BY": session["username"]}
    users_col.update_one({"USERNAME": username}, {"$set": {f"ATTENDANCE.{key}": entry}})
    return jsonify({"success": True}), 200


@app.route("/attendance/<username>/<key>/update", methods=["POST"])
@admin_required
def attendance_update(username, key):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("Present", "Absent", "Excused"):
        return jsonify({"error": "Invalid status."}), 400
    users_col.update_one({"USERNAME": username}, {"$set": {f"ATTENDANCE.{key}.STATUS": status}})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# News (shared "_NEWS_BOARD" document)
# ---------------------------------------------------------------------------
@app.route("/news", methods=["GET"])
@login_required
def news():
    ctx = nav_context()
    doc = get_news_doc()
    posts = [{**p, "_key": k} for k, p in doc.get("POSTS", {}).items()]
    posts.sort(key=lambda p: p.get("CREATED_AT", ""), reverse=True)
    return render_template("news.html", posts=posts, **ctx)


@app.route("/news/create", methods=["POST"])
@admin_required
def news_create():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not title or not content:
        return jsonify({"error": "Title and content are required."}), 400

    doc = get_news_doc()
    key = f"N{len(doc.get('POSTS', {})) + 1}"
    entry = {"TITLE": title, "CONTENT": content, "AUTHOR": session["username"], "CREATED_AT": ts()}
    users_col.update_one({"USERNAME": NEWS_DOC_ID}, {"$set": {f"POSTS.{key}": entry}})
    return jsonify({"success": True}), 200


@app.route("/news/<key>/delete", methods=["POST"])
@admin_required
def news_delete(key):
    users_col.update_one({"USERNAME": NEWS_DOC_ID}, {"$unset": {f"POSTS.{key}": ""}})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Experience Letters
# ---------------------------------------------------------------------------
@app.route("/experience", methods=["GET"])
@login_required
def experience():
    ctx = nav_context()
    if ctx["role"] == "admin":
        letters = []
        for m in all_members():
            exp = m.get("EXPERIENCE")
            if exp:
                letters.append({**exp, "member_name": m["USERNAME"]})
        members = all_members()
        return render_template("experience.html", letters=letters, all_users=members, **ctx)
    else:
        user = get_current_user()
        letter = (user or {}).get("EXPERIENCE") or None
        return render_template("experience.html", letter=letter, **ctx)


@app.route("/experience/issue", methods=["POST"])
@admin_required
def experience_issue():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    tenure = (data.get("tenure") or "").strip()
    achievements = [a.strip() for a in (data.get("key_achievements") or []) if a.strip()]

    if not username or not tenure:
        return jsonify({"error": "username and tenure are required."}), 400

    code = secrets.token_hex(3).upper()
    doc = {"TENURE": tenure, "ISSUE_DATE": ts(), "KEY_ACHIEVEMENTS": achievements, "VERIFICATION_CODE": code}
    users_col.update_one({"USERNAME": username}, {"$set": {"EXPERIENCE": doc}})
    return jsonify({"success": True, "verification_code": code}), 200


@app.route("/experience/<username>/revoke", methods=["POST"])
@admin_required
def experience_revoke(username):
    users_col.update_one({"USERNAME": username}, {"$unset": {"EXPERIENCE": ""}})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Applications Hub
# ---------------------------------------------------------------------------
@app.route("/applications", methods=["GET"])
@login_required
def applications():
    ctx = nav_context()
    if ctx["role"] == "admin":
        apps = []
        for m in all_members():
            for key, a in m.get("APPLICATION", {}).items():
                apps.append({**a, "_key": key, "applicant_name": m["USERNAME"]})
        apps.sort(key=lambda a: a.get("SUBMITTED_AT", ""), reverse=True)
        return render_template("applications.html", apps=apps, **ctx)
    else:
        user = get_current_user()
        apps = [{**a, "_key": k} for k, a in (user or {}).get("APPLICATION", {}).items()]
        apps.sort(key=lambda a: a.get("SUBMITTED_AT", ""), reverse=True)
        return render_template("applications.html", apps=apps, **ctx)


@app.route("/applications/submit", methods=["POST"])
@login_required
def applications_submit():
    data = request.get_json(silent=True) or {}
    app_type = data.get("type")
    subject = (data.get("subject") or "").strip()
    statement = (data.get("statement") or "").strip()

    if app_type not in ("Leave", "Issue", "Role Transfer", "General") or not subject or not statement:
        return jsonify({"error": "type, subject, and statement are required."}), 400

    user = get_current_user()
    apps = (user or {}).get("APPLICATION", {})
    key = f"APP{len(apps) + 1}"
    entry = {"TYPE": app_type, "SUBJECT": subject, "STATEMENT": statement, "STATUS": "Under Review", "SUBMITTED_AT": ts()}
    users_col.update_one({"USERNAME": session["username"]}, {"$set": {f"APPLICATION.{key}": entry}})
    return jsonify({"success": True}), 200


@app.route("/applications/<username>/<key>/resolve", methods=["POST"])
@admin_required
def applications_resolve(username, key):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("Approved", "Rejected", "Under Review"):
        return jsonify({"error": "Invalid status."}), 400
    users_col.update_one(
        {"USERNAME": username},
        {"$set": {f"APPLICATION.{key}.STATUS": status, f"APPLICATION.{key}.ADMIN_NOTES": data.get("admin_notes", "")}},
    )
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Contributions
# ---------------------------------------------------------------------------
@app.route("/contributions", methods=["GET"])
@login_required
def contributions():
    ctx = nav_context()
    if ctx["role"] == "admin":
        items = []
        for m in all_members():
            for key, c in m.get("CONTRIBUTIONS", {}).items():
                items.append({**c, "_key": key, "member_name": m["USERNAME"]})
        items.sort(key=lambda c: c.get("SUBMITTED_AT", ""), reverse=True)
        return render_template("contributions.html", items=items, **ctx)
    else:
        user = get_current_user()
        items = [{**c, "_key": k} for k, c in (user or {}).get("CONTRIBUTIONS", {}).items()]
        items.sort(key=lambda c: c.get("SUBMITTED_AT", ""), reverse=True)
        return render_template("contributions.html", items=items, **ctx)


@app.route("/contributions/submit", methods=["POST"])
@login_required
def contributions_submit():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    link = (data.get("link") or "").strip()

    if not title or not description:
        return jsonify({"error": "Title and description are required."}), 400

    user = get_current_user()
    items = (user or {}).get("CONTRIBUTIONS", {})
    key = f"C{len(items) + 1}"
    entry = {"TITLE": title, "DESCRIPTION": description, "LINK": link, "STATUS": "Pending", "SUBMITTED_AT": ts()}
    users_col.update_one({"USERNAME": session["username"]}, {"$set": {f"CONTRIBUTIONS.{key}": entry}})
    return jsonify({"success": True}), 200


@app.route("/contributions/<username>/<key>/review", methods=["POST"])
@admin_required
def contributions_review(username, key):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("Pending", "Approved", "Rejected"):
        return jsonify({"error": "Invalid status."}), 400
    users_col.update_one({"USERNAME": username}, {"$set": {f"CONTRIBUTIONS.{key}.STATUS": status}})
    return jsonify({"success": True}), 200


@app.route("/contributions/<username>/<key>/delete", methods=["POST"])
@admin_required
def contributions_delete(username, key):
    users_col.update_one({"USERNAME": username}, {"$unset": {f"CONTRIBUTIONS.{key}": ""}})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Badges (shared "_BADGES_CATALOG" document + per-user BADGES array)
# ---------------------------------------------------------------------------
@app.route("/badges", methods=["GET"])
@login_required
def badges():
    ctx = nav_context()
    catalog = get_badges_doc().get("CATALOG", {})
    all_badges = [{"name": n, "description": d} for n, d in catalog.items()]

    if ctx["role"] == "admin":
        members = all_members()
        return render_template("badges.html", all_badges=all_badges, all_users=members, **ctx)
    else:
        user = get_current_user()
        earned = set((user or {}).get("BADGES", []))
        for b in all_badges:
            b["earned"] = b["name"] in earned
        return render_template("badges.html", all_badges=all_badges, **ctx)


@app.route("/badges/create", methods=["POST"])
@admin_required
def badges_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    if not name:
        return jsonify({"error": "Badge name is required."}), 400
    users_col.update_one({"USERNAME": BADGES_DOC_ID}, {"$set": {f"CATALOG.{name}": description}})
    return jsonify({"success": True}), 200


@app.route("/badges/award", methods=["POST"])
@admin_required
def badges_award():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    badge_name = data.get("badge_name")
    if not username or not badge_name:
        return jsonify({"error": "username and badge_name are required."}), 400
    users_col.update_one({"USERNAME": username}, {"$addToSet": {"BADGES": badge_name}})
    return jsonify({"success": True}), 200


@app.route("/badges/revoke", methods=["POST"])
@admin_required
def badges_revoke():
    data = request.get_json(silent=True) or {}
    users_col.update_one({"USERNAME": data.get("username")}, {"$pull": {"BADGES": data.get("badge_name")}})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@app.route("/reports", methods=["GET"])
@login_required
def reports():
    ctx = nav_context()
    if ctx["role"] == "admin":
        items = []
        for m in all_members():
            for key, r in m.get("REPORTS", {}).items():
                items.append({**r, "_key": key, "reporter_name": m["USERNAME"]})
        items.sort(key=lambda r: r.get("CREATED_AT", ""), reverse=True)
        return render_template("reports.html", items=items, **ctx)
    else:
        user = get_current_user()
        items = [{**r, "_key": k} for k, r in (user or {}).get("REPORTS", {}).items()]
        items.sort(key=lambda r: r.get("CREATED_AT", ""), reverse=True)
        return render_template("reports.html", items=items, **ctx)


@app.route("/reports/submit", methods=["POST"])
@login_required
def reports_submit():
    data = request.get_json(silent=True) or {}
    category = data.get("category")
    details = (data.get("details") or "").strip()
    if category not in ("Technical", "Behavioral", "Other") or not details:
        return jsonify({"error": "category and details are required."}), 400

    user = get_current_user()
    items = (user or {}).get("REPORTS", {})
    key = f"R{len(items) + 1}"
    entry = {"CATEGORY": category, "DETAILS": details, "STATUS": "Open", "CREATED_AT": ts()}
    users_col.update_one({"USERNAME": session["username"]}, {"$set": {f"REPORTS.{key}": entry}})
    return jsonify({"success": True}), 200


@app.route("/reports/<username>/<key>/update", methods=["POST"])
@admin_required
def reports_update(username, key):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("Open", "Investigating", "Resolved"):
        return jsonify({"error": "Invalid status."}), 400
    users_col.update_one({"USERNAME": username}, {"$set": {f"REPORTS.{key}.STATUS": status}})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# Raw Data Editor (Admin only) — since it's all one collection now, this
# just lists every document (members + the two system docs) for direct edits.
# ---------------------------------------------------------------------------
@app.route("/admin/raw", methods=["GET"])
@admin_required
def raw_data_editor():
    ctx = nav_context()
    docs = list(users_col.find({}, {"PASSWORD": 0}))
    for d in docs:
        d["_id"] = str(d["_id"])
    return render_template("raw_editor.html", docs=docs, **ctx)


@app.route("/admin/raw/<username>", methods=["POST"])
@admin_required
def raw_data_update(username):
    data = request.get_json(silent=True) or {}
    fields = data.get("fields", {})
    if not isinstance(fields, dict) or not fields:
        return jsonify({"error": "No fields to update."}), 400
    fields.pop("_id", None)
    users_col.update_one({"USERNAME": username}, {"$set": fields})
    return jsonify({"success": True}), 200


@app.route("/admin/raw/<username>/delete", methods=["POST"])
@admin_required
def raw_data_delete(username):
    users_col.delete_one({"USERNAME": username})
    return jsonify({"success": True}), 200


# ---------------------------------------------------------------------------
# AI Assistant placeholder
# ---------------------------------------------------------------------------
@app.route("/assistant", methods=["GET"])
@login_required
def assistant():
    return render_template("assistant.html", **nav_context())


@app.route("/assistant/message", methods=["POST"])
@login_required
def assistant_message():
    data = request.get_json(silent=True) or {}
    if not (data.get("message") or "").strip():
        return jsonify({"error": "Message is required."}), 400
    reply = "This is a placeholder response. Connect this endpoint to your AI provider of choice."
    return jsonify({"success": True, "reply": reply}), 200


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050)
