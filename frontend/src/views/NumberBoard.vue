<template>
  <ListShell ref="shell" :title="isContract ? '合同编号' : '发票编号'" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" @query="load" @reset="reset" @page="(p) => { page = p; load(); }" @size="(s) => { pageSize = s; page = 1; load(); }">
    <template #filters>
      <el-input v-model="keyword" :placeholder="isContract ? '合同编号 / 产品 / 乙方 / 归属人' : '发票号 / 合同 / 内容 / PO'" style="width:260px" clearable />
      <el-select v-if="isContract" v-model="businessType" clearable placeholder="业务类型" style="width:140px">
        <el-option label="锰矿" value="锰矿" />
        <el-option label="铝矿" value="铝矿" />
      </el-select>
      <el-select v-else v-model="numberRule" clearable placeholder="编号规则" style="width:160px">
        <el-option label="锰矿" value="锰矿" />
        <el-option label="铝矿海运" value="铝矿海运" />
        <el-option label="铝矿空运" value="铝矿空运" />
      </el-select>
      <el-select v-model="year" clearable placeholder="编号年份" style="width:130px">
        <el-option v-for="item in years" :key="item" :label="String(item)" :value="String(item)" />
      </el-select>
      <el-radio-group v-model="sortOrder" @change="changeSort">
        <el-radio-button value="desc">倒序</el-radio-button>
        <el-radio-button value="asc">正序</el-radio-button>
      </el-radio-group>
    </template>
    <template #toolbar>
      <el-button type="primary" @click="openCreate">{{ isContract ? "登记合同编号" : "登记发票编号" }}</el-button>
      <el-button @click="showImport = true">批量导入</el-button>
      <el-button @click="floorVisible = true">顺序号下限</el-button>
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="openEdit(row)">编辑</span>
      <span class="ops" style="margin-left:8px" @click="openManual(row)">改号</span>
      <el-popconfirm title="确定删除？删除后空号可被再次使用。" @confirm="remove(row)">
        <template #reference><span class="ops" style="margin-left:8px">删除</span></template>
      </el-popconfirm>
    </template>
  </ListShell>

  <el-dialog v-model="visible" :title="(form.id ? '编辑' : '新增') + (isContract ? '合同编号' : '发票编号')" width="760px" append-to-body :close-on-click-modal="false">
    <div v-if="isContract && form.purchase_contract_id" class="hint">已关联采购合同 {{ form.purchase_code }}。金额和乙方以采购合同为准，保存采购合同时会回写到这里。</div>
    <div v-else-if="!isContract && form.customs_invoice_id" class="hint">已关联报关发票。金额、内容和提单信息以报关发票为准，保存报关发票时会回写到这里。</div>
    <el-form label-width="108px">
      <template v-if="isContract">
        <el-form-item label="业务类型">
          <el-select v-model="form.business_type" :disabled="!!form.id">
            <el-option v-for="item in contractTypes" :key="item.value" :label="item.text" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="编号年份">
          <el-select v-model="form.number_year" :disabled="!!form.id">
            <el-option v-for="item in years" :key="item" :label="String(item)" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="合同编号">
          <el-input v-model="form.contract_no" :disabled="!!form.id" :placeholder="form.id ? '' : '留空按规则生成'" />
        </el-form-item>
        <el-form-item v-if="!form.id && !form.contract_no" label="预览">
          <el-input :model-value="previewText" disabled />
        </el-form-item>
        <el-form-item label="产品/合同名称"><el-input v-model="form.product_name" /></el-form-item>
        <el-form-item label="乙方"><el-input v-model="form.party_b" :disabled="!!form.purchase_contract_id" /></el-form-item>
        <el-form-item label="甲方"><el-input v-model="form.party_a" :disabled="!!form.purchase_contract_id" /></el-form-item>
        <el-form-item label="合同金额CNY"><el-input v-model="form.amount_cny" :disabled="!!form.purchase_contract_id" /></el-form-item>
        <el-form-item label="签订时间"><el-date-picker v-model="form.sign_date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="归属人">
          <el-select v-model="form.owner_id" filterable placeholder="选择归属人">
            <el-option v-for="user in users" :key="user.employee_id" :label="user.employee_id + ' ' + user.name" :value="user.employee_id" />
          </el-select>
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item v-if="!form.id" label="登记方式">
          <el-select v-model="form.mode">
            <el-option label="单票" value="plain" />
            <el-option label="新建批次" value="new_batch" />
            <el-option label="加入已有批次" value="join_batch" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!form.id && form.mode === 'join_batch'" label="批次">
          <el-select v-model="form.batch_id" filterable placeholder="选择批次前缀">
            <el-option v-for="item in batches" :key="item.id" :label="`${item.prefix} ${item.number_rule}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="编号规则">
          <el-select v-model="form.number_rule" :disabled="!!form.id || form.mode === 'join_batch'">
            <el-option v-for="item in invoiceRules" :key="item.value" :label="item.text" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="编号年份">
          <el-select v-model="form.number_year" :disabled="!!form.id || form.mode === 'join_batch'">
            <el-option v-for="item in years" :key="item" :label="String(item)" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="发票号"><el-input :model-value="form.id ? form.invoice_no : previewText" disabled placeholder="保存时生成" /></el-form-item>
        <el-form-item label="关联合同"><el-input v-model="form.contract_no" :disabled="!!form.customs_invoice_id" /></el-form-item>
        <el-form-item label="所含内容"><el-input v-model="form.content" :disabled="!!form.customs_invoice_id" /></el-form-item>
        <el-form-item label="提单日期"><el-date-picker v-model="form.bl_date" value-format="YYYY-MM-DD" :disabled="!!form.customs_invoice_id" /></el-form-item>
        <el-form-item label="价格条款">
          <el-select v-model="form.price_term" filterable allow-create :disabled="!!form.customs_invoice_id">
            <el-option label="FOB" value="FOB" />
            <el-option label="CIF" value="CIF" />
          </el-select>
        </el-form-item>
        <el-form-item label="结算币种">
          <el-select v-model="form.currency" :disabled="!!form.customs_invoice_id">
            <el-option label="USD" value="USD" />
            <el-option label="CNY" value="CNY" />
          </el-select>
        </el-form-item>
        <el-form-item label="美元金额"><el-input v-model="form.amount_usd" :disabled="!!form.customs_invoice_id || form.is_batch_master" /></el-form-item>
        <el-form-item label="人民币金额"><el-input v-model="form.amount_cny" :disabled="!!form.customs_invoice_id || form.is_batch_master" /></el-form-item>
        <el-form-item label="汇率月份"><el-input v-model="form.exchange_month" placeholder="YYYY-MM" :disabled="!!form.customs_invoice_id" /></el-form-item>
        <el-form-item label="汇率"><el-input v-model="form.exchange_rate" :disabled="!!form.customs_invoice_id" /></el-form-item>
        <el-form-item label="PO"><el-input v-model="form.po_no" :disabled="!!form.customs_invoice_id" /></el-form-item>
        <el-form-item label="运输方式"><el-input :model-value="transportText" disabled /></el-form-item>
        <el-form-item label="提单号"><el-input v-model="form.bl_no" :disabled="!!form.customs_invoice_id" /></el-form-item>
        <el-form-item label="发邮件时间"><el-date-picker v-model="form.email_sent_date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="manualVisible" title="手动改号" width="480px" append-to-body :close-on-click-modal="false">
    <el-form label-width="88px">
      <el-form-item label="原编号"><el-input :model-value="manual.old" disabled /></el-form-item>
      <el-form-item label="新编号"><el-input v-model="manual.value" /></el-form-item>
      <el-form-item label="修改原因"><el-input v-model="manual.reason" type="textarea" :rows="3" placeholder="至少 2 个字" /></el-form-item>
    </el-form>
    <div v-if="manual.logs.length" class="hint">
      <div>
        <div v-for="item in manual.logs" :key="item.created_at + item.new_no">{{ item.created_at }} {{ item.operator_name }}：{{ item.old_no }} → {{ item.new_no }}（{{ item.reason }}）</div>
      </div>
    </div>
    <template #footer>
      <el-button @click="manualVisible = false">取消</el-button>
      <el-button type="primary" @click="saveManual">确定</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="floorVisible" title="顺序号下限" width="640px" append-to-body :close-on-click-modal="false">
    <div class="hint">填写最新顺序号或一条完整编号。该号及更小的号视为历史号：不会自动分配，删除后也不回收。1 月默认编入上一年。</div>
    <el-table :data="floors" size="small">
      <el-table-column prop="label" label="规则" width="120" />
      <el-table-column prop="floor" label="当前下限" width="90" />
      <el-table-column prop="preview" label="下一编号" min-width="180" />
      <el-table-column label="设为" min-width="180">
        <template #default="{ row }">
          <el-input v-model="row.draft" placeholder="顺序号或完整编号" />
        </template>
      </el-table-column>
      <el-table-column label="" width="80">
        <template #default="{ row }">
          <el-button link type="primary" @click="saveFloor(row)">保存</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
  <ImportWizard v-model="showImport" :module="isContract ? 'number-contract' : 'number-invoice'" @done="load" />
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import http from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";

