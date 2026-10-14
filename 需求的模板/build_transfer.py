# -*- coding: utf-8 -*-
"""生成合同系统批量传输工作簿。"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent
XLSX = ROOT / "_传输.xlsx"
XLSM = ROOT / "传输.xlsm"
BAS = ROOT / "传输代码.bas"

RED = Font(bold=True, color="9C2F2F")
BLUE = Font(bold=True, color="1F4E79")
GRAY = Font(bold=True, color="666666")
FILL_REQ = PatternFill("solid", fgColor="FDE9E9")
FILL_OPT = PatternFill("solid", fgColor="D6E3F0")
FILL_RO = PatternFill("solid", fgColor="F2F2F2")
FILL_MARK = PatternFill("solid", fgColor="1F4E79")
MARK_FONT = Font(bold=True, color="FFFFFF", size=14)
WRAP = Alignment(wrap_text=True, vertical="center")

# 表, 分段, 字段, 键, 必填(是/或/否), 标记(只读/空), 别名
FIELDS = []


def add(sheet, section, rows):
    for field, key, required, flag, alias in rows:
        FIELDS.append((sheet, section, field, key, required, flag, alias))


add("客商", "明细", [
    ("客商类型", "type", "是", "", "类型"),
    ("编码", "code", "是", "", "供应商编码|客户编码"),
    ("名称", "name", "是", "", "供应商名称|客户名称"),
    ("简称", "short_name", "否", "", "供应商简称|客户简称"),
    ("联系人", "contact_name", "否", "", ""),
    ("联系电话", "contact_phone", "否", "", ""),
    ("手机", "mobile", "否", "", ""),
    ("邮箱", "email", "否", "", ""),
    ("业务员", "salesman_id", "否", "", ""),
    ("供应商类别", "supplier_category", "否", "", ""),
    ("纳税人识别号", "tax_no", "否", "", "税号"),
    ("默认税率", "default_tax_rate", "否", "", ""),
    ("开票名称", "invoice_title", "否", "", ""),
    ("开户银行", "bank_name", "否", "", ""),
    ("账户名称", "account_name", "否", "", ""),
    ("银行账号", "bank_account", "否", "", ""),
    ("开户支行", "bank_branch", "否", "", ""),
    ("开票电话", "invoice_phone", "否", "", ""),
    ("开票地址", "invoice_address", "否", "", ""),
    ("通讯地址", "address", "否", "", "地址"),
    ("法人代表", "legal_name", "否", "", ""),
    ("委托代理人", "agent_name", "否", "", ""),
    ("状态", "status", "否", "", ""),
    ("备注", "remark", "否", "", ""),
])

add("项目", "明细", [
    ("项目编号", "project_code", "是", "", ""),
    ("项目名称", "name", "是", "", ""),
    ("年度", "year", "否", "", ""),
    ("项目类型", "project_type", "否", "", ""),
    ("来源", "source", "否", "", ""),
    ("客户名称", "customer_name", "否", "", ""),
    ("开始日期", "start_date", "否", "", ""),
    ("结束日期", "end_date", "否", "", ""),
    ("状态", "status", "否", "", ""),
    ("备注", "remark", "否", "", ""),
])

PURCHASE_HEAD = [
    ("合同编号", "contract_code", "是", "", ""),
    ("合同名称", "name", "否", "", ""),
    ("合同类型", "type_name", "否", "", ""),
    ("供应商", "party_name", "或", "", "供应商名称|对方名称"),
    ("供应商编码", "party_code", "或", "", "对方编码"),
    ("业务员", "owner_id", "否", "", "业务员员工编号"),
    ("项目编号", "project_code", "否", "", ""),
    ("合同状态", "status", "否", "", ""),
    ("计价方式", "pricing", "否", "", ""),
    ("税率", "tax_rate", "否", "", ""),
    ("签订日期", "sign_date", "否", "", ""),
    ("开始日期", "start_date", "否", "", ""),
    ("结束日期", "end_date", "否", "", ""),
    ("标的名称", "subject_name", "否", "", ""),
    ("收货地址", "ship_address", "否", "", ""),
    ("收货人", "receiver_name", "否", "", ""),
    ("运输方式", "transport_mode", "否", "", ""),
    ("交货期限", "delivery_term", "否", "", ""),
    ("运费承担", "freight_bearer", "否", "", ""),
    ("付款条款", "terms", "否", "", "条款"),
    ("验收标准", "acceptance_text", "否", "", ""),
    ("附件说明", "annex_note", "否", "", ""),
    ("内容概述", "content", "否", "", ""),
    ("备注", "remark", "否", "", ""),
]
SALE_HEAD = [
    ("合同编号", "contract_code", "是", "", ""),
    ("合同名称", "name", "否", "", ""),
    ("合同类型", "type_name", "否", "", ""),
    ("客户", "party_name", "或", "", "客户名称|对方名称"),
    ("客户编码", "party_code", "或", "", "对方编码"),
    ("业务员", "owner_id", "否", "", "业务员员工编号"),
    ("项目编号", "project_code", "否", "", ""),
    ("合同状态", "status", "否", "", ""),
    ("计价方式", "pricing", "否", "", ""),
    ("税率", "tax_rate", "否", "", ""),
    ("签订日期", "sign_date", "否", "", ""),
    ("开始日期", "start_date", "否", "", ""),
    ("结束日期", "end_date", "否", "", ""),
    ("内容概述", "content", "否", "", ""),
    ("条款", "terms", "否", "", "付款条款"),
    ("备注", "remark", "否", "", ""),
]
ITEM = [
    ("合同编号", "contract_code", "否", "", "对应合同编号"),
    ("物料编号", "material_code", "是", "", ""),
    ("中文名称", "name_cn", "否", "", ""),
    ("英文名称", "name_en", "否", "", ""),
    ("规格", "spec", "否", "", "规格型号"),
    ("单位", "unit", "否", "", ""),
    ("数量", "qty", "是", "", ""),
    ("含税单价", "price", "是", "", ""),
    ("备注", "remark", "否", "", "明细备注"),
]
PURCHASE_ITEM = ITEM + [
    ("计划单号", "plan_no", "否", "", ""),
    ("使用设备", "category", "否", "", ""),
]
STAGE = [
    ("合同编号", "contract_code", "否", "", "对应合同编号"),
    ("阶段名称", "name", "是", "", ""),
    ("比例", "ratio", "否", "", ""),
    ("计划金额", "plan_amount", "否", "", ""),
    ("计划日期", "plan_date", "否", "", ""),
    ("备注", "remark", "否", "", "阶段备注"),
]
add("采购合同", "主表", PURCHASE_HEAD)
add("采购合同", "物料明细", PURCHASE_ITEM)
add("采购合同", "阶段付款", STAGE + [("到货阶段", "arrival_flag", "否", "", "")])
add("销售合同", "主表", SALE_HEAD)
add("销售合同", "物料明细", ITEM)
add("销售合同", "阶段付款", STAGE + [("发货阶段", "ship_flag", "否", "", "")])

CUSTOMS = [
    ("物料编号", "material_code", "是", "", ""),
    ("入仓单号", "receipt_no", "否", "", ""),
    ("物料名称", "material_name", "否", "只读", "中文名称"),
    ("英文名称", "material_name_en", "否", "只读", ""),
    ("规格", "specification", "否", "只读", ""),
    ("单位", "unit", "否", "只读", ""),
    ("数量", "quantity", "否", "只读", ""),
    ("合同号", "contract_no", "否", "只读", ""),
    ("供应商", "supplier_name", "否", "只读", ""),
    ("入仓日期", "receipt_date", "否", "只读", ""),
    ("含税单价", "price", "否", "只读", ""),
    ("产地", "origin_country", "否", "", ""),
    ("箱号", "box_no", "否", "", ""),
    ("尺寸", "size", "否", "", ""),
    ("长", "length", "否", "", ""),
    ("宽", "width", "否", "", ""),
    ("高", "height", "否", "", ""),
    ("净重", "net_weight", "否", "", ""),
    ("毛重", "gross_weight", "否", "", ""),
    ("体积", "volume", "否", "", ""),
    ("出发港", "port_of_shipment", "否", "", "出发港口"),
    ("目的港", "port_of_destination", "否", "", ""),
    ("集装箱号", "container_no", "否", "", ""),
    ("提单号", "bill_no", "否", "", ""),
    ("船名/航号", "vessel_voyage", "否", "", ""),
    ("箱单号", "packing_list_no", "否", "", ""),
    ("物料大类", "material_category", "否", "", ""),
    ("使用设备", "equipment", "否", "", ""),
    ("HS Code", "hs_code", "否", "", "HSCODE"),
    ("收货人", "consignee", "否", "", ""),
    ("包件件数", "package_count", "否", "", ""),
    ("付款条款", "payment_terms", "否", "", ""),
    ("申报要素", "declaration_elements", "否", "", ""),
    ("备注", "remark", "否", "", ""),
]
add("报关物料清单", "物料明细", CUSTOMS)

add("HSCode库", "明细", [
    ("HS Code", "HS Code", "是", "", "HSCODE"),
    ("申报名称", "申报名称", "是", "", ""),
    ("产品名称", "产品名称", "否", "", ""),
    ("申报规格", "申报规格", "否", "", ""),
    ("报关要素", "报关要素", "否", "", ""),
    ("描述", "描述", "否", "", ""),
    ("状态", "状态", "否", "", ""),
])
add("汇率库", "明细", [
    ("年", "year", "是", "", "年度"),
    ("月", "month", "是", "", "月份"),
    ("币种", "currency", "否", "", ""),
    ("汇率", "rate", "是", "", ""),
    ("生效日期", "effective_date", "否", "", ""),
])
add("公司管理", "明细", [
    ("编号", "code", "否", "", "公司编号"),
    ("公司名称", "name", "是", "", ""),
    ("简称", "short_name", "否", "", ""),
    ("状态", "status", "否", "", ""),
    ("默认税率", "default_tax_rate", "否", "", ""),
    ("业务员", "salesman_id", "否", "", ""),
    ("纳税人识别号", "tax_no", "否", "", ""),
    ("开票名称", "invoice_title", "否", "", ""),
    ("开户银行", "bank_name", "否", "", ""),
    ("账户名称", "account_name", "否", "", ""),
    ("银行账号", "bank_account", "否", "", ""),
    ("开户支行", "bank_branch", "否", "", ""),
    ("开票电话", "invoice_phone", "否", "", ""),
    ("开票地址", "invoice_address", "否", "", ""),
    ("通讯地址", "address", "否", "", ""),
    ("邮箱", "email", "否", "", ""),
    ("手机", "mobile", "否", "", ""),
    ("法人代表", "legal_name", "否", "", ""),
    ("委托代理人", "agent_name", "否", "", ""),
    ("联系人", "contact_name", "否", "", ""),
    ("联系电话", "contact_phone", "否", "", ""),
    ("备注", "remark", "否", "", ""),
])
add("资金账户", "明细", [
    ("编码", "code", "是", "", ""),
    ("名称", "name", "是", "", ""),
    ("账号", "account_no", "否", "", ""),
    ("状态", "status", "否", "", ""),
])
add("合同类型", "明细", [
    ("编码", "code", "是", "", ""),
    ("名称", "name", "是", "", ""),
    ("备注", "remark", "否", "", ""),
    ("状态", "status", "否", "", ""),
])
add("采购计划", "明细", [
    ("计划月份", "计划月份", "否", "", "月份"),
    ("采购序号", "采购序号", "否", "", "序号"),
    ("物料编号", "物料编号", "是", "", "物料编码|物料代码"),
    ("采购计划单号", "采购计划单号", "否", "", "计划单号"),
    ("使用设备", "使用设备", "否", "", "类别"),
    ("中文名称", "中文名称", "是", "", ""),
    ("英文名称", "英文名称", "否", "", ""),
    ("规格型号", "规格型号", "否", "", "规格"),
    ("单位", "单位", "否", "", ""),
    ("采购数量", "采购数量", "是", "", ""),
    ("用途", "用途", "否", "", ""),
    ("使用部门", "使用部门", "否", "", ""),
    ("备注", "备注", "否", "", ""),
    ("库存数量", "库存数量", "否", "", ""),
    ("在途数量", "在途数量", "否", "", ""),
    ("4个月消耗量", "4个月消耗量", "否", "", ""),
])
add("商品", "明细", [
    ("物料编号", "物料编号", "是", "", ""),
    ("名称", "名称", "是", "", ""),
    ("规格", "规格", "否", "", ""),
    ("单位", "单位", "是", "", ""),
    ("分类编码", "分类编码", "否", "", ""),
    ("含税单价", "含税单价", "否", "", ""),
])
add("采购订单", "明细", [
    ("订单编号", "订单编号", "否", "", ""),
    ("源合同编号", "源合同编号", "是", "", ""),
    ("单据日期", "单据日期", "否", "", ""),
    ("备注", "备注", "否", "", ""),
    ("物料编号", "物料编号", "是", "", ""),
    ("数量", "数量", "是", "", ""),
    ("含税单价", "含税单价", "是", "", ""),
])
add("销售订单", "明细", [
    ("订单编号", "订单编号", "否", "", ""),
    ("源合同编号", "源合同编号", "是", "", ""),
    ("单据日期", "单据日期", "否", "", ""),
    ("备注", "备注", "否", "", ""),
    ("物料编号", "物料编号", "是", "", ""),
    ("数量", "数量", "是", "", ""),
    ("含税单价", "含税单价", "是", "", ""),
])
add("进项发票", "明细", [
    ("单据编号", "单据编号", "否", "", ""),
    ("发票号码", "发票号码", "是", "", ""),
    ("发票日期", "发票日期", "否", "", ""),
    ("发票类型", "发票类型", "否", "", ""),
    ("客商编码", "客商编码", "否", "", ""),
    ("合同编号", "合同编号", "是", "", ""),
    ("不含税金额", "不含税金额", "否", "", ""),
    ("税额", "税额", "否", "", ""),
    ("价税合计", "价税合计", "否", "", ""),
    ("备注", "备注", "否", "", ""),
    ("物料编号", "物料编号", "是", "", ""),
    ("数量", "数量", "是", "", ""),
    ("含税单价", "含税单价", "否", "", ""),
    ("税率", "税率", "否", "", ""),
])
add("销项发票", "明细", [
    ("单据编号", "单据编号", "否", "", ""),
    ("发票号码", "发票号码", "是", "", ""),
    ("发票日期", "发票日期", "否", "", ""),
    ("发票类型", "发票类型", "否", "", ""),
    ("客商编码", "客商编码", "否", "", ""),
    ("合同编号", "合同编号", "是", "", ""),
    ("不含税金额", "不含税金额", "否", "", ""),
    ("税额", "税额", "否", "", ""),
    ("价税合计", "价税合计", "否", "", ""),
    ("备注", "备注", "否", "", ""),
    ("物料编号", "物料编号", "是", "", ""),
    ("数量", "数量", "是", "", ""),
    ("含税单价", "含税单价", "否", "", ""),
    ("税率", "税率", "否", "", ""),
])
add("付款单", "明细", [
    ("单据编号", "单据编号", "否", "", ""),
    ("单据日期", "单据日期", "否", "", ""),
    ("客商编码", "客商编码", "否", "", ""),
    ("合同编号", "合同编号", "是", "", ""),
    ("阶段序号", "阶段序号", "或", "", ""),
    ("阶段名称", "阶段名称", "或", "", ""),
    ("金额", "金额", "是", "", ""),
    ("账户", "账户", "否", "", ""),
    ("备注", "备注", "否", "", ""),
])
add("收款单", "明细", [
    ("单据编号", "单据编号", "否", "", ""),
    ("单据日期", "单据日期", "否", "", ""),
    ("客商编码", "客商编码", "否", "", ""),
    ("合同编号", "合同编号", "是", "", ""),
    ("阶段序号", "阶段序号", "或", "", ""),
    ("阶段名称", "阶段名称", "或", "", ""),
    ("金额", "金额", "是", "", ""),
    ("账户", "账户", "否", "", ""),
    ("备注", "备注", "否", "", ""),
])
add("入仓单", "明细", [
    ("入仓单号", "入仓单号", "否", "", ""),
    ("入仓日期", "入仓日期", "否", "", ""),
    ("合同号", "合同号", "否", "", ""),
    ("箱单号", "箱单号", "否", "", ""),
    ("物料大类", "物料大类", "否", "", ""),
    ("物料编号", "物料编号", "是", "", ""),
    ("中文名称", "中文名称", "是", "", ""),
    ("英文名称", "英文名称", "否", "", ""),
    ("规格", "规格", "否", "", ""),
    ("单位", "单位", "否", "", ""),
    ("数量", "数量", "是", "", ""),
    ("产地", "产地", "否", "", ""),
    ("使用设备", "使用设备", "否", "", ""),
    ("箱号", "箱号", "否", "", ""),
    ("集装箱号", "集装箱号", "否", "", ""),
    ("提单号", "提单号", "否", "", ""),
    ("船名/航号", "船名/航号", "否", "", ""),
    ("毛重", "毛重", "否", "", ""),
    ("净重", "净重", "否", "", ""),
    ("长", "长", "否", "", ""),
    ("宽", "宽", "否", "", ""),
    ("高", "高", "否", "", ""),
    ("体积", "体积", "否", "", ""),
    ("PO单号", "PO单号", "否", "", ""),
    ("含税单价", "含税单价", "否", "", ""),
    ("特殊申报", "特殊申报", "否", "", ""),
    ("包件件数", "包件件数", "否", "", ""),
    ("询价名称", "询价名称", "否", "", ""),
    ("询价型号", "询价型号", "否", "", ""),
    ("询价数量", "询价数量", "否", "", ""),
    ("出发港", "出发港", "否", "", "出发港口"),
    ("目的港", "目的港", "否", "", ""),
    ("收货人", "收货人", "否", "", ""),
    ("付款条款", "付款条款", "否", "", ""),
    ("HS Code", "HS Code", "否", "", "HSCODE"),
    ("申报要素", "申报要素", "否", "", ""),
    ("备注", "备注", "否", "", ""),
])

SIMPLE = [
    "客商", "项目", "HSCode库", "汇率库", "公司管理", "资金账户", "合同类型",
    "采购计划", "商品", "采购订单", "销售订单", "进项发票", "销项发票",
    "付款单", "收款单", "入仓单",
]


def headers_of(sheet, section):
    return [row[2] for row in FIELDS if row[0] == sheet and row[1] == section]


def style_header(cell, required, flag):
    cell.alignment = WRAP
    if flag == "只读":
        cell.font = GRAY
        cell.fill = FILL_RO
        cell.comment = Comment("入库带出的对照列。这一列不会回写。", "传输")
    elif required in ("是", "或"):
        cell.font = RED
        cell.fill = FILL_REQ
        cell.comment = Comment("关键字段，不能删除这一列。单元格可以按行留空的，只限于非关键列。", "传输")
    else:
        cell.font = BLUE
        cell.fill = FILL_OPT
        cell.comment = Comment("不需要的列可以直接删除。不能改成字段库里没有的名字。", "传输")


def write_headers(ws, row, names, sheet, section):
    meta = {(item[2], item[4], item[5]) for item in FIELDS if item[0] == sheet and item[1] == section}
    lookup = {item[2]: item for item in FIELDS if item[0] == sheet and item[1] == section}
    for col, name in enumerate(names, 1):
        cell = ws.cell(row, col, name)
        spec = lookup[name]
        style_header(cell, spec[4], spec[5])
        ws.column_dimensions[get_column_letter(col)].width = max(14, min(28, len(name) * 2 + 4))
    ws.auto_filter.ref = None
    ws.row_dimensions[row].height = 22
    ws.freeze_panes = f"A{row + 1}"
    ws.auto_filter.ref = f"A{row}:{get_column_letter(len(names))}{row}"


def write_simple(wb, name):
    ws = wb.create_sheet(name)
    write_headers(ws, 1, headers_of(name, "明细"), name, "明细")
    ws.sheet_properties.tabColor = "5B9BD5"
    return ws


def write_contract(wb, name):
    ws = wb.create_sheet(name)
    ws.cell(1, 1, "主表").font = MARK_FONT
    ws.cell(1, 1).fill = FILL_MARK
    write_headers(ws, 2, headers_of(name, "主表"), name, "主表")
    ws.cell(4, 1, "物料明细").font = MARK_FONT
    ws.cell(4, 1).fill = FILL_MARK
    write_headers(ws, 5, headers_of(name, "物料明细"), name, "物料明细")
    ws.cell(7, 1, "阶段付款").font = MARK_FONT
    ws.cell(7, 1).fill = FILL_MARK
    write_headers(ws, 8, headers_of(name, "阶段付款"), name, "阶段付款")
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = None
    ws.sheet_properties.tabColor = "C65911"
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[4].height = 24
    ws.row_dimensions[7].height = 24
    return ws


def write_customs(wb):
    ws = wb.create_sheet("报关物料清单")
    ws.cell(1, 1, "先点「使用说明」里的「从入库载入」。灰色列是入库已经有的对照数据，不会回写。白色和蓝色列里，哪一列有值就导入哪一列，空单元格不覆盖原值。物料编号是唯一主键。")
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=8)
    ws.cell(1, 1).alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 22
    ws.cell(3, 1, "物料明细").font = MARK_FONT
    ws.cell(3, 1).fill = FILL_MARK
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=6)
    write_headers(ws, 4, headers_of("报关物料清单", "物料明细"), "报关物料清单", "物料明细")
    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(CUSTOMS))}4"
    ws.sheet_properties.tabColor = "548235"
    return ws


def build_tables():
    wb = Workbook()
    info = wb.active
    info.title = "使用说明"
    lines = [
        ("A1", "合同系统批量传输"),
        ("A2", "服务器"),
        ("B2", "http://127.0.0.1:8001"),
        ("A3", "用户名"),
        ("A4", "密码"),
        ("A5", "公司"),
        ("A6", "登录状态"),
        ("A7", "采购计划方式"),
        ("B7", "按物料编号更新"),
        ("A9", "用法"),
        ("A10", "1. 填写服务器、用户名、密码。公司可填编号、全称或简称；留空则用登录后的默认公司。"),
        ("A11", "2. 打开本文件时选择启用宏。先点「登录」，再点「导入当前工作表」或「按顺序导入全部」。"),
        ("A12", "3. 每张表第 1 行是字段。红色列是关键字段，不能删。其余列可以整列删除。不能把表头改成字段库里没有的名字。"),
        ("A13", "4. 采购合同、销售合同分成三段：主表是字段一行加数据一行；下面是物料明细；再下面是阶段付款。一份合同至少一行物料、一行阶段。主表若有多行，物料和阶段要带上合同编号。"),
        ("A14", "5. 合同名称、业务员可以空着：名称空着时用合同编号，业务员空着时用当前登录人。供应商或客户必须已经在客商里。"),
        ("A15", "6. 阶段只填比例时，金额按比例分摊；比例都空着则平均分摊。到货阶段或发货阶段填「是」的那一行，作为到货或发货阶段。"),
        ("A16", "7. 报关物料清单的数据来自采购入库。点「从入库载入」后，只填写还缺的列。除物料编号外，空列不会覆盖系统原值。"),
        ("A17", "8. 导入顺序是：公司、合同类型、资金账户、客商、项目、HS Code、汇率、商品、采购计划、采购合同、销售合同、订单、发票、收付款、入仓单、报关物料。空表会跳过。"),
        ("A18", "9. 结果写在「导入结果」。字段是否允许，以「字段库」为准，和系统表单字段一致。"),
    ]
    for addr, text in lines:
        info[addr] = text
    info["A1"].font = Font(bold=True, size=18, color="1F4E79")
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 42
    info.row_dimensions[10].height = 20
    for row in range(11, 19):
        info.row_dimensions[row].height = 32
        info.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        info.cell(row, 1).alignment = Alignment(wrap_text=True, vertical="center")
    mode = DataValidation(type="list", formula1='"按物料编号更新,清空后重新导入,追加"', allow_blank=False)
    info.add_data_validation(mode)
    mode.add(info["B7"])

    for name in SIMPLE:
        write_simple(wb, name)
    write_contract(wb, "采购合同")
    write_contract(wb, "销售合同")
    write_customs(wb)

    party = wb["客商"]
    kind = DataValidation(type="list", formula1='"供应商,客户"', allow_blank=False)
    party.add_data_validation(kind)
    kind.add("A2:A500")

    result = wb.create_sheet("导入结果")
    for col, text in enumerate(("时间", "工作表", "结果", "说明"), 1):
        cell = result.cell(1, col, text)
        cell.font = BLUE
        cell.fill = FILL_OPT
    result.column_dimensions["A"].width = 22
    result.column_dimensions["B"].width = 18
    result.column_dimensions["C"].width = 12
    result.column_dimensions["D"].width = 80
    result.freeze_panes = "A2"

    catalog = wb.create_sheet("字段库")
    for col, text in enumerate(("表", "分段", "字段", "键", "必填", "标记", "别名"), 1):
        catalog.cell(1, col, text).font = BLUE
    for index, row in enumerate(FIELDS, 2):
        for col, value in enumerate(row, 1):
            catalog.cell(index, col, value)
    catalog.sheet_state = "hidden"

    info.sheet_view.showGridLines = False
    wb.save(XLSX)


def inject_vba():
    import win32com.client

    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AutomationSecurity = 1
    wb = None
    try:
        wb = excel.Workbooks.Open(str(XLSX))
        references = wb.VBProject.References
        scrrun = "{420B2830-E718-11CF-893D-00A0C9054228}"
        if not any(str(ref.GUID).upper() == scrrun.upper() for ref in references):
            references.AddFromGuid(scrrun, 1, 0)
        json_path = ROOT / "JsonConverter.bas"
        code = BAS.read_text(encoding="utf-8")
        json_code = json_path.read_text(encoding="utf-8")
        if code.startswith("Attribute VB_Name"):
            code = code.split("\n", 1)[1]
        if json_code.startswith("Attribute VB_Name"):
            json_code = json_code.split("\n", 1)[1]
        json_component = wb.VBProject.VBComponents.Add(1)
        json_component.Name = "JsonConverter"
        json_component.CodeModule.AddFromString(json_code)
        component = wb.VBProject.VBComponents.Add(1)
        component.Name = "传输"
        component.CodeModule.AddFromString(code)
        info = wb.Worksheets("使用说明")
        buttons = [
            (220, 18, 90, 28, "登录", "登录"),
            (320, 18, 140, 28, "导入当前工作表", "导入当前工作表"),
            (470, 18, 150, 28, "按顺序导入全部", "按顺序导入全部"),
            (630, 18, 140, 28, "从入库载入", "从入库载入"),
        ]
        for left, top, width, height, caption, macro in buttons:
            button = info.Buttons().Add(left, top, width, height)
            button.Caption = caption
            button.OnAction = macro
        excel.Run("自检")
        if XLSM.exists():
            XLSM.unlink()
        wb.SaveAs(str(XLSM), 52)
        wb.Close(False)
        wb = None
    finally:
        if wb is not None:
            wb.Close(False)
        excel.Quit()
    if XLSX.exists():
        XLSX.unlink()


if __name__ == "__main__":
    build_tables()
    inject_vba()
    print(XLSM)
