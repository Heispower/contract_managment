<template>
  <ListShell ref="shell" title="报关要素" storage-key="customs-element-mark" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" export-module="customs-element" :export-query="{ keyword }" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters>
      <el-input v-model="keyword" placeholder="报关发票编号" style="width:200px" clearable />
    </template>
    <template #toolbar>
      <el-button type="primary" @click="openCreate">新增报关要素</el-button>
      <el-button @click="removeMany">批量删除</el-button>
      <GenerateForm :shell="shell" :rows="rows" doc-code="customs_element" doc-name="报关要素" party-word="供应商" :fallback-name="(row) => `${row.invoice_no || '报关要素'}-报关要素.docx`" />
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row, false)">编辑</span>
      <span class="ops" style="margin-left:8px" @click="open(row, true)">详情</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="createVisible" title="新增报关要素" width="560px" append-to-body>
    <el-form label-width="110px">
      <el-form-item label="关联报关发票">
        <el-select v-model="invoiceId" filterable placeholder="已关联的发票不再显示" style="width:100%">
          <el-option v-for="item in unused" :key="item.id" :label="invoiceOptionLabel(item)" :value="item.id">
            <div class="invoice-option">
              <div>发票：{{ item.invoice_no || "—" }}</div>
              <div>合同号：{{ item.contract_no || "—" }}</div>
            </div>
          </el-option>
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createVisible=false">取消</el-button>
      <el-button type="primary" @click="create">生成</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="detailVisible" class="line-dialog sheet-dialog" width="1180px" top="6vh" append-to-body :close-on-click-modal="false">
    <template #header>
      <div>{{ dialogTitle }} - <span class="name-pill">{{ detail.invoice_no || "—" }}</span></div>
    </template>
    <el-alert v-if="draftIds.length" type="info" show-icon :closable="false" title="请核对并修改。确认后才会生成，取消则不会保存。" style="margin-bottom:12px" />
    <div class="board-summary purchase">
      <div class="sum-line">
        <span><em>报关发票</em><b>{{ detail.invoice_no || "—" }}</b></span>
        <span><em>合同号</em>{{ detail.contract_no || "—" }}</span>
        <span><em>供应商</em>{{ detail.supplier_name || "—" }}</span>
        <span><em>主要物料</em>{{ detail.main_materials || "—" }}</span>
        <span><em>状态</em><i class="tag tag-green">{{ detail.status || "—" }}</i></span>
        <span><em>差异数</em>{{ (detail.issues || []).length }}</span>
      </div>
    </div>
    <el-alert v-if="detail.issues && detail.issues.length" type="warning" show-icon :closable="false" style="margin-bottom:12px">
      <div v-for="item in detail.issues" :key="item">{{ item }}</div>
    </el-alert>
    <div class="hint" style="margin-bottom:8px">同一申报名称共用一套申报要素，产品行只区分产品名称和型号。</div>
    <ResizePane v-slot="{ height }" :height="360">
      <el-table :data="flatRows" :span-method="spanLine" :height="height" size="small" border>
        <el-table-column label="序号" width="60"><template #default="{ row }">{{ row.item.seq }}</template></el-table-column>
        <el-table-column label="HS CODE" min-width="120"><template #default="{ row }"><el-input v-model="row.item.hs_code" :disabled="readonly" /></template></el-table-column>
        <el-table-column label="申报名称" min-width="120"><template #default="{ row }"><el-input v-model="row.item.declaration_name" :disabled="readonly" /></template></el-table-column>
        <el-table-column label="产品名称" min-width="120"><template #default="{ row }"><el-input v-model="row.line.product_name" :disabled="readonly" /></template></el-table-column>
        <el-table-column label="型号" min-width="110"><template #default="{ row }"><el-input v-model="row.line.model" :disabled="readonly" /></template></el-table-column>
        <el-table-column label="申报要素" min-width="180"><template #default="{ row }"><el-input v-model="row.item.declaration_elements" type="textarea" :rows="2" :disabled="readonly" /></template></el-table-column>
        <el-table-column label="货源地" min-width="100"><template #default="{ row }"><el-input v-model="row.line.origin_place" :disabled="readonly" /></template></el-table-column>
        <el-table-column label="数量" width="70"><template #default="{ row }">{{ row.item.quantity }}</template></el-table-column>
        <el-table-column label="匹配" width="70"><template #default="{ row }">{{ row.item.match_source }}</template></el-table-column>
        <el-table-column v-if="!readonly" label="操作" width="130">
          <template #default="{ row }">
            <span class="ops" @click="matchRow(row.item)">匹配</span>
            <span class="ops" style="margin-left:8px" @click="aiRow(row.item)">AI检查</span>
          </template>
        </el-table-column>
      </el-table>
    </ResizePane>
    <el-alert v-if="aiHint" :title="aiHint" type="info" show-icon style="margin-top:12px" />
    <BizAttach v-if="detail.id" business-type="customs_element" :business-id="detail.id" style="margin-top:12px" />
    <template #footer>
      <el-button @click="detailVisible=false">{{ draftIds.length ? "取消" : "关闭" }}</el-button>
      <template v-if="draftIds.length">
        <el-button type="primary" @click="confirmDraft">确认生成</el-button>
      </template>
      <template v-else-if="!readonly">
        <el-button @click="save(false)">保存</el-button>
        <el-button type="primary" @click="save(true)">确认后继续</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";
