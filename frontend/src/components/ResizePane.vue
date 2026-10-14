<template>
  <div class="resize-pane" :style="{ height: height + 'px' }">
    <div class="resize-pane-body">
      <slot :height="Math.max(min, height - 22)" />
    </div>
    <button type="button" class="resize-pane-handle" title="拖动调整高度" @mousedown.prevent="start">拖动可显示更多行</button>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from "vue";

const props = defineProps({
  height: { type: Number, default: 280 },
  min: { type: Number, default: 160 },
  max: { type: Number, default: 720 },
});

const height = ref(props.height);
watch(() => props.height, (value) => { height.value = value; });

let startY = 0;
let startH = 0;

function move(event) {
  height.value = Math.min(props.max, Math.max(props.min, startH + event.clientY - startY));
}
function stop() {
  window.removeEventListener("mousemove", move);
  window.removeEventListener("mouseup", stop);
}
function start(event) {
  startY = event.clientY;
  startH = height.value;
  window.addEventListener("mousemove", move);
  window.addEventListener("mouseup", stop);
}
onBeforeUnmount(stop);
</script>
