"""合同编号、发票编号的批量导入。"""
from io import BytesIO
from types import SimpleNamespace

import openpyxl
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import NumberBatch, NumberContract, NumberInvoice, NumberSlot, SysUser, SysUserCompany
from backend.app.services.numbering_import import execute_number_file, parse_number_file


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _user():
    return SimpleNamespace(employee_id="u", name="测试")


def _xlsx(sheets):
    book = openpyxl.Workbook()
    first = True
    for title, rows in sheets:
        sheet = book.active if first else book.create_sheet(title)
        sheet.title = title
        first = False
        for row in rows:
            sheet.append(row)
    buf = BytesIO()
    book.save(buf)
    return buf.getvalue()


def test_import_contract_numbers_occupy_and_skip_duplicates():
    db = _db()
    content = _xlsx([
        ("购销统计", [
            ["月份", "合同号", "供应商", "合同金额", "签订日期"],
            ["2026-03", "BMI-GMI-2026004", "供应商甲", 8800, "2026-03-02"],
            ["", "KWI-GMI-99", "供应商乙", None, None],
            ["", "BMI-GMI-2026004", "重复", 1, None],
        ]),
    ])
    parsed = parse_number_file(db, 1, "number-contract", content, "统计.xlsx")
    assert [row["ok"] for row in parsed["rows"]] == [True, True, False]
    assert "占用" in parsed["rows"][0]["message"]
    assert "历史编号" in parsed["rows"][1]["message"]
    assert "2026-01-01" in parsed["rows"][1]["message"]
    result = execute_number_file(db, _user(), 1, "number-contract", parsed["rows"])
    assert result["success"] == 2
    assert result["fail"] == 1
    saved = {row.contract_no: row for row in db.query(NumberContract).all()}
    assert saved["BMI-GMI-2026004"].num_seq == 4
    assert saved["BMI-GMI-2026004"].party_b == "供应商甲"
    assert saved["KWI-GMI-99"].num_pool is None
    assert db.query(NumberSlot).filter(NumberSlot.seq == 4, NumberSlot.status == "used").count() == 1
    assert db.query(NumberSlot).filter(NumberSlot.seq == 1, NumberSlot.status == "free").count() == 1
    again = parse_number_file(db, 1, "number-contract", content, "统计.xlsx")
    assert all(not row["ok"] for row in again["rows"][:2])
    db.close()


def test_import_contract_owner_by_name():
    db = _db()
    db.add(SysUser(employee_id="E019", login_name="e019", name="何敏", password_hash="x", status="启用"))
    db.add(SysUserCompany(employee_id="E019", company_id=1, is_default=True))
    db.flush()
    content = _xlsx([
        ("合同", [
            ["合同编号", "产品/合同名称", "乙方", "归属人"],
            ["KWI-OWN-19", "锰矿砂", "供应商甲", "何敏"],
            ["KWI-OWN-20", "锰矿砂", "供应商乙", "不存在的人"],
        ]),
    ])
    parsed = parse_number_file(db, 1, "number-contract", content, "归属.xlsx")
    assert parsed["rows"][0]["ok"] is True
    assert "何敏" in parsed["rows"][0]["message"]
    assert parsed["rows"][1]["ok"] is False
    result = execute_number_file(db, _user(), 1, "number-contract", parsed["rows"])
    assert result["success"] == 1
    saved = db.query(NumberContract).one()
    assert saved.owner_id == "E019"
    db.close()


def test_import_invoice_numbers_and_batch():
    db = _db()
    content = _xlsx([
        ("发票", [
            ["发票号", "所含内容", "人民币金额", "运输方式"],
            ["20260008", "锰矿砂", 100, "海运"],
            ["BMI-BMGGMAZ-26002S", "铝矿批次", 0, "海运"],
            ["BMI-BMGGMAZ-26002S-001", "铝矿第一票", 50, "海运"],
        ]),
    ])
    parsed = parse_number_file(db, 1, "number-invoice", content, "发票.xlsx")
    assert [row["ok"] for row in parsed["rows"]] == [True, True, True]
    assert any("批次" in row["message"] for row in parsed["rows"])
    result = execute_number_file(db, _user(), 1, "number-invoice", parsed["rows"])
    assert result["success"] == 3
    assert result["fail"] == 0
    master = db.query(NumberInvoice).filter(NumberInvoice.invoice_no == "BMI-BMGGMAZ-26002S").one()
    child = db.query(NumberInvoice).filter(NumberInvoice.invoice_no == "BMI-BMGGMAZ-26002S-001").one()
    assert master.is_batch_master is True
    assert child.batch_id == master.batch_id
    assert child.batch_sub_no == "-001"
    assert db.query(NumberBatch).filter(NumberBatch.prefix == "BMI-BMGGMAZ-26002S").count() == 1
    plain = db.query(NumberInvoice).filter(NumberInvoice.invoice_no == "20260008").one()
    assert plain.num_seq == 8
    assert str(plain.amount_cny) == "100.00"
    db.close()
