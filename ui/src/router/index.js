import { createRouter, createWebHistory } from 'vue-router'
import SessionListView from '../views/SessionListView.vue'
import SessionView from '../views/SessionView.vue'
import CodeView from '../views/CodeView.vue'
import IssuesView from '../views/IssuesView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', component: SessionListView },
    {
      path: '/sessions/:id',
      component: SessionView,
      children: [
        { path: 'code', component: CodeView },
        { path: 'issues', component: IssuesView },
      ],
    },
  ],
})

export default router
