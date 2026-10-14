import { createRouter, createWebHashHistory } from "vue-router";
import AppLayout from "./layout/AppLayout.vue";
import Login from "./views/Login.vue";
import Home from "./views/Home.vue";
import Party from "./views/Party.vue";
import Contract from "./views/Contract.vue";
import Order from "./views/Order.vue";
import Wms from "./views/Wms.vue";
import Settle from "./views/Settle.vue";
import Invoice from "./views/Invoice.vue";
import Pending from "./views/Pending.vue";
import Reminder from "./views/Reminder.vue";
import Master from "./views/Master.vue";
import Users from "./views/Users.vue";
import Stats from "./views/Stats.vue";
import SupplierDetail from "./views/SupplierDetail.vue";
import SimpleList from "./views/SimpleList.vue";
import CustomsMaterial from "./views/CustomsMaterial.vue";
import CustomsInvoice from "./views/CustomsInvoice.vue";
import ClearanceInvoice from "./views/ClearanceInvoice.vue";
import CustomsElement from "./views/CustomsElement.vue";
import Sorry from "./views/Sorry.vue";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/login", component: Login },
    {
      path: "/",
      component: AppLayout,
      children: [
        { path: "", redirect: "/home" },
        { path: "home", component: Home },
        { path: "party/list", component: Party },
        { path: "project/list", component: SimpleList, props: { kind: "project" } },
        { path: "purchase-plan", component: SimpleList, props: { kind: "plan" } },
        { path: "contract/:direction", component: Contract, props: true },
        { path: "order/:direction", component: Order, props: true },
        { path: "warehouse/inbound", component: Wms, props: { billType: "inbound" } },
        { path: "warehouse/outbound", component: Wms, props: { billType: "outbound" } },
        { path: "warehouse/stock", component: SimpleList, props: { kind: "stock" } },
        { path: "warehouse/transfer", component: SimpleList, props: { kind: "transfer" } },
        { path: "warehouse/check", component: SimpleList, props: { kind: "check" } },
        { path: "warehouse/receipt", redirect: "/customs/materials" },
        { path: "customs/materials", component: CustomsMaterial },
        { path: "customs/invoices", component: CustomsInvoice },
        { path: "customs/clearance", component: ClearanceInvoice },
        { path: "customs/elements", component: CustomsElement },
        { path: "customs/hs", redirect: "/master/info?tab=hs" },
        { path: "customs/rates", redirect: "/master/info?tab=rate" },
        { path: "settlement/receipt", component: Settle, props: { direction: "receipt" } },
        { path: "settlement/payment", component: Settle, props: { direction: "payment" } },
        { path: "settlement/other-income", component: SimpleList, props: { kind: "income" } },
        { path: "settlement/other-expense", component: SimpleList, props: { kind: "expense" } },
        { path: "settlement/pending-receipt", component: Pending, props: { direction: "sale" } },
        { path: "settlement/pending-payment", component: Pending, props: { direction: "purchase" } },
        { path: "invoice/output", component: Invoice, props: { direction: "output" } },
        { path: "invoice/input", component: Invoice, props: { direction: "input" } },
        { path: "stats/overview", component: Stats, props: { mode: "overview" } },
        { path: "stats/customer", component: Stats, props: { mode: "customer" } },
        { path: "stats/supplier", component: Stats, props: { mode: "supplier" } },
        { path: "stats/supplier-detail", component: SupplierDetail },
        { path: "reminder", component: Reminder },
        { path: "master/info", component: Master },
        { path: "org/user", component: Users },
        { path: "org/role", component: SimpleList, props: { kind: "role" } },
        { path: "org/dept", component: SimpleList, props: { kind: "dept" } },
        { path: "org/post", component: SimpleList, props: { kind: "post" } },
        { path: "settings/log-login", component: SimpleList, props: { kind: "loginLog" } },
        { path: "settings/log-op", component: SimpleList, props: { kind: "opLog" } },
        { path: "settings/security", component: SimpleList, props: { kind: "security" } },
        { path: ":pathMatch(.*)*", component: Sorry },
      ],
    },
  ],
});

router.beforeEach((to) => {
  if (to.path !== "/login" && !localStorage.getItem("token")) return "/login";
  return true;
});

export default router;
