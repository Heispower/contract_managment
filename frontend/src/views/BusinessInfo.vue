<template>
  <div>
    <h2 class="page-title">商务信息</h2>
    <el-tabs v-model="tab" class="business-tabs" @tab-change="onTab">
      <el-tab-pane label="客商" name="party" lazy>
        <Party embedded />
      </el-tab-pane>
      <el-tab-pane label="项目" name="project" lazy>
        <SimpleList kind="project" embedded />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Party from "./Party.vue";
import SimpleList from "./SimpleList.vue";

const route = useRoute();
const router = useRouter();
const tab = ref(route.query.tab === "project" ? "project" : "party");

watch(
  () => route.query.tab,
  (value) => {
    tab.value = value === "project" ? "project" : "party";
  },
);

function onTab(name) {
  router.replace({ path: "/business", query: { tab: name } });
}
</script>
