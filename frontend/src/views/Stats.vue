<template>
  <div>
    <h2 class="page-title">{{ title }}</h2>
    <div v-if="mode==='overview'" class="cards">
      <div v-for="(val, key) in cards" :key="key" class="stat"><div class="label">{{ key }}</div><div class="value">{{ money(val) }}</div></div>
    </div>
    <ListShell v-else :title="title" :storage-key="mode" :columns="columns" :rows="rows" :total="rows.length" :page="1" :page-size="50" :export-module="mode==='customer' ? 'stats-customer' : 'stats-supplier'" :export-query="{ keyword }" @query="load" @reset="keyword='';load()">
      <template #filters><el-input v-model="keyword" placeholder="名称" style="width:200px" /></template>
      <template #ops><span /></template>
    </ListShell>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import http, { money } from "../api";
import ListShell from "../components/ListShell.vue";

const props = defineProps({ mode: String });
const title = computed(() => ({ overview: "经营概况", customer: "客户统计", supplier: "供应商统计" }[props.mode]));
const cards = ref({});
const rows = ref([]);
const keyword = ref("");
const columns = [
  { key: "name", label: "名称", fixed: "left" },
  { key: "count", label: "合同数量" },
  { key: "amount", label: "合同金额", money: true },
  { key: "settled", label: "已收 / 已付", money: true },
  { key: "status", label: "状态", tag: true },
];
async function load() {
  if (props.mode === "overview") {
    cards.value = (await http.get("/api/stats/overview")).data.cards;
  } else {
    rows.value = (await http.get(`/api/stats/${props.mode}`, { params: { keyword: keyword.value } })).data;
  }
}
onMounted(load);
</script>
