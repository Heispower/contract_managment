<template>
  <el-button @click="run()">生成表单</el-button>
  <el-button v-if="zipApi" @click="run(null, true)">一键导出</el-button>
  <el-dialog v-model="visible" title="选择模板" width="640px" append-to-body :close-on-click-modal="false" @close="cancel">
    <p style="margin:0 0 12px">{{ partyWord }}：{{ partyText }}。请选择这份{{ partyWord }}要使用的模板。</p>
    <el-radio-group v-model="pick" style="display:flex;flex-direction:column;align-items:stretch;gap:10px">
      <el-radio v-for="item in choices" :key="item.id" :value="item.id" style="height:auto;align-items:flex-start;white-space:normal">
        <div>{{ item.title || item.doc_name }}<span style="color:var(--muted)">　{{ item.party_name || "不限客商" }}</span></div>
        <div style="color:var(--muted);font-size:12px">{{ item.template_path }}</div>
      </el-radio>
    </el-radio-group>
    <template #footer>
      <el-button @click="visible=false">取消</el-button>
      <el-button type="primary" @click="confirm">生成</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import http from "../api";

const props = defineProps({
  shell: Object,
  rows: { type: Array, default: () => [] },
  docCode: String,
  docName: String,
  partyWord: { type: String, default: "客商" },
  recordId: { type: Function, default: (row) => row.id },
  partyId: { type: Function, default: (row) => row.party_id },
  partyName: { type: Function, default: (row) => row.party_name || "" },
  fallbackName: { type: Function, default: (row) => "导出.docx" },
  zipApi: { type: String, default: "" },
  zipName: { type: Function, default: (row) => `${row.invoice_no || "导出"}.zip` },
});

const visible = ref(false);
const choices = ref([]);
const pick = ref(null);
const partyText = ref("");
let resolver = null;

function rowKey(row) {
  return row.id || `${row.order_id}-${row.material_code}`;
}

function chosen() {
  const set = props.shell?.selected || new Set();
  const hits = (props.rows || []).filter((row) => set.has(rowKey(row)));
  const unique = new Map();
  hits.forEach((row) => {
    const id = props.recordId(row);
    if (!unique.has(id)) unique.set(id, row);
  });
  return [...unique.values()];
}

function downloadName(res, fallback) {
  const raw = res.headers?.["x-download-name"] || "";
  if (!raw) return fallback;
  try { return decodeURIComponent(raw); } catch { return fallback; }
}

function choose(row, items) {
  const ranked = items.slice().sort((left, right) => {
    const score = (item) => {
      if (item.party_id && item.party_id === props.partyId(row)) return 0;
      if (!item.party_id) return 1;
      return 2;
    };
    return score(left) - score(right);
  });
  partyText.value = props.partyName(row) || "";
  choices.value = ranked;
  const matched = ranked.find((item) => item.party_id && item.party_id === props.partyId(row));
  pick.value = (matched || ranked[0]).id;
  visible.value = true;
  return new Promise((resolve) => { resolver = resolve; });
}

function confirm() {
  const resolve = resolver;
  resolver = null;
  visible.value = false;
  if (resolve) resolve(pick.value);
}

function cancel() {
  const resolve = resolver;
  resolver = null;
  if (resolve) resolve(null);
}

async function run(rowOverride = null, zip = false) {
  const rows = rowOverride ? [rowOverride] : chosen();
  if (rows.length !== 1) return ElMessage.warning(`请只勾选一张${props.docName}`);
  const row = rows[0];
  const listed = await http.get("/api/export-profiles", { params: { doc_code: props.docCode } });
  const items = (listed.data.items || []).filter((item) => item.template_path);
  if (!items.length) return ElMessage.warning(`请先在基础资料的导出模板里填写${props.docName}的模板绝对地址`);
  let templateId = items[0].id;
  if (items.length > 1) {
    templateId = await choose(row, items);
    if (!templateId) return;
  }
  const url = zip && props.zipApi
    ? `${props.zipApi}/${props.recordId(row)}/zip`
    : `/api/forms/${props.docCode}/${props.recordId(row)}/word`;
  const res = await http.get(url, {
    params: { template_id: templateId },
    responseType: "blob",
  });
  const fallback = zip ? props.zipName(row) : props.fallbackName(row);
  const fileUrl = URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = fileUrl;
  link.download = downloadName(res, fallback);
  link.click();
  URL.revokeObjectURL(fileUrl);
}

defineExpose({ generateRow: (row) => run(row, false), zipRow: (row) => run(row, true) });
</script>