import BizAttach from "../components/BizAttach.vue";
import GenerateForm from "../components/GenerateForm.vue";
import ResizePane from "../components/ResizePane.vue";

const shell = ref(null);
const columns = [
  { key: "invoice_no", label: "报关发票", fixed: "left" },
  { key: "contract_no", label: "合同号" },
  { key: "supplier_name", label: "供应商" },
  { key: "main_materials", label: "主要物料" },
  { key: "status", label: "状态", tag: true },
  { key: "issue_count", label: "差异数" },
  { key: "created_by", label: "创建人" },
];
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");
const createVisible = ref(false);
const detailVisible = ref(false);
const unused = ref([]);
const invoiceId = ref(null);
const draftIds = ref([]);
const draftInvoiceId = ref(null);
const detail = ref({ items: [], issues: [] });
const readonly = ref(false);
const aiHint = ref("");
const dialogTitle = computed(() => (draftIds.value.length ? "审核报关要素" : readonly.value ? "报关要素详情" : "编辑报关要素"));
const flatRows = computed(() => {
  const out = [];
  for (const item of detail.value.items || []) {
    const lines = item.lines?.length ? item.lines : [{ product_name: "", model: "", declaration_elements: "", origin_place: "" }];
    lines.forEach((line, index) => out.push({ item, line, span: index === 0 ? lines.length : 0 }));
  }
  return out;
});
function spanLine({ row, columnIndex }) {
  const shared = readonly.value ? [0, 1, 2, 5, 7, 8] : [0, 1, 2, 5, 7, 8, 9];
  if (!shared.includes(columnIndex)) return [1, 1];
  return row.span ? [row.span, 1] : [0, 0];
}

async function load() {
  const res = await http.get("/api/customs/elements", { params: { keyword: keyword.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
}
function reset() {
  keyword.value = "";
  page.value = 1;
  load();
}
function invoiceOptionLabel(item) {
  return `发票：${item.invoice_no || "—"}　合同号：${item.contract_no || "—"}`;
}
async function openCreate() {
  unused.value = (await http.get("/api/customs/invoices/unused")).data || [];
  invoiceId.value = unused.value[0]?.id || null;
  createVisible.value = true;
}
async function create() {
  if (!invoiceId.value) {
    ElMessage.warning("请选择报关发票");
    return;
  }
  await http.post("/api/customs/elements", { invoice_id: invoiceId.value });
  createVisible.value = false;
  load();
}
async function openDraft(ids, invoice) {
  detail.value = (await http.post("/api/customs/elements/preview", { invoice_id: invoice, ids })).data;
  draftIds.value = ids;
  draftInvoiceId.value = invoice;
  readonly.value = false;
  aiHint.value = "";
  detailVisible.value = true;
}
async function confirmDraft() {
  const created = (await http.post("/api/customs/elements", {
    invoice_id: draftInvoiceId.value,
    ids: draftIds.value,
  })).data;
  detail.value = { ...detail.value, id: created.id, version: created.version, invoice_no: created.invoice_no || detail.value.invoice_no };
  draftIds.value = [];
  draftInvoiceId.value = null;
  await save(false);
  load();
}
function consumeDraft() {
  const raw = sessionStorage.getItem("customs-element-draft");
  if (!raw) return;
  sessionStorage.removeItem("customs-element-draft");
  const data = JSON.parse(raw);
  if (data?.ids?.length && data.invoice) openDraft(data.ids, data.invoice);
}
async function open(row, viewOnly = false) {
  detail.value = (await http.get(`/api/customs/elements/${row.id}`)).data;
  draftIds.value = [];
  draftInvoiceId.value = null;
  readonly.value = viewOnly;
  aiHint.value = "";
  detailVisible.value = true;
}
async function save(confirm) {
  try {
    const res = await http.put(`/api/customs/elements/${detail.value.id}`, { version: detail.value.version, items: detail.value.items, confirm });
    detail.value = res.data;
    ElMessage.success("已保存");
    detailVisible.value = false;
    load();
  } catch (err) {
    const issues = err?.data?.issues || [];
    if (issues.length && !confirm) {
      try {
        await ElMessageBox.confirm(issues.join("\n") + "\n\n允许确认后继续保存。", "数据不一致", { type: "warning", confirmButtonText: "确认后继续" });
        await save(true);
      } catch {
        /* cancel */
      }
    }
  }
}
async function matchRow(item) {
  const hits = (await http.get("/api/customs/hs/match", { params: { name: item.declaration_name } })).data || [];
  const best = hits[0];
  if (!best) {
    ElMessage.warning("未匹配到 HS Code");
    return;
  }
  item.hs_code = best.hs_code;
  item.declaration_elements = best.declaration_elements || item.declaration_elements;
  for (const line of item.lines || []) line.declaration_elements = item.declaration_elements;
  item.match_source = best.source;
  ElMessage.success(best.reason || "已匹配");
}
async function aiRow(item) {
  const elements = item.declaration_elements || "";
  const res = await http.post("/api/ai/customs/check", {
    declarationName: item.declaration_name,
    hsCode: item.hs_code,
    elements,
  });
  item.ai_suggestion = res.data.suggestion || "";
  aiHint.value = `${item.declaration_name}：${res.data.suggestion || ""} ${(res.data.issues || []).join("；")}`;
}
async function remove(row) {
  await http.delete(`/api/customs/elements/${row.id}`, { params: { version: row.version } });
  load();
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/customs/elements/batch-delete")) load();
}
onMounted(() => {
  load();
  consumeDraft();
});
</script>
