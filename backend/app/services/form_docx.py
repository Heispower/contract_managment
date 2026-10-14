"""按导出模板把字段清单里的单据填进 Word。采购合同仍走原来的专用生成。"""
import re
import zipfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from lxml import etree

from ..errors import BizError
from ..models import (
    CompanyContact,
    Contract,
    ContractOrder,
    CustomsClearance,
    CustomsElement,
    CustomsInvoice,
    Invoice,
    InvoiceItem,
    Party,
    PartyContact,
    Project,
    SettleBill,
    SysUser,
    Warehouse,
    WmsBill,
    WmsItem,
)
from ..money import D, ZERO, max0, qty_str
from . import calc
from .contract_docx import NS, _nodes, _replace_span, cn_date, line_amount, money_comma, rmb_upper
from .export_profile import align_export_name, render_filename, resolve_export
from .util import get_row

_TOKEN = re.compile(r"\{\{[^{}]+\}\}")

ITEM_CONTRACT = ("物料编号", "物料名称", "英文名称", "规格", "单位", "数量", "含税单价", "行价税合计", "计划单号", "使用设备", "采购单价")
STAGE_CONTRACT = ("阶段名称", "阶段比例", "阶段金额", "阶段日期", "阶段备注")
ITEM_ORDER = ("物料编号", "中文名称", "物料名称", "规格", "单位", "数量", "含税单价", "行金额", "到货发货")
ITEM_INVOICE = ("物料编号", "物料名称", "数量", "含税单价", "行不含税金额", "行税额", "行税率")
STAGE_PAY = ("阶段名称", "阶段金额", "阶段已结", "阶段剩余", "本次金额")
ITEM_WMS = ("物料编号", "中文名称", "物料名称", "使用设备", "单位", "数量", "含税单价", "行金额")
ITEM_CUSTOMS_INV = ("申报大类", "英文名称", "人民币单价", "人民币总价", "装箱数")
ITEM_CUSTOMS_SRC = ("物料编号", "箱号", "入仓单", "箱单号")
ITEM_CUSTOMS_CLR = ("中文名", "英文名", "换算美元金额", "PO单号")
ITEM_CUSTOMS_PACK = ("序列号", "品名", "中文名", "包件数", "包装件数", "毛重", "净重", "尺寸", "入仓单号")
ITEM_CUSTOMS_EL = ("HS Code", "申报名称", "产品名称", "明细物料", "申报规格", "型号", "报关要素", "申报要素", "货源地")


def _clean(value) -> str:
    return str(value or "").strip()


def _first(*values) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _rate(value) -> str:
    text = qty_str(value or 0)
    if not text:
        return ""
    return text if text.endswith("%") else f"{text}%"


def _day(value) -> str:
    if not value:
        return ""
    return value.strftime("%Y-%m-%d")


def _person(db, employee_id) -> str:
    text = _clean(employee_id)
    if not text:
        return ""
    user = db.query(SysUser).filter(SysUser.employee_id == text).first()
    if user and _clean(user.name):
        return _clean(user.name)
    return text


def _company_contact(db, company) -> tuple[str, str]:
    if company is None:
        return "", ""
    row = (
        db.query(CompanyContact)
        .filter(CompanyContact.company_id == company.id, CompanyContact.deleted_at.is_(None))
        .order_by(CompanyContact.is_default.desc(), CompanyContact.id)
        .first()
    )
    if row is None:
        return "", ""
    return _clean(row.name), _clean(row.phone)


def _party_contact(db, party) -> tuple[str, str]:
    if party is None:
        return "", ""
    row = (
        db.query(PartyContact)
        .filter(PartyContact.party_id == party.id, PartyContact.deleted_at.is_(None))
        .order_by(PartyContact.is_default.desc(), PartyContact.id)
        .first()
    )
    if row is None:
        return "", ""
    return _clean(row.name), _clean(row.phone)


def _branch(branch, *blocked) -> str:
    text = _clean(branch)
    names = {_clean(name) for name in blocked if _clean(name)}
    if text in names:
        return ""
    return text