const props = defineProps({ kind: { type: String, required: true } });
const isContract = computed(() => props.kind === "contract");
const shell = ref(null);
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref("");
const businessType = ref("");
const numberRule = ref("");
const year = ref("");
const sortOrder = ref("desc");
const years = ref([]);
const batches = ref([]);
const contractTypes = ref([]);
const invoiceRules = ref([]);
const floors = ref([]);
const visible = ref(false);
const floorVisible = ref(false);
const showImport = ref(false);
const manualVisible = ref(false);
const previewText = ref("");
const users = ref([]);
const form = reactive({});
const manual = reactive({ id: null, old: "", value: "", reason: "", logs: [] });

const contractColumns = [
  { key: "contract_no", label: "合同编号", width: 180 },
  { key: "business_type", label: "业务类型", width: 90 },
  { key: "number_year", label: "编号年份", width: 90 },
  { key: "product_name", label: "产品/合同名称" },
  { key: "party_b", label: "乙方" },
  { key: "party_a", label: "甲方" },
  { key: "amount_cny", label: "合同金额CNY", money: true, width: 130 },
  { key: "sign_date", label: "签订时间", width: 110 },
  { key: "owner_name", label: "归属人", width: 100 },
  { key: "linked_label", label: "采购合同", width: 90, tag: true },
];
const invoiceColumns = [
  { key: "invoice_no", label: "发票号", width: 200 },
  { key: "number_rule", label: "编号规则", width: 110 },
  { key: "contract_no", label: "关联合同", width: 160 },
  { key: "content", label: "所含内容" },
  { key: "bl_date", label: "提单日期", width: 110 },
  { key: "price_term", label: "价格条款", width: 90 },
  { key: "currency", label: "币种", width: 70 },
  { key: "amount_usd", label: "美元金额", money: true },
  { key: "amount_cny", label: "人民币金额", money: true },
  { key: "exchange_rate", label: "汇率", width: 90 },
  { key: "po_no", label: "PO", width: 120 },
  { key: "operator_name", label: "操作人", width: 90 },
  { key: "transport_type", label: "运输方式", width: 90 },
  { key: "email_sent_date", label: "发邮件时间", width: 110 },
  { key: "bl_no", label: "提单号", width: 140 },
  { key: "batch_label", label: "批次", width: 70 },
  { key: "linked_label", label: "报关发票", width: 90, tag: true },
  { key: "remark", label: "备注", show: false },
];
const columns = computed(() => (isContract.value ? contractColumns : invoiceColumns));
const transportText = computed(() => {
  if (form.transport_type) return form.transport_type;
  if (form.number_rule === "铝矿空运") return "空运";
  return "海运";
});

