<template>
  <div class="attach-box">
    <div class="toolbar-left" style="margin-bottom:8px">
      <el-button size="small" type="primary" @click="pick">上传附件</el-button>
      <input ref="fileRef" type="file" multiple hidden @change="onFile" />
    </div>
    <el-table :data="rows" size="small" empty-text="暂无附件">
      <el-table-column prop="file_name" label="文件名" min-width="180" />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column prop="file_size" label="大小" width="90">
        <template #default="{ row }">{{ sizeText(row.file_size) }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="上传时间" width="160" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <span class="ops" @click="preview(row)">预览</span>
          <span class="ops" style="margin-left:8px" @click="download(row)">下载</span>
          <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="previewVisible" title="预览" width="720px" append-to-body>
      <img v-if="previewKind === 'image'" :src="previewUrl" style="max-width:100%" />
      <iframe v-else-if="previewKind === 'pdf'" :src="previewUrl" style="width:100%;height:70vh;border:0" />
      <div v-else>该类型请下载后查看</div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import http, { downloadBlob } from "../api";

const props = defineProps({
  businessType: { type: String, required: true },
  businessId: { type: [Number, String], default: null },
});

const rows = ref([]);
const fileRef = ref(null);
const previewVisible = ref(false);
const previewUrl = ref("");
const previewKind = ref("");

async function load() {
  if (!props.businessId) {
    rows.value = [];
    return;
  }
  const res = await http.get("/api/files", { params: { business_type: props.businessType, business_id: props.businessId } });
  rows.value = res.data || [];
}
function pick() {
  if (!props.businessId) {
    ElMessage.warning("请先保存单据再上传附件");
    return;
  }
  fileRef.value && fileRef.value.click();
}
async function onFile(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  for (const file of files) {
    const body = new FormData();
    body.append("file", file);
    body.append("business_type", props.businessType);
    body.append("business_id", String(props.businessId));
    await http.post("/api/files", body);
  }
  ElMessage.success("已上传");
  load();
}
function sizeText(value) {
  const num = Number(value || 0);
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
  return `${(num / 1024 / 1024).toFixed(1)} MB`;
}
async function preview(row) {
  const res = await http.get(`/api/files/${row.id}/download`, { responseType: "blob" });
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = URL.createObjectURL(res.data);
  const type = (row.file_type || "").toLowerCase();
  previewKind.value = [".png", ".jpg", ".jpeg", ".gif", ".webp"].includes(type) ? "image" : type === ".pdf" ? "pdf" : "other";
  previewVisible.value = true;
}
async function download(row) {
  await downloadBlob(`/api/files/${row.id}/download`, row.file_name);
}
async function remove(row) {
  await http.delete(`/api/files/${row.id}`);
  load();
}
watch(() => props.businessId, load);
onMounted(load);
</script>
