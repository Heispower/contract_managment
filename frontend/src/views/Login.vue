<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="brand" style="margin-bottom: 20px">
        <BrandLogo class="logo logo-lg" />
        <span>合同管理系统</span>
      </div>
      <el-form @submit.prevent="submit">
        <el-form-item><el-input v-model="form.login_name" placeholder="用户名" /></el-form-item>
        <el-form-item><el-input v-model="form.password" type="password" show-password placeholder="密码" /></el-form-item>
        <el-form-item><el-checkbox v-model="remember">记住密码</el-checkbox></el-form-item>
        <el-button type="primary" style="width:100%" native-type="submit" :loading="loading">登录</el-button>
        <el-button link type="primary" @click="forgot">忘记密码</el-button>
      </el-form>
    </div>
    <el-dialog v-model="pick" title="选择公司" width="420px" :close-on-click-modal="false">
      <el-radio-group v-model="companyId">
        <el-radio v-for="item in companies" :key="item.id" :value="item.id" style="display:block;margin:8px 0">{{ item.short_name }}</el-radio>
      </el-radio-group>
      <template #footer>
        <el-button type="primary" @click="enter">进入系统</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import http from "../api";
import BrandLogo from "../components/BrandLogo.vue";

const router = useRouter();
const form = reactive({ login_name: "", password: "" });
const remember = ref(false);
const loading = ref(false);
const pick = ref(false);
const companies = ref([]);
const companyId = ref(null);
const token = ref("");

onMounted(() => {
  const saved = localStorage.getItem("remember_login");
  if (saved) {
    const data = JSON.parse(saved);
    form.login_name = data.login_name;
    form.password = data.password;
    remember.value = true;
  }
});

async function submit() {
  loading.value = true;
  try {
    const res = await http.post("/api/auth/login", form);
    if (remember.value) localStorage.setItem("remember_login", JSON.stringify({ login_name: form.login_name, password: form.password }));
    else localStorage.removeItem("remember_login");
    token.value = res.data.token;
    localStorage.setItem("token", token.value);
    localStorage.setItem("user", JSON.stringify(res.data.user));
    localStorage.setItem("company_id", String(res.data.user.company_id));
    companies.value = res.data.user.companies || [];
    companyId.value = res.data.user.company_id;
    if (res.data.need_choose_company) pick.value = true;
    else router.push("/home");
  } finally {
    loading.value = false;
  }
}
async function enter() {
  const res = await http.post("/api/companies/switch", { company_id: companyId.value });
  localStorage.setItem("token", res.data.token);
  localStorage.setItem("user", JSON.stringify(res.data.user));
  localStorage.setItem("company_id", String(res.data.user.company_id));
  pick.value = false;
  router.push("/home");
}
async function forgot() {
  await http.post("/api/auth/forgot-password", { login_name: form.login_name });
  ElMessage.success("邮件已发送");
}
</script>
