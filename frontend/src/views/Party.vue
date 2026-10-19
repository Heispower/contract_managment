<template>
  <ListShell ref="shell" title="客商" :bare="embedded" storage-key="party" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" export-module="party" :export-query="exportQuery" @query="load" @reset="reset" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;page=1;load()}" @select="syncPick">
    <template #title>
      客商
      <el-select v-model="partyType" style="width:140px;margin-left:12px" @change="load">
        <el-option label="供应商" value="supplier" />
        <el-option label="客户" value="customer" />
      </el-select>
    </template>
    <template #filters="{ expanded }">
      <el-select v-if="embedded" v-model="partyType" style="width:140px" @change="load">
        <el-option label="供应商" value="supplier" />
        <el-option label="客户" value="customer" />
      </el-select>
      <el-input v-model="keyword" placeholder="关键字" style="width:180px" />
      <el-select v-model="category" clearable filterable :placeholder="partyType === 'supplier' ? '供应商类别' : '客户类别'" style="width:150px">
        <el-option v-for="item in categories" :key="item" :label="item" :value="item" />
      </el-select>
      <el-select v-model="owner" clearable filterable placeholder="业务员" style="width:150px">
        <el-option v-for="user in users" :key="user.employee_id" :label="user.name" :value="user.employee_id" />
      </el-select>
      <template v-if="expanded">
        <el-input v-model="address" placeholder="地址" style="width:180px" />
        <el-select v-model="status" clearable placeholder="状态" style="width:120px">
          <el-option label="启用" value="启用" />
          <el-option label="停用" value="停用" />
        </el-select>
      </template>
    </template>
    <template #toolbar>
      <el-button type="primary" @click="open()">{{ partyType === "supplier" ? "新增供应商" : "新增客户" }}</el-button>
      <el-button @click="showImport = true">导入</el-button>
      <el-button @click="batchRemove">批量删除</el-button>
      <el-dropdown trigger="hover" @visible-change="(open) => open && syncPick()">
        <span class="more-hover"><el-button>更多</el-button></span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="batchRemove">批量删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">编辑</span>
      <el-popconfirm title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="visible" :title="form.id ? '编辑' + prefix : (partyType === 'supplier' ? '新增供应商' : '新增客户')" width="860px">
    <el-form label-width="110px">
      <div class="card"><strong>基本信息</strong>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item :label="prefix + '编码'"><el-input v-model="form.code" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item :label="prefix + '简称'"><el-input v-model="form.short_name" /></el-form-item></el-col>
        </el-row>
        <el-form-item :label="prefix + '名称'"><el-input v-model="form.name" /></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="业务员"><el-input v-model="form.salesman_id" placeholder="员工编号或姓名" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="form.status" style="width:100%"><el-option label="启用" value="启用" /><el-option label="停用" value="停用" /></el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="默认税率"><el-input v-model="form.default_tax_rate" /><div style="color:#86909c">新增合同时自动带出，仍可手改</div></el-form-item>
      </div>
      <div class="card"><strong>联系方式</strong>
        <div v-for="(c, i) in form.contacts" :key="i" style="display:flex;gap:8px;margin-bottom:8px">
          <el-input v-model="c.name" placeholder="联系人" />
          <el-input v-model="c.phone" placeholder="联系电话" />
          <el-checkbox v-model="c.is_default">默认</el-checkbox>
        </div>
        <el-button @click="form.contacts.push({ name:'', phone:'', is_default:false })">加联系人</el-button>
        <el-row :gutter="12" style="margin-top:12px">
          <el-col :span="12"><el-form-item label="手机"><el-input v-model="form.mobile" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item></el-col>
        </el-row>
      </div>
      <div class="card"><strong>开票与银行</strong>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="纳税人识别号"><el-input v-model="form.tax_no" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="开票名称"><el-input v-model="form.invoice_title" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="开户银行"><el-input v-model="form.bank_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="账户名称"><el-input v-model="form.account_name" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="银行账号"><el-input v-model="form.bank_account" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="开户支行"><el-input v-model="form.bank_branch" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="开票电话"><el-input v-model="form.invoice_phone" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="开票地址"><el-input v-model="form.invoice_address" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="法人代表"><el-input v-model="form.legal_name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="委托代理人"><el-input v-model="form.agent_name" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="通讯地址"><el-input v-model="form.address" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" /></el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="visible=false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
  <ImportWizard v-model="showImport" module="party" :party-type="partyType" @done="load" />
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import http from "../api";
import ListShell from "../components/ListShell.vue";
import ImportWizard from "../components/ImportWizard.vue";

