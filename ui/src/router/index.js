import { createRouter, createWebHistory } from 'vue-router'
import SessionListView from '../views/SessionListView.vue'
import SessionView from '../views/SessionView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', component: SessionListView },
    { path: '/sessions/:id', component: SessionView },
  ],
})

export default router
