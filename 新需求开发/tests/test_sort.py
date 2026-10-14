import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app import create_app


class ColumnSortTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APP_DB"] = str(Path(self.tmp.name) / "app.db")
        os.environ["SECRET_KEY"] = "test-secret"
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["TESTING_SKIP_CSRF"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def login(self):
        response = self.client.post(
            "/login",
            data={"login_name": "admin", "password": "admin123"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_sort_buttons_and_order(self):
        self.login()
        conn = sqlite3.connect(os.environ["APP_DB"])
        admin = conn.execute("SELECT id FROM users WHERE login_name='admin'").fetchone()[0]
        now = "2026-01-01 00:00:00"
        for number, amount in (("ZZZ-9", "9.00"), ("AAA-1", "10.00")):
            conn.execute(
                """INSERT INTO contracts
                   (contract_no, business_type, number_year, product_name, party_b, party_a,
                    amount_cny, sign_date, created_by, created_at, updated_at)
                   VALUES (?, '锰矿', 2026, '产品', '乙方', '甲方', ?, '2026-01-01', ?, ?, ?)""",
                (number, amount, admin, now, now),
            )
        conn.commit()
        conn.close()

        for path in ("/contracts", "/invoices", "/batches", "/rates", "/users", "/logs", "/logs?tab=manual"):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200, path)
            self.assertIn("sort-btn", page.get_data(as_text=True), path)

        ascending = self.client.get("/contracts?sort=contract_no&order=asc").get_data(as_text=True)
        self.assertLess(ascending.find("AAA-1"), ascending.find("ZZZ-9"))
        self.assertIn('aria-label="合同编号升序"', ascending)
        self.assertIn("sort-btn on", ascending)

        descending = self.client.get("/contracts?sort=contract_no&order=desc").get_data(as_text=True)
        self.assertLess(descending.find("ZZZ-9"), descending.find("AAA-1"))

        by_amount = self.client.get("/contracts?sort=amount_cny&order=asc").get_data(as_text=True)
        self.assertLess(by_amount.find(">9.00<"), by_amount.find(">10.00<"))

        ignored = self.client.get("/contracts?sort=id;drop&order=asc").get_data(as_text=True)
        self.assertLess(ignored.find("AAA-1"), ignored.find("ZZZ-9"))
        self.assertNotIn("sort-btn on", ignored)

    def test_default_lists_show_latest_documents_first(self):
        self.login()
        conn = sqlite3.connect(os.environ["APP_DB"])
        admin = conn.execute("SELECT id FROM users WHERE login_name='admin'").fetchone()[0]
        earlier = "2026-01-01 00:00:00"
        later = "2026-02-01 00:00:00"
        conn.execute(
            """INSERT INTO contracts
               (contract_no, business_type, number_year, num_seq, product_name, party_b, party_a,
                amount_cny, sign_date, created_by, created_at, updated_at)
               VALUES ('OLD-001', '锰矿', 2025, 1, '旧合同', '乙方', '甲方', '1.00', '2025-01-01', ?, ?, ?)""",
            (admin, later, later),
        )
        conn.execute(
            """INSERT INTO contracts
               (contract_no, business_type, number_year, num_seq, product_name, party_b, party_a,
                amount_cny, sign_date, created_by, created_at, updated_at)
               VALUES ('NEW-108', '锰矿', 2026, 108, '新合同', '乙方', '甲方', '1.00', '2026-10-13', ?, ?, ?)""",
            (admin, earlier, earlier),
        )
        conn.execute(
            """INSERT INTO users
               (login_name, display_name, password_hash, role, status, allow_rate, created_at, updated_at)
               VALUES ('early', '先建', 'x', 'user', 'active', 0, ?, ?)""",
            (earlier, earlier),
        )
        conn.execute(
            """INSERT INTO users
               (login_name, display_name, password_hash, role, status, allow_rate, created_at, updated_at)
               VALUES ('late', '后建', 'x', 'user', 'active', 0, ?, ?)""",
            (later, later),
        )
        conn.commit()
        conn.close()

        contracts = self.client.get("/contracts").get_data(as_text=True)
        self.assertLess(contracts.find("NEW-108"), contracts.find("OLD-001"))
        users = self.client.get("/users").get_data(as_text=True)
        self.assertLess(users.find("后建"), users.find("先建"))