def _our(db, company) -> dict:
    if company is None:
        company_name = short = ""
        contact_name, contact_phone = "", ""
    else:
        company_name = _clean(company.name)
        short = _clean(company.short_name)
        contact_name, contact_phone = _company_contact(db, company)
    return {
        "我方名称": company_name,
        "我方简称": short,
        "我方税号": _clean(company.tax_no) if company else "",
        "我方开票名称": _clean(company.invoice_title) if company else "",
        "我方开户银行": _clean(company.bank_name) if company else "",
        "我方账户名称": _clean(company.account_name) if company else "",
        "我方银行账号": _clean(company.bank_account) if company else "",
        "我方开户支行": _branch(company.bank_branch if company else "", company_name, short),
        "我方开票电话": _clean(company.invoice_phone) if company else "",
        "我方开票地址": _clean(company.invoice_address) if company else "",
        "我方地址": _first(company.address if company else "", company.invoice_address if company else ""),
        "我方法人": _clean(company.legal_name) if company else "",
        "我方代理": _clean(company.agent_name) if company else "",
        "我方联系人": contact_name,
        "我方联系电话": contact_phone,
        "我方手机": _clean(company.mobile) if company else "",
        "我方邮箱": _clean(company.email) if company else "",
    }


def _their(db, party, fallback_name="") -> dict:
    name = _first(party.name if party else "", fallback_name)
    short = _clean(party.short_name) if party else ""
    contact_name, contact_phone = _party_contact(db, party)
    return {
        "对方名称": name,
        "对方编码": _clean(party.code) if party else "",
        "对方简称": short or name,
        "客商名称": name,
        "客商编码": _clean(party.code) if party else "",
        "对方税号": _clean(party.tax_no) if party else "",
        "对方开票名称": _clean(party.invoice_title) if party else "",
        "对方开户银行": _clean(party.bank_name) if party else "",
        "对方账户名称": _clean(party.account_name) if party else "",
        "对方银行账号": _clean(party.bank_account) if party else "",
        "对方开户支行": _branch(party.bank_branch if party else "", name, short),
        "对方开票电话": _first(party.invoice_phone if party else "", party.mobile if party else ""),
        "对方开票地址": _clean(party.invoice_address) if party else "",
        "对方地址": _clean(party.address) if party else "",
        "对方法人": _clean(party.legal_name) if party else "",
        "对方代理": _clean(party.agent_name) if party else "",
        "对方联系人": contact_name,
        "对方联系电话": contact_phone,
        "对方手机": _clean(party.mobile) if party else "",
        "对方邮箱": _clean(party.email) if party else "",
    }


def _project(db, project_id) -> dict:
    project = db.get(Project, project_id) if project_id else None
    if project is None or project.deleted_at:
        return {"项目名称": "", "项目编号": "", "项目年度": ""}
    return {
        "项目名称": _clean(project.name),
        "项目编号": _clean(project.project_code),
        "项目年度": _clean(project.year),
    }


def _fill_paragraph(paragraph, mapping: dict):
    nodes = _nodes(paragraph)
    if not nodes:
        return
    if "{{" not in "".join(node.text or "" for node in nodes):
        return
    for key in sorted(mapping, key=len, reverse=True):
        token = "{{" + key + "}}"
        while _replace_span(nodes, token, mapping.get(key) or ""):
            pass


def _clear_paragraph(paragraph):
    nodes = _nodes(paragraph)
    if not nodes:
        return
    while True:
        full = "".join(node.text or "" for node in nodes)
        match = _TOKEN.search(full)
        if not match:
            return
        if not _replace_span(nodes, match.group(0), ""):
            return


def _row_text(row) -> str:
    return "".join(row.xpath(".//w:t/text()", namespaces=NS))


def _fill_row(row, mapping: dict):
    for paragraph in row.xpath(".//w:p", namespaces=NS):
        _fill_paragraph(paragraph, mapping)


def _expand_group(root, keys: tuple[str, ...], rows: list[dict]):
    template = None
    best = 0
    for row in root.xpath(".//w:tr", namespaces=NS):
        text = _row_text(row)
        hits = sum(1 for key in keys if "{{" + key + "}}" in text)
        if hits > best:
            best = hits
            template = row
    if template is None:
        return
    parent = template.getparent()
    position = parent.index(template)
    usable = rows or [{key: "" for key in keys}]
    for offset, item in enumerate(usable):
        clone = deepcopy(template)
        _fill_row(clone, item)
        parent.insert(position + offset, clone)
    parent.remove(template)


