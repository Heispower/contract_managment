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
from app.numbering import format_number
from app.utils import default_number_year


class SeqFloorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["APP_DB"] = str(Path(self.tmp.name) / "app.db")
        os.environ["SECRET_KEY"] = "test-secret"
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["TESTING_SKIP_CSRF"] = True
        self.client = self.app.test_client()
        self.year = default_number_year()

    def tearDown(self):
        self.tmp.cleanup()

    def login(self, name="admin", password="admin123"):
        response = self.client.post(
            "/login",
            data={"login_name": name, "password": password},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

    def db(self):
        conn = sqlite3.connect(os.environ["APP_DB"])
        conn.row_factory = sqlite3.Row
        return conn

    def new_contract(self):
        return self.client.post(
            "/contracts/new",
            data={
                "business_type": "锰矿",
                "number_year": str(self.year),
                "product_name": "锰矿石",
                "party_b": "供应商A",
                "party_a": "重庆市博赛国际矿业投资有限公司",
                "amount_cny": "1000",
                "sign_date": f"{self.year}-10-12",
            },
            follow_redirects=True,
        )

    def test_floor_skips_history_and_does_not_recycle(self):
        self.login()
        page = self.client.get("/contracts")
        html = page.get_data(as_text=True)
        self.assertIn("基础数据维护", html)
        self.assertIn("当前序号", html)
        self.assertNotIn(">汇率维护</a>", html.split("nav-menu")[0])

        saved = self.client.post(
            "/sequences",
            data={"pool": "contract_mn", "latest": "10"},
            follow_redirects=True,
        )
        self.assertIn("历史序号划到 10", saved.get_data(as_text=True))
        first = self.new_contract()
        number = format_number("contract_mn", self.year, 11)
        self.assertIn(number, first.get_data(as_text=True))

        conn = self.db()
        cid = conn.execute("SELECT id FROM contracts WHERE contract_no=?", (number,)).fetchone()["id"]
        conn.close()
        self.client.post(f"/contracts/{cid}/delete", follow_redirects=True)
        again = self.new_contract()
        self.assertIn(number, again.get_data(as_text=True))

        conn = self.db()
        cid = conn.execute(
            "SELECT id FROM contracts WHERE contract_no=? AND deleted_at IS NULL",
            (number,),
        ).fetchone()["id"]
        conn.close()
        old = format_number("contract_mn", self.year, 3)
        edited = self.client.post(
            f"/contracts/{cid}/manual",
            data={"new_no": old, "reason": "补录历史合同"},
            follow_redirects=True,
        )
        self.assertIn(old, edited.get_data(as_text=True))
        self.client.post(f"/contracts/{cid}/delete", follow_redirects=True)
        self.new_contract()
        conn = self.db()
        live = [row["contract_no"] for row in conn.execute("SELECT contract_no FROM contracts WHERE deleted_at IS NULL")]
        conn.close()
        self.assertEqual(live, [number])

        parsed = self.client.post(
            "/sequences",
            data={"pool": "invoice_mn", "latest": f"{self.year}0050"},
            follow_redirects=True,
        )
        self.assertIn("历史序号划到 50", parsed.get_data(as_text=True))
        wrong = self.client.post(
            "/sequences",
            data={"pool": "invoice_mn", "latest": format_number("contract_mn", self.year, 8)},
            follow_redirects=True,
        )
        self.assertIn("不属于当前规则", wrong.get_data(as_text=True))

        self.client.post(
            "/users/new",
            data={
                "login_name": "rateuser",
                "display_name": "汇率员",
                "role": "user",
                "password": "abc12345",
                "allow_rate": "1",
            },
            follow_redirects=True,
        )
        self.client.post("/logout")
        self.login("rateuser", "abc12345")
        home = self.client.get("/contracts").get_data(as_text=True)
        self.assertIn("基础数据维护", home)
        self.assertIn("汇率维护", home)
        self.assertNotIn("当前序号", home)
        denied = self.client.get("/sequences")
        self.assertEqual(denied.status_code, 403)
