import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
import sys

sys.path.insert(0, str(ROOT))

from werkzeug.datastructures import MultiDict

from app import create_app


class BatchDeleteTest(unittest.TestCase):
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
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def db(self):
        conn = sqlite3.connect(os.environ["APP_DB"])
        conn.row_factory = sqlite3.Row
        return conn

    def test_pages_show_batch_delete(self):
        self.login()
        for path in ("/contracts", "/invoices", "/batches", "/rates", "/users", "/logs"):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200, path)
            self.assertIn("批量删除", page.get_data(as_text=True), path)
        manual = self.client.get("/logs?tab=manual")
        self.assertIn("批量删除", manual.get_data(as_text=True))

    def test_delete_rates_users_logs_and_batches(self):
        self.login()
        for month in ("2026-08", "2026-09"):
            saved = self.client.post(
                "/rates/new",
                data={"month": month, "rate": "7.1", "effective_date": month + "-01", "remark": ""},
                follow_redirects=True,
            )
            self.assertIn(month, saved.get_data(as_text=True))
        conn = self.db()
        rate_ids = [row["id"] for row in conn.execute("SELECT id FROM exchange_rates")]
        conn.close()
        removed = self.client.post(
            "/rates/batch-delete",
            data=MultiDict([("ids", str(item)) for item in rate_ids]),
            follow_redirects=True,
        )
        self.assertIn("已删除 2 条汇率", removed.get_data(as_text=True))
        conn = self.db()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM exchange_rates").fetchone()[0], 0)
        created = self.client.post(
            "/users/new",
            data={"login_name": "lisi", "display_name": "李四", "role": "user", "password": "abc12345"},
            follow_redirects=True,
        )
        self.assertIn("李四", created.get_data(as_text=True))
        user_id = conn.execute("SELECT id FROM users WHERE login_name='lisi'").fetchone()["id"]
        admin_id = conn.execute("SELECT id FROM users WHERE login_name='admin'").fetchone()["id"]
        conn.close()
        deleted_users = self.client.post(
            "/users/batch-delete",
            data=MultiDict([("ids", str(user_id)), ("ids", str(admin_id))]),
            follow_redirects=True,
        )
        text = deleted_users.get_data(as_text=True)
        self.assertIn("已删除 1 个用户", text)
        self.assertIn("跳过 1 个", text)
        conn = self.db()
        self.assertIsNone(conn.execute("SELECT id FROM users WHERE login_name='lisi'").fetchone())
        self.assertIsNotNone(conn.execute("SELECT id FROM users WHERE login_name='admin'").fetchone())
        log_id = conn.execute("SELECT id FROM operation_logs ORDER BY id LIMIT 1").fetchone()["id"]
        conn.close()
        deleted_logs = self.client.post(
            "/logs/batch-delete?tab=ops",
            data={"ids": str(log_id)},
            follow_redirects=True,
        )
        self.assertIn("已删除 1 条日志", deleted_logs.get_data(as_text=True))
        made = self.client.post(
            "/invoices/new",
            data={
                "mode": "new_batch",
                "business_type": "铝矿",
                "transport_type": "海运",
                "number_rule": "铝矿海运",
                "number_year": "2026",
                "content": "批次",
                "price_term": "CIF",
                "currency": "USD",
                "amount_usd": "10",
                "exchange_month": "2026-10",
                "exchange_rate": "7.2",
            },
            follow_redirects=True,
        )
        self.assertEqual(made.status_code, 200, made.get_data(as_text=True))
        conn = self.db()
        batch_id = conn.execute("SELECT id FROM batches WHERE deleted_at IS NULL").fetchone()["id"]
        conn.close()
        deleted_batch = self.client.post(
            "/batches/batch-delete",
            data={"ids": str(batch_id)},
            follow_redirects=True,
        )
        self.assertIn("已删除 1 个批次", deleted_batch.get_data(as_text=True))
        conn = self.db()
        self.assertIsNotNone(
            conn.execute("SELECT deleted_at FROM batches WHERE id=?", (batch_id,)).fetchone()["deleted_at"]
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
