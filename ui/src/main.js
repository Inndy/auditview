import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import hljs from 'highlight.js'
import { initDark } from './darkMode.js'
import { gamepad } from './input/gamepad.js'
import { attachKeyboard } from './input/keyboard.js'

const app = createApp(App)

app.config.globalProperties.$hljs = hljs

app.use(router)
initDark()
app.mount('#app')

attachKeyboard()
gamepad.start()