const props = defineProps({ embedded: Boolean });
const partyType = ref("supplier");
const keyword = ref("");
const category = ref("");
const owner = ref("");
const address = ref("");
const status = ref("");
const categories = ref([]);
const users = ref([]);
const shell = ref(null);
const selectedRows = ref([]);
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const visible = ref(false);
const showImport = ref(false);
const form = reactive(blank());
const prefix = computed(() => (partyType.value === "supplier" ? "供应商" : "客户"));
const columns = computed(() => [
  { key: "code", label: prefix.value + "编码", fixed: "left", width: 120 },
  { key: "name", label: prefix.value + "名称", width: 240 },
  { key: "short_name", label: prefix.value + "简称", width: 140 },
  { key: "contact_name", label: "联系人", width: 100 },
  { key: "contact_phone", label: "联系电话", width: 140 },
  { key: "tax_no", label: "纳税人识别号", width: 190 },
  { key: "bank_name", label: "开户银行", width: 200 },
  { key: "bank_account", label: "银行账号", width: 200 },
  { key: "default_tax_rate", label: "默认税率", width: 100 },
  { key: "status", label: "状态", tag: true, width: 90 },
  { key: "salesman_name", label: "业务员", width: 100 },
]);
const exportQuery = computed(() => ({
  type: partyType.value,
  keyword: keyword.value,
  category: category.value,
  owner: owner.value,
  address: address.value,
  status: status.value,
}));
function blank() {
  return {
    id: null, version: null, code: "", name: "", short_name: "", tax_no: "", bank_account: "", bank_name: "", account_name: "", bank_branch: "",
    default_tax_rate: "13", status: "启用", supplier_category: "", salesman_id: "", invoice_title: "", invoice_phone: "", invoice_address: "",
    address: "", email: "", mobile: "", legal_name: "", agent_name: "", remark: "", contacts: [{ name: "", phone: "", is_default: true }],
  };
}
async function load() {
  const params = { type: partyType.value, page: page.value, pageSize: pageSize.value };
  if (keyword.value) params.keyword = keyword.value;
  if (category.value) params.category = category.value;
  if (owner.value) params.owner = owner.value;
  if (address.value) params.address = address.value;
  if (status.value) params.status = status.value;
  const res = await http.get("/api/parties", { params });
  rows.value = res.data.items;
  total.value = res.data.total;
  categories.value = res.data.categories || [];
  selectedRows.value = [];
}
function reset() {
  keyword.value = "";
  category.value = "";
  owner.value = "";
  address.value = "";
  status.value = "";
  load();
}
function syncPick() {
  const set = shell.value?.selected || new Set();
  selectedRows.value = rows.value.filter((row) => set.has(row.id));
}
async function batchRemove() {
  syncPick();
  if (!selectedRows.value.length) return ElMessage.warning("请先勾选客商");
  await ElMessageBox.confirm(`确定删除选中的 ${selectedRows.value.length} 条？`, "批量删除", { type: "warning" });
  await http.post("/api/parties/batch-delete", { items: selectedRows.value.map((row) => ({ id: row.id, version: row.version })) });
  ElMessage.success("已删除");
  load();
}
async function open(row) {
  Object.assign(form, blank());
  if (row) {
    const res = await http.get(`/api/parties/${row.id}`);
    Object.assign(form, res.data, { contacts: res.data.contacts.length ? res.data.contacts : blank().contacts });
  }
  visible.value = true;
}
async function save() {
  const payload = { ...form, type: partyType.value };
  const res = form.id ? await http.put(`/api/parties/${form.id}`, payload) : await http.post("/api/parties", payload);
  visible.value = false;
  if (res.data?.need_name_sync) {
    try {
      await ElMessageBox.confirm("是否同步更新引用此客商的单据？", "提示", { confirmButtonText: "确定", cancelButtonText: "取消" });
      await http.post(`/api/parties/${form.id}/sync-name`);
    } catch { /* 取消则保持旧快照 */ }
  }
  load();
}
async function remove(row) {
  await http.delete(`/api/parties/${row.id}`, { params: { version: row.version } });
  load();
}
onMounted(async () => {
  users.value = (await http.get("/api/users", { params: { status: "启用", pageSize: 200 } })).data.items || [];
  load();
});
</script>
