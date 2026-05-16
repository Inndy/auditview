import { computed, watch } from 'vue'
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
      meta: { sse: true },
      children: [
        { path: 'code', component: CodeView },
        { path: 'issues', component: IssuesView },
        { path: 'issues/:issueId', component: IssuesView },
      ],
    },
  ],
})

const sseSessionId = computed(() => {
  const r = router.currentRoute.value
  return r.meta.sse ? (r.params.id ?? null) : null
})

watch(sseSessionId, (sid) => sseClient.setSessionId(sid), { immediate: true })

export default router
