<template>
  <ListShell ref="shell" title="到期提醒" storage-key="reminder" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :expandable="false" @query="search" @reset="reset" @page="(value) => { page = value; load(); }" @size="(value) => { pageSize = value; page = 1; load(); }">
    <template #filters>
      <el-radio-group v-model="tab" @change="search">
        <el-radio-button value="sale">销售合同到期 {{ counts.sale || 0 }}</el-radio-button>
        <el-radio-button value="purchase">采购合同到期 {{ counts.purchase || 0 }}</el-radio-button>
        <el-radio-button value="output">销项发票到期 {{ counts.output || 0 }}</el-radio-button>
        <el-radio-button value="input">进项发票到期 {{ counts.input || 0 }}</el-radio-button>
      </el-radio-group>
      <el-input v-model="keyword" clearable placeholder="单据编号 / 名称" style="width:220px" @keyup.enter="search" />
      <el-select v-model="status" clearable placeholder="状态" style="width:140px">
        <el-option label="未处理" value="未处理" /><el-option label="已确认" value="已确认" /><el-option label="已忽略" value="已忽略" />
      </el-select>
    </template>
    <template #toolbar>
      <el-button @click="check">检查提醒</el-button>
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="view(row)">查看</span>
      <span class="ops" style="margin-left:8px" @click="mark(row, 'confirmed')">确认</span>
      <span class="ops" style="margin-left:8px" @click="mark(row, 'ignored')">忽略</span>
    </template>
  </ListShell>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import http from "../api";
import ListShell from "../components/ListShell.vue";

const tab = ref("sale");
const keyword = ref("");
const status = ref("");
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const counts = ref({});
const columns = [
  { key: "biz_code", label: "单据编号", fixed: "left" },
  { key: "name", label: "单据名称" },
  { key: "type_name", label: "类型" },
  { key: "party_name", label: "客商名称" },
  { key: "amount", label: "金额", money: true },
  { key: "biz_status", label: "业务状态" },
  { key: "due_date", label: "到期日期" },
  { key: "remain_days", label: "剩余天数" },
  { key: "status", label: "状态", tag: true },
];
function search() {
  page.value = 1;
  load();
}
function reset() {
  keyword.value = "";
  status.value = "";
  page.value = 1;
  load();
}
async function load() {
  const res = await http.get("/api/reminders", { params: { tab: tab.value, keyword: keyword.value, status: status.value, page: page.value, pageSize: pageSize.value } });
  rows.value = (res.data.items || []).map((row) => ({ ...row, id: `${row.biz_type}-${row.biz_code}` }));
  total.value = res.data.total;
  counts.value = res.data.counts || {};
}
async function check() {
  await http.post("/api/reminders/check");
  load();
}
function view(row) {
  ElMessage.info(`${row.biz_code} ${row.name} 到期 ${row.due_date}`);
}
async function mark(row, statusValue) {
  await http.post("/api/reminders/mark", { biz_type: row.biz_type, biz_code: row.biz_code, direction: row.direction, status: statusValue });
  load();
}
onMounted(load);
</script>
