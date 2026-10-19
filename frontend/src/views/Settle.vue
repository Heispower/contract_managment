<template>
  <ListShell ref="shell" :title="title" :storage-key="direction" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :sums="sums" export-module="settle" :export-query="{ direction, party_id: partyId }" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters>
      <el-select v-model="partyId" clearable placeholder="客商" style="width:180px"><el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" /></el-select>
    </template>
    <template #toolbar>
      <el-button type="primary" @click="open()">新增{{ title }}</el-button>
      <el-button @click="showImport = true">导入</el-button>
      <el-button @click="removeMany">批量删除</el-button>
      <GenerateForm :shell="shell" :rows="rows" :doc-code="direction==='receipt' ? 'receipt' : 'payment'" :doc-name="title" :party-word="direction==='receipt' ? '客户' : '供应商'" :fallback-name="(row) => `${row.bill_code || title}.docx`" />
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="openEdit(row)">编辑</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="visible" :title="'新增'+title" width="760px" @closed="onPayClosed">
    <el-form label-width="90px">
      <el-form-item label="客商">
        <el-select v-model="form.party_id" filterable style="width:100%" @change="loadContracts">
          <el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="合同">
        <el-select v-model="form.contract_id" filterable style="width:100%" @change="loadStages">
          <el-option v-for="c in contracts" :key="c.id" :label="c.contract_code+' 未结 '+c.unpaid" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="单号"><el-input v-model="form.bill_code" /></el-form-item>
      <el-form-item label="日期"><el-date-picker v-model="form.bill_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="账户">
        <el-select v-model="form.account_name" clearable style="width:100%"><el-option v-for="a in accounts" :key="a.id" :label="a.name" :value="a.name" /></el-select>
      </el-form-item>
    </el-form>
    <div v-if="head">合同金额 {{ head.amount }}，已结 {{ head.settled }}，未结 {{ head.unpaid }}</div>
    <el-table :data="stages" size="small" @selection-change="(v)=>picked=v">
      <el-table-column type="selection" :selectable="(row)=>Number(row.remain)>0" />
      <el-table-column prop="name" label="阶段" />
      <el-table-column prop="plan_amount" label="计划金额" />
      <el-table-column prop="settled_amount" label="已结" />
      <el-table-column prop="remain" label="剩余" />
      <el-table-column label="本次">
        <template #default="{ row }"><el-input v-model="row.pay" :disabled="Number(row.remain)<=0" /></template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="visible=false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="editVisible" :title="'编辑'+title" width="560px">
    <el-form label-width="90px">
      <el-form-item label="单据编号"><el-input v-model="editForm.bill_code" disabled /></el-form-item>
      <el-form-item label="客商"><el-input v-model="editForm.party_name" disabled /></el-form-item>
      <el-form-item label="关联合同"><el-input v-model="editForm.contract_code" disabled /></el-form-item>
      <el-form-item label="阶段"><el-input v-model="editForm.stage_name" disabled /></el-form-item>
      <el-form-item label="日期"><el-date-picker v-model="editForm.bill_date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item>
      <el-form-item label="金额"><el-input v-model="editForm.amount" /></el-form-item>
      <el-form-item label="账户">
        <el-select v-model="editForm.account_name" clearable filterable style="width:100%">
          <el-option v-for="name in editAccounts" :key="name" :label="name" :value="name" />
        </el-select>
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="editForm.remark" type="textarea" :rows="2" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editVisible=false">取消</el-button>
      <el-button type="primary" @click="saveEdit">保存</el-button>
    </template>
  </el-dialog>
  <ImportWizard v-model="showImport" module="settle" :direction="direction" @done="load" />
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useRouter } from "vue-router";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";
import GenerateForm from "../components/GenerateForm.vue";

const props = defineProps({ direction: String });
const shell = ref(null);
const router = useRouter();
const title = computed(() => (props.direction === "receipt" ? "收款单" : "付款单"));
const columns = [
  { key: "bill_code", label: "单据编号", fixed: "left" },
  { key: "bill_date", label: "日期" },
  { key: "party_name", label: "客商" },
  { key: "contract_code", label: "关联合同" },
  { key: "stage_name", label: "阶段名称" },
  { key: "amount", label: "金额", money: true },
  { key: "account_name", label: "账户" },
];
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const sums = ref({});
const partyId = ref(null);
const parties = ref([]);
const contracts = ref([]);
const accounts = ref([]);
const stages = ref([]);
const picked = ref([]);
const head = ref(null);
const visible = ref(false);
const editVisible = ref(false);
const pendingTrigger = ref(null);
const showImport = ref(false);
const form = reactive({ party_id: null, contract_id: null, bill_code: "", bill_date: "", account_name: "" });
const editForm = reactive({ id: null, version: null, bill_code: "", party_name: "", contract_code: "", stage_name: "", bill_date: "", amount: "", account_name: "", remark: "" });
const editAccounts = computed(() => {
  const names = accounts.value.map((item) => item.name);
  return editForm.account_name && !names.includes(editForm.account_name) ? [...names, editForm.account_name] : names;
});

