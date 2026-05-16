import { createRouter, createWebHistory } from 'vue-router'
import SessionListView from '../views/SessionListView.vue'
import SessionView from '../views/SessionView.vue'
import CodeView from '../views/CodeView.vue'
import IssuesView from '../views/IssuesView.vue'
import { sseClient } from '../api/events.js'

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
        { path: 'issues/:issueId', component: IssuesView },
      ],
    },
  ],
})

router.afterEach((to) => {
  const onSession = to.matched.some((r) => r.path.startsWith('/sessions/:id'))
  if (onSession && to.params.id) {
    sseClient.connect(to.params.id)
  } else {
    sseClient.disconnect()
  }
})

export default router
