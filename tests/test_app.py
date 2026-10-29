"""
Automatic tests for FertiBook.   Run with:   python -m unittest -v
Each test uses a temporary database, so your real database.db is never touched.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use a temporary database and a known admin password for the tests.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_PATH"] = _tmp.name
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAIL"] = "admin@test.com"
os.environ["ADMIN_PASSWORD"] = "AdminPass1"

import app as fertibook  # noqa: E402


def token(client):
    client.get("/")
    with client.session_transaction() as s:
        return s["csrf_token"]


def post(client, url, data=None, **kw):
    data = dict(data or {})
    data["csrf_token"] = token(client)
    return client.post(url, data=data, **kw)


def register_and_login(client, email="ravi@test.com", name="Ravi Kumar"):
    post(client, "/register", {"name": name, "email": email, "phone": "9876543210",
                               "password": "secret1", "confirm": "secret1"})
    return post(client, "/login", {"email": email, "password": "secret1"})


class FertiBookTests(unittest.TestCase):
    def setUp(self):
        self.client = fertibook.app.test_client()

    def test_pages_load(self):
        for url in ["/", "/fertilizers", "/login", "/register", "/admin/login"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_sample_data_exists(self):
        html = self.client.get("/fertilizers").get_data(as_text=True)
        for name in ["Urea", "DAP", "NPK", "Potash", "Organic"]:
            self.assertIn(name, html)

    def test_password_is_hashed(self):
        register_and_login(self.client, "hash@test.com")
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        stored = db.execute("SELECT password_hash FROM users WHERE email='hash@test.com'").fetchone()[0]
        db.close()
        self.assertNotEqual(stored, "secret1")
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))

    def test_bad_registration_rejected(self):
        r = post(self.client, "/register", {"name": "A", "email": "bad", "phone": "123",
                                            "password": "abc", "confirm": "x"})
        self.assertEqual(r.status_code, 400)

    def test_post_without_csrf_blocked(self):
        self.assertEqual(self.client.post("/login", data={"email": "a", "password": "b"}).status_code, 400)

    def test_booking_total_stock_and_cancel(self):
        register_and_login(self.client, "book@test.com")
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        fid, price, stock = db.execute("SELECT id, price, stock FROM fertilizers WHERE name='Urea'").fetchone()
        db.close()

        r = post(self.client, "/book/%d" % fid, {"quantity": "3", "address": "Village Road, Kakinada 533001"},
                 follow_redirects=True)
        html = r.get_data(as_text=True)
        self.assertIn("Booking confirmed", html)
        self.assertIn("FB-", html)
        self.assertIn("{:,.2f}".format(3 * price), html)  # total = quantity x price

        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        self.assertEqual(db.execute("SELECT stock FROM fertilizers WHERE id=?", (fid,)).fetchone()[0], stock - 3)
        bid = db.execute("SELECT id FROM bookings ORDER BY id DESC LIMIT 1").fetchone()[0]
        db.close()

        post(self.client, "/bookings/%d/cancel" % bid)
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        self.assertEqual(db.execute("SELECT stock FROM fertilizers WHERE id=?", (fid,)).fetchone()[0], stock)
        self.assertEqual(db.execute("SELECT status FROM bookings WHERE id=?", (bid,)).fetchone()[0], "Cancelled")
        db.close()

    def test_cannot_book_more_than_stock(self):
        register_and_login(self.client, "many@test.com")
        r = post(self.client, "/book/1", {"quantity": "999999", "address": "Some long address here"})
        self.assertEqual(r.status_code, 400)

    def test_farmer_cannot_touch_other_farmers_booking(self):
        a = fertibook.app.test_client()
        register_and_login(a, "a@test.com", "Farmer A")
        post(a, "/book/1", {"quantity": "1", "address": "Farmer A address, Kakinada"})
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        bid = db.execute("SELECT id FROM bookings ORDER BY id DESC LIMIT 1").fetchone()[0]
        db.close()

        b = fertibook.app.test_client()
        register_and_login(b, "b@test.com", "Farmer B")
        self.assertEqual(post(b, "/bookings/%d/cancel" % bid).status_code, 404)
        self.assertNotIn("FB-%06d" % bid, b.get("/bookings").get_data(as_text=True))

    def test_admin_routes_protected(self):
        self.assertEqual(self.client.get("/admin").status_code, 302)
        register_and_login(self.client, "f@test.com")
        self.assertEqual(self.client.get("/admin").status_code, 302)  # farmer is not admin
        self.assertEqual(self.client.get("/admin/farmers").status_code, 302)

    def test_admin_flow(self):
        admin = fertibook.app.test_client()
        r = post(admin, "/admin/login", {"email": "admin@test.com", "password": "AdminPass1"})
        self.assertEqual(r.status_code, 302)
        for url in ["/admin", "/admin/farmers", "/admin/fertilizers", "/admin/bookings"]:
            self.assertEqual(admin.get(url).status_code, 200, url)

        # add, edit, update stock, delete a fertilizer
        post(admin, "/admin/fertilizers/add", {"name": "Zinc Sulphate", "type": "Micronutrient",
             "price": "250", "stock": "40", "description": "Fixes zinc deficiency in soil."})
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        fid = db.execute("SELECT id FROM fertilizers WHERE name='Zinc Sulphate'").fetchone()[0]
        db.close()
        post(admin, "/admin/fertilizers/%d/edit" % fid, {"name": "Zinc Sulphate", "type": "Micronutrient",
             "price": "275", "stock": "40", "description": "Fixes zinc deficiency in soil."})
        post(admin, "/admin/fertilizers/%d/stock" % fid, {"stock": "55"})
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        self.assertEqual(db.execute("SELECT price, stock FROM fertilizers WHERE id=?", (fid,)).fetchone(), (275.0, 55))
        db.close()
        post(admin, "/admin/fertilizers/%d/delete" % fid)
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        self.assertIsNone(db.execute("SELECT id FROM fertilizers WHERE id=?", (fid,)).fetchone())
        db.close()

    def test_admin_confirms_and_cancels_booking(self):
        farmer = fertibook.app.test_client()
        register_and_login(farmer, "g@test.com", "Farmer G")
        post(farmer, "/book/2", {"quantity": "2", "address": "Farmer G address, Kakinada"})
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        bid = db.execute("SELECT id FROM bookings ORDER BY id DESC LIMIT 1").fetchone()[0]
        stock_after_booking = db.execute("SELECT stock FROM fertilizers WHERE id=2").fetchone()[0]
        db.close()

        admin = fertibook.app.test_client()
        post(admin, "/admin/login", {"email": "admin@test.com", "password": "AdminPass1"})
        post(admin, "/admin/bookings/%d/status" % bid, {"status": "Confirmed"})
        # a confirmed booking can no longer be cancelled by the farmer
        post(farmer, "/bookings/%d/cancel" % bid)
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        self.assertEqual(db.execute("SELECT status FROM bookings WHERE id=?", (bid,)).fetchone()[0], "Confirmed")
        db.close()

        post(admin, "/admin/bookings/%d/status" % bid, {"status": "Cancelled"})
        db = fertibook.sqlite3.connect(fertibook.DATABASE)
        self.assertEqual(db.execute("SELECT stock FROM fertilizers WHERE id=2").fetchone()[0], stock_after_booking + 2)
        db.close()


if __name__ == "__main__":
    unittest.main()
