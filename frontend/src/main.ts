import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import './styles/global.scss'

// 说明：Element Plus 曾在这里全量注册（JS + CSS 约 1MB），但项目里没有任何 <el-*> 组件或 ElMessage 调用，
// 已移除以缩小首屏主包。若以后要用，请按需引入单个组件，不要再全量 app.use()。
const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')