async function load() {
  const res = await http.get("/api/settle-bills", { params: { direction: props.direction, party_id: partyId.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
  sums.value = res.data.sums || {};
}
function reset() { partyId.value = null; load(); }
async function open(prefill) {
  form.party_id = prefill?.party_id || null;
  form.contract_id = null;
  form.bill_code = "";
  form.bill_date = new Date().toISOString().slice(0, 10);
  form.account_name = "";
  stages.value = [];
  head.value = null;
  visible.value = true;
  if (!prefill?.party_id) return;
  await loadContracts();
  const hit = contracts.value.find((row) => row.id === prefill.contract_id);
  if (!hit) {
    ElMessage.warning(props.direction === "receipt" ? "该合同没有未结金额，无法生成收款单" : "该合同没有未结金额，无法生成付款单");
    return;
  }
  form.contract_id = prefill.contract_id;
  await loadStages();
}
async function loadContracts() {
  const direction = props.direction === "receipt" ? "sale" : "purchase";
  const res = await http.get("/api/contracts", { params: { direction, party_id: form.party_id, status: "已签订", pageSize: 200 } });
  contracts.value = res.data.items.filter((row) => Number(row.unpaid) > 0);
  if (!contracts.value.length) {
    ElMessage.warning("请去维护合同与阶段");
  }
}
async function loadStages() {
  const res = await http.get(`/api/contracts/${form.contract_id}`);
  head.value = res.data;
  stages.value = res.data.stages.map((s) => ({ ...s, pay: s.remain }));
}
async function save() {
  const lines = picked.value.filter((row) => Number(row.pay) > 0).map((row) => ({ stage_id: row.id, amount: row.pay, remark: row.remark || "" }));
  if (!lines.length) return ElMessage.warning("请勾选阶段并填写金额");
  const res = await http.post("/api/settle-bills/multi-stage", { ...form, direction: props.direction, lines });
  pendingTrigger.value = res.data.triggers?.[0] || null;
  visible.value = false;
  if (!pendingTrigger.value) load();
}
async function onPayClosed() {
  const trigger = pendingTrigger.value;
  pendingTrigger.value = null;
  if (!trigger) return;
  let agreed = false;
  try {
    await ElMessageBox.confirm(trigger.message, "提示", { confirmButtonText: "确定", cancelButtonText: "取消" });
    agreed = true;
  } catch {
    agreed = false;
  }
  await http.post(`/api/contracts/stages/${trigger.stage_id}/ack-trigger`, { kind: trigger.kind });
  if (!agreed) {
    load();
    return;
  }
  const path = trigger.kind === "arrival" ? "generate-arrival" : "generate-shipment";
  const pre = await http.post(`/api/contracts/${trigger.contract_id}/${path}`);
  sessionStorage.setItem("wms-prefill", JSON.stringify(pre.data));
  router.push(trigger.kind === "arrival" ? "/warehouse/inbound" : "/warehouse/outbound");
}
async function remove(row) { await http.delete(`/api/settle-bills/${row.id}`, { params: { version: row.version } }); load(); }
function openEdit(row) {
  Object.assign(editForm, {
    id: row.id,
    version: row.version,
    bill_code: row.bill_code || "",
    party_name: row.party_name || "",
    contract_code: row.contract_code || "",
    stage_name: row.stage_name || "",
    bill_date: row.bill_date || "",
    amount: row.amount || "",
    account_name: row.account_name || "",
    remark: row.remark || "",
  });
  editVisible.value = true;
}
async function saveEdit() {
  await http.put(`/api/settle-bills/${editForm.id}`, {
    version: editForm.version,
    bill_date: editForm.bill_date,
    amount: editForm.amount,
    account_name: editForm.account_name,
    remark: editForm.remark,
  });
  editVisible.value = false;
  load();
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/settle-bills/batch-delete")) load();
}
onMounted(async () => {
  const type = props.direction === "receipt" ? "customer" : "supplier";
  parties.value = (await http.get("/api/parties", { params: { type, status: "启用", pageSize: 200 } })).data.items;
  accounts.value = (await http.get("/api/fund-accounts", { params: { status: "启用", pageSize: 100 } })).data.items;
  await load();
  const raw = sessionStorage.getItem("pay-prefill");
  if (raw) {
    const data = JSON.parse(raw);
    if ((data.direction || "payment") === props.direction) {
      sessionStorage.removeItem("pay-prefill");
      await open(data);
    }
  }
});
</script>
