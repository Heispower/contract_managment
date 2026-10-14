import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
import sys

sys.path.insert(0, str(ROOT))

from app import create_app
from app.db import connect
from app.numbering import allocate_number, format_number
from app.utils import default_number_year


class SystemTest(unittest.TestCase):
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

    def login(self, name="admin", password="admin123"):
        response = self.client.post(
            "/login",
            data={"login_name": name, "password": password},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response

    def db(self):
        return sqlite3.connect(os.environ["APP_DB"])

    def contract(self, business="锰矿", year="2026", name="锰矿石"):
        return self.client.post(
            "/contracts/new",
            data={
                "business_type": business,
                "number_year": year,
                "product_name": name,
                "party_b": "供应商A",
                "party_a": "重庆市博赛国际矿业投资有限公司",
                "amount_cny": "1000.5",
                "sign_date": "2026-10-12",
            },
            follow_redirects=True,
        )

    def invoice(self, **extra):
        data = {
            "mode": "normal",
            "business_type": "锰矿",
            "transport_type": "海运",
            "number_rule": "锰矿",
            "number_year": "2026",
            "content": "锰矿发票",
            "price_term": "CIF",
            "currency": "USD",
            "amount_usd": "100",
            "amount_cny": "",
            "exchange_month": "2026-10",
            "exchange_rate": "7.2",
        }
        data.update(extra)
        return self.client.post("/invoices/new", data=data, follow_redirects=True)

    def test_year_default(self):
        self.assertEqual(default_number_year(date(2026, 1, 8)), 2025)
        self.assertEqual(default_number_year(date(2026, 10, 12)), 2026)
        self.assertEqual(format_number("contract_mn", 2026, 1), "BMI-GMI-2026001")
        self.assertEqual(format_number("contract_al", 2026, 2), "BMGG-MAZ-26002")
        self.assertEqual(format_number("invoice_al_sea", 2026, 1), "BMI-BMGGMAZ-26001S")
        self.assertEqual(format_number("invoice_al_air", 2026, 1), "BMI-BMGGMAZ-26001A")
        self.assertEqual(format_number("invoice_mn", 2026, 1), "20260001")

    def test_login_and_contract_rules(self):
        page = self.login()
        self.assertIn("合同登记", page.get_data(as_text=True))
        first = self.contract()
        self.assertIn("BMI-GMI-2026001", first.get_data(as_text=True))
        second = self.contract(name="第二单")
        self.assertIn("BMI-GMI-2026002", second.get_data(as_text=True))
        aluminum = self.contract(business="铝矿", name="铝矿石")
        self.assertIn("BMGG-MAZ-26001", aluminum.get_data(as_text=True))
        conn = self.db()
        cid = conn.execute(
            "SELECT id FROM contracts WHERE contract_no='BMI-GMI-2026001'"
        ).fetchone()[0]
        conn.close()
        deleted = self.client.post(f"/contracts/{cid}/delete", follow_redirects=True)
        self.assertIn("BMI-GMI-2026001", deleted.get_data(as_text=True))
        reused = self.contract(year="2027", name="跨年回收")
        text = reused.get_data(as_text=True)
        self.assertIn("BMI-GMI-2027001", text)
        self.assertIn("已复用空闲编号", text)
        still = self.contract(business="铝矿", name="铝矿第二单")
        self.assertIn("BMGG-MAZ-26002", still.get_data(as_text=True))

    def test_invoice_pools_batch_and_rate(self):
        self.login()
        sea = self.invoice(
            business_type="铝矿",
            transport_type="海运",
            number_rule="铝矿海运",
            content="海运铝矿",
            amount_usd="10",
            amount_cny="72",
        )
        self.assertIn("BMI-BMGGMAZ-26001S", sea.get_data(as_text=True))
        air = self.invoice(
            business_type="铝矿",
            transport_type="空运",
            number_rule="铝矿空运",
            content="空运铝矿",
        )
        self.assertIn("BMI-BMGGMAZ-26001A", air.get_data(as_text=True))
        mn = self.invoice(amount_cny="720.00")
        body = mn.get_data(as_text=True)
        self.assertIn("20260001", body)
        self.assertIn("720.00", body)
        conn = self.db()
        sea_id = conn.execute(
            "SELECT id FROM invoices WHERE invoice_no='BMI-BMGGMAZ-26001S'"
        ).fetchone()[0]
        conn.close()
        self.client.post(f"/invoices/{sea_id}/delete", follow_redirects=True)
        again = self.invoice(
            business_type="铝矿",
            transport_type="海运",
            number_rule="铝矿海运",
            content="复用海运",
        )
        text = again.get_data(as_text=True)
        self.assertIn("BMI-BMGGMAZ-26001S", text)
        self.assertIn("已复用空闲编号", text)
        nxt_air = self.invoice(
            business_type="铝矿",
            transport_type="空运",
            number_rule="铝矿空运",
            content="空运第二",
        )
        self.assertIn("BMI-BMGGMAZ-26002A", nxt_air.get_data(as_text=True))

        made = self.invoice(
            mode="new_batch",
            business_type="铝矿",
            transport_type="海运",
            number_rule="铝矿海运",
            content="新建批次",
        )
        self.assertIn("批次", made.get_data(as_text=True))
        conn = self.db()
        batch_id, prefix = conn.execute(
            "SELECT id, prefix FROM batches WHERE deleted_at IS NULL"
        ).fetchone()
        conn.close()
        self.assertTrue(prefix.startswith("BMI-BMGGMAZ-"))
        first_sub = self.invoice(mode="join_batch", batch_id=str(batch_id), content="小批1", amount_usd="1")
        second_sub = self.invoice(mode="join_batch", batch_id=str(batch_id), content="小批2", amount_usd="2")
        self.assertIn(prefix + "-001", first_sub.get_data(as_text=True))
        self.assertIn(prefix + "-002", second_sub.get_data(as_text=True))
        conn = self.db()
        sub_id = conn.execute(
            "SELECT id FROM invoices WHERE invoice_no=?",
            (prefix + "-001",),
        ).fetchone()[0]
        conn.close()
        self.client.post(f"/invoices/{sub_id}/delete", follow_redirects=True)
        reused_sub = self.invoice(mode="join_batch", batch_id=str(batch_id), content="再复用", amount_usd="3")
        reused_text = reused_sub.get_data(as_text=True)
        self.assertIn(prefix + "-001", reused_text)
        self.assertIn("已复用空闲编号", reused_text)

    def test_batch_amount_can_be_zero_and_rolls_up(self):
        self.login()
        form = self.client.get("/invoices/new")
        self.assertIn('value="FOB" selected', form.get_data(as_text=True))
        blocked = self.invoice(amount_usd="", amount_cny="")
        self.assertIn("请填写美元金额或人民币金额", blocked.get_data(as_text=True))
        made = self.invoice(
            mode="new_batch",
            business_type="铝矿",
            transport_type="海运",
            number_rule="铝矿海运",
            content="零金额批次",
            amount_usd="0",
            amount_cny="",
            price_term="FOB",
        )
        self.assertNotIn("请填写美元金额", made.get_data(as_text=True))
        conn = self.db()
        batch_id, prefix = conn.execute(
            "SELECT id, prefix FROM batches WHERE deleted_at IS NULL"
        ).fetchone()
        master = conn.execute(
            "SELECT amount_usd, amount_cny, price_term FROM invoices WHERE invoice_no=?",
            (prefix,),
        ).fetchone()
        conn.close()
        self.assertEqual(master[0], "0.00")
        self.assertEqual(master[1], "0.00")
        self.assertEqual(master[2], "FOB")
        self.invoice(mode="join_batch", batch_id=str(batch_id), content="小批有金额", amount_usd="10", amount_cny="")
        self.invoice(mode="join_batch", batch_id=str(batch_id), content="小批为零", amount_usd="0", amount_cny="0")
        conn = self.db()
        master = conn.execute(
            "SELECT amount_usd, amount_cny FROM invoices WHERE invoice_no=?",
            (prefix,),
        ).fetchone()
        conn.close()
        self.assertEqual(master[0], "10.00")
        self.assertEqual(master[1], "72.00")
        conn = self.db()
        conn.execute(
            "UPDATE invoices SET amount_usd='0.00', amount_cny='0.00' WHERE invoice_no=?",
            (prefix,),
        )
        conn.commit()
        conn.close()
        listed = self.client.get("/invoices")
        self.assertEqual(listed.status_code, 200)
        conn = self.db()
        master = conn.execute(
            "SELECT amount_usd, amount_cny FROM invoices WHERE invoice_no=?",
            (prefix,),
        ).fetchone()
        conn.close()
        self.assertEqual(master[0], "10.00")
        self.assertEqual(master[1], "72.00")

        saved = self.client.post(
            "/rates/new",
            data={"month": "2026-10", "rate": "7.123456", "effective_date": "2026-10-01", "remark": "测试"},
            follow_redirects=True,
        )
        self.assertIn("7.123456", saved.get_data(as_text=True))
        exported = self.client.get("/invoices/export")
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.data.startswith(b"PK"))

    def test_permissions_and_manual_edit(self):
        self.login()
        self.contract()
        created = self.client.post(
            "/users/new",
            data={
                "login_name": "zhangsan",
                "display_name": "张三",
                "role": "user",
                "password": "abc12345",
            },
            follow_redirects=True,
        )
        self.assertIn("张三", created.get_data(as_text=True))
        self.client.post("/logout")
        self.login("zhangsan", "abc12345")
        conn = self.db()
        admin_contract = conn.execute("SELECT id FROM contracts").fetchone()[0]
        conn.close()
        denied = self.client.post(f"/contracts/{admin_contract}/delete", follow_redirects=True)
        self.assertIn("只能删除自己登记的合同", denied.get_data(as_text=True))
        own = self.contract(name="张三的合同")
        self.assertIn("BMI-GMI-2026002", own.get_data(as_text=True))
        manual = self.client.get("/contracts/1/manual")
        self.assertEqual(manual.status_code, 403)
        self.client.post("/logout")
        self.login()
        self.client.post("/users/settings", data={"allow_user_manual_edit": "1"})
        self.client.post("/logout")
        self.login("zhangsan", "abc12345")
        conn = self.db()
        own_id = conn.execute(
            "SELECT id FROM contracts WHERE product_name='张三的合同'"
        ).fetchone()[0]
        conn.close()
        page = self.client.get(f"/contracts/{own_id}/manual")
        self.assertEqual(page.status_code, 200)
        changed = self.client.post(
            f"/contracts/{own_id}/manual",
            data={"new_no": "BMI-GMI-2026010", "reason": "保底修正"},
            follow_redirects=True,
        )
        self.assertIn("BMI-GMI-2026010", changed.get_data(as_text=True))
        nxt = self.contract(name="补洞")
        self.assertIn("BMI-GMI-2026002", nxt.get_data(as_text=True))
        self.client.post("/logout")
        self.login()
        viewer = self.client.post(
            "/users/new",
            data={"login_name": "viewer", "display_name": "只读", "role": "viewer", "password": "abc12345"},
            follow_redirects=True,
        )
        self.assertEqual(viewer.status_code, 200)
        self.client.post("/logout")
        self.login("viewer", "abc12345")
        blocked = self.client.post(
            "/contracts/new",
            data={"business_type": "锰矿", "number_year": "2026"},
            follow_redirects=True,
        )
        self.assertEqual(blocked.status_code, 403)

    def test_concurrent_numbers(self):
        self.login()
        barrier = threading.Barrier(6)
        found = []
        errors = []

        def worker():
            conn = connect()
            try:
                barrier.wait(timeout=10)
                conn.execute("BEGIN IMMEDIATE")
                got = allocate_number(conn, "contract_al", 2026)
                conn.commit()
                found.append(got["number"])
            except Exception as exc:
                errors.append(repr(exc))
                try:
                    conn.rollback()
                except Exception:
                    pass
            finally:
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        self.assertEqual(errors, [])
        self.assertEqual(len(found), 6)
        self.assertEqual(len(set(found)), 6)
        self.assertIn("BMGG-MAZ-26001", found)
        self.assertIn("BMGG-MAZ-26006", found)


if __name__ == "__main__":
    unittest.main()
