<template>
  <ListShell ref="shell" :title="title" :storage-key="'inv-'+direction" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :summary="summary" :sums="{ total: sumTotal }" export-module="invoice" :export-query="{ direction, keyword, party_id: partyId, project_id: projectId, invoice_type: invoiceType }" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}" @select="syncPick">
    <template #filters="{ expanded }">
      <el-input v-model="keyword" placeholder="关键字" style="width:180px" />
      <el-select v-model="partyId" clearable placeholder="客商" style="width:180px"><el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" /></el-select>
      <el-select v-model="projectId" clearable placeholder="项目" style="width:160px"><el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" /></el-select>
      <template v-if="expanded">
        <el-select v-model="invoiceType" clearable placeholder="发票类型" style="width:160px">
          <el-option v-for="t in types" :key="t" :label="t" :value="t" />
        </el-select>
      </template>
    </template>
    <template #toolbar>
      <el-button type="primary" @click="open()">新增{{ title }}</el-button>
      <el-button @click="showImport = true">导入</el-button>
      <el-button @click="removeMany">批量删除</el-button>
      <GenerateForm :shell="shell" :rows="rows" :doc-code="direction==='input' ? 'input_invoice' : 'output_invoice'" :doc-name="title" :party-word="direction==='input' ? '供应商' : '客户'" :fallback-name="(row) => `${row.invoice_no || row.bill_code || title}.docx`" />
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">编辑</span>
      <el-popconfirm title="确定要删除这个发票吗？" confirm-button-text="确定" cancel-button-text="取消" @confirm="remove(row)">
        <template #reference><span class="ops" style="margin-left:8px">删除</span></template>
      </el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="visible" class="line-dialog" :title="title" width="980px" top="8vh" append-to-body :close-on-click-modal="false">
    <el-form label-width="110px">
      <el-form-item label="客商">
        <el-select v-model="form.party_id" filterable style="width:70%" @change="onParty"><el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" /></el-select>
      </el-form-item>
      <el-form-item label="合同">
        <el-select v-model="form.contract_id" filterable style="width:100%" @change="take"><el-option v-for="c in contracts" :key="c.id" :label="c.contract_code+' '+c.name" :value="c.id" /></el-select>
      </el-form-item>
      <el-form-item label="发票号码"><el-input v-model="form.invoice_no" /></el-form-item>
      <el-form-item label="发票日期"><el-date-picker v-model="form.invoice_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="发票类型">
        <el-select v-model="form.invoice_type"><el-option v-for="t in types" :key="t" :label="t" :value="t" /></el-select>
      </el-form-item>
      <el-form-item :label="direction==='input'?'销售方名称':'购买方名称'"><el-input v-model="form.party_name" /></el-form-item>
      <el-form-item label="税号"><el-input v-model="form.party_tax_no" /></el-form-item>
    </el-form>
    <el-button @click="form.items.push({ material_code:'', name_cn:'', qty:'1', price:'0', tax_rate: form.tax_rate || '13', manual_tax:false })">手加行</el-button>
    <div class="line-box" style="margin-top:8px">
    <el-table :data="form.items" height="320" size="small" empty-text="暂无物料">
      <el-table-column label="物料编号" width="130"><template #default="{ row }"><el-input v-model="row.material_code" /></template></el-table-column>
      <el-table-column label="名称"><template #default="{ row }"><el-input v-model="row.name_cn" /></template></el-table-column>
      <el-table-column label="数量" width="90"><template #default="{ row }"><el-input v-model="row.qty" /></template></el-table-column>
      <el-table-column label="含税单价" width="110"><template #default="{ row }"><el-input v-model="row.price" @change="row.manual_tax=false" /></template></el-table-column>
      <el-table-column label="不含税金额" width="120"><template #default="{ row }"><el-input v-model="row.amount_ex_tax" @change="row.manual_tax=true" /></template></el-table-column>
      <el-table-column label="税额" width="100"><template #default="{ row }"><el-input v-model="row.tax" @change="row.manual_tax=true" /></template></el-table-column>
      <el-table-column label="税率" width="80"><template #default="{ row }"><el-input v-model="row.tax_rate" /></template></el-table-column>
    </el-table>
    </div>
    <template #footer>
      <el-button @click="visible=false">关闭</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
  <ImportWizard v-model="showImport" module="invoice" :direction="direction" @done="load" />
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import http, { batchDelete, money } from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";
import GenerateForm from "../components/GenerateForm.vue";