def _word_part(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return name.startswith("word/") and base.endswith(".xml") and (
        base == "document.xml" or base.startswith("header") or base.startswith("footer")
    )


def _office_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    head = path.read_bytes()[:8]
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as source:
                names = source.namelist()
        except zipfile.BadZipFile:
            names = []
        if any(name.startswith("xl/") for name in names):
            return "xlsx"
        if any(name.startswith("word/") for name in names):
            return "docx"
    if suffix in {".txt", ".csv", ".rtf"} or head.startswith((b"{\\rtf", b"<?xml", b"<html", b"\xef\xbb\xbf")):
        return "text"
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return "xlsx"
    if suffix in {".xls", ".xlt"}:
        return "xls"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".doc", ".dot"}:
        return "doc"
    return "docx"


def is_word_template(path: Path) -> bool:
    return _office_kind(path) == "docx"


def _apply_text(value, mapping: dict):
    if not isinstance(value, str) or "{{" not in value:
        return value

    def repl(match):
        key = match.group(1).strip()
        if key not in mapping:
            return match.group(0)
        return str(mapping.get(key) or "")

    return re.sub(r"\{\{([^{}]+)\}\}", repl, value)


def _is_merged(cell) -> bool:
    from openpyxl.cell.cell import MergedCell

    return isinstance(cell, MergedCell)


def _write_cell(cell, value):
    if _is_merged(cell):
        return
    cell.value = value


def _copy_sheet_row(sheet, src: int, dst: int, max_col: int):
    from copy import copy

    for col in range(1, max_col + 1):
        source = sheet.cell(src, col)
        target = sheet.cell(dst, col)
        if _is_merged(source) or _is_merged(target):
            continue
        target.value = source.value
        if source.has_style:
            target.font = copy(source.font)
            target.border = copy(source.border)
            target.fill = copy(source.fill)
            target.number_format = source.number_format
            target.alignment = copy(source.alignment)
    height = sheet.row_dimensions[src].height
    if height:
        sheet.row_dimensions[dst].height = height
    spans = [
        (merged.min_col, merged.max_col)
        for merged in sheet.merged_cells.ranges
        if merged.min_row == merged.max_row == src
    ]
    for min_col, max_col_span in spans:
        sheet.merge_cells(start_row=dst, start_column=min_col, end_row=dst, end_column=max_col_span)


def _row_blob(sheet, index: int, max_col: int) -> str:
    return "".join(
        sheet.cell(index, col).value if isinstance(sheet.cell(index, col).value, str) else ""
        for col in range(1, max_col + 1)
    )


def _expand_sheet(sheet, groups):
    max_col = max(sheet.max_column or 1, 1)
    last = sheet.max_row or 1
    jobs = []
    for keys, rows in groups:
        best_row = None
        best = 0
        for index in range(1, last + 1):
            text = _row_blob(sheet, index, max_col)
            hits = sum(1 for key in keys if "{{" + key + "}}" in text)
            if hits >= 2 and hits > best:
                best = hits
                best_row = index
        if best_row:
            jobs.append((best_row, rows or [{key: "" for key in keys}]))
    for row_index, items in sorted(jobs, key=lambda item: item[0], reverse=True):
        usable = list(items)
        extra = max(len(usable) - 1, 0)
        if extra:
            sheet.insert_rows(row_index + 1, extra)
            for offset in range(1, len(usable)):
                _copy_sheet_row(sheet, row_index, row_index + offset, max_col)
        for offset, item in enumerate(usable):
            for col in range(1, max_col + 1):
                cell = sheet.cell(row_index + offset, col)
                _write_cell(cell, _apply_text(cell.value, item))


def _fill_sheet_headers(sheet, mapping: dict):
    for row in sheet.iter_rows():
        for cell in row:
            _write_cell(cell, _apply_text(cell.value, mapping))
    for header in (sheet.oddHeader, sheet.evenHeader, sheet.firstHeader, sheet.oddFooter, sheet.evenFooter, sheet.firstFooter):
        for part in ("left", "center", "right"):
            section = getattr(header, part, None)
            if section is not None and section.text and "{{" in section.text:
                section.text = _apply_text(section.text, mapping)


def render_xlsx(path: Path, mapping: dict, groups: list[tuple[tuple[str, ...], list[dict]]]) -> bytes:
    from openpyxl import load_workbook

    book = load_workbook(path)
    for sheet in book.worksheets:
        _expand_sheet(sheet, groups)
        _fill_sheet_headers(sheet, mapping)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def render_text(path: Path, mapping: dict) -> bytes:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        encoding = "utf-16"
    elif raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "gb18030"
        text = raw.decode(encoding)
    return _apply_text(text, mapping).encode(encoding)


