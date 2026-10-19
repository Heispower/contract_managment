<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand" @click="$router.push('/home')">
        <BrandLogo class="logo" />
        <span>{{ companyName || "合同管理系统" }}</span>
      </div>
      <el-menu class="menu" mode="horizontal" :ellipsis="true" :default-active="active" router>
        <el-menu-item index="/home">首页</el-menu-item>
        <el-menu-item index="/business">商务信息</el-menu-item>
        <el-menu-item index="/purchase-plan">采购计划</el-menu-item>
        <el-sub-menu index="number">
          <template #title>编号</template>
          <el-menu-item index="/number/contracts">合同编号</el-menu-item>
          <el-menu-item index="/number/invoices">发票编号</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="contract">
          <template #title>合同</template>
          <el-menu-item index="/contract/sale">销售合同</el-menu-item>
          <el-menu-item index="/contract/purchase">采购合同</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="wms">
          <template #title>仓储管理</template>
          <el-menu-item index="/warehouse/inbound">采购入库</el-menu-item>
          <el-menu-item index="/warehouse/outbound">销售出库</el-menu-item>
          <el-menu-item index="/warehouse/stock">库存余额</el-menu-item>
          <el-menu-item index="/warehouse/transfer">调拨记录</el-menu-item>
          <el-menu-item index="/warehouse/check">盘点记录</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="customs">
          <template #title>报关系统</template>
          <el-menu-item index="/customs/materials">报关物料清单</el-menu-item>
          <el-menu-item index="/customs/invoices">报关发票</el-menu-item>
          <el-menu-item index="/customs/clearance">清关发票</el-menu-item>
          <el-menu-item index="/customs/elements">报关要素</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="settle">
          <template #title>结算管理</template>
          <el-menu-item index="/settlement/receipt">收款单</el-menu-item>
          <el-menu-item index="/settlement/payment">付款单</el-menu-item>
          <el-menu-item index="/settlement/pending-receipt">待收款</el-menu-item>
          <el-menu-item index="/settlement/pending-payment">待付款</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="invoice">
          <template #title>发票</template>
          <el-menu-item index="/invoice/output">销项发票</el-menu-item>
          <el-menu-item index="/invoice/input">进项发票</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="stats">
          <template #title>统计</template>
          <el-menu-item index="/stats/overview">经营概况</el-menu-item>
          <el-menu-item index="/stats/customer">客户统计</el-menu-item>
          <el-menu-item index="/stats/supplier">供应商统计</el-menu-item>
          <el-menu-item index="/stats/supplier-detail">供应商往来统计</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/reminder">提醒</el-menu-item>
        <el-menu-item index="/master/info">基础资料</el-menu-item>
        <el-sub-menu index="org">
          <template #title>组织管理</template>
          <el-menu-item index="/org/user">用户</el-menu-item>
          <el-menu-item index="/org/role">角色</el-menu-item>
          <el-menu-item index="/org/dept">部门</el-menu-item>
          <el-menu-item index="/org/post">岗位</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="settings">
          <template #title>设置</template>
          <el-menu-item index="/settings/log-login">登录日志</el-menu-item>
          <el-menu-item index="/settings/log-op">操作日志</el-menu-item>
          <el-menu-item index="/settings/security">安全设置</el-menu-item>
        </el-sub-menu>
      </el-menu>
      <div class="top-actions">
        <el-button link @click="toggleTheme">{{ dark ? "亮色" : "暗色" }}</el-button>
        <el-button link @click="full">全屏</el-button>
        <el-badge :value="bell" :hidden="!bell">
          <el-button link @click="$router.push('/reminder')">通知</el-button>
        </el-badge>
        <el-dropdown>
          <span style="cursor:pointer">{{ user.name || "用户" }}</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="pwdVisible = true">修改密码</el-dropdown-item>
              <el-dropdown-item @click="companyVisible = true">选择公司</el-dropdown-item>
              <el-dropdown-item @click="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>
    <main class="page">
      <div class="page-swap">
        <router-view v-slot="{ Component }">
          <transition name="fade-page">
            <div class="page-stage" :key="route.fullPath">
              <component :is="Component" />
            </div>
          </transition>
        </router-view>
      </div>
    </main>
    <el-dialog v-model="pwdVisible" title="修改密码" width="420px">
      <el-form label-width="90px">
        <el-form-item label="旧密码"><el-input v-model="pwd.old_password" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="pwd.new_password" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" @click="changePwd">确定</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="companyVisible" title="选择公司" width="420px">
      <el-radio-group v-model="companyId">
        <el-radio v-for="item in companies" :key="item.id" :value="item.id" style="display:block;margin:8px 0">{{ item.short_name }}</el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="companyVisible = false">取消</el-button>
        <el-button type="primary" @click="switchCompany">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import http from "../api";
import BrandLogo from "../components/BrandLogo.vue";

const route = useRoute();
const router = useRouter();
const user = ref(JSON.parse(localStorage.getItem("user") || "{}"));
const companies = ref(user.value.companies || []);
const companyId = ref(user.value.company_id);
const companyName = computed(() => user.value.company_name || "");
const active = computed(() => route.path);
const dark = ref(document.documentElement.classList.contains("dark"));
const bell = ref(0);
const pwdVisible = ref(false);
const companyVisible = ref(false);
const pwd = reactive({ old_password: "", new_password: "" });

function toggleTheme() {
  dark.value = !dark.value;
  document.documentElement.classList.toggle("dark", dark.value);
  localStorage.setItem("theme", dark.value ? "dark" : "light");
}
function full() {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
}
async function loadBell() {
  try {
    const res = await http.post("/api/reminders/check");
    bell.value = res.data.bell || 0;
  } catch {
    bell.value = 0;
  }
}
async function changePwd() {
  const res = await http.post("/api/auth/change-password", pwd);
  localStorage.setItem("token", res.data.token);
  ElMessage.success("密码已修改");
  pwdVisible.value = false;
}
async function switchCompany() {
  const res = await http.post("/api/companies/switch", { company_id: companyId.value });
  localStorage.setItem("token", res.data.token);
  localStorage.setItem("company_id", String(res.data.user.company_id));
  localStorage.setItem("user", JSON.stringify(res.data.user));
  user.value = res.data.user;
  companyVisible.value = false;
  location.reload();
}
function logout() {
  localStorage.removeItem("token");
  router.push("/login");
}
onMounted(loadBell);
</script>
