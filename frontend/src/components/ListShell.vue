<template>
  <div>
    <h2 v-if="!bare" class="page-title">
      <slot name="title">{{ title }}</slot>
    </h2>
    <div v-show="showSearch" class="card">
      <div class="filters">
        <slot name="filters" :expanded="expanded" />
        <el-button type="primary" :icon="Search" @click="$emit('query')">查询</el-button>
        <el-button :icon="Refresh" @click="$emit('reset')">重置</el-button>
        <el-button v-if="expandable" link type="primary" @click="expanded = !expanded">
          {{ expanded ? "收起" : "展开" }}
        </el-button>
      </div>
    </div>
    <div class="card toolbar">
      <div class="toolbar-left">
        <slot name="toolbar" />
      </div>
      <div class="toolbar-right">
        <span v-if="summary" v-html="summary" />
        <el-tooltip content="导出"><el-button :icon="Download" circle @click="exportFile" /></el-tooltip>
        <el-tooltip content="搜索区域"><el-button :icon="Search" circle @click="showSearch = !showSearch" /></el-tooltip>
        <el-tooltip content="刷新"><el-button :icon="Refresh" circle @click="$emit('query')" /></el-tooltip>
        <el-dropdown @command="setDensity">
          <el-button circle :icon="Operation" />
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="loose">宽松</el-dropdown-item>
              <el-dropdown-item command="medium">中等</el-dropdown-item>
              <el-dropdown-item command="compact">紧凑</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-popover placement="bottom" :width="340" trigger="click">
          <template #reference>
            <el-button circle :icon="Setting" />
          </template>
          <div class="col-panel">
            <el-button link type="primary" @click="resetCols">重置为默认</el-button>
            <div v-for="col in columnState" :key="col.key" class="col-row" :class="{ locked: col.fixed }">
              <span class="col-grip">⋮⋮</span>
              <el-checkbox v-model="col.show" :disabled="!!col.fixed" @change="saveCols" />
              <span class="col-name">{{ col.label }}</span>
              <button type="button" class="col-pin" :class="{ on: col.fixed }" :disabled="col.key === pinKey" @click="togglePin(col)" title="固定">📌</button>
              <el-button link :disabled="!!col.fixed" @click="move(col, -1)">上</el-button>
              <el-button link :disabled="!!col.fixed" @click="move(col, 1)">下</el-button>
            </div>
          </div>
        </el-popover>
      </div>
    </div>
    <div class="card table-card">
      <div class="table-scroll">
        <table class="data">
          <thead>
            <tr>
              <th class="sticky-left" style="width:42px"><el-checkbox :model-value="allChecked" @change="toggleAll" /></th>
              <th v-for="col in visibleCols" :key="col.key" :class="{ money: col.money, 'sticky-left': col.fixed === 'left' }" :style="{ minWidth: (col.width || 120) + 'px' }">{{ col.label }}</th>
              <th v-if="showOps" class="sticky-right" style="width:160px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id || row.order_id + row.material_code">
              <td class="sticky-left"><el-checkbox :model-value="selected.has(rowKey(row))" @change="(v) => toggle(row, v)" /></td>
              <td v-for="col in visibleCols" :key="col.key" :class="{ money: col.money, wrap: col.wrap, danger: col.danger && Number(String(row[col.key]).replace(/,/g,'')) > 0, 'sticky-left': col.fixed === 'left' }">
                <span v-if="col.tag" :class="['tag', col.tone || tagClass(row[col.key])]">{{ row[col.key] || "—" }}</span>
                <span v-else-if="col.money">{{ money(row[col.key]) }}</span>
                <span v-else-if="col.kind === 'percent'" class="pct" :style="{ '--p': percentFill(row[col.key]) }"><i /><em>{{ row[col.key] || "0%" }}</em></span>
                <span v-else-if="col.kind === 'link'" class="cell-link" :class="col.tone" @click="emit('cell', { key: col.key, row })">
                  <span v-if="col.key === 'contract_code' && row.nature === 'supplement'" class="sup-mark">补</span>{{ row[col.key] || "—" }}
                </span>
                <template v-else>{{ row[col.key] || "" }}</template>
              </td>
              <td v-if="showOps" class="sticky-right">
                <slot name="ops" :row="row" />
              </td>
            </tr>
            <tr v-if="!rows.length"><td :colspan="visibleCols.length + 1 + (showOps ? 1 : 0)" style="text-align:center;color:#86909c">暂无数据</td></tr>
          </tbody>
          <tfoot v-if="hasSums">
            <tr class="sum-row">
              <td class="sticky-left sticky-sum"></td>
              <td v-for="(col, index) in visibleCols" :key="col.key" :class="{ money: col.money, 'sticky-sum': true, danger: col.danger && Number(String(sums[col.key] || 0).replace(/,/g,'')) > 0 }">
                <template v-if="index === 0">合计</template>
                <template v-else-if="sums[col.key] != null">{{ col.money || col.danger ? money(sums[col.key]) : sums[col.key] }}</template>
              </td>
              <td v-if="showOps" class="sticky-right sticky-sum"></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div class="foot">
        <div class="foot-sum"></div>
        <div style="display:flex;align-items:center;gap:8px">
          <span>第 {{ from }}-{{ to }} 条/总共 {{ total }} 条</span>
          <el-pagination
            background
            layout="prev, pager, next, sizes"
            :total="total"
            :page-size="pageSize"
            :current-page="page"
            :page-sizes="[20, 50, 100]"
            @current-change="$emit('page', $event)"
            @size-change="$emit('size', $event)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { Download, Operation, Refresh, Search, Setting } from "@element-plus/icons-vue";
