<template>
  <el-dialog v-model="visible" fullscreen :show-close="false" :close-on-click-modal="false" class="import-dialog" append-to-body>
    <div class="import-page">
      <h2 class="import-title">{{ meta.title }}</h2>
      <div class="steps">
        <div v-for="(item, index) in steps" :key="item.title" class="step" :class="{ on: step === index, done: step > index }">
          <div class="dot">{{ index + 1 }}</div>
          <div>{{ item.title }}</div>
          <div class="sub">{{ item.desc }}</div>
        </div>
      </div>

      <div v-if="meta.modes.length" class="card" style="margin-top:16px">
        <el-radio-group v-model="mode" :disabled="step > 0">
          <el-radio v-for="item in meta.modes" :key="item.value" :value="item.value">{{ item.label }}</el-radio>
        </el-radio-group>
      </div>

      <div v-if="step <= 1" class="import-grid">
        <div class="card">
          <h3>1. 下载模板</h3>
          <div class="hint"><el-icon><InfoFilled /></el-icon><span>{{ meta.hint }}</span></div>
          <el-button type="primary" @click="download"><el-icon><Download /></el-icon>{{ meta.template }}</el-button>
        </div>
        <div class="card">
          <h3>2. 上传文件</h3>
          <el-button :loading="step === 1" @click="pick">选择 Excel 文件</el-button>
          <div class="import-note">支持 .xlsx 和 .xls 格式，文件大小不超过 10MB。</div>
          <input ref="fileRef" type="file" accept=".xlsx,.xls" hidden @change="onFile" />
        </div>
      </div>

      <div v-if="step === 2" class="card" style="margin-top:16px">
        <h3>预览数据</h3>
        <el-alert v-if="parsed.batch_error" :title="parsed.batch_error" type="error" show-icon style="margin-bottom:12px" />
        <el-table :data="parsed.rows" max-height="460">
          <el-table-column prop="row_no" label="行号" width="80" />
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag :type="row.ok ? 'success' : 'danger'">{{ row.ok ? "可导入" : "失败" }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="summary" label="内容" min-width="240" />
          <el-table-column prop="message" label="说明" min-width="220" />
        </el-table>
        <div class="import-actions">
          <el-button type="primary" @click="run">确认导入</el-button>
          <el-button @click="close">返回列表</el-button>
        </div>
      </div>

      <div v-if="step === 3" class="card" style="margin-top:16px">正在导入</div>

      <div v-if="step === 4" class="card" style="margin-top:16px">
        <el-result icon="success" title="导入完成" :sub-title="`成功 ${result.success} 条，失败 ${result.fail} 条`">
          <template #extra>
            <el-button type="primary" @click="close">返回列表</el-button>
            <el-button @click="again">再次导入</el-button>
          </template>
        </el-result>
        <el-table v-if="result.errors && result.errors.length" :data="result.errors" max-height="280">
          <el-table-column prop="row_no" label="行号" width="80" />
          <el-table-column prop="message" label="说明" />
        </el-table>
      </div>

      <div v-if="step === 0" class="import-actions">
        <el-button @click="close">返回列表</el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Download, InfoFilled } from "@element-plus/icons-vue";
import http from "../api";