def render_office(path: Path, mapping: dict, groups: list[tuple[tuple[str, ...], list[dict]]]) -> bytes:
    kind = _office_kind(path)
    if kind == "docx":
        return render_docx(path, mapping, groups)
    if kind == "xlsx":
        return render_xlsx(path, mapping, groups)
    if kind == "text":
        return render_text(path, mapping)
    if kind == "pdf":
        content = path.read_bytes()
        if b"{{" in content:
            raise BizError("PDF 模板里的占位符还不能替换，请改用 doc、docx、xls 或 xlsx")
        return content
    from .office_binary import render_binary

    return render_binary(path, mapping, groups, kind)


def render_docx(path: Path, mapping: dict, groups: list[tuple[tuple[str, ...], list[dict]]]) -> bytes:
    if not path.is_file():
        raise BizError(f"找不到模板文件：{path.name}")
    with zipfile.ZipFile(path) as source:
        packed = [(info, source.read(info.filename)) for info in source.infolist()]
    rewritten = {}
    for info, payload in packed:
        if not _word_part(info.filename) or b"{{" not in payload:
            continue
        root = etree.fromstring(payload)
        if info.filename == "word/document.xml":
            for keys, rows in groups:
                _expand_group(root, keys, rows)
        for paragraph in root.xpath(".//w:p", namespaces=NS):
            _fill_paragraph(paragraph, mapping)
            _clear_paragraph(paragraph)
        rewritten[info.filename] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for info, payload in packed:
            target.writestr(info, rewritten.get(info.filename, payload))
    return output.getvalue()


def _finish(db, company_id, doc_code, template_id, mapping, groups, fallback) -> tuple[bytes, str]:
    path, rule = resolve_export(db, company_id, doc_code, template_id)
    filename = align_export_name(render_filename(rule, mapping, fallback), path)
    return render_office(path, mapping, groups), filename


def _sale_contract(db, company, record_id, template_id):
    contract = get_row(db, Contract, record_id, company.id)
    if contract.direction != "sale":
        raise BizError("只有销售合同可以生成这张表单")
    party = db.get(Party, contract.party_id)
    names = []
    plans = []
    qty_total = D(0)
    items = []
    for item in calc.items_of(db, contract.id):
        amount = line_amount(item.qty, item.price)
        qty_total += D(item.qty)
        if item.name_cn and item.name_cn not in names:
            names.append(item.name_cn)
        if item.plan_no and item.plan_no not in plans:
            plans.append(item.plan_no)
        items.append({
            "物料编号": item.material_code or "",
            "物料名称": item.name_cn or "",
            "英文名称": item.name_en or "",
            "规格": item.spec or "",
            "单位": item.unit or "",
            "数量": qty_str(item.qty),
            "含税单价": money_comma(item.price),
            "行价税合计": money_comma(amount),
            "计划单号": item.plan_no or "",
            "使用设备": item.category or "",
            "采购单价": "",
            "备注": item.remark or "",
        })
    stages = []
    for stage in calc.stages_of(db, contract.id):
        stages.append({
            "阶段名称": stage.name or "",
            "阶段比例": _rate(stage.ratio),
            "阶段金额": money_comma(stage.plan_amount),
            "阶段日期": _day(stage.plan_date),
            "阶段备注": stage.remark or "",
        })
    subject = _clean(contract.subject_name) or "、".join(names)
    amount = money_comma(contract.amount)
    mapping = {
        **_our(db, company),
        **_their(db, party, contract.party_name or ""),
        **_project(db, contract.project_id),
        "合同编号": contract.contract_code or "",
        "合同名称": contract.name or "",
        "合同类型": contract.type_name or "",
        "签订日期": cn_date(contract.sign_date),
        "税率": _rate(contract.tax_rate),
        "业务员": _person(db, contract.owner_id),
        "合同状态": contract.status or "",
        "计价方式": "按实结算" if contract.pricing == "actual" else "固定总价",
        "备注": contract.remark or "",
        "内容概述": contract.content or "",
        "条款": contract.terms or "",
        "标的名称": subject,
        "物料名称1": subject,
        "物料名称2": subject,
        "合同金额": amount,
        "合同金额1": amount,
        "合同金额2": amount,
        "合同金额3": amount,
        "合同金额（大写）": rmb_upper(contract.amount),
        "不含税金额": money_comma(contract.amount_ex_tax),
        "数量合计": qty_str(qty_total),
        "价税合计": amount,
        "计划单号": "、".join(plans),
        "使用设备": "、".join(calc.equipment_name(item) for item in calc.items_of(db, contract.id) if calc.equipment_name(item)),
        "收货地址": contract.ship_address or "",
        "收货人": contract.receiver_name or "",
        "运输方式": contract.transport_mode or "",
        "交货期限": contract.delivery_term or "",
        "运费承担": contract.freight_bearer or "",
        "附件说明": contract.annex_note or "",
        "付款方式期限等条款": contract.terms or "",
        "货物验收标准和方法": contract.acceptance_text or "",
    }
    if party:
        mapping["对方名称"] = _first(contract.party_name, party.name)
        mapping["对方税号"] = _first(contract.party_tax_no, party.tax_no)
    return _finish(
        db, contract.company_id, "sale_contract", template_id, mapping,
        [(ITEM_CONTRACT, items), (STAGE_CONTRACT, stages)],
        f"{contract.contract_code or '销售合同'}.docx",
    )


