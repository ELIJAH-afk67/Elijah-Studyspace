from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import uuid
import os
import random
from pathlib import Path

# Configuration
DATA_FILE = "db.json"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")  # change for production

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Helper DB functions (simple JSON DB)
def init_db():
    if not Path(DATA_FILE).exists():
        data = {
            "classrooms": {}
        }
        save_db(data)

def load_db():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    # Overwrite file with pretty JSON (simple atomic technique could be added)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def generate_code():
    return "".join(str(random.randint(0, 9)) for _ in range(6))

# Initialize DB if needed
init_db()

# Simple session helpers
def current_user():
    return {
        "name": session.get("user_name"),
        "role": session.get("role"),
        "joined": session.get("joined_classrooms", [])
    }

# Routes
@app.route("/")
def index():
    db = load_db()
    # featured public classrooms: first 5
    public = [c for c in db["classrooms"].values() if c["visibility"] == "Public"]
    featured = public[:5]
    return render_template("index.html", featured=featured, user=current_user())

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role")
        if not name or role not in ("Teacher", "Student"):
            flash("Please provide a name and role.", "warning")
            return redirect(url_for("login"))
        session["user_name"] = name
        session["role"] = role
        session.setdefault("joined_classrooms", [])
        flash(f"Logged in as {name} ({role})", "success")
        if role == "Teacher":
            return redirect(url_for("teacher_dashboard"))
        return redirect(url_for("index"))
    return render_template("login.html", user=current_user())

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("index"))

@app.route("/teacher/dashboard")
def teacher_dashboard():
    user = current_user()
    if user["role"] != "Teacher" or not user["name"]:
        flash("Teacher access only. Please log in as a teacher.", "warning")
        return redirect(url_for("login"))
    db = load_db()
    # classrooms created by this teacher
    mine = [c for c in db["classrooms"].values() if c["teacher_name"] == user["name"]]
    return render_template("teacher_dashboard.html", classrooms=mine, user=user)

@app.route("/create_classroom", methods=["POST"])
def create_classroom():
    user = current_user()
    if user["role"] != "Teacher" or not user["name"]:
        flash("Teacher access only.", "warning")
        return redirect(url_for("login"))
    name = request.form.get("classroom_name", "Untitled Classroom").strip()
    visibility = request.form.get("visibility", "Private")
    cid = str(uuid.uuid4())
    code = generate_code() if visibility == "Private" else ""
    classroom = {
        "id": cid,
        "name": name,
        "teacher_name": user["name"],
        "visibility": "Private" if visibility != "Public" else "Public",
        "code": code,
        "announcements": [],
        "lessons": [],
        "assignments": []
    }
    db = load_db()
    db["classrooms"][cid] = classroom
    save_db(db)
    flash(f"Classroom '{name}' created.", "success")
    return redirect(url_for("teacher_dashboard"))

@app.route("/public")
def public_directory():
    db = load_db()
    public = [c for c in db["classrooms"].values() if c["visibility"] == "Public"]
    return render_template("public_directory.html", classrooms=public, user=current_user())

@app.route("/classroom/<class_id>", methods=["GET", "POST"])
def classroom_page(class_id):
    db = load_db()
    classroom = db["classrooms"].get(class_id)
    if not classroom:
        flash("Classroom not found.", "danger")
        return redirect(url_for("index"))

    user = current_user()

    # Access check for private classrooms
    if classroom["visibility"] == "Private":
        allowed = False
        # Teacher who owns it
        if user["role"] == "Teacher" and user["name"] == classroom["teacher_name"]:
            allowed = True
        # Joined in session
        elif class_id in user["joined"]:
            allowed = True
        if not allowed:
            flash("This is a private classroom. Use a join code or be invited.", "warning")
            return redirect(url_for("index"))

    # Handle POST actions (teacher posting content, or students submitting assignment)
    if request.method == "POST":
        action = request.form.get("action")
        db = load_db()  # reload to avoid stale data
        classroom = db["classrooms"].get(class_id)
        if action == "post_announcement":
            if user["role"] == "Teacher" and user["name"] == classroom["teacher_name"]:
                text = request.form.get("announcement", "").strip()
                if text:
                    classroom["announcements"].insert(0, {"text": text})
                    save_db(db)
                    flash("Announcement posted.", "success")
            else:
                flash("Only the classroom teacher may post announcements.", "danger")
        elif action == "post_lesson":
            if user["role"] == "Teacher" and user["name"] == classroom["teacher_name"]:
                title = request.form.get("lesson_title", "Untitled").strip()
                body = request.form.get("lesson_body", "").strip()
                classroom["lessons"].insert(0, {"title": title, "body": body})
                save_db(db)
                flash("Lesson posted.", "success")
            else:
                flash("Only the classroom teacher may post lessons.", "danger")
        elif action == "post_assignment":
            if user["role"] == "Teacher" and user["name"] == classroom["teacher_name"] and classroom["visibility"] == "Private":
                title = request.form.get("assignment_title", "Assignment").strip()
                desc = request.form.get("assignment_desc", "").strip()
                classroom["assignments"].insert(0, {"title": title, "desc": desc, "submissions": []})
                save_db(db)
                flash("Assignment posted.", "success")
            else:
                flash("Assignments allowed only in private classrooms by the teacher.", "danger")
        elif action == "submit_assignment":
            # student submit to a private classroom if joined
            if classroom["visibility"] == "Private" and (class_id in user["joined"] or (user["role"] == "Teacher" and user["name"] == classroom["teacher_name"])):
                assign_idx = int(request.form.get("assignment_idx", -1))
                submission_text = request.form.get("submission_text", "").strip()
                if 0 <= assign_idx < len(classroom["assignments"]):
                    classroom["assignments"][assign_idx]["submissions"].append({"student": user["name"], "text": submission_text})
                    save_db(db)
                    flash("Assignment submitted.", "success")
                else:
                    flash("Invalid assignment.", "danger")
            else:
                flash("You cannot submit assignments to this classroom.", "danger")
        # reload classroom after modifications
        db = load_db()
        classroom = db["classrooms"].get(class_id)

    return render_template("classroom.html", classroom=classroom, user=user)

@app.route("/join", methods=["POST"])
def join_classroom():
    code = request.form.get("code", "").strip()
    db = load_db()
    # find classroom by code
    found = None
    for c in db["classrooms"].values():
        if c["visibility"] == "Private" and c.get("code") == code:
            found = c
            break
    if not found:
        flash("Invalid join code.", "danger")
        return redirect(url_for("index"))
    # add to session joined list
    joined = session.setdefault("joined_classrooms", [])
    if found["id"] not in joined:
        joined.append(found["id"])
        session["joined_classrooms"] = joined
    flash(f"Joined classroom '{found['name']}'.", "success")
    return redirect(url_for("classroom_page", class_id=found["id"]))

@app.route("/classroom/<class_id>/info.json")
def classroom_info_json(class_id):
    db = load_db()
    classroom = db["classrooms"].get(class_id)
    if not classroom:
        return jsonify({"error": "not found"}), 404
    # hide code field for public consumption unless teacher
    user = current_user()
    info = dict(classroom)
    if not (user["role"] == "Teacher" and user["name"] == classroom["teacher_name"]):
        info.pop("code", None)
    return jsonify(info)

if __name__ == "__main__":
    # For simple local testing; on Replit set run to `python app.py`
    app.run(host="0.0.0.0", port=3000, debug=True)
