<template>
  <div>
    <ListShell title="供应商往来统计" storage-key="supplier-summary" :columns="supplierColumns" :rows="suppliers" :total="suppliers.length" :page="1" :page-size="Math.max(suppliers.length, 1)" :expandable="false" :show-ops="false" @query="load()" @reset="load()" @cell="pick">
      <template #filters>
        <span style="color:var(--muted)">点击供应商名称查看下面的合同</span>
      </template>
    </ListShell>
    <ListShell bare title="合同明细" storage-key="supplier-contracts" :columns="contractColumns" :rows="contracts" :total="contracts.length" :page="1" :page-size="Math.max(contracts.length, 1)" :expandable="false" :show-ops="false" @query="load(partyId)" @reset="partyId = null; load()">
      <template #filters>
        <span v-if="!partyId" style="color:var(--muted)">请先选择供应商</span>
      </template>
    </ListShell>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import http from "../api";
import ListShell from "../components/ListShell.vue";

const suppliers = ref([]);
const contracts = ref([]);
const partyId = ref(null);
const supplierColumns = [
  { key: "name", label: "供应商名称", fixed: "left", kind: "link" },
  { key: "amount", label: "采购金额", money: true },
  { key: "paid", label: "已付款", money: true },
  { key: "unpaid", label: "未付款", money: true },
  { key: "debt", label: "欠款", tag: true },
  { key: "overdue", label: "是否有逾期", tag: true },
  { key: "count", label: "合同数量" },
];
const contractColumns = [
  { key: "contract_code", label: "合同编号", fixed: "left" },
  { key: "name", label: "合同名称" },
  { key: "amount", label: "合同金额", money: true },
  { key: "paid", label: "已付款", money: true },
  { key: "unpaid", label: "未付款", money: true },
  { key: "pay_status", label: "付款状态", tag: true },
  { key: "overdue", label: "逾期状态", tag: true },
  { key: "sign_date", label: "签订日期" },
  { key: "stages_text", label: "阶段付款信息", width: 320, wrap: true },
];
async function load(id) {
  const res = await http.get("/api/supplier-detail", { params: { party_id: id || "" } });
  suppliers.value = (res.data.suppliers || []).map((row) => ({ ...row, id: row.party_id }));
  contracts.value = (res.data.contracts || []).map((row) => ({
    ...row,
    stages_text: (row.stages || []).map((stage) => `${stage.name} ${stage.plan_date} 已付 ${stage.paid} 未付 ${stage.unpaid}`).join("；"),
  }));
}
function pick(event) {
  if (!event?.row) return;
  partyId.value = event.row.party_id;
  load(event.row.party_id);
}
onMounted(() => load());
</script>
