"""
FertiBook - Online Fertilizer Booking and Management System
A beginner-friendly Flask + SQLite project.

Run locally:   python app.py
Production:    gunicorn app:app
"""
import os
import re
import secrets
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

# ----------------------------------------------------------------------
# 1. CONFIGURATION
# ----------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# DATABASE_PATH lets you move the database file (useful on hosting platforms).
DATABASE = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "database.db"))
ON_RENDER = bool(os.environ.get("RENDER"))  # Render sets this variable automatically

STATUSES = ["Pending", "Confirmed", "Completed", "Cancelled"]
LOW_STOCK_LIMIT = 20

app = Flask(__name__)

# The secret key signs the session cookie. It must come from an environment
# variable so it is never written inside the code (and never goes to GitHub).
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    if ON_RENDER:
        raise RuntimeError("Set the SECRET_KEY environment variable on Render.")
    secret_key = "dev-only-secret-key-do-not-use-online"
    print("WARNING: SECRET_KEY not set. Using a development key (fine on your own computer only).")

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,    # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE="Lax",   # helps block cross-site requests
    SESSION_COOKIE_SECURE=ON_RENDER, # cookie only over HTTPS when online
)

# ----------------------------------------------------------------------
# 2. DATABASE
# ----------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    phone         TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'farmer',   -- 'farmer' or 'admin'
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fertilizers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    price       REAL NOT NULL CHECK (price > 0),     -- price per bag
    stock       INTEGER NOT NULL CHECK (stock >= 0), -- bags available
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    fertilizer_id    INTEGER NOT NULL,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    price_per_bag    REAL NOT NULL,   -- price at the time of booking
    total_price      REAL NOT NULL,
    delivery_address TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'Pending',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    FOREIGN KEY (user_id)       REFERENCES users(id),
    FOREIGN KEY (fertilizer_id) REFERENCES fertilizers(id)
);
"""

SAMPLE_FERTILIZERS = [
    ("Urea", "Nitrogen", 267, 200,
     "46% nitrogen. Boosts leaf growth and gives crops a deep green colour. Good for paddy, wheat and maize."),
    ("DAP", "Phosphatic", 1350, 120,
     "Diammonium phosphate. Helps strong root growth. Apply at sowing time."),
    ("NPK 10-26-26", "Complex", 1470, 80,
     "Balanced mix of nitrogen, phosphorus and potassium for all-round crop nutrition."),
    ("Potash (MOP)", "Potassic", 1700, 60,
     "Muriate of potash. Improves fruit quality, grain filling and resistance to disease."),
    ("Organic Compost", "Organic", 650, 150,
     "Made from farm waste and cow dung. Improves soil health and water holding capacity."),
]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    """One database connection per request."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row            # lets us use row["name"]
        g.db.execute("PRAGMA foreign_keys = ON")  # make foreign keys work in SQLite
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables, add sample fertilizers and make the admin account."""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)

    if db.execute("SELECT COUNT(*) FROM fertilizers").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO fertilizers (name, type, price, stock, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [row + (now(),) for row in SAMPLE_FERTILIZERS],
        )

    if db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 0:
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@fertibook.com").lower()
        admin_password = os.environ.get("ADMIN_PASSWORD")
        if not admin_password and not ON_RENDER:
            admin_password = "Admin@123"  # local testing only
            print("Local admin created -> email: %s  password: %s" % (admin_email, admin_password))
        if admin_password:
            db.execute(
                "INSERT INTO users (name, email, phone, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, 'admin', ?)",
                ("Administrator", admin_email, "9000000000",
                 generate_password_hash(admin_password), now()),
            )
        else:
            print("WARNING: ADMIN_PASSWORD is not set, so no admin account was created.")
    db.commit()
    db.close()


# ----------------------------------------------------------------------
# 3. SECURITY HELPERS (login checks + CSRF protection)
# ----------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def farmer_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if session.get("role") != "farmer":
            return redirect(url_for("admin_dashboard"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access only. Please log in as admin.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


def start_session(user):
    session.clear()  # remove anything left over from before
    session["csrf_token"] = secrets.token_hex(16)
    session["user_id"] = user["id"]
    session["name"] = user["name"]
    session["role"] = user["role"]


def safe_next(target):
    """Only allow redirects to pages inside this website."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


@app.before_request
def csrf_protect():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not secrets.compare_digest(sent, session["csrf_token"]):
            abort(400, "Invalid or missing security token. Go back, refresh the page and try again.")


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.context_processor
def template_helpers():
    def csrf_field():
        return Markup('<input type="hidden" name="csrf_token" value="%s">' % session["csrf_token"])
    return {"csrf_field": csrf_field, "STATUSES": STATUSES}


@app.template_filter("money")
def money(value):
    return "\u20b9{:,.2f}".format(value or 0)