import { money, downloadExport } from "../api";

const props = defineProps({
  title: String,
  columns: Array,
  rows: Array,
  total: Number,
  page: Number,
  pageSize: Number,
  sums: { type: Object, default: () => ({}) },
  summary: String,
  storageKey: String,
  startExpanded: Boolean,
  expandable: { type: Boolean, default: true },
  exportModule: String,
  exportQuery: { type: Object, default: () => ({}) },
  bare: Boolean,
  showOps: { type: Boolean, default: true },
});
const emit = defineEmits(["query", "reset", "page", "size", "export", "select", "cell"]);
const expanded = ref(!!props.startExpanded);
const showSearch = ref(true);
const selected = ref(new Set());
const columnState = ref([]);

function loadCols() {
  const fresh = (props.columns || []).map((col) => ({ ...col, show: col.show !== false }));
  const saved = props.storageKey ? localStorage.getItem("cols:" + props.storageKey) : null;
  if (!saved) {
    columnState.value = fresh;
    return;
  }
  let old = [];
  try { old = JSON.parse(saved); } catch { old = []; }
  const merged = [];
  const seen = new Set();
  for (const col of old) {
    const current = fresh.find((item) => item.key === col.key);
    if (!current) continue;
    merged.push({ ...current, show: current.fixed ? true : col.show !== false });
    seen.add(col.key);
  }
  for (const col of fresh) {
    if (!seen.has(col.key)) merged.push(col);
  }
  columnState.value = merged;
}
watch(() => props.columns, loadCols, { immediate: true });
function saveCols() {
  if (props.storageKey) localStorage.setItem("cols:" + props.storageKey, JSON.stringify(columnState.value));
}
function resetCols() {
  localStorage.removeItem("cols:" + props.storageKey);
  loadCols();
}
function move(col, dir) {
  if (col.fixed) return;
  const list = columnState.value;
  const index = list.indexOf(col);
  const next = index + dir;
  if (next < 0 || next >= list.length || list[next].fixed) return;
  list.splice(index, 1);
  list.splice(next, 0, col);
  saveCols();
}
const visibleCols = computed(() => columnState.value.filter((col) => col.show));
const hasSums = computed(() => Object.keys(props.sums || {}).length > 0);
const pinKey = computed(() => columnState.value.find((col) => col.fixed)?.key || "");
function togglePin(col) {
  if (col.key === pinKey.value && col.fixed) return;
  col.fixed = col.fixed ? undefined : "left";
  if (col.fixed) col.show = true;
  saveCols();
}
const from = computed(() => (props.total ? (props.page - 1) * props.pageSize + 1 : 0));
const to = computed(() => Math.min(props.page * props.pageSize, props.total || 0));
function rowKey(row) {
  return row.id || `${row.order_id}-${row.material_code}`;
}
const allChecked = computed(() => props.rows.length > 0 && props.rows.every((row) => selected.value.has(rowKey(row))));
function toggleAll(value) {
  const next = new Set(selected.value);
  props.rows.forEach((row) => (value ? next.add(rowKey(row)) : next.delete(rowKey(row))));
  selected.value = next;
  emit("select");
}
function toggle(row, value) {
  const next = new Set(selected.value);
  value ? next.add(rowKey(row)) : next.delete(rowKey(row));
  selected.value = next;
  emit("select");
}
function setDensity(mode) {
  document.documentElement.classList.remove("density-loose", "density-compact");
  if (mode === "loose") document.documentElement.classList.add("density-loose");
  if (mode === "compact") document.documentElement.classList.add("density-compact");
  localStorage.setItem("density", mode);
}
const savedDensity = localStorage.getItem("density") || "medium";
if (savedDensity !== "medium") setDensity(savedDensity);

