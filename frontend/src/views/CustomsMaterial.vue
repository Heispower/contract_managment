<template>
  <ListShell ref="shell" title="报关物料清单" storage-key="customs-material-fields" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" export-module="customs-material" :export-query="query" :expandable="false" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters>
      <el-select v-for="field in mainFilters" :key="field.key" v-model="filters[field.key]" clearable filterable :placeholder="field.label" style="width:160px" @change="onFilter(field.key)">
        <el-option v-for="item in (options[field.key] || [])" :key="item" :label="item" :value="item" />
      </el-select>
      <el-checkbox v-for="field in statusFilters" :key="field.key" v-model="filters[field.key]" @change="onStatusFilter">{{ field.label }}</el-checkbox>
    </template>
    <template #toolbar>
      <el-button @click="removeMany">批量删除</el-button>
      <el-dropdown @command="openAssign">
        <el-button>批量赋值</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="item in assignFields" :key="item.key" :command="item.key">{{ item.label }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button @click="showFill = true">批量导入</el-button>
      <el-dropdown @command="generate">
        <el-button type="primary">生成</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="invoice">报关发票</el-dropdown-item>
            <el-dropdown-item command="clearance">清关发票</el-dropdown-item>
            <el-dropdown-item command="element">报关要素</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">详情</span>
      <span class="ops" style="margin-left:8px" @click="open(row, true)">编辑</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="editVisible" class="line-dialog sheet-dialog" width="1080px" top="4vh" append-to-body :close-on-click-modal="false">
    <template #header>
      <div>{{ editing ? "编辑报关物料" : "报关物料详情" }} - <span class="name-pill">{{ form.material_name || form.material_code || "—" }}</span></div>
    </template>
    <div class="board-summary purchase">
      <div class="sum-line">
        <span><em>采购合同</em><b :class="{ danger: !form.contract_code }">{{ form.contract_code || "未关联" }}</b></span>
        <span><em>采购入库</em><b :class="{ danger: !form.inbound_code }">{{ form.inbound_code || "未入库" }}</b></span>
        <span><em>报关发票</em><i :class="['tag', statusTag(form.invoice_generated)]">{{ form.invoice_generated || "未生成" }}</i><template v-if="form.customs_invoice_no"> {{ form.customs_invoice_no }}</template></span>
        <span><em>清关发票</em><i :class="['tag', statusTag(form.clearance_generated)]">{{ form.clearance_generated || "未生成" }}</i><template v-if="form.clearance_invoice_no"> {{ form.clearance_invoice_no }}</template></span>
        <span><em>报关要素</em><i :class="['tag', statusTag(form.element_generated)]">{{ form.element_generated || "未生成" }}</i></span>
        <span><em>报关完毕</em><i :class="['tag', statusTag(form.customs_done)]">{{ form.customs_done || "未报关" }}</i></span>
      </div>
      <div class="sum-line">
        <span><em>物料编号</em><b>{{ form.material_code || "—" }}</b></span>
        <span><em>物料名称</em>{{ form.material_name || "—" }}</span>
        <span><em>物料大类</em><i class="tag tag-blue-soft">{{ form.material_category || "—" }}</i></span>
        <span><em>状态</em><i class="tag tag-green">{{ form.status || "—" }}</i></span>
        <span><em>申报</em><i :class="['tag', form.special_declare ? 'tag-orange' : 'tag-gray']">{{ form.special_label || (form.special_declare ? "特殊申报" : "普通") }}</i></span>
        <span><em>数量</em>{{ form.quantity || "—" }} {{ form.unit }}</span>
        <span v-if="form.missing_text"><em>缺失字段</em><b class="danger">{{ form.missing_text }}</b></span>
      </div>
    </div>
    <div class="sheet-section">单据状态</div>
    <div class="info-grid">
      <div v-for="field in docFields" :key="field.key" class="cell">
        <em>{{ field.label }}</em>
        <span><i :class="['tag', statusTag(form[field.key])]">{{ form[field.key] || field.empty }}</i></span>
      </div>
    </div>
    <template v-for="group in fieldGroups" :key="group.title">
      <div class="sheet-section">{{ group.title }}</div>
      <div class="info-grid">
        <div v-for="field in group.fields" :key="field.key" class="cell" :class="{ wide: wideKeys.has(field.key), 'cell-error': fieldError(field.key) }">
          <em>{{ field.label }}<i v-if="field.required" class="req">*</i></em>
          <span>
            <template v-if="editing && field.key === 'special_declare'"><el-checkbox v-model="form.special_declare">特殊申报</el-checkbox></template>
            <template v-else-if="editing && !field.readonly">
              <el-input v-model="form[field.key]" :type="wideKeys.has(field.key) ? 'textarea' : 'text'" :rows="2" :class="{ 'is-error': fieldError(field.key) }" />
            </template>
            <template v-else-if="field.key === 'special_declare'"><i :class="['tag', form.special_declare ? 'tag-orange' : 'tag-gray']">{{ form.special_declare ? "特殊申报" : "普通" }}</i></template>
            <template v-else>{{ form[field.key] || "—" }}</template>
            <small v-if="fieldError(field.key)" class="cell-hint">{{ fieldError(field.key) }}</small>
          </span>
        </div>
        <template v-if="group.title === '物流信息'">
          <div class="cell"><em>供应商</em><span>{{ form.supplier_name || "—" }}</span></div>
          <div class="cell"><em>入仓日期</em><span>{{ form.receipt_date || "—" }}</span></div>
        </template>
      </div>
    </template>
    <template #footer>
      <el-button v-if="editing" type="primary" @click="save">保存</el-button>
      <el-button @click="editVisible=false">{{ editing ? "取消" : "关闭" }}</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="assignVisible" title="批量赋值" width="420px" append-to-body>
    <el-form label-width="90px">
      <el-form-item label="字段">{{ assignLabel }}</el-form-item>
      <el-form-item label="值">
        <el-select v-if="assignField === 'special_declare'" v-model="assignValue" style="width:100%">
          <el-option label="特殊申报" value="特殊申报" />
          <el-option label="普通" value="普通" />
        </el-select>
        <el-input v-else v-model="assignValue" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="assignVisible=false">取消</el-button>
      <el-button type="primary" @click="doAssign">确定</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="elementVisible" title="生成报关要素" width="560px" append-to-body>
    <el-form label-width="110px">
      <el-form-item label="关联报关发票">
        <el-select v-model="invoiceId" filterable placeholder="只显示所选物料的报关发票" style="width:100%">
          <el-option v-for="item in unused" :key="item.id" :label="invoiceOptionLabel(item)" :value="item.id">
            <div class="invoice-option">
              <div>发票：{{ item.invoice_no || "—" }}</div>
              <div>合同号：{{ item.contract_no || "—" }}</div>
            </div>
          </el-option>
        </el-select>
      </el-form-item>
    </el-form>
    <p class="hint" style="margin:0 0 12px">选择发票后进入报关要素编辑页，核对并修改后再确认生成。</p>
    <template #footer>
      <el-button @click="elementVisible=false">取消</el-button>
      <el-button type="primary" @click="goElement">去审核</el-button>
    </template>
  </el-dialog>
  <ImportWizard v-model="showFill" module="customs-material-fill" @done="load" />
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import http, { batchDelete } from "../api";
import ImportWizard from "../components/ImportWizard.vue";
import ListShell from "../components/ListShell.vue";

const route = useRoute();
const router = useRouter();

const shell = ref(null);
const mainFilters = [
  { key: "receipt_no", label: "入仓单号" },
  { key: "supplier_name", label: "供应商" },
  { key: "contract_no", label: "合同号" },
  { key: "packing_list_no", label: "箱单号" },
  { key: "material_category", label: "物料大类" },
  { key: "material_code", label: "物料编号" },
  { key: "material_name", label: "物料名称" },
  { key: "equipment", label: "使用设备" },
];
const statusFilters = [
  { key: "hide_invoice", label: "隐藏已生成报关发票" },
  { key: "hide_clearance", label: "隐藏已生成清关发票" },
  { key: "hide_element", label: "隐藏已生成报关要素" },
];
const docFields = [
  { key: "invoice_generated", label: "报关发票", empty: "未生成" },
  { key: "clearance_generated", label: "清关发票", empty: "未生成" },
  { key: "element_generated", label: "报关要素", empty: "未生成" },
  { key: "customs_done", label: "报关完毕", empty: "未报关" },
];
const options = reactive({
  receipt_no: [],
  supplier_name: [],
  contract_no: [],
  packing_list_no: [],
  material_category: [],
  material_code: [],
  material_name: [],
  equipment: [],
});
const columns = [
  { key: "material_code", label: "物料编号", fixed: "left" },
  { key: "material_name", label: "物料名称" },
  { key: "material_name_en", label: "英文名称" },
  { key: "material_category", label: "物料大类" },
  { key: "specification", label: "规格" },
  { key: "unit", label: "单位", width: 70 },
  { key: "quantity", label: "数量", width: 80 },
  { key: "origin_country", label: "产地" },
  { key: "equipment", label: "使用设备" },
  { key: "contract_no", label: "合同号" },
  { key: "packing_list_no", label: "箱单号" },
  { key: "receipt_no", label: "入仓单号" },
  { key: "receipt_date", label: "入仓日期" },
  { key: "supplier_name", label: "供应商" },
  { key: "box_no", label: "箱号" },
  { key: "container_no", label: "集装箱号" },
  { key: "bill_no", label: "提单号" },
  { key: "vessel_voyage", label: "船名/航号" },
  { key: "port_of_shipment", label: "出发港" },
  { key: "port_of_destination", label: "目的港" },
  { key: "consignee", label: "收货人", width: 180 },
  { key: "gross_weight", label: "毛重", width: 90 },
  { key: "net_weight", label: "净重", width: 90 },
  { key: "length", label: "长", width: 80 },
  { key: "width", label: "宽", width: 80 },
  { key: "height", label: "高", width: 80 },
  { key: "volume", label: "体积", width: 90 },
  { key: "package_count", label: "包件件数", width: 90 },
  { key: "po_no", label: "PO单号" },
  { key: "price", label: "含税单价", money: true },
  { key: "inquiry_name", label: "询价名称" },
  { key: "inquiry_model", label: "询价型号" },
  { key: "inquiry_qty", label: "询价数量", width: 90 },
  { key: "hs_code", label: "HS Code" },
  { key: "special_label", label: "特殊申报", tag: true },
  { key: "payment_terms", label: "付款条款", width: 180, wrap: true },
  { key: "declaration_elements", label: "申报要素", width: 180, wrap: true },
  { key: "remark", label: "备注", width: 160, wrap: true },
  { key: "status", label: "状态", tag: true },
  { key: "invoice_generated", label: "报关发票", tag: true, width: 100 },
  { key: "clearance_generated", label: "清关发票", tag: true, width: 100 },
  { key: "element_generated", label: "报关要素", tag: true, width: 100 },
  { key: "customs_done", label: "报关完毕", tag: true, width: 100 },
  { key: "missing_text", label: "缺失字段", width: 160 },
];
const assignFields = [
  { key: "receipt_no", label: "入仓单号" },
  { key: "material_category", label: "物料大类" },
  { key: "container_no", label: "集装箱号" },
  { key: "bill_no", label: "提单号" },
  { key: "vessel_voyage", label: "船名/航号" },
  { key: "packing_list_no", label: "箱单号" },
  { key: "port_of_shipment", label: "出发港" },
  { key: "port_of_destination", label: "目的港" },
  { key: "consignee", label: "收货人" },
  { key: "hs_code", label: "HS Code" },
  { key: "special_declare", label: "特殊申报" },
];
const editFields = [
  { key: "material_code", label: "物料编号", required: true },
  { key: "material_name", label: "物料名称", required: true },
  { key: "material_name_en", label: "英文名称" },
  { key: "material_category", label: "物料大类", required: true },
  { key: "specification", label: "规格" },
  { key: "unit", label: "单位" },
  { key: "quantity", label: "数量" },
  { key: "origin_country", label: "产地", required: true },
  { key: "equipment", label: "使用设备", required: true },
  { key: "contract_no", label: "合同号", required: true, readonly: true },
  { key: "packing_list_no", label: "箱单号", required: true },
  { key: "receipt_no", label: "入仓单号" },
  { key: "box_no", label: "箱号" },
  { key: "container_no", label: "集装箱号" },
  { key: "bill_no", label: "提单号" },
  { key: "vessel_voyage", label: "船名/航号" },
  { key: "gross_weight", label: "毛重", required: true },
  { key: "net_weight", label: "净重", required: true },
  { key: "length", label: "长" },
  { key: "width", label: "宽" },
  { key: "height", label: "高" },
  { key: "volume", label: "体积", required: true },
  { key: "po_no", label: "PO单号" },
  { key: "price", label: "含税单价" },
  { key: "package_count", label: "包件件数" },
  { key: "inquiry_name", label: "询价名称" },
  { key: "inquiry_model", label: "询价型号" },
  { key: "inquiry_qty", label: "询价数量" },
  { key: "port_of_shipment", label: "出发港" },
  { key: "port_of_destination", label: "目的港" },
  { key: "consignee", label: "收货人" },
  { key: "payment_terms", label: "付款条款" },
  { key: "hs_code", label: "HS Code" },
  { key: "declaration_elements", label: "申报要素" },
  { key: "remark", label: "备注" },
  { key: "special_declare", label: "特殊申报" },
];
const wideKeys = new Set(["consignee", "payment_terms", "declaration_elements", "remark"]);
const fieldGroups = [
  { title: "物料信息", keys: ["material_code", "material_name", "material_name_en", "material_category", "specification", "unit", "quantity", "origin_country", "equipment"] },
  { title: "物流信息", keys: ["contract_no", "packing_list_no", "receipt_no", "box_no", "container_no", "bill_no", "vessel_voyage", "port_of_shipment", "port_of_destination", "consignee"] },
  { title: "重量尺寸", keys: ["gross_weight", "net_weight", "length", "width", "height", "volume", "package_count"] },
  { title: "价格与申报", keys: ["po_no", "price", "inquiry_name", "inquiry_model", "inquiry_qty", "hs_code", "special_declare", "payment_terms", "declaration_elements", "remark"] },
].map((group) => ({ title: group.title, fields: group.keys.map((key) => editFields.find((item) => item.key === key)).filter(Boolean) }));
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const filters = reactive({ contract_no: "", packing_list_no: "", material_category: "", material_code: "", material_name: "", receipt_no: "", supplier_name: "", equipment: "", hide_invoice: false, hide_clearance: false, hide_element: false });
const linkedBillId = ref("");
const query = computed(() => {
  const data = { ...filters };
  statusFilters.forEach((field) => {
    if (data[field.key]) data[field.key] = "1";
    else delete data[field.key];
  });
  if (linkedBillId.value) data.wms_bill_id = linkedBillId.value;
  return data;
});
const editVisible = ref(false);
const editing = ref(false);
const assignVisible = ref(false);
const elementVisible = ref(false);
const form = reactive({});
const fieldErrors = ref([]);
const assignField = ref("");
const assignValue = ref("");
const unused = ref([]);
const invoiceId = ref(null);
const showFill = ref(false);
const filterAnchor = ref("");
let optionSeq = 0;
let listSeq = 0;
let filterSeq = 0;
const assignLabel = computed(() => assignFields.find((item) => item.key === assignField.value)?.label || "");

function picked() {
  const set = shell.value?.selected || new Set();
  return rows.value.filter((row) => set.has(row.id));
}
function statusTag(text) {
  if (text === "已生成" || text === "已报关") return "tag-green";
  return "tag-gray";
}
function fieldError(key) {
  const hit = fieldErrors.value.find((item) => item.key === key || (key === "length" && item.key === "size"));
  return hit ? `${hit.label}不能为空` : "";
}
async function loadOptions(prune = false) {
  const seq = ++optionSeq;
  const res = await http.get("/api/customs/materials/options", { params: { ...query.value } });
  if (seq !== optionSeq) return;
  const data = res.data || {};
  if (prune && filterAnchor.value) {
    const dropped = mainFilters.filter((field) => {
      if (field.key === filterAnchor.value) return false;
      const value = filters[field.key];
      return value && !(data[field.key] || []).includes(value);
    });
    if (dropped.length) {
      dropped.forEach((field) => { filters[field.key] = ""; });
      return loadOptions(true);
    }
  }
  const current = filterAnchor.value && filters[filterAnchor.value];
  if (current && !(data[filterAnchor.value] || []).includes(current)) {
    data[filterAnchor.value] = [current, ...(data[filterAnchor.value] || [])];
  }
  Object.assign(options, data);
}
async function loadList() {
  const seq = ++listSeq;
  const listRes = await http.get("/api/customs/materials", { params: { ...query.value, page: page.value, pageSize: pageSize.value } });
  if (seq !== listSeq) return;
  rows.value = listRes.data.items;
  total.value = listRes.data.total;
}
async function onFilter(key) {
  const seq = ++filterSeq;
  filterAnchor.value = key;
  if (filters[key] == null) filters[key] = "";
  page.value = 1;
  await loadOptions(true);
  if (seq !== filterSeq) return;
  await loadList();
}
async function onStatusFilter() {
  const seq = ++filterSeq;
  page.value = 1;
  await loadOptions(false);
  if (seq !== filterSeq) return;
  await loadList();
}
async function load() {
  await Promise.all([loadList(), loadOptions(false)]);
}
function reset() {
  filterAnchor.value = "";
  linkedBillId.value = "";
  const flags = new Set(statusFilters.map((field) => field.key));
  Object.keys(filters).forEach((key) => { filters[key] = flags.has(key) ? false : ""; });
  page.value = 1;
  load();
}
async function open(row, edit = false) {
  Object.keys(form).forEach((key) => delete form[key]);
  Object.assign(form, (await http.get(`/api/customs/materials/${row.id}`)).data);
  editing.value = !!edit;
  fieldErrors.value = (form.missing || []).map((label) => {
    const field = editFields.find((item) => item.label === label);
    return { key: field?.key || (label === "尺寸" ? "size" : ""), label };
  });
  editVisible.value = true;
}
async function save() {
  try {
    await http.put(`/api/customs/materials/${form.id}`, form);
    editVisible.value = false;
    load();
  } catch (err) {
    fieldErrors.value = err?.data?.fields || [];
  }
}
async function remove(row) {
  await http.delete(`/api/customs/materials/${row.id}`, { params: { version: row.version } });
  load();
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/customs/materials/batch-delete")) load();
}
function openAssign(field) {
  if (!picked().length) {
    ElMessage.warning("请先勾选记录");
    return;
  }
  assignField.value = field;
  assignValue.value = field === "special_declare" ? "特殊申报" : "";
  assignVisible.value = true;
}
async function doAssign() {
  const ids = picked().map((row) => row.id);
  await http.post("/api/customs/materials/batch-assign", { ids, field: assignField.value, value: assignValue.value });
  ElMessage.success(`已更新 ${ids.length} 条`);
  assignVisible.value = false;
  load();
}
function invoiceOptionLabel(item) {
  return `发票：${item.invoice_no || "—"}　合同号：${item.contract_no || "—"}`;
}
function generate(kind) {
  const ids = picked().map((row) => row.id);
  if (!ids.length) {
    ElMessage.warning("请先勾选物料");
    return;
  }
  if (kind === "invoice") {
    sessionStorage.setItem("customs-invoice-draft", JSON.stringify(ids));
    router.push("/customs/invoices");
    return;
  }
  if (kind === "clearance") {
    sessionStorage.setItem("customs-clearance-draft", JSON.stringify(ids));
    router.push("/customs/clearance");
    return;
  }
  openElement();
}
async function openElement() {
  const ids = picked().map((row) => row.id);
  unused.value = (await http.get("/api/customs/invoices/unused", { params: { material_ids: ids.join(",") } })).data || [];
  if (!unused.value.length) {
    ElMessage.warning("所选物料没有可关联的报关发票");
    return;
  }
  invoiceId.value = unused.value[0]?.id || null;
  elementVisible.value = true;
}
function goElement() {
  if (!invoiceId.value) {
    ElMessage.warning("请选择报关发票");
    return;
  }
  const ids = picked().map((row) => row.id);
  if (!ids.length) {
    ElMessage.warning("请先勾选物料");
    return;
  }
  elementVisible.value = false;
  sessionStorage.setItem("customs-element-draft", JSON.stringify({ ids, invoice: invoiceId.value }));
  router.push("/customs/elements");
}
function applyRoute() {
  if (route.query.receipt_no) filters.receipt_no = String(route.query.receipt_no);
  linkedBillId.value = route.query.wms_bill_id ? String(route.query.wms_bill_id) : "";
}
onMounted(() => {
  applyRoute();
  load();
});
watch(() => [route.query.receipt_no, route.query.wms_bill_id], () => {
  applyRoute();
  page.value = 1;
  load();
});
</script>