def _order(db, company, record_id, template_id, direction, doc_code):
    order = get_row(db, ContractOrder, record_id, company.id)
    if order.direction != direction:
        label = "销售订单" if direction == "sale" else "采购订单"
        raise BizError(f"只有{label}可以生成这张表单")
    contract = db.get(Contract, order.contract_id)
    party = db.get(Party, order.party_id)
    items = []
    for item in calc.order_items(db, order.id):
        moved = calc.moved_qty(db, contract, item.material_code) if contract else ZERO
        items.append({
            "物料编号": item.material_code or "",
            "中文名称": item.name_cn or "",
            "物料名称": item.name_cn or "",
            "规格": item.spec or "",
            "单位": item.unit or "",
            "数量": qty_str(item.qty),
            "含税单价": money_comma(item.price),
            "行金额": money_comma(line_amount(item.qty, item.price)),
            "到货发货": calc.arrival_text(item.name_cn or "", item.unit or "", moved, item.qty, direction == "sale"),
        })
    mapping = {
        **_our(db, company),
        **_their(db, party, contract.party_name if contract else ""),
        "订单号": order.order_code or "",
        "合同编号": contract.contract_code if contract else "",
        "合同名称": contract.name if contract else "",
        "备注": order.remark or "",
        "对方名称": _first(contract.party_name if contract else "", party.name if party else ""),
    }
    label = "销售订单" if direction == "sale" else "采购订单"
    return _finish(
        db, order.company_id, doc_code, template_id, mapping,
        [(ITEM_ORDER, items)],
        f"{order.order_code or label}.docx",
    )


def _invoice(db, company, record_id, template_id, direction, doc_code):
    invoice = get_row(db, Invoice, record_id, company.id)
    if invoice.direction != direction:
        label = "进项发票" if direction == "input" else "销项发票"
        raise BizError(f"只有{label}可以生成这张表单")
    contract = db.get(Contract, invoice.contract_id)
    party = db.get(Party, invoice.party_id)
    rows = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id, InvoiceItem.deleted_at.is_(None)).order_by(InvoiceItem.id).all()
    items = []
    qty_total = D(0)
    for item in rows:
        qty_total += D(item.qty)
        items.append({
            "物料编号": item.material_code or "",
            "物料名称": item.name_cn or "",
            "数量": qty_str(item.qty),
            "含税单价": money_comma(item.price),
            "行不含税金额": money_comma(item.amount_ex_tax),
            "行税额": money_comma(item.tax),
            "行税率": _rate(item.tax_rate),
        })
    mapping = {
        **_our(db, company),
        **_their(db, party, invoice.party_name or ""),
        **_project(db, contract.project_id if contract else None),
        "单据编号": invoice.bill_code or "",
        "客商名称": _first(party.name if party else "", invoice.party_name),
        "客商编码": _clean(party.code) if party else "",
        "合同编号": contract.contract_code if contract else "",
        "合同名称": contract.name if contract else "",
        "发票号码": invoice.invoice_no or "",
        "发票日期": _day(invoice.invoice_date),
        "发票类型": invoice.invoice_type or "",
        "对方名称": invoice.party_name or "",
        "对方税号": _first(invoice.party_tax_no, party.tax_no if party else ""),
        "不含税金额": money_comma(invoice.amount_ex_tax),
        "税额": money_comma(invoice.tax),
        "价税合计": money_comma(invoice.total),
        "数量合计": qty_str(qty_total),
        "备注": invoice.remark or "",
    }
    label = "进项发票" if direction == "input" else "销项发票"
    return _finish(
        db, invoice.company_id, doc_code, template_id, mapping,
        [(ITEM_INVOICE, items)],
        f"{invoice.invoice_no or invoice.bill_code or label}.docx",
    )


