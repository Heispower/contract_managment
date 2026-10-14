"""按项目根目录「需求的模板」里的 Word 模板填充采购合同。"""
import zipfile
from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from lxml import etree

from ..config import ROOT
from ..errors import BizError
from ..models import CompanyContact, Party, PartyContact
from ..money import D, qty_str, round2
from . import calc

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
TEMPLATE_NAME = "一般供应商模板.docx"
SAMPLE_EX_TAX = "189,697.79"
SAMPLE_ANNEX = "LZZ5ELSDXMN896549"


def template_path() -> Path:
    return ROOT / "需求的模板" / TEMPLATE_NAME


def money_comma(value) -> str:
    return f"{round2(value):,.2f}"


def cn_date(value) -> str:
    if not value:
        return ""
    return f"{value.year}年{value.month}月{value.day}日"


def rmb_upper(value) -> str:
    amount = round2(value)
    if amount < 0:
        return "负" + rmb_upper(-amount)
    digits = "零壹贰叁肆伍陆柒捌玖"
    small = ["", "拾", "佰", "仟"]
    big = ["", "万", "亿", "兆"]
    text = f"{amount:.2f}"
    integer, decimal = text.split(".")

    def four(block: str) -> str:
        out = ""
        pending_zero = False
        for index, char in enumerate(block):
            number = int(char)
            unit = small[len(block) - index - 1]
            if number == 0:
                pending_zero = True
                continue
            if pending_zero and out:
                out += "零"
            out += digits[number] + unit
            pending_zero = False
        return out

    raw = integer.lstrip("0") or "0"
    if raw == "0":
        head = "零"
    else:
        chunks = []
        while raw:
            chunks.append(raw[-4:])
            raw = raw[:-4]
        pieces = []
        for index, chunk in enumerate(chunks):
            piece = four(chunk)
            if piece:
                pieces.append(piece + big[index])
            elif pieces:
                pieces.append("零")
        head = "".join(reversed(pieces))
        while "零零" in head:
            head = head.replace("零零", "零")
        if head.endswith("零"):
            head = head[:-1]
    jiao = int(decimal[0])
    fen = int(decimal[1])
    if jiao == 0 and fen == 0:
        tail = "整"
    else:
        tail = ""
        if jiao:
            tail += digits[jiao] + "角"
        elif head != "零":
            tail += "零"
        if fen:
            tail += digits[fen] + "分"
    if head == "零" and tail != "整":
        return tail[1:] if tail.startswith("零") else tail
    return head + "元" + tail


def _nodes(element):
    return element.xpath(".//w:t", namespaces=NS)


def _mark_space(node, text: str):
    if text[:1].isspace() or text[-1:].isspace():
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _write_runs(nodes, text: str):
    if not nodes:
        return
    nodes[0].text = text
    _mark_space(nodes[0], text)
    for node in nodes[1:]:
        node.text = ""


def _replace_span(nodes, old: str, new: str) -> bool:
    """只替换占位符所在的文字块，沿用这块原来的字号，不把整段并到第一块。"""
    if not old:
        return False
    texts = [node.text or "" for node in nodes]
    full = "".join(texts)
    start = full.find(old)
    if start < 0:
        return False
    end = start + len(old)
    pos = 0
    start_i = end_i = 0
    start_off = end_off = 0
    found_end = False
    for index, text in enumerate(texts):
        nxt = pos + len(text)
        if pos <= start < nxt:
            start_i = index
            start_off = start - pos
        if pos < end <= nxt:
            end_i = index
            end_off = end - pos
            found_end = True
            break
        pos = nxt
    if not found_end:
        return False
    prefix = texts[start_i][:start_off]
    suffix = texts[end_i][end_off:]
    merged = prefix + new + suffix
    nodes[start_i].text = merged
    _mark_space(nodes[start_i], merged)
    for index in range(start_i + 1, end_i + 1):
        nodes[index].text = ""
    return True


def _paragraph_text(paragraph) -> str:
    return "".join(node.text or "" for node in _nodes(paragraph))


def _replace_paragraph(paragraph, mapping: dict[str, str]):
    nodes = _nodes(paragraph)
    if not nodes:
        return
    original = "".join(node.text or "" for node in nodes)
    if "{{" not in original and SAMPLE_EX_TAX not in original:
        return
    for key in sorted(mapping, key=len, reverse=True):
        token = "{{" + key + "}}"
        while _replace_span(nodes, token, mapping[key] or ""):
            pass
    while _replace_span(nodes, SAMPLE_EX_TAX, mapping.get("不含税金额", "") or ""):
        pass