@app.template_filter("booking_code")
def booking_code(booking_id):
    return "FB-{:06d}".format(booking_id)


# ----------------------------------------------------------------------
# 4. VALIDATION HELPERS
# ----------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")  # 10-digit Indian mobile number


def validate_registration(name, email, phone, password, confirm):
    errors = []
    if len(name) < 2 or len(name) > 60:
        errors.append("Name must be 2 to 60 characters.")
    if not EMAIL_RE.match(email):
        errors.append("Enter a valid email address.")
    if not PHONE_RE.match(phone):
        errors.append("Phone number must be 10 digits and start with 6, 7, 8 or 9.")
    if len(password) < 6 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors.append("Password must be at least 6 characters with a letter and a number.")
    if password != confirm:
        errors.append("Passwords do not match.")
    return errors


def read_fertilizer_form(form):
    """Read and validate the add/edit fertilizer form. Returns (data, errors)."""
    data = {
        "name": form.get("name", "").strip(),
        "type": form.get("type", "").strip(),
        "price": form.get("price", "").strip(),
        "stock": form.get("stock", "").strip(),
        "description": form.get("description", "").strip(),
    }
    errors = []
    if not 2 <= len(data["name"]) <= 60:
        errors.append("Name must be 2 to 60 characters.")
    if not 2 <= len(data["type"]) <= 40:
        errors.append("Type must be 2 to 40 characters.")
    try:
        price = float(data["price"])
        if price <= 0 or price > 1000000:
            raise ValueError
        data["price"] = round(price, 2)
    except ValueError:
        errors.append("Price must be a number greater than 0.")
    try:
        stock = int(data["stock"])
        if stock < 0 or stock > 1000000:
            raise ValueError
        data["stock"] = stock
    except ValueError:
        errors.append("Stock must be a whole number (0 or more).")
    if not 10 <= len(data["description"]) <= 500:
        errors.append("Description must be 10 to 500 characters.")
    return data, errors


BOOKING_SELECT = """
    SELECT b.*, f.name AS fertilizer_name, f.type AS fertilizer_type,
           u.name AS farmer_name, u.phone AS farmer_phone
    FROM bookings b
    JOIN fertilizers f ON f.id = b.fertilizer_id
    JOIN users u ON u.id = b.user_id
"""


def status_counts(db, user_id=None):
    """Return {'Pending': 2, 'Confirmed': 1, ...} (for one farmer or for everyone)."""
    sql = "SELECT status, COUNT(*) AS c FROM bookings"
    params = ()
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params = (user_id,)
    sql += " GROUP BY status"
    counts = {s: 0 for s in STATUSES}
    for row in db.execute(sql, params):
        counts[row["status"]] = row["c"]
    counts["Total"] = sum(counts[s] for s in STATUSES)
    return counts


def cancel_booking_and_restore_stock(db, booking):
    """Mark a booking as Cancelled and give the bags back to stock."""
    db.execute("UPDATE bookings SET status = 'Cancelled', updated_at = ? WHERE id = ?",
               (now(), booking["id"]))
    db.execute("UPDATE fertilizers SET stock = stock + ? WHERE id = ?",
               (booking["quantity"], booking["fertilizer_id"]))


# ----------------------------------------------------------------------
# 5. PUBLIC PAGES
# ----------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    categories = db.execute(
        "SELECT type, COUNT(*) AS products, MIN(price) AS from_price "
        "FROM fertilizers GROUP BY type ORDER BY type").fetchall()
    return render_template("index.html", categories=categories)


@app.route("/fertilizers")
def fertilizers():
    db = get_db()
    q = request.args.get("q", "").strip()
    ftype = request.args.get("type", "").strip()
    sql = "SELECT * FROM fertilizers WHERE 1=1"
    params = []
    if q:
        sql += " AND (name LIKE ? OR description LIKE ?)"
        params += ["%" + q + "%", "%" + q + "%"]
    if ftype:
        sql += " AND type = ?"
        params.append(ftype)
    sql += " ORDER BY name"
    items = db.execute(sql, params).fetchall()
    types = [r["type"] for r in db.execute("SELECT DISTINCT type FROM fertilizers ORDER BY type")]
    return render_template("fertilizers.html", items=items, types=types, q=q, ftype=ftype,
                           low_limit=LOW_STOCK_LIMIT)


# ----------------------------------------------------------------------
# 6. REGISTER / LOGIN / LOGOUT
# ----------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = validate_registration(name, email, phone, password, confirm)
        db = get_db()
        if not errors and db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            errors.append("An account with this email already exists. Try logging in.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html", form=request.form), 400

        db.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, 'farmer', ?)",
            (name, email, phone, generate_password_hash(password), now()))
        db.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Wrong email or password.", "error")
            return render_template("login.html", form=request.form), 401
        if user["role"] == "admin":
            flash("Admins must sign in from the admin login page.", "info")
            return redirect(url_for("admin_login"))

        start_session(user)
        flash("Welcome back, %s!" % user["name"], "success")
        return redirect(safe_next(request.args.get("next")) or url_for("dashboard"))
    return render_template("login.html", form={})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE email = ? AND role = 'admin'", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Wrong admin email or password.", "error")
            return render_template("admin_login.html", form=request.form), 401
        start_session(user)
        flash("Admin login successful.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html", form={})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# 7. FARMER PAGES: dashboard, booking, history
