<template>
  <div>
    <h2 class="page-title">基础资料</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="公司管理" name="company" />
      <el-tab-pane label="资金账户" name="account" />
      <el-tab-pane label="合同类型" name="type" />
      <el-tab-pane label="编号规则" name="numbering" />
      <el-tab-pane label="仓库" name="warehouse" />
      <el-tab-pane label="商品列表" name="goods" />
      <el-tab-pane label="商品分类" name="category" />
      <el-tab-pane label="HS Code库" name="hs" />
      <el-tab-pane label="汇率库" name="rate" />
      <el-tab-pane label="导出模板" name="export" />
      <el-tab-pane label="Deepseek" name="deepseek" />
    </el-tabs>
    <p v-if="tab === 'export'" style="color:var(--muted);margin:0 0 12px">同一张单据可以维护多份模板。模板可以是 doc、docx、xls、xlsx 等文件，填写绝对地址或直接上传。生成时如果有多份，会按供应商弹出选择。</p>
    <p v-if="tab === 'numbering'" style="color:var(--muted);margin:0 0 12px">这里只改以后新编号的前缀、年份位数、序号位数和后缀。已经保存的合同编号、发票编号以及它们的顺序号不会重算；改前缀后序号仍从原池子继续排。</p>
    <ListShell v-if="tab !== 'deepseek'" ref="shell" bare :title="tabLabel" :storage-key="'master-' + tab" :columns="shellColumns" :rows="rows" :total="total" :page="page" :page-size="pageSize" :expandable="false" :export-module="exportModule" :export-query="{ keyword }" @query="search" @reset="reset" @page="(value) => { page = value; load(); }" @size="(value) => { pageSize = value; page = 1; load(); }">
      <template #filters>
        <el-input v-model="keyword" clearable placeholder="关键字" style="width:220px" @keyup.enter="search" />
      </template>
      <template #toolbar>
        <el-button v-if="tab !== 'numbering'" type="primary" @click="tab === 'export' ? openExport() : open()">新增</el-button>
        <el-button v-if="tab === 'goods' || tab === 'hs'" @click="showImport = true">导入</el-button>
        <el-button v-if="batchApi[tab]" @click="removeMany">批量删除</el-button>
        <el-button v-if="tab === 'export'" @click="downloadFields">字段清单</el-button>
      </template>
      <template #ops="{ row }">
        <span class="ops" @click="tab === 'export' ? openExport(row) : open(row)">编辑</span>
        <el-popconfirm v-if="tab !== 'numbering'" title="确定删除？" @confirm="tab === 'export' ? removeExport(row) : remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
      </template>
    </ListShell>
    <div v-if="tab === 'deepseek'" class="card" style="max-width:760px;padding:16px">
      <p style="color:var(--muted);margin:0 0 16px">报关要素里的 AI 检查使用这里的配置。保存后立即生效，可随时改接口、密钥和模型。</p>
      <el-form label-width="120px">
        <el-form-item label="启用"><el-switch v-model="ai.enabled" /></el-form-item>
        <el-form-item label="接口地址"><el-input v-model="ai.api_base" placeholder="https://api.deepseek.com" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="ai.api_key" type="password" show-password /></el-form-item>
        <el-form-item label="模型">
          <el-select v-model="ai.model" filterable allow-create default-first-option style="width:100%">
            <el-option v-for="item in aiModels" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时（秒）"><el-input-number v-model="ai.timeout_seconds" :min="5" :max="120" /></el-form-item>
        <el-form-item label="温度"><el-input-number v-model="ai.temperature" :min="0" :max="2" :step="0.1" :precision="1" /></el-form-item>
        <el-form-item label="思考模式">
          <el-switch v-model="ai.thinking" />
          <span style="margin-left:8px;color:var(--muted)">关闭时直接给出核对结果，适合日常办公</span>
        </el-form-item>
      </el-form>
      <el-button type="primary" @click="saveDeepseek">保存</el-button>
      <el-button :loading="aiTesting" @click="testDeepseek">测试连接</el-button>
      <p v-if="aiTestText" style="margin:12px 0 0">{{ aiTestText }}</p>
    </div>
    <el-dialog v-model="companyVisible" :title="companyForm.id ? '编辑公司' : '新增公司'" width="860px">
      <el-form label-width="110px">
        <div class="card"><strong>基本信息</strong>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="公司编码"><el-input v-model="companyForm.code" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="公司简称"><el-input v-model="companyForm.short_name" /></el-form-item></el-col>
          </el-row>
          <el-form-item label="公司名称"><el-input v-model="companyForm.name" /></el-form-item>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="业务员"><el-input v-model="companyForm.salesman_id" placeholder="员工编号或姓名" /></el-form-item></el-col>
            <el-col :span="12">
              <el-form-item label="状态">
                <el-select v-model="companyForm.status" style="width:100%"><el-option label="启用" value="启用" /><el-option label="停用" value="停用" /></el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="默认税率"><el-input v-model="companyForm.default_tax_rate" /></el-form-item>
        </div>
        <div class="card"><strong>联系方式</strong>
          <div v-for="(c, i) in companyForm.contacts" :key="i" style="display:flex;gap:8px;margin-bottom:8px">
            <el-input v-model="c.name" placeholder="联系人" />
            <el-input v-model="c.phone" placeholder="联系电话" />
            <el-checkbox v-model="c.is_default">默认</el-checkbox>
          </div>
          <el-button @click="companyForm.contacts.push({ name:'', phone:'', is_default:false })">加联系人</el-button>
          <el-row :gutter="12" style="margin-top:12px">
            <el-col :span="12"><el-form-item label="手机"><el-input v-model="companyForm.mobile" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="邮箱"><el-input v-model="companyForm.email" /></el-form-item></el-col>
          </el-row>
        </div>
        <div class="card"><strong>开票与银行</strong>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="纳税人识别号"><el-input v-model="companyForm.tax_no" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="开票名称"><el-input v-model="companyForm.invoice_title" /></el-form-item></el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="开户银行"><el-input v-model="companyForm.bank_name" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="账户名称"><el-input v-model="companyForm.account_name" /></el-form-item></el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="银行账号"><el-input v-model="companyForm.bank_account" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="开户支行"><el-input v-model="companyForm.bank_branch" /></el-form-item></el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="开票电话"><el-input v-model="companyForm.invoice_phone" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="开票地址"><el-input v-model="companyForm.invoice_address" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="法人代表"><el-input v-model="companyForm.legal_name" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="委托代理人"><el-input v-model="companyForm.agent_name" /></el-form-item></el-col>
          </el-row>
          <el-form-item label="通讯地址"><el-input v-model="companyForm.address" /></el-form-item>
          <el-form-item label="备注"><el-input v-model="companyForm.remark" type="textarea" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="companyVisible=false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="visible" :title="(form.id ? '编辑' : '新增') + tabLabel" :width="tab === 'hs' ? '640px' : '520px'">
      <el-form label-width="100px">
        <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
          <el-select v-if="field.key==='status'" v-model="form[field.key]" style="width:100%"><el-option label="启用" value="启用" /><el-option label="停用" value="停用" /></el-select>
          <el-date-picker v-else-if="field.key==='effective_date'" v-model="form[field.key]" value-format="YYYY-MM-DD" placeholder="请选择日期" style="width:100%" />
          <el-input v-else-if="field.key==='declaration_elements' || field.key==='description'" v-model="form[field.key]" type="textarea" :rows="2" />
          <el-input v-else v-model="form[field.key]" />
        </el-form-item>
      </el-form>
      <template #footer><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="exportVisible" :title="exportForm.id ? '编辑导出模板' : '新增导出模板'" width="760px">
      <el-form label-width="120px">
        <el-form-item label="单据">
          <el-select v-model="exportForm.doc_code" filterable style="width:100%" @change="onExportKind">
            <el-option v-for="kind in exportKinds" :key="kind.code" :label="kind.name" :value="kind.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板名称"><el-input v-model="exportForm.title" placeholder="例如一般供应商、康明斯" /></el-form-item>
        <el-form-item label="适用客商">
          <el-select v-model="exportForm.party_id" clearable filterable placeholder="不限，生成时再选" style="width:100%">
            <el-option v-for="party in exportParties" :key="party.id" :label="partyLabel(party)" :value="party.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板绝对地址">
          <div style="display:flex;gap:8px;width:100%">
            <el-input v-model="exportForm.template_path" placeholder="D:\合同模板\一般供应商.xlsx" />
            <el-upload :show-file-list="false" accept=".doc,.docx,.dot,.dotx,.xls,.xlsx,.xlsm,.xlt,.xltx,.pdf,.rtf,.csv,.txt" :http-request="uploadTemplate">
              <el-button>上传</el-button>
            </el-upload>
          </div>
        </el-form-item>
        <el-form-item label="导出名称">
          <el-input v-model="exportForm.name_rule" :placeholder="nameHint" />
        </el-form-item>
        <el-form-item label="可用字段">
          <div style="display:flex;flex-wrap:wrap;gap:6px">
            <el-tag v-for="name in exportForm.placeholders" :key="name" style="cursor:pointer" @click="addToken(name)">{{ tokenText(name) }}</el-tag>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="exportVisible=false">取消</el-button>
        <el-button type="primary" @click="saveExport">保存</el-button>
      </template>
    </el-dialog>
    <ImportWizard v-if="tab === 'goods' || tab === 'hs'" v-model="showImport" :module="tab === 'hs' ? 'hs-code' : 'goods'" @done="load" />
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";

