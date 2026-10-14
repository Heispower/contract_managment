import os
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
import sys

sys.path.insert(0, str(ROOT))

from openpyxl import Workbook

from app import create_app


def workbook_bytes(sheets):
    wb = Workbook()
    first = True
    for name, rows in sheets:
        if first:
            ws = wb.active
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


class ImportTest(unittest.TestCase):
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
        conn = sqlite3.connect(os.environ["APP_DB"])
        conn.row_factory = sqlite3.Row
        return conn

    def post_file(self, url, payload, filename="hist.xlsx"):
        return self.client.post(
            url,
            data={"file": (BytesIO(payload), filename)},
            follow_redirects=True,
        )

    def test_contract_history_and_pool(self):
        self.login()
        page = self.client.get("/contracts/import")
        self.assertIn("批量导入合同", page.get_data(as_text=True))
        template = self.client.get("/contracts/import-template")
        self.assertEqual(template.status_code, 200)
        self.assertTrue(template.data.startswith(b"PK"))
        payload = workbook_bytes(
            [
                (
                    "2023购销统计表",
                    [
                        ["2023年购销统计"],
                        ["序号", "供应商名称", "合同号", "合同总额", None, "产品名称"],
                        [1, "三一", "BS-GMI-2023001", 187013.05, "直采", "挖机配件"],
                        [2, "现行", "BMI-GMI-2026010", 1000, "直采", "占用顺序号"],
                        [3, "铝矿供应商", "BMGG-MAZ-SYMT-23001", 500, "直采", "铝矿设备"],
                        [4, "重复", "BS-GMI-2023001", 1, "直采", "重复行"],
                    ],
                ),
                (
                    "2023合同",
                    [
                        ["产品名称", "规格型号", "数量"],
                        ["博赛实业BIC-GMI-2024999合同震坤行", "x", 1],
                    ],
                ),
            ]
        )
        imported = self.post_file("/contracts/import", payload)
        text = imported.get_data(as_text=True)
        self.assertIn("成功导入 3 条", text)
        self.assertIn("2023合同", text)
        conn = self.db()
        legacy = conn.execute(
            "SELECT * FROM contracts WHERE contract_no='BS-GMI-2023001'"
        ).fetchone()
        self.assertIsNone(legacy["num_pool"])
        self.assertEqual(legacy["business_type"], "锰矿")
        self.assertEqual(legacy["party_b"], "三一")
        self.assertEqual(legacy["product_name"], "挖机配件")
        self.assertEqual(legacy["amount_cny"], "187013.05")
        self.assertEqual(legacy["sign_date"], "2023-01-01")
        aluminum = conn.execute(
            "SELECT * FROM contracts WHERE contract_no='BMGG-MAZ-SYMT-23001'"
        ).fetchone()
        self.assertEqual(aluminum["business_type"], "铝矿")
        self.assertEqual(aluminum["number_year"], 2023)
        self.assertIsNone(aluminum["num_pool"])
        occupied = conn.execute(
            "SELECT num_seq, number_year FROM contracts WHERE contract_no='BMI-GMI-2026010'"
        ).fetchone()
        self.assertEqual(occupied["num_seq"], 10)
        self.assertEqual(occupied["number_year"], 2026)
        ghost = conn.execute(
            "SELECT id FROM contracts WHERE contract_no='BIC-GMI-2024999'"
        ).fetchone()
        self.assertIsNone(ghost)
        conn.close()
        again = self.post_file("/contracts/import", payload)
        self.assertIn("成功导入 0 条", again.get_data(as_text=True))
        created = self.client.post(
            "/contracts/new",
            data={
                "business_type": "锰矿",
                "number_year": "2026",
                "product_name": "补洞",
                "party_b": "供应商A",
                "party_a": "重庆市博赛国际矿业投资有限公司",
                "amount_cny": "10",
                "sign_date": "2026-10-12",
            },
            follow_redirects=True,
        )
        self.assertIn("BMI-GMI-2026001", created.get_data(as_text=True))

    def test_invoice_history_batch_and_pool(self):
        self.login()
        payload = workbook_bytes(
            [
                (
                    "冶金级工厂发票号",
                    [
                        ["序号", "发票号", "所含内容", "提单日期", "发票价格CIF/FOB（CNY和USD）", "PO", "操作人", "运输方式", "发邮件时间", "备注", "提单号"],
                        [1, "SI-BMGGMAZ-5500-23002S", "卡特挖掘机", None, None, None, "何", "BBC海运", None, None, None],
                        [None, "SI-BMGGMAZ-5500-23002S-002", "牵引车", "2024.1.2", 122602.33, 3057744, "尹", "忆星", "2024.4.24", "已发", "SF09"],
                        [None, "BMI-BMGGMAZ-26005S", "现行海运", "2026-10-01", 100, None, None, "海运", None, None, None],
                        [None, "BIC-BMGGMAZ-24002S-010（山推）", "带备注编号", None, None, None, None, None, None, None, None],
                        [None, "BMI-GMI-2026001", "这是合同号", None, None, None, None, None, None, None, None],
                        [None, "BMGG-MAZ-PO-JZKRS-5500-23024S", "补发物资", None, None, None, None, "海运", "不退税", None, None],
                    ],
                )
            ]
        )
        imported = self.post_file("/invoices/import", payload)
        text = imported.get_data(as_text=True)
        self.assertIn("成功导入 5 条", text, text)
        self.assertIn("该编号属于合同规则", text)
        conn = self.db()
        master = conn.execute(
            "SELECT * FROM invoices WHERE invoice_no='SI-BMGGMAZ-5500-23002S'"
        ).fetchone()
        self.assertEqual(master["is_batch_master"], 1)
        self.assertIsNone(master["num_pool"])
        self.assertEqual(master["operator_name"], "何")
        self.assertEqual(master["amount_cny"], "122602.33")
        child = conn.execute(
            "SELECT * FROM invoices WHERE invoice_no='SI-BMGGMAZ-5500-23002S-002'"
        ).fetchone()
        self.assertEqual(child["sub_seq"], 2)
        self.assertEqual(child["batch_sub_no"], "-002")
        self.assertEqual(child["batch_id"], master["batch_id"])
        self.assertEqual(child["bl_date"], "2024-01-02")
        self.assertEqual(child["amount_cny"], "122602.33")
        self.assertEqual(child["operator_name"], "尹")
        self.assertIn("原运输方式：忆星", child["remark"])
        standard = conn.execute(
            "SELECT num_pool, num_seq FROM invoices WHERE invoice_no='BMI-BMGGMAZ-26005S'"
        ).fetchone()
        self.assertEqual(standard["num_pool"], "invoice_al_sea")
        self.assertEqual(standard["num_seq"], 5)
        kept = conn.execute(
            "SELECT invoice_no FROM invoices WHERE invoice_no LIKE '%山推%'"
        ).fetchone()
        self.assertEqual(kept["invoice_no"], "BIC-BMGGMAZ-24002S-010（山推）")
        noted = conn.execute(
            "SELECT remark FROM invoices WHERE invoice_no='BMGG-MAZ-PO-JZKRS-5500-23024S'"
        ).fetchone()
        self.assertIn("不退税", noted["remark"])
        free = conn.execute(
            "SELECT status FROM number_slots WHERE pool_key='invoice_al_sea' AND seq=1"
        ).fetchone()
        self.assertEqual(free["status"], "free")
        conn.close()
        created = self.client.post(
            "/invoices/new",
            data={
                "mode": "normal",
                "business_type": "铝矿",
                "transport_type": "海运",
                "number_rule": "铝矿海运",
                "number_year": "2026",
                "content": "新发票",
                "price_term": "CIF",
                "currency": "CNY",
                "amount_cny": "8",
                "exchange_month": "2026-10",
                "exchange_rate": "7.1",
            },
            follow_redirects=True,
        )
        self.assertIn("BMI-BMGGMAZ-26001S", created.get_data(as_text=True))

    def test_viewer_cannot_import(self):
        self.login()
        self.client.post(
            "/users/new",
            data={"login_name": "viewer", "display_name": "只读", "role": "viewer", "password": "abc12345"},
            follow_redirects=True,
        )
        self.client.post("/logout")
        self.login("viewer", "abc12345")
        blocked = self.client.get("/invoices/import")
        self.assertEqual(blocked.status_code, 403)
        posted = self.client.post("/contracts/import", data={}, follow_redirects=True)
        self.assertEqual(posted.status_code, 403)


if __name__ == "__main__":
    unittest.main()
