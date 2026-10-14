<template>
  <ListShell ref="shell" :title="title" :storage-key="'order-'+direction" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :sums="sums" export-module="order" :export-query="{ direction, ...query }" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters>
      <el-select v-model="query.party_id" clearable placeholder="客商" style="width:180px"><el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" /></el-select>
      <el-input v-model="query.keyword" placeholder="合同 / 物料编号" style="width:200px" />
    </template>
    <template #toolbar>
      <el-button type="primary" @click="open()">新增{{ title }}</el-button>
      <el-button @click="showImport = true">导入</el-button>
      <el-button @click="removeMany">批量删除</el-button>
      <GenerateForm :shell="shell" :rows="rows" :doc-code="direction==='sale' ? 'sale_order' : 'purchase_order'" :doc-name="title" :party-word="direction==='sale' ? '客户' : '供应商'" :record-id="(row) => row.order_id || row.id" :fallback-name="(row) => `${row.order_code || title}.docx`" />
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">编辑</span>
      <span class="ops" style="margin-left:8px" @click="close(row)">{{ row.status==='closed' ? '取消关闭' : '关闭订单' }}</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="visible" class="line-dialog" :title="title" width="860px" top="8vh" append-to-body :close-on-click-modal="false">
    <el-form label-width="90px">
      <el-form-item label="源合同">
        <el-select v-model="form.contract_id" filterable style="width:100%" @change="takeContract">
          <el-option v-for="c in contracts" :key="c.id" :label="c.contract_code + ' ' + c.name" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="订单号"><el-input v-model="form.order_code" disabled placeholder="保存时生成" /></el-form-item>
      <el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item>
    </el-form>
    <div class="line-box">
    <el-table :data="form.items" height="320" size="small" empty-text="选择合同后带出物料">
      <el-table-column prop="material_code" label="物料编号" />
      <el-table-column prop="name_cn" label="中文名称" />
      <el-table-column label="数量"><template #default="{ row }"><el-input v-model="row.qty" /></template></el-table-column>
      <el-table-column label="含税单价"><template #default="{ row }"><el-input v-model="row.price" /></template></el-table-column>
      <el-table-column prop="moved_text" label="到货 / 发货" />
    </el-table>
    </div>
    <template #footer>
      <el-button @click="visible=false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
  <ImportWizard v-model="showImport" module="order" :direction="direction" @done="load" />
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";
import GenerateForm from "../components/GenerateForm.vue";

const props = defineProps({ direction: String });
const shell = ref(null);
const title = computed(() => (props.direction === "sale" ? "销售订单" : "采购订单"));
const columns = [
  { key: "order_code", label: "订单号", fixed: "left", width: 180 },
  { key: "contract_code", label: "合同编号" },
  { key: "party_name", label: "客商" },
  { key: "material_code", label: "物料编号" },
  { key: "name_cn", label: "中文名称" },
  { key: "spec", label: "规格" },
  { key: "unit", label: "单位" },
  { key: "qty", label: "数量" },
  { key: "price", label: "含税单价", money: true },
  { key: "amount", label: "金额", money: true },
  { key: "moved_text", label: "到货 / 发货", width: 220 },
  { key: "status_label", label: "状态", tag: true },
];
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const sums = ref({});
const query = reactive({ party_id: null, keyword: "" });
const parties = ref([]);
const contracts = ref([]);
const visible = ref(false);
const showImport = ref(false);
const form = reactive({ id: null, version: null, contract_id: null, order_code: "", remark: "", items: [] });

async function load() {
  const res = await http.get("/api/orders", { params: { direction: props.direction, ...query, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
  sums.value = res.data.sums || {};
}
function reset() { query.party_id = null; query.keyword = ""; load(); }
async function open(row) {
  const res = await http.get("/api/orders/available-contracts", { params: { direction: props.direction, current_id: row?.contract_id || "" } });
  contracts.value = res.data;
  if (!row && !contracts.value.length) {
    ElMessage.warning("请先去录入合同");
    return;
  }
  if (row) {
    const detail = await http.get(`/api/orders/${row.order_id || row.id}`);
    Object.assign(form, detail.data);
  } else Object.assign(form, { id: null, version: null, contract_id: null, order_code: "", remark: "", items: [] });
  visible.value = true;
}
async function takeContract() {
  const detail = await http.get(`/api/contracts/${form.contract_id}`);
  form.items = detail.data.items.map((item) => ({ ...item, moved_text: "" }));
  form.remark = detail.data.content || "";
}
async function save() {
  const payload = { ...form, direction: props.direction };
  if (form.id) await http.put(`/api/orders/${form.id}`, payload);
  else await http.post("/api/orders", payload);
  visible.value = false;
  load();
}
async function remove(row) {
  await http.delete(`/api/orders/${row.order_id || row.id}`, { params: { version: row.version } });
  load();
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/orders/batch-delete")) load();
}
async function close(row) {
  const path = row.status === "closed" ? "reopen" : "close";
  await http.post(`/api/orders/${row.order_id}/${path}`, { version: row.version });
  load();
}
async function boot() {
  parties.value = (await http.get("/api/parties", { params: { type: props.direction === "sale" ? "customer" : "supplier", status: "启用", pageSize: 200 } })).data.items;
  load();
}
watch(() => props.direction, boot);
onMounted(boot);
</script>