# ----------------------------------------------------------------------
@app.route("/dashboard")
@farmer_required
def dashboard():
    db = get_db()
    counts = status_counts(db, session["user_id"])
    recent = db.execute(BOOKING_SELECT + " WHERE b.user_id = ? ORDER BY b.id DESC LIMIT 5",
                        (session["user_id"],)).fetchall()
    return render_template("dashboard.html", counts=counts, bookings=recent)


@app.route("/book/<int:fertilizer_id>", methods=["GET", "POST"])
@farmer_required
def book(fertilizer_id):
    db = get_db()
    fert = db.execute("SELECT * FROM fertilizers WHERE id = ?", (fertilizer_id,)).fetchone()
    if fert is None:
        abort(404)

    if request.method == "POST":
        address = request.form.get("address", "").strip()
        errors = []
        try:
            quantity = int(request.form.get("quantity", ""))
        except ValueError:
            quantity = 0
        if quantity < 1:
            errors.append("Quantity must be at least 1 bag.")
        if not 10 <= len(address) <= 300:
            errors.append("Delivery address must be 10 to 300 characters.")

        if not errors:
            # Take the bags out of stock ONLY if enough are left (one safe step).
            cur = db.execute(
                "UPDATE fertilizers SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (quantity, fertilizer_id, quantity))
            if cur.rowcount == 0:
                db.rollback()
                errors.append("Not enough stock. Only %d bags are available." % fert["stock"])

        if errors:
            for e in errors:
                flash(e, "error")
            fert = db.execute("SELECT * FROM fertilizers WHERE id = ?", (fertilizer_id,)).fetchone()
            return render_template("book.html", fert=fert, form=request.form), 400

        total = quantity * fert["price"]  # Total Price = Quantity x Price per Bag
        cur = db.execute(
            "INSERT INTO bookings (user_id, fertilizer_id, quantity, price_per_bag, total_price, "
            "delivery_address, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?, ?)",
            (session["user_id"], fertilizer_id, quantity, fert["price"], total, address, now(), now()))
        db.commit()
        flash("Booking confirmed! Your booking ID is %s." % booking_code(cur.lastrowid), "success")
        return redirect(url_for("my_bookings", new=cur.lastrowid))

    return render_template("book.html", fert=fert, form={})


@app.route("/bookings")
@farmer_required
def my_bookings():
    # "WHERE user_id = ?" is what stops farmers from seeing each other's bookings.
    rows = get_db().execute(BOOKING_SELECT + " WHERE b.user_id = ? ORDER BY b.id DESC",
                            (session["user_id"],)).fetchall()
    return render_template("bookings.html", bookings=rows,
                           new_id=request.args.get("new", type=int))


@app.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@farmer_required
def cancel_my_booking(booking_id):
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ? AND user_id = ?",
                         (booking_id, session["user_id"])).fetchone()
    if booking is None:
        abort(404)  # not yours (or doesn't exist) -> same answer, reveals nothing
    if booking["status"] != "Pending":
        flash("Only Pending bookings can be cancelled. Contact the admin for help.", "error")
    else:
        cancel_booking_and_restore_stock(db, booking)
        db.commit()
        flash("Booking %s was cancelled." % booking_code(booking_id), "success")
    return redirect(url_for("my_bookings"))


# ----------------------------------------------------------------------
# 8. ADMIN PAGES
# ----------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    counts = status_counts(db)
    stats = {
        "farmers": db.execute("SELECT COUNT(*) FROM users WHERE role='farmer'").fetchone()[0],
        "products": db.execute("SELECT COUNT(*) FROM fertilizers").fetchone()[0],
        "revenue": db.execute("SELECT COALESCE(SUM(total_price), 0) FROM bookings "
                              "WHERE status IN ('Confirmed', 'Completed')").fetchone()[0],
    }
    low_stock = db.execute("SELECT * FROM fertilizers WHERE stock < ? ORDER BY stock",
                           (LOW_STOCK_LIMIT,)).fetchall()
    recent = db.execute(BOOKING_SELECT + " ORDER BY b.id DESC LIMIT 5").fetchall()
    return render_template("admin.html", counts=counts, stats=stats,
                           low_stock=low_stock, bookings=recent)