def _row_text(row) -> str:
    return "".join(row.xpath(".//w:t/text()", namespaces=NS))


def _set_cell(cell, text: str):
    _write_runs(_nodes(cell), text)


def _fill_item_row(row, item: dict, index: int):
    mapping = {
        "物料名称": item.get("name_cn") or "",
        "英文名称": item.get("name_en") or "",
        "规格": item.get("spec") or "",
        "数量": item.get("qty") or "",
        "单位": item.get("unit") or "",
        "含税单价": item.get("price") or "",
        "行价税合计": item.get("amount") or "",
        "使用设备": item.get("category") or "",
    }
    for paragraph in row.xpath(".//w:p", namespaces=NS):
        _replace_paragraph(paragraph, mapping)
    cells = row.xpath("./w:tc", namespaces=NS)
    if cells:
        _set_cell(cells[0], str(index))
    if cells and item.get("remark"):
        _set_cell(cells[-1], item["remark"])


def _expand_items(root, items: list[dict]):
    template = None
    for row in root.xpath(".//w:tr", namespaces=NS):
        text = _row_text(row)
        if "{{物料名称}}" in text and "{{物料名称1}}" not in text and "{{物料名称2}}" not in text:
            template = row
            break
    if template is None:
        raise BizError("模板里没有物料明细占位行")
    parent = template.getparent()
    position = parent.index(template)
    usable = items or [{"name_cn": "", "name_en": "", "spec": "", "qty": "", "unit": "", "price": "", "amount": "", "remark": ""}]
    for offset, item in enumerate(usable):
        clone = deepcopy(template)
        _fill_item_row(clone, item, offset + 1)
        parent.insert(position + offset, clone)
    parent.remove(template)


def _apply_annex(root, note: str):
    for row in list(root.xpath(".//w:tr", namespaces=NS)):
        if SAMPLE_ANNEX not in _row_text(row):
            continue
        if note:
            cells = row.xpath("./w:tc", namespaces=NS)
            if cells:
                _set_cell(cells[0], note)
        else:
            row.getparent().remove(row)
        return


def render_supplier_contract(mapping: dict[str, str], items: list[dict], path: Path) -> bytes:
    if not path.is_file():
        raise BizError(f"找不到模板文件：{path.name}")
    with zipfile.ZipFile(path) as source:
        root = etree.fromstring(source.read("word/document.xml"))
    _expand_items(root, items)
    _apply_annex(root, mapping.get("附件说明") or "")
    for paragraph in root.xpath(".//w:p", namespaces=NS):
        _replace_paragraph(paragraph, mapping)
    document = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    output = BytesIO()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            payload = document if info.filename == "word/document.xml" else source.read(info.filename)
            target.writestr(info, payload)
    return output.getvalue()


def line_amount(qty, price) -> Decimal:
    return round2(D(qty) * D(price))


def _clean(value) -> str:
    return str(value or "").strip()


def _first(*values) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _bank_line(bank: str, branch: str, *names: str) -> str:
    bank = _clean(bank)
    branch = _clean(branch)
    blocked = {_clean(name) for name in names if _clean(name)}
    if branch in blocked:
        branch = ""
    if bank and branch and branch not in bank and bank not in branch:
        return f"{bank} {branch}"
    return branch or bank


def _named_contact(db, model, column, owner_id) -> tuple[str, str]:
    if not owner_id:
        return "", ""
    row = (
        db.query(model)
        .filter(column == owner_id, model.deleted_at.is_(None))
        .order_by(model.is_default.desc(), model.id)
        .first()
    )
    if row is None:
        return "", ""
    return _clean(row.name), _clean(row.phone)


