<template>
  <div class="pad-test">
    <div class="pad-header">
      <router-link to="/" class="back-btn">&#8592;</router-link>
      <h2>Gamepad test</h2>
      <DarkModeToggle style="font-size: 16px" />
    </div>

    <div v-if="!info" class="pad-waiting">
      <p>No gamepad detected.</p>
      <p class="hint">
        Chrome only reports a pad after you press one of its buttons — press any button now.
        For a Steam Controller or Steam Deck, Steam must be running so Steam Input can present
        it as a standard (Xbox-layout) pad; the touchpads are consumed by Steam Input and are not
        visible to the browser at all.
      </p>
    </div>

    <template v-else>
      <table class="pad-info">
        <tbody>
          <tr><td>id</td><td class="mono">{{ info.id }}</td></tr>
          <tr><td>mapping</td><td class="mono">{{ info.mapping }}</td></tr>
          <tr><td>index</td><td class="mono">{{ info.index }}</td></tr>
          <tr><td>buttons / axes</td><td class="mono">{{ info.buttons }} / {{ info.axes }}</td></tr>
          <tr><td>last action</td><td class="mono">{{ lastAction || '—' }}</td></tr>
        </tbody>
      </table>

      <div class="pad-actions">
        <button @click="testRumble">Test rumble</button>
        <span v-if="!rumbleSupported" class="hint">vibrationActuator unavailable in this browser</span>
      </div>

      <h3>Buttons</h3>
      <div class="grid">
        <div v-for="(b, i) in buttons" :key="i" class="cell" :class="{ active: b.pressed }">
          <div class="cell-idx">{{ i }}</div>
          <div class="cell-name">{{ buttonNames[i] || '—' }}</div>
          <div class="cell-val mono">{{ b.value.toFixed(2) }}</div>
        </div>
      </div>

      <h3>Axes</h3>
      <div class="axis-list">
        <div v-for="(v, i) in axes" :key="i" class="axis-row">
          <span class="axis-idx">{{ i }}</span>
          <span class="axis-name">{{ axisNames[i] || '—' }}</span>
          <span class="axis-val mono">{{ v.toFixed(3) }}</span>
          <span class="axis-bar"><span class="axis-fill" :style="barStyle(v)"></span></span>
        </div>
      </div>

      <h3>Bindings</h3>
      <table class="binding-table">
        <thead><tr><th>Input</th><th>Action</th></tr></thead>
        <tbody>
          <tr v-for="row in bindingRows" :key="row.binding">
            <td class="mono">{{ row.label }}</td>
            <td>{{ row.actions }}</td>
          </tr>
        </tbody>
      </table>
      <p class="hint">
        Override a binding by setting <span class="mono">localStorage['auditview:gamepad:bindings']</span>
        to a JSON object of action id → array of input ids, e.g.
        <span class="mono">{"MARK_SELECTED": ["x"], "ADD_NOTE": ["a"]}</span>.
        Remap the physical inputs themselves (for a pad that reports triggers as axes, say) with
        <span class="mono">localStorage['auditview:gamepad:inputs']</span>, e.g.
        <span class="mono">{"rt": {"axis": 5, "dir": 1}}</span>. Both are read at page load.
      </p>
    </template>
  </div>
</template>

<script>
import { ACTIONS } from '../input/actions.js'
import { gamepad, padLabel, INPUT_LABELS } from '../input/gamepad.js'
import DarkModeToggle from '../components/DarkModeToggle.vue'

const BUTTON_NAMES = []
const AXIS_NAMES = []
for (const [id, spec] of Object.entries(gamepad.inputs)) {
  if (spec.button !== undefined) BUTTON_NAMES[spec.button] = INPUT_LABELS[id] || id
  else if (AXIS_NAMES[spec.axis] === undefined) AXIS_NAMES[spec.axis] = `axis ${spec.axis}`
}

export default {
  name: 'GamepadTestView',
  components: { DarkModeToggle },
  data() {
    return {
      buttonNames: BUTTON_NAMES,
      axisNames: AXIS_NAMES,
    }
  },
  computed: {
    info() {
      return gamepad.info.value
    },
    lastAction() {
      return gamepad.lastAction.value
    },
    buttons() {
      return gamepad.raw.value?.buttons || []
    },
    axes() {
      return gamepad.raw.value?.axes || []
    },
    rumbleSupported() {
      return Boolean(navigator.getGamepads?.()[this.info?.index]?.vibrationActuator)
    },
    bindingRows() {
      const rows = []
      for (const candidates of Object.values(gamepad.bindings)) {
        for (const c of candidates) {
          rows.push({
            binding: c.binding,
            label: padLabel(c.binding),
            actions: c.ids.map((id) => ACTIONS[id]?.label || id).join(' / '),
          })
        }
      }
      return rows.sort((a, b) => a.label.localeCompare(b.label))
    },
  },
  mounted() {
    this._unsubRaw = gamepad.subscribeRaw()
  },
  beforeUnmount() {
    this._unsubRaw?.()
  },
  methods: {
    barStyle(v) {
      return { left: v < 0 ? `${50 + v * 50}%` : '50%', width: `${Math.abs(v) * 50}%` }
    },
    testRumble() {
      gamepad.rumble(300, 0.8)
    },
  },
}
</script>

<style scoped>
.pad-test {
  padding: 20px 28px 60px;
  max-width: 780px;
  margin: 0 auto;
  font-size: 13px;
}

.pad-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}

.pad-header h2 {
  flex: 1;
  font-size: 16px;
  margin: 0;
}

.back-btn {
  color: var(--text-muted);
  text-decoration: none;
  font-size: 18px;
}

h3 {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin: 24px 0 8px;
}

.mono {
  font-family: 'Fira Mono', 'Consolas', monospace;
  font-size: 12px;
}

.hint {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.6;
}

.pad-waiting p {
  margin: 6px 0;
}

.pad-info td {
  padding: 3px 12px 3px 0;
}

.pad-info td:first-child {
  color: var(--text-muted);
}

.pad-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 6px;
}

.cell {
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 5px 7px;
  background: var(--bg-surface);
}

.cell.active {
  border-color: var(--status-success);
  background: var(--bg-hover);
}

.cell-idx {
  font-size: 10px;
  color: var(--text-faint);
}

.cell-name {
  font-size: 11px;
}

.cell-val {
  color: var(--text-muted);
}

.axis-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 3px 0;
}

.axis-idx {
  width: 16px;
  color: var(--text-faint);
  font-size: 11px;
}

.axis-name {
  width: 70px;
  font-size: 11px;
  color: var(--text-muted);
}

.axis-val {
  width: 60px;
}

.axis-bar {
  position: relative;
  flex: 1;
  height: 8px;
  background: var(--bg-gutter);
  border: 1px solid var(--border);
  border-radius: 4px;
}

.axis-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--status-success);
  border-radius: 4px;
}

.binding-table {
  width: 100%;
  border-collapse: collapse;
}

.binding-table th {
  text-align: left;
  font-size: 11px;
  font-weight: normal;
  color: var(--text-faint);
  padding: 0 6px 4px 0;
}

.binding-table td {
  padding: 3px 6px 3px 0;
  border-top: 1px solid var(--border-light);
}
</style>
