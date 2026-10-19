"""合同编号、发票编号的分配、回收和采购合同回写。"""
from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import Contract, NumberContract, NumberInvoice, NumberSlot, SysUser
from backend.app.services.numbering import (
    allocate_number,
    create_contract_number,
    list_contract_numbers,
    default_number_year,
    detach_purchase_contract,
    format_number,
    set_pool_floor,
    sync_purchase_contract,
    take_purchase_number,
)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    return session


def _user():
    return SimpleNamespace(employee_id="u", name="测试")


def test_year_and_formats():
    assert default_number_year(date(2026, 1, 15)) == 2025
    assert default_number_year(date(2026, 10, 9)) == 2026
    assert format_number("contract_mn", 2026, 1) == "BMI-GMI-2026001"
    assert format_number("contract_al", 2026, 12) == "BMGG-MAZ-26012"
    assert format_number("invoice_mn", 2026, 1) == "20260001"
    assert format_number("invoice_al_sea", 2026, 3) == "BMI-BMGGMAZ-26003S"
    assert format_number("invoice_al_air", 2026, 3) == "BMI-BMGGMAZ-26003A"


def test_reuse_smallest_free_and_floor():
    db = _db()
    first = allocate_number(db, 1, "contract_mn", 2026)
    assert first["number"] == "BMI-GMI-2026001"
    assert first["reused"] is False
    from backend.app.services.numbering import release_number
    release_number(db, 1, "contract_mn", 1)
    again = allocate_number(db, 1, "contract_mn", 2026)
    assert again["number"] == "BMI-GMI-2026001"
    assert again["reused"] is True
    set_pool_floor(db, 1, "contract_mn", 5)
    nxt = allocate_number(db, 1, "contract_mn", 2026)
    assert nxt["number"] == "BMI-GMI-2026006"
    db.close()


def test_purchase_contract_writes_number_row_and_recycles():
    db = _db()
    user = _user()
    contract = Contract(
        company_id=1,
        contract_code="HOLD",
        name="锰矿采购",
        nature="main",
        direction="purchase",
        party_id=1,
        party_name="供应商甲",
        owner_id="u",
        subject_name="锰矿砂",
        amount="1000.00",
        sign_date=date(2026, 3, 2),
        created_by="u",
        updated_by="u",
    )
    db.add(contract)
    db.flush()
    allocated = take_purchase_number(db, 1, {"number_business": "锰矿", "number_year": 2026})
    contract.contract_code = allocated["number"]
    sync_purchase_contract(db, user, 1, contract, {"number_business": "锰矿", "number_year": 2026}, allocated)
    row = db.query(NumberContract).one()
    assert row.contract_no == "BMI-GMI-2026001"
    assert row.purchase_contract_id == contract.id
    assert row.product_name == "锰矿砂"
    assert row.party_b == "供应商甲"
    assert row.owner_id == "u"
    assert row.business_type == "锰矿"
    assert str(row.amount_cny) == "1000.00"
    detach_purchase_contract(db, user, 1, contract)
    assert db.query(NumberContract).count() == 0
    db.delete(contract)
    db.flush()
    reused = allocate_number(db, 1, "contract_mn", 2026)
    assert reused["number"] == "BMI-GMI-2026001"
    assert reused["reused"] is True
    db.close()


def test_historical_number_does_not_take_a_slot():
    db = _db()
    db.add(SysUser(employee_id="u", login_name="u", name="测试", password_hash="x", status="启用", is_super_admin=True))
    db.flush()
    created = create_contract_number(db, _user(), 1, {
        "business_type": "锰矿",
        "number_year": 2026,
        "contract_no": "旧合同-1",
        "product_name": "历史矿",
        "party_b": "乙方",
        "party_a": "甲方",
        "amount_cny": "1",
        "owner_id": "u",
    })
    assert created["contract_no"] == "旧合同-1"
    row = db.query(NumberContract).one()
    assert row.num_pool is None
    assert db.query(NumberSlot).count() == 0
    other = create_contract_number(db, _user(), 1, {
        "business_type": "铝矿",
        "number_year": 2026,
        "product_name": "铝矿砂",
        "party_b": "乙",
        "amount_cny": "2",
        "owner_id": "测试",
    })
    assert other["owner_name"] == "测试"
    assert other["contract_no"] == "BMGG-MAZ-26001"
    assert db.query(NumberContract).count() == 2
    db.close()


def test_number_list_defaults_to_newest_number_first():
    db = _db()
    for code, year, seq in (("BMI-GMI-2026001", 2026, 1), ("BMI-GMI-2026003", 2026, 3), ("BMGG-MAZ-25002", 2025, 2)):
        db.add(NumberContract(
            company_id=1, contract_no=code, number_year=year, num_seq=seq,
            business_type="锰矿", product_name="矿", party_b="乙", party_a="甲",
        ))
    db.flush()
    newest, *_ = list_contract_numbers(db, 1, {})
    oldest, *_ = list_contract_numbers(db, 1, {"order": "asc"})
    assert [row["contract_no"] for row in newest] == ["BMI-GMI-2026003", "BMI-GMI-2026001", "BMGG-MAZ-25002"]
    assert [row["contract_no"] for row in oldest] == ["BMGG-MAZ-25002", "BMI-GMI-2026001", "BMI-GMI-2026003"]
    db.close()


def test_invoice_pools():
    db = _db()
    assert allocate_number(db, 1, "invoice_mn", 2025)["number"] == "20250001"
    assert allocate_number(db, 1, "invoice_al_sea", 2026)["number"] == "BMI-BMGGMAZ-26001S"
    assert allocate_number(db, 1, "invoice_al_air", 2026)["number"] == "BMI-BMGGMAZ-26001A"
    assert db.query(NumberInvoice).count() == 0
    db.close()