const props = defineProps({
  modelValue: Boolean,
  module: String,
  direction: { type: String, default: "" },
  partyType: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue", "done"]);

const steps = [
  { title: "上传文件", desc: "选择 Excel 文件" },
  { title: "解析数据", desc: "解析文件内容" },
  { title: "预览数据", desc: "确认导入数据" },
  { title: "执行导入", desc: "保存到数据库" },
  { title: "完成", desc: "导入完成" },
];

const step = ref(0);
const mode = ref("");
const parsed = ref(null);
const result = ref(null);
const fileRef = ref(null);

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const meta = computed(() => describe(props.module, props.direction, props.partyType));

watch(() => props.modelValue, (open) => {
  if (!open) return;
  step.value = 0;
  parsed.value = null;
  result.value = null;
  mode.value = meta.value.modes[0]?.value || meta.value.defaultMode;
});

function describe(module, direction, partyType) {
  if (module === "contract") {
    const purchase = direction !== "sale";
    return {
      title: purchase ? "采购合同导入" : "销售合同导入",
      hint: purchase ? "请下载采购合同导入模板填写后上传。须填写供应商编码。" : "请下载销售合同导入模板填写后上传。须填写客户编码。",
      template: purchase ? "下载采购合同导入模板" : "下载销售合同导入模板",
      file: purchase ? "采购合同导入模板.xlsx" : "销售合同导入模板.xlsx",
      defaultMode: "overwrite",
      modes: [
        { value: "overwrite", label: "覆盖现有物料" },
        { value: "append", label: "追加到现有物料后面" },
      ],
    };
  }
  if (module === "invoice") {
    const incoming = direction !== "output";
    return {
      title: incoming ? "进项发票导入" : "销项发票导入",
      hint: incoming ? "请下载进项发票导入模板填写后上传。须填写供应商编码、发票号码。" : "请下载销项发票导入模板填写后上传。须填写客户编码、发票号码。",
      template: incoming ? "下载进项发票导入模板" : "下载销项发票导入模板",
      file: incoming ? "进项发票导入模板.xlsx" : "销项发票导入模板.xlsx",
      defaultMode: "create",
      modes: [],
    };
  }
  if (module === "settle") {
    const receipt = direction === "receipt";
    return {
      title: receipt ? "收款单导入" : "付款单导入",
      hint: receipt ? "请下载收款单导入模板填写后上传。须填写合同编号和阶段。" : "请下载付款单导入模板填写后上传。须填写合同编号和阶段。",
      template: receipt ? "下载收款单导入模板" : "下载付款单导入模板",
      file: receipt ? "收款单导入模板.xlsx" : "付款单导入模板.xlsx",
      defaultMode: "create",
      modes: [],
    };
  }
  if (module === "party") {
    const supplier = partyType !== "customer";
    return {
      title: supplier ? "供应商导入" : "客户导入",
      hint: supplier ? "请下载供应商导入模板填写后上传。须填写供应商编码和供应商名称。" : "请下载客户导入模板填写后上传。须填写客户编码和客户名称。",
      template: supplier ? "下载供应商导入模板" : "下载客户导入模板",
      file: supplier ? "供应商导入模板.xlsx" : "客户导入模板.xlsx",
      defaultMode: "update",
      modes: [],
    };
  }
  if (module === "warehouse-receipt") {
    return {
      title: "报关物料导入",
      hint: "请下载模板填写后上传。全部校验通过后写入报关物料清单。",
      template: "下载报关物料导入模板",
      file: "报关物料导入模板.xlsx",
      defaultMode: "create",
      modes: [],
    };
  }
  if (module === "customs-material-fill") {
    return {
      title: "报关物料批量导入",
      hint: "按物料编号匹配已有报关物料，填写产地、箱号、尺寸（长*宽*高）、净重、毛重、体积、出发港等。同一编号有多条时，可再填入仓单号指定其中一条；不填则全部更新。空白单元格不会覆盖原值。",
      template: "下载报关物料批量导入模板",
      file: "报关物料批量导入模板.xlsx",
      defaultMode: "update",
      modes: [],
    };
  }
  if (module === "hs-code") {
    return {
      title: "HS Code 导入",
      hint: "请下载 HS Code 导入模板填写后上传。存在错误行时整批不会导入。",
      template: "下载HS Code导入模板",
      file: "HS Code导入模板.xlsx",
      defaultMode: "create",
      modes: [],
    };
  }
  if (module === "number-contract") {
    return {
      title: "合同编号导入",
      hint: "下载模板填写后上传，也可直接上传表头含「合同号」的统计表。合同编号按原样保存；符合现行规则的编号会占用顺序号，已存在的编号会跳过。",
      template: "下载合同编号导入模板",
      file: "合同编号导入模板.xlsx",
      defaultMode: "create",
      modes: [],
    };
  }
  if (module === "number-invoice") {
    return {
      title: "发票编号导入",
      hint: "下载模板填写后上传，也可直接上传表头含「发票号」的登记表。以 -001 结尾的分单号会归入同一批次，已存在的发票号会跳过。",
      template: "下载发票编号导入模板",
      file: "发票编号导入模板.xlsx",
      defaultMode: "create",
      modes: [],
    };
  }
  if (module === "purchase-plan") {
    return {
      title: "采购计划导入",
      hint: "请下载采购计划导入模板填写后上传。须填写物料编号和采购数量。",
      template: "下载采购计划导入模板",
      file: "采购计划导入模板.xlsx",
      defaultMode: "update",
      modes: [
        { value: "update", label: "按物料编号更新" },
        { value: "replace", label: "清空后重新导入" },
        { value: "append", label: "追加" },
      ],
    };
  }
  return {
    title: "商品导入",
    hint: "请下载商品导入模板填写后上传。须填写物料编号和名称。",
    template: "下载商品导入模板",
    file: "商品导入模板.xlsx",
    defaultMode: "update",
    modes: [],
  };
}

async function download() {
  const res = await http.get(`/api/import/${props.module}/template`, {
    params: { direction: props.direction || "", party_type: props.partyType || "" },
    responseType: "blob",
  });
  const url = URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = meta.value.file;
  link.click();
  URL.revokeObjectURL(url);
}

function pick() {
  fileRef.value && fileRef.value.click();
}

async function onFile(event) {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const name = file.name.toLowerCase();
  if (!name.endsWith(".xlsx") && !name.endsWith(".xls")) {
    ElMessageBox.alert("文件格式不正确，请上传 xlsx 或 xls 文件。", "提示", { type: "error", confirmButtonText: "确定", closeOnClickModal: false });
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessageBox.alert("文件大小超过限制，不能超过 10MB。", "提示", { type: "error", confirmButtonText: "确定", closeOnClickModal: false });
    return;
  }
  const body = new FormData();
  body.append("file", file);
  body.append("mode", mode.value || meta.value.defaultMode);
  body.append("direction", props.direction || "");
  body.append("party_type", props.partyType || "");
  step.value = 1;
  try {
    const res = await http.post(`/api/import/${props.module}/parse`, body);
    parsed.value = res.data;
    step.value = 2;
  } catch (err) {
    step.value = 0;
  }
}

async function run() {
  step.value = 3;
  try {
    const res = await http.post(`/api/import/${props.module}/execute`, {
      file_hash: parsed.value.file_hash,
      mode: mode.value || meta.value.defaultMode,
      direction: props.direction || "",
      party_type: props.partyType || "",
      rows: parsed.value.rows,
      locks: parsed.value.locks || [],
    });
    result.value = res.data;
    if (res.data.need_name_sync && res.data.party_ids && res.data.party_ids.length) {
      try {
        await ElMessageBox.confirm("是否同步更新引用此客商的单据？", "提示", {
          confirmButtonText: "确定",
          cancelButtonText: "取消",
          type: "warning",
        });
        await http.post("/api/parties/sync-names", { ids: res.data.party_ids });
      } catch (err) {
        /* 取消则保持旧快照 */
      }
    }
    step.value = 4;
    emit("done");
  } catch (err) {
    step.value = 2;
  }
}

function again() {
  step.value = 0;
  parsed.value = null;
  result.value = null;
}

function close() {
  visible.value = false;
  emit("done");
}
</script>
