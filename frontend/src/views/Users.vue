<template>
  <ListShell ref="shell" title="用户" storage-key="users" :columns="columns" :rows="rows" :total="total" :page="page" :page-size="pageSize" export-module="users" :export-query="{ keyword }" @query="load" @reset="keyword='';load()" @page="(p)=>{page=p;load()}" @size="(s)=>{pageSize=s;load()}">
    <template #filters><el-input v-model="keyword" placeholder="员工编号 / 登录名 / 姓名" style="width:240px" /></template>
    <template #toolbar>
      <el-button type="primary" @click="open()">新增用户</el-button>
      <el-button @click="removeMany">批量删除</el-button>
    </template>
    <template #ops="{ row }">
      <span class="ops" @click="open(row)">编辑</span>
      <span class="ops" style="margin-left:8px" @click="reset(row)">修改密码</span>
      <el-popconfirm v-if="row.login_name!=='admin'" title="确定删除？" @confirm="remove(row)"><template #reference><span class="ops" style="margin-left:8px">删除</span></template></el-popconfirm>
    </template>
  </ListShell>
  <el-dialog v-model="visible" title="用户" width="560px">
    <el-form label-width="110px">
      <el-form-item label="员工编号"><el-input v-model="form.employee_id" :disabled="!!form.id" /></el-form-item>
      <el-form-item label="登录名"><el-input v-model="form.login_name" :disabled="!!form.id" /></el-form-item>
      <el-form-item label="中文姓名"><el-input v-model="form.name" /></el-form-item>
      <el-form-item v-if="!form.id" label="初始密码"><el-input v-model="form.password" placeholder="空则 123456" /></el-form-item>
      <el-form-item label="角色"><el-input v-model="form.role_text" /></el-form-item>
      <el-form-item label="状态"><el-select v-model="form.status"><el-option label="启用" value="启用" /><el-option label="停用" value="停用" /></el-select></el-form-item>
      <el-form-item label="可访问公司">
        <el-select v-model="form.companies" multiple style="width:100%"><el-option v-for="c in companies" :key="c.id" :label="c.short_name" :value="c.id" /></el-select>
      </el-form-item>
      <el-form-item label="默认公司">
        <el-select v-model="form.default_company_id" style="width:100%"><el-option v-for="id in form.companies" :key="id" :label="nameOf(id)" :value="id" /></el-select>
      </el-form-item>
      <el-form-item label="导入覆盖"><el-checkbox v-model="form.can_import_overwrite" :disabled="form.is_super_admin">允许覆盖他人记录</el-checkbox></el-form-item>
    </el-form>
    <template #footer><el-button type="primary" @click="save">保存</el-button></template>
  </el-dialog>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessageBox } from "element-plus";
import http, { batchDelete } from "../api";
import ListShell from "../components/ListShell.vue";

const shell = ref(null);
const columns = [
  { key: "employee_id", label: "员工编号", fixed: "left" },
  { key: "login_name", label: "登录名" },
  { key: "name", label: "中文姓名" },
  { key: "role_text", label: "角色" },
  { key: "status", label: "状态", tag: true },
  { key: "can_import_overwrite", label: "导入覆盖" },
];
const rows = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");
const companies = ref([]);
const visible = ref(false);
const form = reactive({ companies: [], status: "启用", can_import_overwrite: false });
function nameOf(id) { return companies.value.find((c) => c.id === id)?.short_name || id; }
async function load() {
  const res = await http.get("/api/users", { params: { keyword: keyword.value, page: page.value, pageSize: pageSize.value } });
  rows.value = res.data.items.map((row) => ({ ...row, can_import_overwrite: row.can_import_overwrite ? "是" : "否" }));
  total.value = res.data.total;
}
function open(row) {
  Object.assign(form, { id: null, employee_id: "", login_name: "", name: "", password: "", role_text: "", status: "启用", companies: companies.value.map((c) => c.id).slice(0, 1), default_company_id: companies.value[0]?.id, can_import_overwrite: false, is_super_admin: false, version: null });
  if (row) {
    const raw = rows.value.find((item) => item.id === row.id);
    Object.assign(form, row, { can_import_overwrite: raw?.can_import_overwrite === "是" || row.can_import_overwrite === true, companies: row.companies || [], default_company_id: row.default_company_id });
  }
  visible.value = true;
}
async function save() {
  if (form.id) await http.put(`/api/users/${form.id}`, form);
  else await http.post("/api/users", form);
  visible.value = false;
  load();
}
async function reset(row) {
  const { value } = await ElMessageBox.prompt("输入新密码", "修改密码");
  await http.put(`/api/users/${row.id}/reset-password`, { password: value });
}
async function remove(row) { await http.delete(`/api/users/${row.id}`, { params: { version: row.version } }); load(); }
async function removeMany() {
  if (await batchDelete(shell.value, rows.value, "/api/users/batch-delete")) load();
}
onMounted(async () => {
  companies.value = (await http.get("/api/companies")).data;
  load();
});
</script>
