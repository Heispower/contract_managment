<template>
  <ListShell ref="shell" :title="cfg.title" :storage-key="kind" :columns="cfg.columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :summary="summary" :start-expanded="kind === 'project'" :export-module="exportModule" :export-query="exportQuery" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}">
    <template #filters="{ expanded }">
      <template v-if="kind === 'project'">
        <label class="filter-item"><span>关键字：</span><el-input v-model="keyword" clearable placeholder="请输入关键字" style="width:180px" /></label>
        <label class="filter-item"><span>项目类型</span>
          <el-select v-model="projectType" clearable placeholder="请选择" style="width:150px">
            <el-option v-for="item in projectFacets.types" :key="item" :label="item" :value="item" />
          </el-select>
        </label>
        <label class="filter-item"><span>项目来源</span>
          <el-select v-model="projectSource" clearable placeholder="请选择" style="width:150px">
            <el-option v-for="item in projectFacets.sources" :key="item" :label="item" :value="item" />
          </el-select>
        </label>
        <label class="filter-item"><span>项目年份</span>
          <el-select v-model="projectYear" clearable placeholder="请选择" style="width:130px">
            <el-option v-for="item in projectFacets.years" :key="item" :label="item" :value="item" />
          </el-select>
        </label>
        <label class="filter-item"><span>状态</span>
          <el-select v-model="projectStatus" clearable placeholder="请选择" style="width:130px">
            <el-option v-for="item in projectFacets.statuses" :key="item" :label="item" :value="item" />
          </el-select>
        </label>
        <template v-if="expanded">
          <label class="filter-item"><span>客户</span>
            <el-select v-model="projectCustomer" clearable filterable placeholder="请选择" style="width:180px">
              <el-option v-for="item in projectFacets.customers" :key="item" :label="item" :value="item" />
            </el-select>
          </label>
          <label class="filter-item"><span>开始日期</span>
            <el-date-picker v-model="projectStart" value-format="YYYY-MM-DD" placeholder="请选择日期" style="width:160px" />
          </label>
          <label class="filter-item"><span>结束日期</span>
            <el-date-picker v-model="projectEnd" value-format="YYYY-MM-DD" placeholder="请选择日期" style="width:160px" />
          </label>
        </template>
      </template>
      <el-input v-else v-model="keyword" placeholder="关键字" style="width:220px" />
      <template v-if="kind === 'plan'">
        <el-input v-model="planMonth" clearable placeholder="计划月份" style="width:160px" />
        <el-input v-model="planName" clearable placeholder="中文名称" style="width:180px" />
        <el-select v-model="planState" clearable placeholder="是否采购" style="width:140px">
          <el-option label="待采购" value="待采购" />
          <el-option label="采购完毕" value="采购完毕" />
        </el-select>
      </template>
    </template>
    <template #toolbar>
      <el-button v-if="cfg.create" type="primary" @click="open()">{{ cfg.create }}</el-button>
      <el-button v-if="kind === 'plan'" @click="showImport = true">导入</el-button>
      <el-button v-if="kind === 'hs'" @click="showImport = true">导入</el-button>
      <el-button v-if="cfg.remove" @click="removeMany">批量删除</el-button>
      <el-button v-if="kind === 'security' && isAdmin" type="danger" @click="wipeAll">清空全部数据</el-button>
    </template>
    <template #ops="{ row }">
      <span v-if="cfg.edit" class="ops" @click="open(row)">编辑</span>
      <el-popconfirm v-if="cfg.remove" title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="visible" :title="cfg.title" width="560px">
    <el-form label-width="100px">
      <el-form-item v-for="field in cfg.fields" :key="field.key" :label="field.label">
        <el-select v-if="field.options" v-model="form[field.key]" style="width:100%">
          <el-option v-for="op in field.options" :key="op" :label="op" :value="op" />
        </el-select>
        <el-select v-else-if="field.lookup" v-model="form[field.key]" style="width:100%">
          <el-option v-for="op in lookups[field.lookup]" :key="op.id" :label="op.name" :value="op.id" />
        </el-select>
        <el-date-picker v-else-if="field.date" v-model="form[field.key]" value-format="YYYY-MM-DD" placeholder="请选择日期" style="width:100%" />
        <el-input v-else v-model="form[field.key]" :disabled="field.disabled && !!form.id" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible=false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
  <ImportWizard v-if="kind === 'plan'" v-model="showImport" module="purchase-plan" @done="load" />
  <ImportWizard v-if="kind === 'hs'" v-model="showImport" module="hs-code" @done="load" />
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";

