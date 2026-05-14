import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import hljs from 'highlight.js'
import { initDark } from './darkMode.js'

const app = createApp(App)

app.config.globalProperties.$hljs = hljs

app.use(router)
app.mount('#app')

initDark()
