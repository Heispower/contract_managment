<template>
  <ListShell ref="shell" title="报关发票" storage-key="customs-invoice-mark" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" export-module="customs-invoice" :export-query="query" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters>
      <el-input v-model="keyword" placeholder="发票编号 / 合同号" style="width:200px" clearable />
      <el-select v-model="elementStatus" clearable placeholder="报关要素" style="width:140px">
        <el-option label="未关联" value="未关联" />
        <el-option label="已关联" value="已关联" />
      </el-select>
    </template>
    <template #toolbar>
      <el-button type="primary" @click="openCreate">新增报关发票</el-button>
      <el-button @click="removeMany">批量删除</el-button>
      <GenerateForm :shell="shell" :rows="rows" doc-code="customs_invoice" doc-name="报关发票" party-word="供应商" zip-api="/api/customs/invoices" :fallback-name="(row) => `${row.invoice_no || '报关发票'}.docx`" :zip-name="(row) => `${row.invoice_no || '报关发票'}-报关文件.zip`" />
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">详情</span>
      <span class="ops" style="margin-left:8px" @click="open(row, true)">编辑</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="createVisible" title="新增报关发票" width="860px" append-to-body :close-on-click-modal="false">
    <div class="hint" style="margin-bottom:8px">按物料大类/申报名称汇总；特殊申报物料单独成行。</div>
    <ResizePane v-slot="{ height }" :height="360">
      <el-table :data="candidates" :height="height" size="small" @selection-change="picked = $event">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="material_code" label="物料编号" width="120" />
        <el-table-column prop="material_name" label="名称" />
        <el-table-column prop="material_category" label="物料大类" />
        <el-table-column prop="equipment" label="使用设备" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column prop="special_label" label="申报" width="90" />
      </el-table>
    </ResizePane>
    <template #footer>
      <el-button @click="createVisible=false">取消</el-button>
      <el-button type="primary" @click="create">生成</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="detailVisible" class="line-dialog sheet-dialog" width="1100px" top="4vh" append-to-body :close-on-click-modal="false">
    <template #header>
      <div>{{ draftIds.length ? "审核报关发票" : (editing ? "编辑报关发票" : "报关发票详情") }} - <span class="name-pill">{{ detail.invoice_no || "—" }}</span></div>
    </template>
    <el-alert v-if="draftIds.length" type="info" show-icon :closable="false" title="请核对并修改。确认后才会生成，取消则不会保存。" style="margin-bottom:12px" />
    <div class="board-summary purchase">
      <div class="sum-line">
        <span><em>发票编号</em><b>{{ detail.invoice_no || "—" }}</b></span>
        <span><em>发票日期</em>{{ detail.invoice_date_1 || "—" }}</span>
        <span><em>状态</em><i class="tag tag-green">{{ detail.status || "—" }}</i></span>
        <span><em>报关要素</em><i :class="['tag', detail.linked ? 'tag-green' : 'tag-red']">{{ detail.element_status || "—" }}</i></span>
        <span><em>总金额</em>{{ detail.total_amount || "0.00" }}</span>
        <span><em>美元金额</em>{{ detail.total_amount_usd || "0.00" }}</span>
      </div>
      <div class="sum-line">
        <span><em>供应商</em>{{ detail.supplier_name || "—" }}</span>
        <span><em>主要物料</em>{{ detail.main_materials || "—" }}</span>
        <span><em>合同号</em>{{ detail.contract_no || "—" }}</span>
      </div>
    </div>
    <el-tabs v-model="detailTab">
      <el-tab-pane label="主页面" name="master">
        <div class="info-grid">
          <div class="cell"><em>发票编号</em><span>{{ detail.invoice_no || "—" }}</span></div>
          <div class="cell"><em>发票日期</em><span><el-date-picker v-if="editing" v-model="detail.invoice_date_1" value-format="YYYY-MM-DD" /><template v-else>{{ detail.invoice_date_1 || "—" }}</template></span></div>
          <div class="cell"><em>船名/航号</em><span><el-input v-if="editing" v-model="detail.vessel_voyage" /><template v-else>{{ detail.vessel_voyage || "—" }}</template></span></div>
          <div class="cell"><em>集装箱号</em><span><el-input v-if="editing" v-model="detail.container_no" /><template v-else>{{ detail.container_no || "—" }}</template></span></div>
          <div class="cell"><em>提单号</em><span><el-input v-if="editing" v-model="detail.bl_no" /><template v-else>{{ detail.bl_no || "—" }}</template></span></div>
          <div class="cell"><em>出发港</em><span><el-input v-if="editing" v-model="detail.port_of_shipment" /><template v-else>{{ detail.port_of_shipment || "—" }}</template></span></div>
          <div class="cell"><em>目的港</em><span><el-input v-if="editing" v-model="detail.port_of_destination" /><template v-else>{{ detail.port_of_destination || "—" }}</template></span></div>
          <div class="cell"><em>箱单号</em><span><el-input v-if="editing" v-model="detail.packing_list_no" /><template v-else>{{ detail.packing_list_no || "—" }}</template></span></div>
          <div class="cell"><em>合同编号</em><span><el-input v-if="editing" v-model="detail.contract_no" /><template v-else>{{ detail.contract_no || "—" }}</template></span></div>
          <div class="cell"><em>PO NO.</em><span><el-input v-if="editing" v-model="detail.po_no" /><template v-else>{{ detail.po_no || "—" }}</template></span></div>
          <div class="cell"><em>汇率</em><span><el-input v-if="editing" v-model="detail.exchange_rate" /><template v-else>{{ detail.exchange_rate || "—" }}</template></span></div>
          <div class="cell"><em>状态</em><span><i class="tag tag-green">{{ detail.status || "—" }}</i></span></div>
          <div class="cell wide"><em>收货人</em><span><el-input v-if="editing" v-model="detail.consignee" /><template v-else>{{ detail.consignee || "—" }}</template></span></div>
          <div class="cell wide"><em>付款条款</em><span><el-input v-if="editing" v-model="detail.payment_terms" type="textarea" :rows="2" /><template v-else>{{ detail.payment_terms || "—" }}</template></span></div>
          <div class="cell wide"><em>报关要素</em><span><el-input v-if="editing" v-model="detail.customs_elements" type="textarea" :rows="2" /><template v-else>{{ detail.customs_elements || "—" }}</template></span></div>
        </div>
      </el-tab-pane>
      <el-tab-pane label="物料大类详情" name="category">
        <ResizePane v-slot="{ height }" :height="320">
          <el-table :data="detail.categories || []" size="small" :height="height">
            <el-table-column prop="seq" label="序列号" width="70" />
            <el-table-column prop="material_category" label="物料大类" min-width="120" />
            <el-table-column prop="specification" label="规格" min-width="120" />
            <el-table-column prop="quantity" label="数量" width="80" />
            <el-table-column prop="unit" label="单位" width="70" />
            <el-table-column prop="package_count" label="包件件数" width="90" />
            <el-table-column prop="gross_weight" label="毛重" width="80" />
            <el-table-column prop="net_weight" label="净重" width="80" />
            <el-table-column prop="size_display" label="尺寸" min-width="130" />
            <el-table-column prop="weight" label="重量" width="80" />
          </el-table>
        </ResizePane>
      </el-tab-pane>
      <el-tab-pane label="物料明细表" name="detail">
        <el-select v-model="specPick" style="width:280px;margin-bottom:8px">
          <el-option v-for="item in detail.specification_options || []" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <ResizePane v-slot="{ height }" :height="320">
          <el-table :data="currentItems" size="small" :height="height">
            <el-table-column prop="seq" label="编号" width="70" />
            <el-table-column prop="chinese_name" label="中文名称" min-width="120" />
            <el-table-column prop="english_name" label="英文名称" min-width="120" />
            <el-table-column prop="model" label="型号" min-width="120" />
            <el-table-column prop="unit" label="单位" width="70" />
            <el-table-column prop="quantity" label="数量" width="80" />
            <el-table-column prop="fob_unit_price" label="FOB单价" width="100" />
            <el-table-column prop="fob_total_price" label="FOB总价" width="110" />
            <el-table-column prop="convert_to_usd" label="Convert to USD" width="130" />
          </el-table>
        </ResizePane>
      </el-tab-pane>
    </el-tabs>
    <BizAttach v-if="detail.id" business-type="customs_invoice" :business-id="detail.id" style="margin-top:12px" />
    <template #footer>
      <el-button v-if="detail.id" @click="exportExcel(detail)">导出Excel</el-button>
      <el-button v-if="draftIds.length" type="primary" @click="confirmDraft">确认生成</el-button>
      <el-button v-else-if="editing" type="primary" @click="saveDetail">保存</el-button>
      <el-button @click="detailVisible=false">{{ draftIds.length ? "取消" : "关闭" }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import http, { batchDelete, downloadBlob } from "../api";
import ListShell from "../components/ListShell.vue";
import BizAttach from "../components/BizAttach.vue";
import GenerateForm from "../components/GenerateForm.vue";
import ResizePane from "../components/ResizePane.vue";

const shell = ref(null);
const columns = [
  { key: "invoice_no", label: "发票编号", fixed: "left" },
  { key: "supplier_name", label: "供应商" },
  { key: "main_materials", label: "主要物料" },
  { key: "contract_no", label: "合同号" },
  { key: "invoice_date", label: "日期" },
  { key: "total_amount", label: "总金额", money: true },
  { key: "element_status", label: "报关要素", tag: true },
  { key: "status", label: "状态", tag: true },
];
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");
const elementStatus = ref("");
const query = computed(() => ({ keyword: keyword.value, element_status: elementStatus.value }));
const createVisible = ref(false);
const detailVisible = ref(false);
const candidates = ref([]);
const picked = ref([]);
const detailTab = ref("master");
const specPick = ref("");
const editing = ref(false);
const draftIds = ref([]);
const detail = ref({ items: [], sources: [], categories: [], specification_options: [], detail_groups: [] });
const currentItems = computed(() => {
  const groups = detail.value.detail_groups || [];
  const hit = groups.find((group) => group.container_no === specPick.value) || groups[0];
  return hit?.items || [];
});

async function load() {
  const res = await http.get("/api/customs/invoices", { params: { ...query.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
}
function reset() {
  keyword.value = "";
  elementStatus.value = "";
  page.value = 1;
  load();
}
async function openCreate() {
  candidates.value = (await http.get("/api/customs/materials", { params: { unlinked: "invoice", pageSize: 200 } })).data.items;
  picked.value = [];
  createVisible.value = true;
}
async function create() {
  if (!picked.value.length) {
    ElMessage.warning("请勾选物料");
    return;
  }
  await http.post("/api/customs/invoices", { ids: picked.value.map((row) => row.id) });
  createVisible.value = false;
  load();
}
async function openDraft(ids) {
  detail.value = (await http.post("/api/customs/invoices/preview", { ids })).data;
  draftIds.value = ids;
  editing.value = true;
  detailTab.value = "master";
  specPick.value = detail.value.specification_options?.[0]?.value || "";
  detailVisible.value = true;
}
async function confirmDraft() {
  const created = (await http.post("/api/customs/invoices", {
    ids: draftIds.value,
    invoice_no: detail.value.invoice_no,
    invoice_date: detail.value.invoice_date_1,
  })).data;
  const payload = { ...detail.value, version: created.version };
  delete payload.items;
  delete payload.sources;
  delete payload.categories;
  delete payload.detail_groups;
  delete payload.specification_options;
  delete payload.draft;
  detail.value = (await http.put(`/api/customs/invoices/${created.id}`, payload)).data;
  draftIds.value = [];
  ElMessage.success("已生成报关发票，可继续修改");
  load();
}
function consumeDraft() {
  const raw = sessionStorage.getItem("customs-invoice-draft");
  if (!raw) return;
  sessionStorage.removeItem("customs-invoice-draft");
  const ids = JSON.parse(raw);
  if (Array.isArray(ids) && ids.length) openDraft(ids);
}
async function open(row, edit = false) {
  detail.value = (await http.get(`/api/customs/invoices/${row.id}`)).data;
  editing.value = !!edit;
  detailTab.value = "master";
  specPick.value = detail.value.specification_options?.[0]?.value || "";
  detailVisible.value = true;
}
async function saveDetail() {
  const payload = { ...detail.value };
  delete payload.items;
  delete payload.sources;
  delete payload.categories;
  delete payload.detail_groups;
  delete payload.specification_options;
  detail.value = (await http.put(`/api/customs/invoices/${detail.value.id}`, payload)).data;
  ElMessage.success("已保存");
  load();
}
async function exportExcel(row) {
  if (!row?.id) return;
  await downloadBlob(`/api/customs/invoices/${row.id}/excel`, `${row.invoice_no || "报关发票"}.xlsx`);
}
async function remove(row) {
  await http.delete(`/api/customs/invoices/${row.id}`, { params: { version: row.version } });
  load();
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/customs/invoices/batch-delete")) load();
}
onMounted(() => {
  load();
  consumeDraft();
});
</script>