const props = defineProps({ kind: String });
const catalogs = {
  project: { title: "项目", api: "/api/projects", create: "新增项目", edit: true, remove: true, columns: [
    { key: "project_code", label: "项目编号", fixed: "left" }, { key: "name", label: "项目名称" },
    { key: "project_type", label: "项目类型" }, { key: "source", label: "项目来源" }, { key: "year", label: "项目年度" },
    { key: "customer_name", label: "客户名称" }, { key: "start_date", label: "开始日期" }, { key: "end_date", label: "结束日期" },
    { key: "status", label: "状态", tag: true }, { key: "contracts", label: "关联合同" }, { key: "remark", label: "备注" },
  ], fields: [
    { key: "project_code", label: "项目编号" }, { key: "name", label: "项目名称" },
    { key: "project_type", label: "项目类型" }, { key: "source", label: "项目来源" }, { key: "year", label: "项目年度" },
    { key: "customer_name", label: "客户名称" }, { key: "status", label: "状态", options: ["进行中", "已完成", "已终止"] },
    { key: "start_date", label: "开始日期", date: true }, { key: "end_date", label: "结束日期", date: true }, { key: "remark", label: "备注" },
  ]},
  plan: { title: "采购计划", api: "/api/purchase-plans", remove: true, columns: [
    { key: "plan_month", label: "计划月份" }, { key: "purchase_seq", label: "采购序号" }, { key: "material_code", label: "物料编号", fixed: "left" },
    { key: "plan_no", label: "采购计划单号" }, { key: "category", label: "使用设备" }, { key: "name_cn", label: "中文名称" }, { key: "spec", label: "规格型号" }, { key: "unit", label: "单位" },
    { key: "qty", label: "采购数量" }, { key: "bought_qty", label: "已采购数量" }, { key: "remain_qty", label: "待采购数量" },
    { key: "purchase_state", label: "是否采购", tag: true }, { key: "purpose", label: "用途" },
  ], fields: [] },
  stock: { title: "库存余额", api: "/api/stocks", remove: true, columns: [
    { key: "material_code", label: "物料编号", fixed: "left" }, { key: "warehouse_name", label: "仓库" }, { key: "goods_code", label: "商品编码" },
    { key: "goods_name", label: "商品名称" }, { key: "unit", label: "单位" }, { key: "qty", label: "数量" }, { key: "cost", label: "成本" },
  ], fields: [] },
  transfer: { title: "调拨记录", api: "/api/transfer-bills", create: "新增调拨记录", remove: true, columns: [
    { key: "bill_code", label: "单号", fixed: "left" }, { key: "bill_date", label: "日期" }, { key: "warehouse_out_name", label: "调出仓库" },
    { key: "warehouse_in_name", label: "调入仓库" }, { key: "material_code", label: "物料编号" }, { key: "qty", label: "数量" }, { key: "remark", label: "备注" },
  ], fields: [
    { key: "bill_date", label: "日期" }, { key: "warehouse_out", label: "调出仓库", lookup: "warehouses" }, { key: "warehouse_in", label: "调入仓库", lookup: "warehouses" },
    { key: "material_code", label: "物料编号" }, { key: "qty", label: "数量" }, { key: "remark", label: "备注" },
  ]},
  check: { title: "盘点记录", api: "/api/check-bills", create: "新增盘点记录", remove: true, columns: [
    { key: "bill_code", label: "单号", fixed: "left" }, { key: "bill_date", label: "日期" }, { key: "warehouse_name", label: "仓库" },
    { key: "material_code", label: "物料编号" }, { key: "book_qty", label: "账面数量" }, { key: "actual_qty", label: "实际数量" }, { key: "diff_qty", label: "差异" },
  ], fields: [
    { key: "bill_date", label: "日期" }, { key: "warehouse_id", label: "仓库", lookup: "warehouses" }, { key: "material_code", label: "物料编号" }, { key: "actual_qty", label: "实际数量" }, { key: "remark", label: "备注" },
  ]},
  income: { title: "其他收入", api: "/api/other-bills", extra: { direction: "income" }, create: "新增其他收入", edit: true, remove: true, columns: billCols(), fields: billFields() },
  expense: { title: "其他支出", api: "/api/other-bills", extra: { direction: "expense" }, create: "新增其他支出", edit: true, remove: true, columns: billCols(), fields: billFields() },
  role: dict("角色", "/api/roles"),
  dept: dict("部门", "/api/depts"),
  post: dict("岗位", "/api/posts"),
  loginLog: { title: "登录日志", api: "/api/login-logs", columns: [{ key: "user", label: "用户" }, { key: "login_time", label: "登录时间" }, { key: "ip", label: "IP" }, { key: "result", label: "结果", tag: true }], fields: [] },
  opLog: { title: "操作日志", api: "/api/op-logs", columns: [{ key: "user", label: "用户" }, { key: "action", label: "操作" }, { key: "time", label: "时间" }, { key: "detail", label: "摘要", width: 320 }], fields: [] },
  security: { title: "安全设置", api: "/api/configs", edit: true, columns: [{ key: "config_name", label: "配置名", fixed: "left" }, { key: "config_value", label: "配置值" }], fields: [{ key: "config_name", label: "配置名", disabled: true }, { key: "config_value", label: "配置值" }] },
  hs: { title: "HS Code库", api: "/api/customs/hs", create: "新增HS Code", edit: true, remove: true, columns: [
    { key: "hs_code", label: "HS Code", fixed: "left" }, { key: "declaration_name", label: "申报名称" },
    { key: "product_name", label: "产品名称" },
    { key: "specification", label: "申报规格" }, { key: "declaration_elements", label: "报关要素", width: 280 },
    { key: "description", label: "描述" }, { key: "status", label: "状态", tag: true },
  ], fields: [
    { key: "hs_code", label: "HS Code" }, { key: "declaration_name", label: "申报名称" },
    { key: "product_name", label: "产品名称" },
    { key: "specification", label: "申报规格" }, { key: "declaration_elements", label: "报关要素" },
    { key: "description", label: "描述" }, { key: "status", label: "状态", options: ["启用", "停用"] },
  ]},
  rate: { title: "汇率库", api: "/api/customs/rates", create: "新增汇率", edit: true, remove: true, columns: [
    { key: "year", label: "年" }, { key: "month", label: "月" }, { key: "currency", label: "币种" },
    { key: "rate", label: "汇率" }, { key: "effective_date", label: "生效日期" },
  ], fields: [
    { key: "year", label: "年" }, { key: "month", label: "月" }, { key: "currency", label: "币种" },
    { key: "rate", label: "汇率" }, { key: "effective_date", label: "生效日期", date: true },
  ]},
};
function billCols() { return [{ key: "bill_code", label: "单号", fixed: "left" }, { key: "bill_date", label: "日期" }, { key: "party_name", label: "客商" }, { key: "contract_code", label: "合同编号" }, { key: "amount", label: "金额", money: true }, { key: "account_name", label: "账户" }, { key: "remark", label: "备注" }]; }
function billFields() { return [{ key: "bill_date", label: "日期" }, { key: "party_name", label: "客商" }, { key: "contract_code", label: "合同编号" }, { key: "amount", label: "金额" }, { key: "account_name", label: "账户" }, { key: "remark", label: "备注" }]; }
function dict(title, api) { return { title, api, create: "新增", edit: true, remove: true, columns: [{ key: "code", label: "编码", fixed: "left" }, { key: "name", label: "名称" }, { key: "remark", label: "备注" }], fields: [{ key: "code", label: "编码" }, { key: "name", label: "名称" }, { key: "remark", label: "备注" }] }; }