function defaultYear() {
  const now = new Date();
  return now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear();
}
function currentEmployeeId() {
  try {
    return JSON.parse(localStorage.getItem("user") || "{}").employee_id || "";
  } catch (err) {
    return "";
  }
}
function blankContract(partyA) {
  const mine = currentEmployeeId();
  const owner = users.value.some((user) => user.employee_id === mine) ? mine : "";
  return { id: null, business_type: "锰矿", number_year: defaultYear(), contract_no: "", product_name: "", party_b: "", party_a: partyA || "", amount_cny: "", sign_date: "", owner_id: owner, purchase_contract_id: null };
}
function blankInvoice() {
  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return {
    id: null, mode: "plain", number_rule: "锰矿", number_year: defaultYear(), batch_id: null, invoice_no: "",
    contract_no: "", content: "", bl_date: "", price_term: "FOB", currency: "USD", amount_usd: "", amount_cny: "",
    exchange_month: month, exchange_rate: "", po_no: "", bl_no: "", email_sent_date: "", remark: "",
    customs_invoice_id: null, is_batch_master: false, transport_type: "",
  };
}
function assignForm(data) {
  Object.keys(form).forEach((key) => delete form[key]);
  Object.assign(form, data);
}

async function loadMeta() {
  const res = await http.get("/api/numbering/meta");
  years.value = res.data.years || [];
  batches.value = res.data.batches || [];
  contractTypes.value = res.data.contract_types || [];
  invoiceRules.value = res.data.invoice_rules || [];
  const source = isContract.value ? res.data.contract_floors : res.data.invoice_floors;
  floors.value = (source || []).map((item) => ({ ...item, draft: "" }));
  return res.data;
}
async function load() {
  const params = { page: page.value, pageSize: pageSize.value, keyword: keyword.value, order: sortOrder.value };
  if (year.value) params.number_year = year.value;
  const url = isContract.value ? "/api/numbering/contracts" : "/api/numbering/invoices";
  if (isContract.value && businessType.value) params.business_type = businessType.value;
  if (!isContract.value && numberRule.value) params.number_rule = numberRule.value;
  const res = await http.get(url, { params });
  rows.value = res.data.items || [];
  total.value = res.data.total || 0;
}
function changeSort() {
  page.value = 1;
  load();
}
function reset() {
  keyword.value = "";
  businessType.value = "";
  numberRule.value = "";
  year.value = "";
  sortOrder.value = "desc";
  page.value = 1;
  load();
}
async function refreshPreview() {
  if (!visible.value || form.id) {
    previewText.value = "";
    return;
  }
  if (isContract.value) {
    if (form.contract_no) {
      previewText.value = "";
      return;
    }
    const res = await http.get("/api/numbering/preview", { params: { kind: "contract", business_type: form.business_type, year: form.number_year } });
    previewText.value = res.data.reused ? `${res.data.number}（复用空号）` : res.data.number;
    return;
  }
  if (form.mode === "join_batch") {
    if (!form.batch_id) {
      previewText.value = "";
      return;
    }
    const res = await http.get("/api/numbering/preview", { params: { kind: "sub", batch_id: form.batch_id } });
    previewText.value = res.data.number;
    return;
  }
  const res = await http.get("/api/numbering/preview", { params: { kind: "invoice", number_rule: form.number_rule, year: form.number_year } });
  previewText.value = res.data.reused ? `${res.data.number}（复用空号）` : res.data.number;
}
async function loadUsers() {
  if (!isContract.value) return;
  users.value = (await http.get("/api/users", { params: { status: "启用", pageSize: 200 } })).data.items || [];
}
async function openCreate() {
  const meta = await loadMeta();
  if (isContract.value) await loadUsers();
  assignForm(isContract.value ? blankContract(meta.party_a) : blankInvoice());
  visible.value = true;
  refreshPreview();
}
async function openEdit(row) {
  if (isContract.value) await loadUsers();
  const url = isContract.value ? `/api/numbering/contracts/${row.id}` : `/api/numbering/invoices/${row.id}`;
  assignForm((await http.get(url)).data);
  visible.value = true;
}
async function save() {
  if (isContract.value) {
    if (!form.owner_id) {
      ElMessage.warning("请选择归属人");
      return;
    }
    const payload = { ...form };
    if (form.id) await http.put(`/api/numbering/contracts/${form.id}`, payload);
    else await http.post("/api/numbering/contracts", payload);
  } else if (form.id) {
    await http.put(`/api/numbering/invoices/${form.id}`, { ...form });
  } else {
    await http.post("/api/numbering/invoices", { ...form });
  }
  ElMessage.success("已保存");
  visible.value = false;
  loadMeta();
  load();
}
async function remove(row) {
  const url = isContract.value ? `/api/numbering/contracts/${row.id}` : `/api/numbering/invoices/${row.id}`;
  await http.delete(url, { params: { version: row.version } });
  load();
}
async function openManual(row) {
  const url = isContract.value ? `/api/numbering/contracts/${row.id}` : `/api/numbering/invoices/${row.id}`;
  const data = (await http.get(url)).data;
  manual.id = row.id;
  manual.old = isContract.value ? data.contract_no : data.invoice_no;
  manual.value = "";
  manual.reason = "";
  manual.logs = data.logs || [];
  manualVisible.value = true;
}
async function saveManual() {
  const url = isContract.value ? `/api/numbering/contracts/${manual.id}/manual` : `/api/numbering/invoices/${manual.id}/manual`;
  const payload = isContract.value ? { contract_no: manual.value, reason: manual.reason } : { invoice_no: manual.value, reason: manual.reason };
  await http.post(url, payload);
  ElMessage.success("已改号");
  manualVisible.value = false;
  load();
}
async function saveFloor(row) {
  const res = await http.put("/api/numbering/floors", { pool: row.pool, value: row.draft });
  row.floor = res.data.floor;
  row.preview = res.data.preview;
  row.draft = "";
  ElMessage.success("已更新顺序号下限");
}
watch(() => props.kind, () => {
  page.value = 1;
  sortOrder.value = "desc";
  visible.value = false;
  showImport.value = false;
  loadMeta();
  load();
});
watch(() => [form.business_type, form.number_year, form.contract_no, form.number_rule, form.mode, form.batch_id, visible.value], () => {
  if (visible.value && !form.id) refreshPreview();
});
onMounted(() => {
  loadMeta();
  load();
});
</script>