const props = defineProps({ direction: String });
const shell = ref(null);
const title = computed(() => (props.direction === "output" ? "销项发票" : "进项发票"));
const types = ["增值税专用发票", "增值税普通发票", "电子专票", "电子普票"];
const columns = [
  { key: "bill_date", label: "单据日期" },
  { key: "bill_code", label: "单据编号", fixed: "left" },
  { key: "invoice_no", label: "发票号码", fixed: "left" },
  { key: "invoice_type", label: "发票类型", tag: true },
  { key: "party_code", label: "客商编码" },
  { key: "party_name", label: "客商名称" },
  { key: "amount_ex_tax", label: "不含税金额", money: true },
  { key: "tax", label: "税额", money: true },
  { key: "total", label: "价税合计", money: true },
  { key: "qty_total", label: "商品数量" },
  { key: "contract_code", label: "合同编号" },
  { key: "contract_name", label: "合同名称" },
  { key: "pay_status", label: "付款状态", tag: true },
  { key: "pay_progress", label: "付款进度" },
  { key: "created_by_name", label: "创建人" },
];
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");
const partyId = ref(null);
const projectId = ref(null);
const invoiceType = ref("");
const parties = ref([]);
const projects = ref([]);
const contracts = ref([]);
const visible = ref(false);
const showImport = ref(false);
const sumTotal = ref(0);
const selectedRows = ref([]);
const summary = computed(() => `发票金额（含税合计）：￥${money(sumTotal.value)}`);
const form = reactive({ id: null, version: null, party_id: null, contract_id: null, invoice_no: "", invoice_date: "", invoice_type: "增值税专用发票", party_name: "", party_tax_no: "", items: [] });

async function load() {
  const res = await http.get("/api/invoices", { params: { direction: props.direction, keyword: keyword.value, party_id: partyId.value, project_id: projectId.value, invoice_type: invoiceType.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
  sumTotal.value = res.data.sums?.total || 0;
  syncPick();
}
function syncPick() {
  const set = shell.value?.selected || new Set();
  selectedRows.value = rows.value.filter((row) => set.has(row.id));
}
function reset() { keyword.value = ""; partyId.value = null; projectId.value = null; invoiceType.value = ""; load(); }
async function open(row) {
  if (row) Object.assign(form, (await http.get(`/api/invoices/${row.id}`)).data);
  else Object.assign(form, { id: null, version: null, party_id: null, contract_id: null, invoice_no: "", invoice_date: new Date().toISOString().slice(0, 10), invoice_type: "增值税专用发票", party_name: "", party_tax_no: "", items: [] });
  visible.value = true;
}
async function applyPrefill(data) {
  Object.assign(form, {
    id: null,
    version: null,
    party_id: data.party_id,
    contract_id: data.contract_id,
    invoice_no: "",
    invoice_date: new Date().toISOString().slice(0, 10),
    invoice_type: data.invoice_type || "增值税专用发票",
    party_name: data.party_name || "",
    party_tax_no: data.party_tax_no || "",
    items: data.items || [],
  });
  const contractDirection = props.direction === "output" ? "sale" : "purchase";
  contracts.value = (await http.get("/api/contracts", { params: { direction: contractDirection, party_id: form.party_id, status: "已签订", pageSize: 200 } })).data.items;
  visible.value = true;
}
async function onParty() {
  const party = parties.value.find((p) => p.id === form.party_id);
  form.party_name = party?.invoice_title || party?.name || "";
  form.party_tax_no = party?.tax_no || "";
  form.contract_id = null;
  form.items = [];
  const direction = props.direction === "output" ? "sale" : "purchase";
  contracts.value = (await http.get("/api/contracts", { params: { direction, party_id: form.party_id, status: "已签订", pageSize: 200 } })).data.items;
}
async function take() {
  const detail = await http.get(`/api/contracts/${form.contract_id}`);
  form.items = detail.data.items.filter((item) => Number(item.uninvoiced_qty) > 0).map((item) => ({
    material_code: item.material_code, name_cn: item.name_cn, spec: item.spec, unit: item.unit,
    qty: item.uninvoiced_qty, price: item.price, tax_rate: detail.data.tax_rate, manual_tax: false,
  }));
}
async function save() {
  const payload = { ...form, direction: props.direction };
  if (form.id) await http.put(`/api/invoices/${form.id}`, payload);
  else await http.post("/api/invoices", payload);
  visible.value = false;
  load();
}
async function remove(row) { await http.delete(`/api/invoices/${row.id}`, { params: { version: row.version } }); load(); }
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/invoices/batch-delete")) load();
}
const route = useRoute();
onMounted(async () => {
  const type = props.direction === "output" ? "customer" : "supplier";
  parties.value = (await http.get("/api/parties", { params: { type, status: "启用", pageSize: 200 } })).data.items;
  projects.value = (await http.get("/api/projects", { params: { pageSize: 200 } })).data.items;
  await load();
  const raw = sessionStorage.getItem("invoice-prefill");
  if (raw) {
    const data = JSON.parse(raw);
    if ((data.direction || "input") === props.direction) {
      sessionStorage.removeItem("invoice-prefill");
      await applyPrefill(data);
    }
  }
  if (route.query.open) open({ id: route.query.open });
});
</script>