const cfg = computed(() => catalogs[props.kind]);
const exportModule = computed(() => ({
  project: "project",
  plan: "purchase-plan",
  stock: "stock",
  transfer: "transfer",
  check: "check",
  income: "other",
  expense: "other",
  role: "roles",
  dept: "depts",
  post: "posts",
  loginLog: "login-logs",
  opLog: "op-logs",
  security: "configs",
  hs: "hs-code",
  rate: "exchange-rate",
}[props.kind]));
const exportQuery = computed(() => ({
  keyword: keyword.value,
  ...(cfg.value.extra || {}),
  plan_month: planMonth.value,
  name_cn: planName.value,
  purchase_state: planState.value,
  project_type: projectType.value,
  source: projectSource.value,
  year: projectYear.value,
  status: projectStatus.value,
  customer_name: projectCustomer.value,
  start_date: projectStart.value,
  end_date: projectEnd.value,
}));
const isAdmin = computed(() => {
  try {
    return !!JSON.parse(localStorage.getItem("user") || "{}").is_super_admin;
  } catch {
    return false;
  }
});
const shell = ref(null);
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");
const projectType = ref("");
const projectSource = ref("");
const projectYear = ref("");
const projectStatus = ref("");
const projectCustomer = ref("");
const projectStart = ref("");
const projectEnd = ref("");
const projectFacets = ref({ types: [], sources: [], years: [], customers: [], statuses: ["进行中", "已完成", "已终止"] });
const planMonth = ref("");
const planName = ref("");
const planState = ref("");
const summary = ref("");
const visible = ref(false);
const showImport = ref(false);
const form = reactive({});
const lookups = reactive({ warehouses: [] });