@app.route("/admin/farmers")
@admin_required
def admin_farmers():
    farmers = get_db().execute(
        "SELECT u.*, COUNT(b.id) AS booking_count FROM users u "
        "LEFT JOIN bookings b ON b.user_id = u.id "
        "WHERE u.role = 'farmer' GROUP BY u.id ORDER BY u.id DESC").fetchall()
    return render_template("admin_farmers.html", farmers=farmers)


@app.route("/admin/fertilizers")
@admin_required
def admin_fertilizers():
    items = get_db().execute("SELECT * FROM fertilizers ORDER BY name").fetchall()
    return render_template("admin_fertilizers.html", items=items, low_limit=LOW_STOCK_LIMIT)


@app.route("/admin/fertilizers/add", methods=["GET", "POST"])
@admin_required
def admin_add_fertilizer():
    if request.method == "POST":
        data, errors = read_fertilizer_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("fertilizer_form.html", item=request.form, editing=False), 400
        db = get_db()
        db.execute("INSERT INTO fertilizers (name, type, price, stock, description, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?)",
                   (data["name"], data["type"], data["price"], data["stock"], data["description"], now()))
        db.commit()
        flash("Fertilizer added.", "success")
        return redirect(url_for("admin_fertilizers"))
    return render_template("fertilizer_form.html", item={}, editing=False)


@app.route("/admin/fertilizers/<int:fid>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_fertilizer(fid):
    db = get_db()
    item = db.execute("SELECT * FROM fertilizers WHERE id = ?", (fid,)).fetchone()
    if item is None:
        abort(404)
    if request.method == "POST":
        data, errors = read_fertilizer_form(request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("fertilizer_form.html", item=request.form, editing=True, fid=fid), 400
        db.execute("UPDATE fertilizers SET name=?, type=?, price=?, stock=?, description=? WHERE id=?",
                   (data["name"], data["type"], data["price"], data["stock"], data["description"], fid))
        db.commit()
        flash("Fertilizer updated.", "success")
        return redirect(url_for("admin_fertilizers"))
    return render_template("fertilizer_form.html", item=item, editing=True, fid=fid)


@app.route("/admin/fertilizers/<int:fid>/stock", methods=["POST"])
@admin_required
def admin_update_stock(fid):
    try:
        stock = int(request.form.get("stock", ""))
        if stock < 0 or stock > 1000000:
            raise ValueError
    except ValueError:
        flash("Stock must be a whole number (0 or more).", "error")
        return redirect(url_for("admin_fertilizers"))
    db = get_db()
    db.execute("UPDATE fertilizers SET stock = ? WHERE id = ?", (stock, fid))
    db.commit()
    flash("Stock updated.", "success")
    return redirect(url_for("admin_fertilizers"))


@app.route("/admin/fertilizers/<int:fid>/delete", methods=["POST"])
@admin_required
def admin_delete_fertilizer(fid):
    db = get_db()
    try:
        db.execute("DELETE FROM fertilizers WHERE id = ?", (fid,))
        db.commit()
        flash("Fertilizer deleted.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("This fertilizer has bookings, so it cannot be deleted. Set its stock to 0 instead.", "error")
    return redirect(url_for("admin_fertilizers"))


@app.route("/admin/bookings")
@admin_required
def admin_bookings():
    status = request.args.get("status", "")
    sql, params = BOOKING_SELECT, []
    if status in STATUSES:
        sql += " WHERE b.status = ?"
        params.append(status)
    rows = get_db().execute(sql + " ORDER BY b.id DESC", params).fetchall()
    return render_template("admin_bookings.html", bookings=rows, current=status)


@app.route("/admin/bookings/<int:booking_id>/status", methods=["POST"])
@admin_required
def admin_update_status(booking_id):
    new_status = request.form.get("status", "")
    db = get_db()
    booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if booking is None:
        abort(404)
    if new_status not in STATUSES:
        flash("Invalid status.", "error")
    elif booking["status"] in ("Cancelled", "Completed"):
        flash("A %s booking cannot be changed." % booking["status"].lower(), "error")
    elif new_status == booking["status"]:
        flash("Status is already %s." % new_status, "info")
    elif new_status == "Cancelled":
        cancel_booking_and_restore_stock(db, booking)
        db.commit()
        flash("Booking %s cancelled and stock restored." % booking_code(booking_id), "success")
    else:
        db.execute("UPDATE bookings SET status = ?, updated_at = ? WHERE id = ?",
                   (new_status, now(), booking_id))
        db.commit()
        flash("Booking %s is now %s." % (booking_code(booking_id), new_status), "success")
    return redirect(request.referrer or url_for("admin_bookings"))


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


# ----------------------------------------------------------------------
# 9. START THE APP
# ----------------------------------------------------------------------
init_db()  # runs when the file is loaded (python app.py OR gunicorn app:app)

if __name__ == "__main__":
    app.run(debug=not ON_RENDER)