def _settle(db, company, record_id, template_id, direction, doc_code):
    bill = get_row(db, SettleBill, record_id, company.id)
    if bill.direction != direction:
        label = "收款单" if direction == "receipt" else "付款单"
        raise BizError(f"只有{label}可以生成这张表单")
    contract = db.get(Contract, bill.contract_id)
    party = db.get(Party, bill.party_id)
    unpaid = max0(D(contract.amount) - D(contract.settled_sum)) if contract else ZERO
    stages = []
    if contract:
        for stage in calc.stages_of(db, contract.id):
            remain = max0(D(stage.plan_amount) - D(stage.settled_amount))
            current = money_comma(bill.amount) if stage.id == bill.stage_id else ""
            stages.append({
                "阶段名称": stage.name or "",
                "阶段金额": money_comma(stage.plan_amount),
                "阶段已结": money_comma(stage.settled_amount),
                "阶段剩余": money_comma(remain),
                "本次金额": current,
            })
    mapping = {
        **_our(db, company),
        **_their(db, party, bill.party_name or ""),
        "单据编号": bill.bill_code or "",
        "单据日期": _day(bill.bill_date),
        "对方名称": _first(bill.party_name, party.name if party else ""),
        "合同编号": contract.contract_code if contract else "",
        "合同名称": contract.name if contract else "",
        "账户": bill.account_name or "",
        "合同金额": money_comma(contract.amount) if contract else "",
        "已结金额": money_comma(contract.settled_sum) if contract else "",
        "未结金额": money_comma(unpaid) if contract else "",
        "本次金额": money_comma(bill.amount),
        "备注": bill.remark or "",
    }
    label = "收款单" if direction == "receipt" else "付款单"
    return _finish(
        db, bill.company_id, doc_code, template_id, mapping,
        [(STAGE_PAY, stages)],
        f"{bill.bill_code or label}.docx",
    )


def _wms(db, company, record_id, template_id, bill_type, doc_code):
    bill = get_row(db, WmsBill, record_id, company.id)
    if bill.type != bill_type:
        label = "采购入库" if bill_type == "inbound" else "销售出库"
        raise BizError(f"只有{label}可以生成这张表单")
    contract = db.get(Contract, bill.contract_id)
    party = db.get(Party, bill.party_id)
    warehouse = db.get(Warehouse, bill.warehouse_id)
    rows = db.query(WmsItem).filter(WmsItem.bill_id == bill.id, WmsItem.deleted_at.is_(None)).order_by(WmsItem.id).all()
    items = [{
        "物料编号": item.material_code or "",
        "中文名称": item.name_cn or "",
        "物料名称": item.name_cn or "",
        "使用设备": item.category or "",
        "单位": item.unit or "",
        "数量": qty_str(item.qty),
        "含税单价": money_comma(item.price),
        "行金额": money_comma(item.amount),
    } for item in rows]
    mapping = {
        **_our(db, company),
        **_their(db, party, bill.party_name or ""),
        "单据编号": bill.bill_code or "",
        "单据日期": _day(bill.bill_date),
        "合同编号": contract.contract_code if contract else "",
        "合同名称": contract.name if contract else "",
        "对方名称": _first(bill.party_name, party.name if party else ""),
        "仓库": warehouse.name if warehouse else "",
        "使用设备": "、".join(dict.fromkeys(item.get("使用设备") for item in items if item.get("使用设备"))),
        "备注": bill.remark or "",
    }
    label = "采购入库" if bill_type == "inbound" else "销售出库"
    return _finish(
        db, bill.company_id, doc_code, template_id, mapping,
        [(ITEM_WMS, items)],
        f"{bill.bill_code or label}.docx",
    )


