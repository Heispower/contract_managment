<template>
  <ListShell ref="shell" :title="title" :storage-key="billType" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" export-module="wms" :export-query="{ type: billType, party_id: partyId, warehouse_id: warehouseId }" @query="load" @reset="load" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters>
      <el-select v-model="partyId" clearable :placeholder="billType==='inbound' ? '供应商' : '客户'" style="width:180px"><el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" /></el-select>
      <el-select v-model="warehouseId" clearable placeholder="仓库" style="width:160px"><el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" /></el-select>
    </template>
    <template #toolbar>
      <el-button type="primary" @click="open()">新增{{ title }}</el-button>
      <el-button @click="removeMany">批量删除</el-button>
      <GenerateForm :shell="shell" :rows="rows" :doc-code="billType==='inbound' ? 'purchase_in' : 'sale_out'" :doc-name="title" :party-word="billType==='inbound' ? '供应商' : '客户'" :fallback-name="(row) => `${row.bill_code || title}.docx`" />
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">编辑</span>
      <span v-if="billType==='inbound'" class="ops" style="margin-left:8px" @click="toCustoms(row)">报关物料</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="visible" class="line-dialog" :title="title" width="860px" top="8vh" append-to-body :close-on-click-modal="false">
    <el-form label-width="90px">
      <el-form-item label="单据编号"><el-input v-model="form.bill_code" placeholder="留空自动生成" /></el-form-item>
      <el-form-item label="单据日期"><el-date-picker v-model="form.bill_date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item :label="billType==='inbound'?'采购合同':'销售合同'">
        <el-select v-model="form.contract_id" filterable style="width:100%" @change="take">
          <el-option v-for="c in contracts" :key="c.id" :label="c.contract_code+' '+c.name" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="仓库">
        <el-select v-model="form.warehouse_id" style="width:100%"><el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" /></el-select>
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="form.remark" /></el-form-item>
    </el-form>
    <div style="margin-bottom:8px">{{ billType==='inbound' ? '供应商' : '客户' }}：{{ form.party_name }}</div>
    <div class="line-box">
    <el-table :data="form.items" height="320" size="small" empty-text="选择合同后带出物料">
      <el-table-column prop="material_code" label="物料编号" />
      <el-table-column v-if="billType==='inbound'" prop="category" label="使用设备" min-width="110" />
      <el-table-column prop="name_cn" label="中文名称" />
      <el-table-column prop="unit" label="单位" width="70" />
      <el-table-column label="数量"><template #default="{ row }"><el-input v-model="row.qty" /></template></el-table-column>
      <el-table-column label="含税单价"><template #default="{ row }"><el-input v-model="row.price" /></template></el-table-column>
      <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button link @click="form.items.splice($index,1)">删除</el-button></template></el-table-column>
    </el-table>
    </div>
    <template #footer>
      <el-button @click="visible=false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";
import GenerateForm from "../components/GenerateForm.vue";

const props = defineProps({ billType: String });
const router = useRouter();
const shell = ref(null);
const title = computed(() => (props.billType === "inbound" ? "采购入库" : "销售出库"));
const columns = computed(() => {
  const cols = [
    { key: "bill_code", label: "单据编号", fixed: "left" },
    { key: "bill_date", label: "单据日期" },
    { key: "contract_code", label: "合同编号" },
    { key: "party_name", label: props.billType === "inbound" ? "供应商" : "客户" },
  ];
  if (props.billType === "inbound") cols.push({ key: "category", label: "使用设备" });
  cols.push(
    { key: "qty", label: "数量" },
    { key: "amount", label: "金额", money: true },
    { key: "remark", label: "备注" },
  );
  return cols;
});
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const partyId = ref(null);
const warehouseId = ref(null);
const parties = ref([]);
const warehouses = ref([]);
const contracts = ref([]);
const visible = ref(false);
const form = reactive({ id: null, version: null, bill_code: "", bill_date: "", contract_id: null, warehouse_id: null, party_name: "", remark: "", items: [] });

async function load() {
  const res = await http.get("/api/wms-bills", { params: { type: props.billType, party_id: partyId.value, warehouse_id: warehouseId.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
}
async function open(row, fromPrefill = false) {
  const direction = props.billType === "inbound" ? "purchase" : "sale";
  contracts.value = (await http.get("/api/contracts", { params: { direction, status: "已签订", pageSize: 200 } })).data.items;
  if (row) Object.assign(form, (await http.get(`/api/wms-bills/${row.id}`)).data);
  else Object.assign(form, { id: null, version: null, bill_code: "", bill_date: new Date().toISOString().slice(0, 10), contract_id: null, warehouse_id: warehouses.value[0]?.id, party_name: "", remark: "", items: [] });
  if (!row && sessionStorage.getItem("wms-prefill")) {
    const data = JSON.parse(sessionStorage.getItem("wms-prefill"));
    if (data.type === props.billType) {
      sessionStorage.removeItem("wms-prefill");
      Object.assign(form, data, { id: null, version: null, bill_date: new Date().toISOString().slice(0, 10), warehouse_id: warehouses.value[0]?.id });
    } else if (fromPrefill) return;
  }
  visible.value = true;
}
async function take() {
  const detail = await http.get(`/api/contracts/${form.contract_id}`);
  form.party_name = detail.data.party_name;
  form.items = detail.data.items.filter((item) => Number(item.qty) > Number(item.settled_qty || 0)).map((item) => ({ ...item, qty: String(Number(item.qty) - Number(item.settled_qty || 0)) }));
}
async function save() {
  const payload = { ...form, type: props.billType };
  if (form.id) await http.put(`/api/wms-bills/${form.id}`, payload);
  else await http.post("/api/wms-bills", payload);
  visible.value = false;
  load();
}
async function remove(row) { await http.delete(`/api/wms-bills/${row.id}`, { params: { version: row.version } }); load(); }
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/wms-bills/batch-delete")) load();
}
function toCustoms(row) {
  router.push({ path: "/customs/materials", query: { wms_bill_id: row.id } });
}
onMounted(async () => {
  const direction = props.billType === "inbound" ? "supplier" : "customer";
  parties.value = (await http.get("/api/parties", { params: { type: direction, status: "启用", pageSize: 200 } })).data.items;
  warehouses.value = (await http.get("/api/warehouses", { params: { status: "启用", pageSize: 200 } })).data.items;
  await load();
  if (sessionStorage.getItem("wms-prefill")) open(null, true);
});
</script>