async function load() {
  const params = { keyword: keyword.value, page: page.value, pageSize: pageSize.value, ...(cfg.value.extra || {}) };
  if (props.kind === "plan") {
    params.plan_month = planMonth.value;
    params.name_cn = planName.value;
    params.purchase_state = planState.value;
  }
  if (props.kind === "project") {
    params.project_type = projectType.value;
    params.source = projectSource.value;
    params.year = projectYear.value;
    params.status = projectStatus.value;
    params.customer_name = projectCustomer.value;
    params.start_date = projectStart.value;
    params.end_date = projectEnd.value;
  }
  const res = await http.get(cfg.value.api, { params });
  if (props.kind === "project" && res.data.facets) projectFacets.value = res.data.facets;
  const data = res.data.items ? res.data : { items: res.data, total: res.data.length, page: 1, pageSize: res.data.length };
  rows.value = data.items || [];
  total.value = data.total || rows.value.length;
}
function reset() {
  keyword.value = "";
  projectType.value = "";
  projectSource.value = "";
  projectYear.value = "";
  projectStatus.value = "";
  projectCustomer.value = "";
  projectStart.value = "";
  projectEnd.value = "";
  planMonth.value = "";
  planName.value = "";
  planState.value = "";
  load();
}
function open(row) {
  Object.keys(form).forEach((k) => delete form[k]);
  Object.assign(form, row || { bill_date: new Date().toISOString().slice(0, 10), status: "进行中" });
  visible.value = true;
}
async function save() {
  const payload = { ...form, ...(cfg.value.extra || {}) };
  if (form.id) await http.put(`${cfg.value.api}/${form.id}`, payload);
  else await http.post(cfg.value.api, payload);
  visible.value = false;
  load();
}
async function remove(row) {
  await http.delete(`${cfg.value.api}/${row.id}`, { params: { version: row.version } });
  load();
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, `${cfg.value.api}/batch-delete`)) load();
}
async function wipeAll() {
  let value = "";
  try {
    const result = await ElMessageBox.prompt(
      "将永久删除合同、客商、采购计划、订单、仓储、结算、发票、项目、基础资料、组织和其他账号，包括已经删除但仍占用编号的记录。当前登录账号和当前公司会保留。请输入「清空全部数据」确认。",
      "清空全部数据",
      {
        confirmButtonText: "清空",
        cancelButtonText: "取消",
        inputPlaceholder: "清空全部数据",
        confirmButtonClass: "el-button--danger",
        closeOnClickModal: false,
      },
    );
    value = (result.value || "").trim();
  } catch {
    return;
  }
  if (value !== "清空全部数据") {
    ElMessage.error("确认文字不正确");
    return;
  }
  await http.post("/api/settings/wipe", { confirm: value });
  ElMessage.success("系统数据已清空");
  location.reload();
}
watch(() => props.kind, () => { page.value = 1; load(); });
onMounted(async () => {
  if (["transfer", "check"].includes(props.kind)) {
    lookups.warehouses = (await http.get("/api/warehouses", { params: { status: "启用", pageSize: 100 } })).data.items;
  }
  load();
});
</script>
