# FertiBook – Online Fertilizer Booking and Management System

A beginner-friendly full-stack mini project. Farmers register, browse fertilizers, book bags, and track their bookings. An admin manages fertilizers, stock, farmers and bookings.

**Tech:** HTML, CSS, JavaScript | Python Flask | SQLite

## Project structure

```
FertiBook/
├── app.py                  # All backend code: routes, database, security
├── requirements.txt        # Python packages (Flask, gunicorn)
├── Procfile                # Start command for Heroku-style hosts
├── render.yaml             # Optional Render blueprint
├── .env.example            # Example environment variables
├── .gitignore              # Keeps secrets and database.db out of GitHub
├── database.db             # Created automatically on first run
├── templates/              # HTML pages (Jinja2)
│   ├── base.html           # Navbar, footer, flash messages (shared)
│   ├── index.html  login.html  register.html  fertilizers.html
│   ├── book.html  dashboard.html  bookings.html
│   ├── admin.html  admin_login.html  admin_bookings.html
│   ├── admin_farmers.html  admin_fertilizers.html  fertilizer_form.html
│   ├── _bookings_table.html  _admin_nav.html  404.html
├── static/css/style.css    # Green agricultural theme, responsive
├── static/js/script.js     # Menu, live total price, form checks
└── tests/test_app.py       # Automatic tests
```

## Run on your computer (VS Code)

1. Install Python 3.10 or newer from python.org (tick "Add Python to PATH").
2. Open the `FertiBook` folder in VS Code (File > Open Folder).
3. Open the terminal (Terminal > New Terminal) and run:

**Windows (PowerShell)**
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process Bypass` first.

**Mac / Linux**
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

4. Open http://127.0.0.1:5000 in your browser.

The first run creates `database.db`, the three tables and five sample fertilizers.

**Local admin login** (http://127.0.0.1:5000/admin/login)
- Email: `admin@fertibook.com`
- Password: `Admin@123`

This default works only on your own computer. Online, you must set your own `ADMIN_PASSWORD` (see Render steps).

## How the code fits together

- **Database:** `users`, `fertilizers`, `bookings`. `bookings.user_id` and `bookings.fertilizer_id` are foreign keys.
- **Booking:** total = quantity × price per bag. The price is saved inside the booking, so later price changes do not alter old bookings. Booking removes bags from stock; cancelling puts them back.
- **Booking ID:** shown as `FB-000001` (the database id, padded).
- **Farmer can cancel** only while the booking is **Pending**. Admin can move Pending → Confirmed → Completed, or Cancel.
- **Security:** passwords hashed with Werkzeug; Flask sessions; admin routes protected by `@admin_required`; every booking query filters by the logged-in user; all forms have a CSRF token; inputs are validated in the browser (JavaScript) and again on the server (the server check is the one that really matters).

## Testing

Automatic tests (use a temporary database):
```
python -m unittest discover -s tests -v
```
Manual checklist:
1. Register a farmer with a bad phone number. You should see an error.
2. Register properly, log in, open Fertilizers, click Book now on Urea.
3. Enter 3 bags and an address. The total updates as you type. Confirm; you get a booking ID.
4. Open My bookings. Cancel it. Stock goes back up on the Fertilizers page.
5. Log out. Open `/admin`. You are sent to the login page.
6. Log in as admin. Add a fertilizer, edit it, change stock, confirm a booking, and delete the new fertilizer.
7. Resize the browser to phone width. Menu and tables should still work.

## Upload to GitHub

1. Create an account at github.com. Click **New repository**, name it `FertiBook`, keep it Public or Private, do NOT add a README (you already have one), then click **Create repository**.
2. Install Git from git-scm.com. In the VS Code terminal, inside the project folder:
```
git init
git add .
git commit -m "FertiBook first version"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/FertiBook.git
git push -u origin main
```
3. Check on GitHub that `.env` and `database.db` are NOT listed (`.gitignore` blocks them).

If Git asks you to sign in, use the browser sign-in window, or a Personal Access Token as the password.

## Deploy on Render

1. Make sure the code is on GitHub (above).
2. Go to render.com and sign up with your GitHub account.
3. Click **New +** > **Web Service** > connect your `FertiBook` repository.
4. Fill in:
   - **Runtime/Language:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance type:** Free
5. Under **Environment Variables** add:
   - `SECRET_KEY` = a long random text. To make one, run: `python -c "import secrets; print(secrets.token_hex(32))"`
   - `ADMIN_EMAIL` = your admin email
   - `ADMIN_PASSWORD` = a strong password (not `Admin@123`)
   - `PYTHON_VERSION` = `3.12.3` (optional but recommended)
6. Click **Create Web Service**. Wait for the build log to say the service is live.
7. Your public address is shown at the top of the service page, like `https://fertibook-xxxx.onrender.com`. Open it and test.
8. Every time you `git push`, Render redeploys automatically.

Note: Render reads the **Start Command** you type in the dashboard. The `Procfile` is included for Heroku-style hosts and is harmless on Render. Alternatively, `render.yaml` can set these up as a Blueprint.

The app is not deployed until you complete these steps yourself. Only then will you have a real public URL.

## SQLite on hosting platforms (important)

- On Render's free plan the disk is **temporary**. When the service restarts, sleeps, or redeploys, `database.db` is reset: farmers, bookings and stock edits are lost, and the sample data comes back.
- Free services also "sleep" after a period with no visitors, so the first page load can be slow.
- **For a college demo** this is acceptable. Say so in your viva.
- **For real use,** use a persistent database:
  1. **PostgreSQL** (Render, Neon or Supabase). This is the usual choice. You would change `sqlite3` calls to a PostgreSQL library (such as `psycopg2`) and `?` placeholders to `%s`. Check each provider's current free-plan limits first, as they change.
  2. **SQLite on a paid persistent disk** (Render paid plan). Set `DATABASE_PATH` to the disk's mount path. Simplest, but paid.

## Ideas to extend

Email or SMS notifications, online payment, order PDF receipts, charts on the admin page, farmer profile edit, forgot-password.
