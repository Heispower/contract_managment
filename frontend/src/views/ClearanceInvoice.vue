<template>
  <ListShell ref="shell" title="清关发票" storage-key="customs-clearance-mark" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" export-module="customs-clearance" :export-query="{ keyword }" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters>
      <el-input v-model="keyword" placeholder="发票号 / 提单 / 集装箱" style="width:220px" clearable />
    </template>
    <template #toolbar>
      <el-button type="primary" @click="openCreate">新增清关发票</el-button>
      <el-button @click="removeMany">批量删除</el-button>
      <GenerateForm :shell="shell" :rows="rows" doc-code="customs_clearance" doc-name="清关发票" party-word="供应商" zip-api="/api/customs/clearances" :fallback-name="(row) => `${row.invoice_no || '清关发票'}.docx`" :zip-name="(row) => `${row.invoice_no || '清关发票'}-清关文件.zip`" />
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">详情</span>
      <span class="ops" style="margin-left:8px" @click="open(row, true)">编辑</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="createVisible" title="新增清关发票" width="860px" append-to-body :close-on-click-modal="false">
    <el-form label-width="90px" style="margin-bottom:8px">
      <el-form-item label="发票号"><el-input v-model="invoiceNo" placeholder="可为空，空则显示无发票号" /></el-form-item>
    </el-form>
    <ResizePane v-slot="{ height }" :height="320">
      <el-table :data="candidates" :height="height" size="small" @selection-change="picked = $event">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="material_code" label="物料编号" />
        <el-table-column prop="material_name" label="中文名" />
        <el-table-column prop="specification" label="规格" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column prop="po_no" label="PO" />
      </el-table>
    </ResizePane>
    <template #footer>
      <el-button @click="createVisible=false">取消</el-button>
      <el-button type="primary" @click="create">生成</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="detailVisible" class="line-dialog sheet-dialog" width="1180px" top="4vh" append-to-body :close-on-click-modal="false">
    <template #header>
      <div>{{ draftIds.length ? "审核清关发票" : (editing ? "编辑清关发票" : "清关发票详情") }} - <span class="name-pill">{{ detail.invoice_no || "无发票号" }}</span></div>
    </template>
    <el-alert v-if="draftIds.length" type="info" show-icon :closable="false" title="请核对并修改。确认后才会生成，取消则不会保存。" style="margin-bottom:12px" />
    <div class="board-summary purchase">
      <div class="sum-line">
        <span><em>发票号</em><b>{{ detail.invoice_no || "无发票号" }}</b></span>
        <span><em>制单日期</em>{{ detail.invoice_date || "—" }}</span>
        <span><em>状态</em><i class="tag tag-green">{{ detail.status || "—" }}</i></span>
        <span><em>人民币合计</em>{{ detail.total_amount || "0.00" }}</span>
        <span><em>美元合计</em>{{ detail.total_usd || "0.00" }}</span>
      </div>
      <div class="sum-line">
        <span><em>供应商</em>{{ detail.supplier_name || "—" }}</span>
        <span><em>主要物料</em>{{ detail.main_materials || "—" }}</span>
        <span><em>合同号</em>{{ detail.contract_no || "—" }}</span>
      </div>
    </div>
    <el-tabs v-model="detailTab">
      <el-tab-pane label="主表" name="master">
        <div class="info-grid">
          <div class="cell"><em>发票号</em><span><el-input v-if="editing" v-model="detail.invoice_no" placeholder="可为空" /><template v-else>{{ detail.invoice_no || "无发票号" }}</template></span></div>
          <div class="cell"><em>制单日期</em><span><el-date-picker v-if="editing" v-model="detail.invoice_date" value-format="YYYY-MM-DD" /><template v-else>{{ detail.invoice_date || "—" }}</template></span></div>
          <div class="cell"><em>船名/航号</em><span><el-input v-if="editing" v-model="detail.vessel_voyage" /><template v-else>{{ detail.vessel_voyage || "—" }}</template></span></div>
          <div class="cell"><em>集装箱号</em><span><el-input v-if="editing" v-model="detail.container_no" /><template v-else>{{ detail.container_no || "—" }}</template></span></div>
          <div class="cell"><em>提单号</em><span><el-input v-if="editing" v-model="detail.bill_no" /><template v-else>{{ detail.bill_no || "—" }}</template></span></div>
          <div class="cell"><em>出发港口</em><span><el-input v-if="editing" v-model="detail.port_of_shipment" /><template v-else>{{ detail.port_of_shipment || "—" }}</template></span></div>
          <div class="cell"><em>装箱号</em><span><el-input v-if="editing" v-model="detail.packing_list_no" /><template v-else>{{ detail.packing_list_no || "—" }}</template></span></div>
          <div class="cell"><em>汇率</em><span><el-input v-if="editing" v-model="detail.exchange_rate" /><template v-else>{{ detail.exchange_rate || "—" }}</template></span></div>
          <div class="cell"><em>人民币合计</em><span>{{ detail.total_amount || "0.00" }}</span></div>
          <div class="cell"><em>美元合计</em><span>{{ detail.total_usd || "0.00" }}</span></div>
          <div class="cell"><em>状态</em><span><i class="tag tag-green">{{ detail.status || "—" }}</i></span></div>
        </div>
      </el-tab-pane>
      <el-tab-pane label="物料大类清单" name="category">
        <ResizePane v-slot="{ height }" :height="320">
          <el-table :data="detail.packing" size="small" :height="height">
            <el-table-column prop="seq" label="序列号" width="70" />
            <el-table-column label="品名" min-width="110"><template #default="{ row }"><el-input v-model="row.category" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="规格" min-width="100"><template #default="{ row }"><el-input v-model="row.specification" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="数量" width="80"><template #default="{ row }"><el-input v-model="row.quantity" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="单位" width="70"><template #default="{ row }"><el-input v-model="row.unit" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="包装件数" width="90"><template #default="{ row }"><el-input v-model="row.packages" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="毛重" width="80"><template #default="{ row }"><el-input v-model="row.gross_weight" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="净重" width="80"><template #default="{ row }"><el-input v-model="row.net_weight" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="尺寸" min-width="120"><template #default="{ row }"><el-input v-model="row.size_text" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="入仓单号" min-width="120"><template #default="{ row }"><el-input v-model="row.receipt_no" :disabled="!editing" /></template></el-table-column>
          </el-table>
        </ResizePane>
      </el-tab-pane>
      <el-tab-pane label="物料明细" name="lines">
        <ResizePane v-slot="{ height }" :height="360">
          <el-table :data="detail.items" size="small" :height="height">
            <el-table-column prop="seq" label="序号" width="60" />
            <el-table-column label="中文名" min-width="110"><template #default="{ row }"><el-input v-model="row.name_cn" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="英文名" min-width="110"><template #default="{ row }"><el-input v-model="row.name_en" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="规格" min-width="100"><template #default="{ row }"><el-input v-model="row.specification" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="数量" width="80"><template #default="{ row }"><el-input v-model="row.quantity" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="单位" width="70"><template #default="{ row }"><el-input v-model="row.unit" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="人民币单价" width="110"><template #default="{ row }"><el-input v-model="row.price" :disabled="!editing" /></template></el-table-column>
            <el-table-column prop="amount" label="人民币总价" width="110" />
            <el-table-column prop="amount_usd" label="换算美元金额" width="120" />
            <el-table-column label="PO单号" width="100"><template #default="{ row }"><el-input v-model="row.po_no" :disabled="!editing" /></template></el-table-column>
            <el-table-column label="备注" min-width="100"><template #default="{ row }"><el-input v-model="row.remark" :disabled="!editing" /></template></el-table-column>
          </el-table>
        </ResizePane>
      </el-tab-pane>
    </el-tabs>
    <BizAttach v-if="detail.id" business-type="customs_clearance" :business-id="detail.id" style="margin-top:12px" />
    <template #footer>
      <el-button v-if="draftIds.length" type="primary" @click="confirmDraft">确认生成</el-button>
      <el-button v-else-if="editing" type="primary" @click="saveDetail">保存</el-button>
      <el-button @click="detailVisible=false">{{ draftIds.length ? "取消" : "关闭" }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";
import BizAttach from "../components/BizAttach.vue";
import GenerateForm from "../components/GenerateForm.vue";
import ResizePane from "../components/ResizePane.vue";

const shell = ref(null);
const columns = [
  { key: "invoice_no", label: "发票号", fixed: "left", tag: true },
  { key: "supplier_name", label: "供应商" },
  { key: "main_materials", label: "主要物料" },
  { key: "contract_no", label: "合同号" },
  { key: "invoice_date", label: "制单日期" },
  { key: "vessel_voyage", label: "船名/航号" },
  { key: "container_no", label: "集装箱号" },
  { key: "bill_no", label: "提单号" },
  { key: "exchange_rate", label: "汇率" },
  { key: "total_amount", label: "人民币合计", money: true },
  { key: "total_usd", label: "美元合计", money: true },
  { key: "status", label: "状态", tag: true },
];
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");
const createVisible = ref(false);
const detailVisible = ref(false);
const candidates = ref([]);
const picked = ref([]);
const invoiceNo = ref("");
const detailTab = ref("master");
const editing = ref(false);
const draftIds = ref([]);
const detail = ref({ items: [], packing: [] });

async function load() {
  const res = await http.get("/api/customs/clearances", { params: { keyword: keyword.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
}
function reset() {
  keyword.value = "";
  page.value = 1;
  load();
}
async function openCreate() {
  candidates.value = (await http.get("/api/customs/materials", { params: { unlinked: "clearance", pageSize: 200 } })).data.items;
  picked.value = [];
  invoiceNo.value = "";
  createVisible.value = true;
}
async function create() {
  if (!picked.value.length) {
    ElMessage.warning("请勾选物料");
    return;
  }
  await http.post("/api/customs/clearances", { ids: picked.value.map((row) => row.id), invoice_no: invoiceNo.value });
  createVisible.value = false;
  load();
}
async function openDraft(ids) {
  const data = (await http.post("/api/customs/clearances/preview", { ids })).data;
  if (!data.invoice_no || data.invoice_no === "无发票号") data.invoice_no = "";
  detail.value = data;
  draftIds.value = ids;
  editing.value = true;
  detailTab.value = "master";
  detailVisible.value = true;
}
async function confirmDraft() {
  const created = (await http.post("/api/customs/clearances", {
    ids: draftIds.value,
    invoice_no: detail.value.invoice_no,
    invoice_date: detail.value.invoice_date,
    vessel_voyage: detail.value.vessel_voyage,
    container_no: detail.value.container_no,
    bill_no: detail.value.bill_no,
    port_of_shipment: detail.value.port_of_shipment,
    packing_list_no: detail.value.packing_list_no,
    exchange_rate: detail.value.exchange_rate,
  })).data;
  const payload = { ...detail.value, version: created.version };
  if (payload.invoice_no === "无发票号") payload.invoice_no = "";
  delete payload.draft;
  detail.value = (await http.put(`/api/customs/clearances/${created.id}`, payload)).data;
  if (!detail.value.invoice_no) detail.value.invoice_no = "";
  draftIds.value = [];
  ElMessage.success("已生成清关发票，可继续修改");
  load();
}
function consumeDraft() {
  const raw = sessionStorage.getItem("customs-clearance-draft");
  if (!raw) return;
  sessionStorage.removeItem("customs-clearance-draft");
  const ids = JSON.parse(raw);
  if (Array.isArray(ids) && ids.length) openDraft(ids);
}
async function open(row, edit = false) {
  const data = (await http.get(`/api/customs/clearances/${row.id}`)).data;
  if (!data.invoice_no || data.invoice_no === "无发票号") data.invoice_no = "";
  editing.value = !!edit;
  detailTab.value = "master";
  detail.value = data;
  detailVisible.value = true;
}
async function saveDetail() {
  const payload = { ...detail.value };
  if (payload.invoice_no === "无发票号") payload.invoice_no = "";
  detail.value = (await http.put(`/api/customs/clearances/${detail.value.id}`, payload)).data;
  if (!detail.value.invoice_no) detail.value.invoice_no = "";
  ElMessage.success("已保存");
  load();
}
async function remove(row) {
  await http.delete(`/api/customs/clearances/${row.id}`, { params: { version: row.version } });
  load();
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/customs/clearances/batch-delete")) load();
}
onMounted(() => {
  load();
  consumeDraft();
});
</script>