function percentFill(value) {
  const text = String(value ?? "");
  const frac = text.match(/^(\d+)\/(\d+)$/);
  if (!frac) return text || "0%";
  const total = Number(frac[2]);
  return total ? `${Math.min(100, Math.round((Number(frac[1]) / total) * 100))}%` : "0%";
}
function csvCell(value) {
  const text = value == null ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}
function exportPayload() {
  const chosen = props.rows.filter((row) => selected.value.has(rowKey(row)));
  const cols = visibleCols.value.map((col) => ({ key: col.key, label: col.label }));
  const query = { ...(props.exportQuery || {}) };
  Object.keys(query).forEach((key) => {
    if (query[key] === "" || query[key] == null) delete query[key];
  });
  return {
    ...query,
    title: props.title || "",
    columns: cols,
    ids: chosen.map((row) => rowKey(row)),
  };
}
async function exportFile() {
  emit("export");
  if (props.exportModule) {
    await downloadExport(props.exportModule, exportPayload(), `${props.title || "导出"}.xlsx`);
    return;
  }
  exportCsv();
}
function exportCsv() {
  const chosen = props.rows.filter((row) => selected.value.has(rowKey(row)));
  const data = chosen.length ? chosen : props.rows;
  const cols = visibleCols.value;
  const lines = [cols.map((col) => csvCell(col.label)).join(",")];
  data.forEach((row) => lines.push(cols.map((col) => csvCell(row[col.key])).join(",")));
  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${props.title || "导出"}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}
function tagClass(text) {
  if (["已签订", "启用", "进行中", "未关闭"].includes(text)) return "tag-blue";
  if (["固定总价"].includes(text)) return "tag-blue-soft";
  if (["按实结算"].includes(text)) return "tag-purple";
  if (["采购合同", "销售合同", "材料采购", "产品销售", "服务合同"].includes(text) || (text && text.endsWith("合同") && !["未签订", "已签订", "已终止"].includes(text))) return "tag-orange";
  if (["已终止", "停用", "逾期", "有逾期", "有欠款", "未关联", "无发票号"].includes(text)) return "tag-red";
  if (["已归档", "已完成", "已关闭", "已收清", "已付清", "已收到", "已收票", "已开票", "已到货", "已发货", "采购完毕", "已生成", "已报关"].includes(text)) return "tag-green";
  if (["未归档", "未签订", "未付", "未收", "未收票", "未开票", "未到货", "未发货", "无发票", "未生成", "未报关"].includes(text)) return "tag-gray";
  if (["部分付款", "部分收款", "部分收票", "部分开票", "部分到货", "部分发货", "部分", "待采购", "特殊申报"].includes(text)) return "tag-orange";
  if (["已关联", "已关联报关要素", "已检查", "已导出"].includes(text)) return "tag-green";
  return "tag-gray";
}
defineExpose({ selected, expanded, exportCsv, exportFile });
</script>