def build_purchase_docx(db, contract, company, template_id: int | None = None) -> tuple[bytes, str]:
    from .export_profile import align_export_name, purchase_export, render_filename

    if contract.direction != "purchase":
        raise BizError("只有采购合同可以生成合同")
    rows = []
    names = []
    plans = []
    devices = []
    qty_total = D(0)
    for item in calc.items_of(db, contract.id):
        amount = line_amount(item.qty, item.price)
        qty_total += D(item.qty)
        if item.name_cn and item.name_cn not in names:
            names.append(item.name_cn)
        if item.plan_no and item.plan_no not in plans:
            plans.append(item.plan_no)
        if item.category and item.category not in devices:
            devices.append(item.category)
        rows.append({
            "name_cn": item.name_cn or "",
            "name_en": item.name_en or "",
            "spec": item.spec or "",
            "qty": qty_str(item.qty),
            "unit": item.unit or "",
            "price": money_comma(item.price),
            "amount": money_comma(amount),
            "category": item.category or "",
            "remark": item.remark or "",
        })
    party = db.get(Party, contract.party_id)
    our_contact, our_phone = _named_contact(db, CompanyContact, CompanyContact.company_id, company.id if company else None)
    their_contact, their_phone = _named_contact(db, PartyContact, PartyContact.party_id, party.id if party else None)
    subject = (contract.subject_name or "").strip() or "、".join(names)
    rate = qty_str(contract.tax_rate)
    if not rate.endswith("%"):
        rate = f"{rate}%"
    amount = money_comma(contract.amount)
    mapping = {
        "对方名称": contract.party_name or "",
        "对方简称": (party.short_name if party else "") or "",
        "合同编号": contract.contract_code or "",
        "签订日期": cn_date(contract.sign_date),
        "我方名称": company.name if company else "",
        "我方简称": company.short_name if company else "",
        "物料名称1": subject,
        "物料名称2": subject,
        "标的名称": subject,
        "合同金额1": amount,
        "合同金额2": amount,
        "合同金额3": amount,
        "不含税金额": money_comma(contract.amount_ex_tax),
        "税率": rate,
        "合同金额（大写）": rmb_upper(contract.amount),
        "收货地址": contract.ship_address or "",
        "运输方式": contract.transport_mode or "",
        "交货期限": contract.delivery_term or "",
        "收货人": contract.receiver_name or "",
        "运费承担": contract.freight_bearer or "",
        "付款方式期限等条款": contract.terms or "",
        "货物验收标准和方法": contract.acceptance_text or "",
        "对方地址": _first(contract.party_address, party.address if party else ""),
        "对方法人": _first(party.legal_name if party else "", contract.party_legal_name),
        "对方代理": _first(party.agent_name if party else "", contract.party_agent),
        "对方联系人": their_contact,
        "对方联系电话": _first(their_phone, contract.party_invoice_phone, party.invoice_phone if party else "", party.mobile if party else ""),
        "对方开票电话": _first(contract.party_invoice_phone, party.invoice_phone if party else "", party.mobile if party else ""),
        "对方银行账号": _first(contract.party_bank_account, party.bank_account if party else ""),
        "对方开户支行": _bank_line(
            _first(contract.party_bank_name, party.bank_name if party else ""),
            _first(contract.party_bank_branch, party.bank_branch if party else ""),
            party.name if party else "",
            party.short_name if party else "",
        ),
        "对方税号": _first(contract.party_tax_no, party.tax_no if party else ""),
        "我方地址": _first(company.address if company else "", company.invoice_address if company else ""),
        "我方法人": _clean(company.legal_name) if company else "",
        "我方代理": _clean(company.agent_name) if company else "",
        "我方联系人": our_contact,
        "我方联系电话": _first(our_phone, company.invoice_phone if company else "", company.mobile if company else ""),
        "我方开票电话": _clean(company.invoice_phone) if company else "",
        "我方银行账号": _clean(company.bank_account) if company else "",
        "我方开户支行": _bank_line(
            company.bank_name if company else "",
            company.bank_branch if company else "",
            company.name if company else "",
            company.short_name if company else "",
        ),
        "我方税号": _clean(company.tax_no) if company else "",
        "计划单号": "、".join(plans),
        "使用设备": "、".join(devices),
        "数量合计": qty_str(qty_total),
        "价税合计": amount,
        "附件说明": contract.annex_note or "",
    }
    path, rule = purchase_export(db, contract.company_id, template_id)
    filename = align_export_name(render_filename(rule, mapping, f"{contract.contract_code or '采购合同'}.docx"), path)
    from .form_docx import is_word_template, render_office

    if is_word_template(path):
        return render_supplier_contract(mapping, rows, path), filename
    items = []
    for index, item in enumerate(rows, start=1):
        items.append({
            "序号": str(index),
            "物料名称": item.get("name_cn") or "",
            "英文名称": item.get("name_en") or "",
            "规格": item.get("spec") or "",
            "数量": item.get("qty") or "",
            "单位": item.get("unit") or "",
            "含税单价": item.get("price") or "",
            "行价税合计": item.get("amount") or "",
            "使用设备": item.get("category") or "",
            "备注": item.get("remark") or "",
        })
    keys = tuple(items[0].keys()) if items else ("物料名称",)
    return render_office(path, mapping, [(keys, items or [{"物料名称": ""}])]), filename
