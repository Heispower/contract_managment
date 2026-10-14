<template>
  <ListShell ref="shell" :title="title" :storage-key="'pending-'+direction" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :summary="summary" export-module="pending" :export-query="{ direction, months: months.join(','), party_id: partyId }" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}" @select="syncPick">
    <template #filters>
      <el-select v-model="months" multiple collapse-tags placeholder="月份" style="width:280px">
        <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value" />
      </el-select>
      <el-select v-model="partyId" clearable :placeholder="direction==='purchase'?'供应商':'客户'" style="width:180px">
        <el-option v-for="p in parties" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
    </template>
    <template #ops><span /></template>
  </ListShell>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import http, { money } from "../api";
import ListShell from "../components/ListShell.vue";

const props = defineProps({ direction: String });
const title = computed(() => (props.direction === "purchase" ? "待付款" : "待收款"));
const monthOptions = computed(() => props.direction === "purchase"
  ? [["this", "本月未付"], ["next", "下月未付"], ["m2", "未来2月"], ["m3", "未来3月"], ["m4", "未来4月"], ["m5", "未来5月"], ["later", "半年后"]].map(([value, label]) => ({ value, label }))
  : [["this", "本月未收"], ["next", "下月未收"], ["m2", "未来2月"], ["m3", "未来3月"], ["m4", "未来4月"], ["m5", "未来5月"], ["later", "半年后"]].map(([value, label]) => ({ value, label })));
const columns = computed(() => [
  { key: "contract_code", label: "合同编号", fixed: "left" },
  { key: "name", label: "合同名称" },
  { key: "party_name", label: props.direction === "purchase" ? "供应商" : "客户" },
  { key: "balance", label: "余额", money: true, danger: true },
  { key: "detail", label: props.direction === "purchase" ? "付款详情" : "收款详情", width: 260, wrap: true },
  { key: "remark", label: "备注", width: 180, wrap: true },
  { key: "overdue", label: "逾期", tag: true },
]);
const shell = ref(null);
const rows = ref([]);
const selectedRows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const months = ref([]);
const partyId = ref(null);
const parties = ref([]);
const totalHint = ref("");
const summary = computed(() => totalHint.value || `选中${props.direction === "purchase" ? "待付" : "待收"}累计：￥${money(pickedAmount(selectedRows.value, "balance"))}`);
async function load() {
  const res = await http.get("/api/pending", { params: { direction: props.direction, months: months.value.join(","), party_id: partyId.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items;
  total.value = res.data.total;
  const info = res.data.summary || {};
  totalHint.value = info.amount != null ? `${info.label || ""}金额合计：<span class="sum-link">${money(info.amount)}</span>　阶段 ${info.stage_count || 0} 条` : "";
  syncPick();
}
function pickedAmount(list, key) {
  return (list || []).reduce((sum, row) => {
    const num = Number(String(row?.[key] ?? 0).replace(/,/g, ""));
    return sum + (Number.isFinite(num) ? num : 0);
  }, 0);
}
function syncPick() {
  const set = shell.value?.selected || new Set();
  selectedRows.value = rows.value.filter((row) => set.has(row.id));
}
function reset() { months.value = []; partyId.value = null; load(); }
onMounted(async () => {
  parties.value = (await http.get("/api/parties", { params: { type: props.direction === "purchase" ? "supplier" : "customer", pageSize: 200 } })).data.items;
  load();
});
</script>