const route = useRoute();
const openedTabs = ["hs", "rate", "deepseek", "numbering"];
const tab = ref(openedTabs.includes(String(route.query.tab || "")) ? String(route.query.tab) : "company");
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");
const shell = ref(null);
const visible = ref(false);
const companyVisible = ref(false);
const showImport = ref(false);
const form = reactive({});
const batchApi = {
  account: "/api/fund-accounts/batch-delete",
  type: "/api/contract-types/batch-delete",
  warehouse: "/api/warehouses/batch-delete",
  goods: "/api/goods/batch-delete",
  category: "/api/goods-categories/batch-delete",
  hs: "/api/customs/hs/batch-delete",
  rate: "/api/customs/rates/batch-delete",
};
const meta = {
  company: {
    label: "公司", api: "/api/companies", export: "",
    columns: [
      { key: "code", label: "公司编码", fixed: "left" }, { key: "short_name", label: "公司简称" }, { key: "name", label: "公司名称", width: 180 },
      { key: "tax_no", label: "纳税人识别号", width: 160 }, { key: "legal_name", label: "法人代表" }, { key: "agent_name", label: "委托代理人" },
      { key: "invoice_phone", label: "开票电话" }, { key: "status", label: "状态", tag: true },
    ],
  },
  account: {
    label: "资金账户", api: "/api/fund-accounts", export: "fund-accounts",
    columns: [
      { key: "code", label: "编码", fixed: "left" }, { key: "name", label: "名称" }, { key: "account_no", label: "账号" }, { key: "status", label: "状态", tag: true },
    ],
    fields: ["code", "name", "account_no", "status"],
  },
  type: {
    label: "合同类型", api: "/api/contract-types", export: "contract-types",
    columns: [
      { key: "code", label: "编码", fixed: "left" }, { key: "name", label: "名称" }, { key: "remark", label: "备注" }, { key: "status", label: "状态", tag: true },
    ],
    fields: ["code", "name", "remark", "status"],
  },
  numbering: {
    label: "编号规则", api: "/api/numbering/rules", export: "",
    columns: [
      { key: "label", label: "单据", fixed: "left", width: 110 },
      { key: "prefix", label: "前缀", width: 140 },
      { key: "format_text", label: "编号组成", width: 210 },
      { key: "preview", label: "下一个编号", width: 180 },
      { key: "remark", label: "备注" },
    ],
    fields: ["prefix", "year_digits", "seq_width", "suffix", "remark"],
  },
  warehouse: {
    label: "仓库", api: "/api/warehouses", export: "warehouses",
    columns: [
      { key: "code", label: "编码", fixed: "left" }, { key: "name", label: "名称" }, { key: "remark", label: "备注" }, { key: "status", label: "状态", tag: true },
    ],
    fields: ["code", "name", "remark", "status"],
  },
  goods: {
    label: "商品", api: "/api/goods", export: "goods",
    columns: [
      { key: "material_code", label: "物料编号", fixed: "left" }, { key: "name", label: "名称" }, { key: "spec", label: "规格" },
      { key: "unit", label: "单位" }, { key: "category_code", label: "分类编码" }, { key: "price", label: "含税单价", money: true },
    ],
    fields: ["material_code", "name", "spec", "unit", "category_code", "price"],
  },
  category: {
    label: "商品分类", api: "/api/goods-categories", export: "goods-categories",
    columns: [
      { key: "code", label: "编码", fixed: "left" }, { key: "name", label: "名称" }, { key: "remark", label: "备注" },
    ],
    fields: ["code", "name", "remark"],
  },
  hs: {
    label: "HS Code", api: "/api/customs/hs", export: "hs-code",
    columns: [
      { key: "hs_code", label: "HS Code", fixed: "left", width: 140 }, { key: "declaration_name", label: "申报名称" },
      { key: "product_name", label: "产品名称" }, { key: "specification", label: "申报规格" },
      { key: "declaration_elements", label: "报关要素", width: 280, wrap: true }, { key: "description", label: "描述", width: 180 },
      { key: "status", label: "状态", tag: true },
    ],
    fields: ["hs_code", "declaration_name", "product_name", "specification", "declaration_elements", "description", "status"],
  },
  rate: {
    label: "汇率", api: "/api/customs/rates", export: "exchange-rate",
    columns: [
      { key: "year", label: "年" }, { key: "month", label: "月" }, { key: "currency", label: "币种" },
      { key: "rate", label: "汇率" }, { key: "effective_date", label: "生效日期" },
    ],
    fields: ["year", "month", "currency", "rate", "effective_date"],
  },
  export: {
    label: "导出模板", api: "/api/export-profiles", export: "",
    columns: [
      { key: "doc_name", label: "单据", fixed: "left", width: 120 }, { key: "title", label: "模板名称" },
      { key: "party_name", label: "适用客商" }, { key: "template_path", label: "模板绝对地址", width: 280 },
      { key: "name_rule", label: "导出名称", width: 220 },
    ],
  },
};
const fieldLabels = {
  name: "名称", code: "编码", account_no: "账号", status: "状态", remark: "备注", material_code: "物料编号", spec: "规格", unit: "单位",
  category_code: "分类编码", price: "含税单价", hs_code: "HS Code", declaration_name: "申报名称", product_name: "产品名称",
  specification: "申报规格", declaration_elements: "报关要素", description: "描述", year: "年", month: "月", currency: "币种",
  rate: "汇率", effective_date: "生效日期", prefix: "前缀", year_digits: "年份位数", seq_width: "序号位数", suffix: "后缀",
};
const tabLabel = computed(() => meta[tab.value]?.label || "");
const shellColumns = computed(() => meta[tab.value]?.columns || []);
const exportModule = computed(() => meta[tab.value]?.export || "");
const fields = computed(() => (meta[tab.value]?.fields || []).map((key) => ({ key, label: fieldLabels[key] || key })));
function blankCompany() {
  return {
    id: null, version: null, code: "", name: "", short_name: "", status: "启用", default_tax_rate: "13", salesman_id: "",
    tax_no: "", invoice_title: "", bank_name: "", account_name: "", bank_account: "", bank_branch: "",
    invoice_phone: "", invoice_address: "", legal_name: "", agent_name: "", mobile: "", email: "", address: "", remark: "",
    contacts: [{ name: "", phone: "", is_default: true }],
  };
}
const companyForm = reactive(blankCompany());
const exportVisible = ref(false);
const exportKinds = ref([]);
const exportPartiesAll = ref([]);
const exportForm = reactive({ id: null, version: null, doc_code: "", title: "", party_id: null, template_path: "", name_rule: "", placeholders: [] });
const nameHint = "{{合同编号}}.xlsx";
const exportParties = computed(() => {
  const kind = exportKinds.value.find((item) => item.code === exportForm.doc_code);
  const type = kind?.party_type || "";
  return exportPartiesAll.value.filter((party) => !type || party.type === type);
});
function search() {
  page.value = 1;
  load();
}
function reset() {
  keyword.value = "";
  page.value = 1;
  load();
}
function localPage(items) {
  const text = keyword.value.trim().toLowerCase();
  const filtered = text ? items.filter((row) => JSON.stringify(row).toLowerCase().includes(text)) : items;
  total.value = filtered.length;
  const start = (page.value - 1) * pageSize.value;
  rows.value = filtered.slice(start, start + pageSize.value);
}
const aiModels = ref([
  { value: "deepseek-v4-flash", label: "V4 Flash（办公）" },
  { value: "deepseek-flash", label: "V4.1 Flash" },
  { value: "deepseek-v4-pro", label: "V4 Pro" },
]);
const ai = reactive({
  id: null, version: null, enabled: true, api_base: "https://api.deepseek.com", api_key: "",
  model: "deepseek-v4-flash", timeout_seconds: 30, temperature: 0.2, thinking: false,
});
const aiTesting = ref(false);
const aiTestText = ref("");
async function load() {
  if (tab.value === "deepseek") {
    const res = await http.get("/api/settings/deepseek");
    Object.assign(ai, res.data, {
      temperature: Number(res.data.temperature),
      timeout_seconds: Number(res.data.timeout_seconds),
    });
    if (res.data.models && res.data.models.length) aiModels.value = res.data.models;
    return;
  }
  if (tab.value === "numbering") {
    const res = await http.get(meta.numbering.api);
    localPage(res.data || []);
    return;
  }
  const res = await http.get(meta[tab.value].api, { params: { page: page.value, pageSize: pageSize.value, keyword: keyword.value } });
  if (tab.value === "export") {
    exportKinds.value = res.data.kinds || [];
    if (!exportPartiesAll.value.length) {
      const suppliers = await http.get("/api/parties", { params: { type: "supplier", pageSize: 500 } });
      const customers = await http.get("/api/parties", { params: { type: "customer", pageSize: 500 } });
      exportPartiesAll.value = [...(suppliers.data.items || []), ...(customers.data.items || [])];
    }
    localPage((res.data.items || []).map((row) => ({ ...row, party_name: row.party_name || "不限" })));
    return;
  }
  if (Array.isArray(res.data)) {
    localPage(res.data);
    return;
  }
  rows.value = res.data.items || [];
  total.value = res.data.total ?? rows.value.length;
}
function tokenText(name) {
  return "{{" + name + "}}";
}
function partyLabel(party) {
  return party.short_name ? `${party.short_name} ${party.name}` : party.name;
}
function onExportKind(code) {
  const kind = exportKinds.value.find((item) => item.code === code);
  exportForm.placeholders = kind?.placeholders || [];
  if (!exportForm.id && kind) exportForm.name_rule = kind.name_rule || "";
  if (exportForm.party_id && !exportParties.value.some((party) => party.id === exportForm.party_id)) exportForm.party_id = null;
}
function openExport(row) {
  const kind = exportKinds.value.find((item) => item.code === (row?.doc_code || "purchase_contract")) || exportKinds.value[0];
  Object.assign(exportForm, {
    id: row?.id || null,
    version: row?.version || null,
    doc_code: kind?.code || "",
    title: row?.title || "",
    party_id: row?.party_id || null,
    template_path: row?.template_path || "",
    name_rule: row?.name_rule || kind?.name_rule || "",
    placeholders: kind?.placeholders || [],
  });
  exportVisible.value = true;
}
function addToken(name) {
  const piece = tokenText(name);
  const current = exportForm.name_rule || "";
  exportForm.name_rule = current && !current.endsWith(" ") ? current + " " + piece : current + piece;
}
function matchRuleExt(rule, filename) {
  const ext = (String(filename || "").match(/(\.[A-Za-z0-9]+)$/) || [])[1] || "";
  if (!ext) return rule;
  const current = String(rule || "");
  if (/\.[A-Za-z0-9]+$/.test(current)) return current.replace(/\.[A-Za-z0-9]+$/, ext);
  return current ? `${current}${ext}` : ext;
}
async function uploadTemplate(option) {
  const body = new FormData();
  body.append("file", option.file);
  const res = await http.post("/api/export-profiles/upload", body);
  exportForm.template_path = res.data.path;
  const uploaded = (res.data.path || "").split(/[/\\]/).pop();
  if (!exportForm.title) exportForm.title = uploaded.replace(/\.[^.]+$/, "");
  exportForm.name_rule = matchRuleExt(exportForm.name_rule, uploaded);
  ElMessage.success("模板已上传");
}
async function saveExport() {
  const payload = {
    version: exportForm.version,
    doc_code: exportForm.doc_code,
    title: exportForm.title,
    party_id: exportForm.party_id,
    template_path: exportForm.template_path,
    name_rule: exportForm.name_rule,
  };
  if (exportForm.id) await http.put(`/api/export-profiles/${exportForm.id}`, payload);
  else await http.post("/api/export-profiles", payload);
  exportVisible.value = false;
  load();
}
async function downloadFields() {
  const res = await http.get("/api/export-profiles/fields", { responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = "表单字段.xlsx";
  link.click();
  URL.revokeObjectURL(url);
}
async function removeExport(row) {
  await http.delete(`/api/export-profiles/${row.id}`, { params: { version: row.version } });
  load();
}
function open(row) {
  if (tab.value === "company") {
    Object.assign(companyForm, blankCompany(), row || {});
    companyForm.contacts = (row && row.contacts && row.contacts.length) ? row.contacts.map((item) => ({ ...item })) : [{ name: "", phone: "", is_default: true }];
    companyVisible.value = true;
    return;
  }
  Object.keys(form).forEach((k) => delete form[k]);
  const today = new Date();
  const blank = { status: "启用" };
  if (tab.value === "rate") Object.assign(blank, { year: today.getFullYear(), month: today.getMonth() + 1, currency: "USD", rate: "", effective_date: today.toISOString().slice(0, 10) });
  Object.assign(form, row || blank);
  visible.value = true;
}
async function save() {
  if (tab.value === "company") {
    const api = meta.company.api;
    const payload = { ...companyForm, contacts: companyForm.contacts };
    if (companyForm.id) await http.put(`${api}/${companyForm.id}`, payload);
    else await http.post(api, payload);
    companyVisible.value = false;
    load();
    return;
  }
  const api = meta[tab.value].api;
  if (form.id) await http.put(`${api}/${form.id}`, form);
  else await http.post(api, form);
  visible.value = false;
  load();
}
async function remove(row) {
  const res = await http.delete(`${meta[tab.value].api}/${row.id}`, { params: { version: row.version } });
  if (res.data && res.data.token) {
    localStorage.setItem("token", res.data.token);
    localStorage.setItem("company_id", String(res.data.company_id));
    const me = await http.get("/api/auth/me");
    localStorage.setItem("user", JSON.stringify(me.data));
    location.reload();
    return;
  }
  load();
}
async function saveDeepseek() {
  const res = await http.put("/api/settings/deepseek", { ...ai });
  Object.assign(ai, res.data, {
    temperature: Number(res.data.temperature),
    timeout_seconds: Number(res.data.timeout_seconds),
  });
  ElMessage.success("已保存，报关要素检查会使用这份配置");
}
async function testDeepseek() {
  aiTesting.value = true;
  aiTestText.value = "";
  try {
    const res = await http.post("/api/settings/deepseek/test", { ...ai });
    aiTestText.value = `连接成功：${res.data.reply || "ok"}`;
    ElMessage.success("连接成功");
  } finally {
    aiTesting.value = false;
  }
}
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, batchApi[tab.value])) {
    shell.value.selected = new Set();
    load();
  }
}
watch(tab, () => { keyword.value = ""; page.value = 1; load(); }, { immediate: true });
watch(() => route.query.tab, (value) => {
  if (openedTabs.includes(String(value || "")) && tab.value !== value) tab.value = String(value);
});
</script>