def _customs_invoice(db, company, record_id, template_id):
    from . import customs

    invoice = get_row(db, CustomsInvoice, record_id, company.id)
    if not invoice.customs_element_id:
        raise BizError("当前报关发票尚未关联报关要素，请先完成报关要素后再导出。")
    detail = customs.invoice_view(db, invoice)
    items = [{
        "序号": str(item.get("seq") or ""),
        "申报大类": item.get("name_cn") or "",
        "英文名称": item.get("name_en") or "",
        "规格": item.get("specification") or "",
        "数量": item.get("quantity") or "",
        "单位": item.get("unit") or "",
        "人民币单价": item.get("price") or "",
        "人民币总价": item.get("amount") or "",
        "装箱数": str(item.get("packages") or ""),
    } for item in detail.get("items") or []]
    sources = [{
        "物料编号": item.get("material_code") or "",
        "物料名称": item.get("material_name") or "",
        "箱号": item.get("box_no") or "",
        "集装箱号": item.get("container_no") or "",
        "入仓单": item.get("receipt_no") or "",
        "箱单号": item.get("packing_list_no") or "",
        "船名/航号": item.get("vessel_voyage") or "",
        "合同号": item.get("contract_no") or "",
    } for item in detail.get("sources") or []]
    mapping = {
        **_our(db, company),
        "发票编号": invoice.invoice_no or "",
        "发票日期": _day(invoice.invoice_date),
        "合同号": invoice.contract_no or "",
        "总金额": detail.get("total_amount") or "",
        "币种": invoice.currency or "CNY",
        "状态": invoice.status or "",
    }
    path, rule = resolve_export(db, invoice.company_id, "customs_invoice", template_id)
    filename = align_export_name(render_filename(rule, mapping, f"{invoice.invoice_no or '报关发票'}.xlsx"), path)
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        from .customs_xlsx import export_invoice_xlsx

        content, _name = export_invoice_xlsx(detail, template_path=path)
        return content, filename
    return _finish(
        db, invoice.company_id, "customs_invoice", template_id, mapping,
        [(ITEM_CUSTOMS_INV, items), (ITEM_CUSTOMS_SRC, sources)],
        f"{invoice.invoice_no or '报关发票'}.docx",
    )


def _customs_clearance(db, company, record_id, template_id):
    from . import customs

    row = get_row(db, CustomsClearance, record_id, company.id)
    detail = customs.clearance_view(db, row)
    items = [{
        "序号": str(item.get("seq") or ""),
        "中文名": item.get("name_cn") or "",
        "英文名": item.get("name_en") or "",
        "规格": item.get("specification") or "",
        "数量": item.get("quantity") or "",
        "单位": item.get("unit") or "",
        "人民币单价": item.get("price") or "",
        "人民币总价": item.get("amount") or "",
        "换算美元金额": item.get("amount_usd") or "",
        "PO单号": item.get("po_no") or "",
        "备注": item.get("remark") or "",
    } for item in detail.get("items") or []]
    packing = [{
        "序列号": str(item.get("seq") or ""),
        "品名": item.get("category") or "",
        "规格": item.get("specification") or "",
        "数量": item.get("quantity") or "",
        "单位": item.get("unit") or "",
        "包件数": str(item.get("packages") or ""),
        "包装件数": str(item.get("packages") or ""),
        "毛重": item.get("gross_weight") or "",
        "净重": item.get("net_weight") or "",
        "尺寸": item.get("size_text") or "",
        "入仓单号": item.get("receipt_no") or "",
        "中文名": item.get("category") or "",
    } for item in detail.get("packing") or []]
    mapping = {
        **_our(db, company),
        "发票号": "" if detail.get("invoice_missing") else (detail.get("invoice_no") or ""),
        "制单日期": detail.get("invoice_date") or "",
        "船名": detail.get("vessel_name") or "",
        "航号": detail.get("voyage_no") or "",
        "船名/航号": detail.get("vessel_voyage") or "",
        "集装箱号": detail.get("container_no") or "",
        "提单号": detail.get("bill_no") or "",
        "出发港口": detail.get("port_of_shipment") or "",
        "出发港": detail.get("port_of_shipment") or "",
        "装箱号": detail.get("packing_list_no") or "",
        "汇率": detail.get("exchange_rate") or "",
        "人民币合计": detail.get("total_amount") or "",
        "美元合计": detail.get("total_usd") or "",
        "状态": detail.get("status") or "",
    }
    if not detail.get("exchange_rate"):
        linked = next((item.invoice_id for item in customs._clearance_materials(db, row) if item.invoice_id), None)
        invoice = db.get(CustomsInvoice, linked) if linked else None
        if invoice and invoice.exchange_rate not in (None, ""):
            detail["exchange_rate"] = qty_str(invoice.exchange_rate)
    path, rule = resolve_export(db, row.company_id, "customs_clearance", template_id)
    filename = align_export_name(render_filename(rule, mapping, f"{row.invoice_no or '清关发票'}.xlsx"), path)
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        from .customs_xlsx import export_clearance_xlsx

        return export_clearance_xlsx(detail, path), filename
    return _finish(
        db, row.company_id, "customs_clearance", template_id, mapping,
        [(ITEM_CUSTOMS_CLR, items), (ITEM_CUSTOMS_PACK, packing)],
        f"{row.invoice_no or '清关发票'}.docx",
    )


def _customs_element(db, company, record_id, template_id):
    from . import customs

    row = get_row(db, CustomsElement, record_id, company.id)
    detail = customs.element_view(db, row)
    items = []
    for item in detail.get("items") or []:
        lines = item.get("lines") or [{}]
        for line in lines:
            model = line.get("model") or item.get("specification") or ""
            elements = line.get("declaration_elements") or item.get("declaration_elements") or ""
            product = line.get("product_name") or ""
            origin = line.get("origin_place") or ""
            items.append({
                "序号": str(item.get("seq") or ""),
                "HS Code": item.get("hs_code") or "",
                "HS CODE": item.get("hs_code") or "",
                "申报名称": item.get("declaration_name") or "",
                "产品名称": product,
                "明细物料": product,
                "申报规格": model,
                "型号": model,
                "报关要素": elements,
                "申报要素": elements,
                "货源地": origin,
                "数量": item.get("quantity") or "",
            })
    mapping = {
        **_our(db, company),
        "报关发票编号": detail.get("invoice_no") or "",
        "状态": detail.get("status") or "",
    }
    path, rule = resolve_export(db, row.company_id, "customs_element", template_id)
    filename = align_export_name(render_filename(rule, mapping, f"{detail.get('invoice_no') or '报关要素'}-报关要素.xlsx"), path)
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        from .customs_xlsx import export_element_xlsx

        return export_element_xlsx(detail, path), filename
    return _finish(
        db, row.company_id, "customs_element", template_id, mapping,
        [(ITEM_CUSTOMS_EL, items)],
        f"{detail.get('invoice_no') or '报关要素'}-报关要素.docx",
    )


_BUILDERS = {
    "sale_contract": _sale_contract,
    "purchase_order": lambda db, company, record_id, template_id: _order(db, company, record_id, template_id, "purchase", "purchase_order"),
    "sale_order": lambda db, company, record_id, template_id: _order(db, company, record_id, template_id, "sale", "sale_order"),
    "input_invoice": lambda db, company, record_id, template_id: _invoice(db, company, record_id, template_id, "input", "input_invoice"),
    "output_invoice": lambda db, company, record_id, template_id: _invoice(db, company, record_id, template_id, "output", "output_invoice"),
    "payment": lambda db, company, record_id, template_id: _settle(db, company, record_id, template_id, "payment", "payment"),
    "receipt": lambda db, company, record_id, template_id: _settle(db, company, record_id, template_id, "receipt", "receipt"),
    "purchase_in": lambda db, company, record_id, template_id: _wms(db, company, record_id, template_id, "inbound", "purchase_in"),
    "sale_out": lambda db, company, record_id, template_id: _wms(db, company, record_id, template_id, "outbound", "sale_out"),
    "customs_invoice": _customs_invoice,
    "customs_clearance": _customs_clearance,
    "customs_element": _customs_element,
}


def build_form(db, company, doc_code: str, record_id: int, template_id: int | None = None) -> tuple[bytes, str]:
    builder = _BUILDERS.get(doc_code)
    if builder is None:
        raise BizError("这种单据还不能生成")
    if company is None:
        raise BizError("请先选择公司")
    return builder(db, company, record_id, template_id)
