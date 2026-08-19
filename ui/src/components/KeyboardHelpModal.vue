<template>
  <div class="modal-overlay" v-if="visible" @click.self="$emit('close')">
    <div class="modal-box help-box">
      <div class="help-header">
        <h3>Shortcuts</h3>
        <button class="btn-icon" data-modal-cancel @click="$emit('close')">✕</button>
      </div>
      <table class="help-table">
        <thead>
          <tr>
            <th>Keys</th>
            <th>Gamepad</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody v-for="group in groups" :key="group.name">
          <tr class="group-row">
            <td colspan="3">{{ group.name }}</td>
          </tr>
          <tr v-for="row in group.rows" :key="row.id">
            <td class="binding">
              <span v-for="k in row.keys" :key="k" class="key">{{ k }}</span>
            </td>
            <td class="binding">
              <span v-for="p in row.pad" :key="p" class="key">{{ p }}</span>
            </td>
            <td>{{ row.label }}</td>
          </tr>
        </tbody>
      </table>
      <p class="help-hint">
        With no anchor, j/k moves a single-line cursor. Press Space to drop an anchor, then j/k
        extends the selection from anchor to cursor. Drag the line-number gutter for a mouse range.
        A {{ countHint }} prefix repeats a motion (e.g. 10j).
      </p>
      <p class="help-hint">
        Gamepad bindings assume the standard mapping (Xbox layout — a Steam Controller or Deck
        reports this through Steam Input). Note text still needs a keyboard.
        <router-link to="/gamepad">Open the gamepad test page</router-link> to see live button
        and axis values, or to check an unusual pad.
      </p>
    </div>
  </div>
</template>

<script>
import { ACTIONS, GROUP_ORDER } from '../input/actions.js'
import { padLabel } from '../input/gamepad.js'

const KEY_LABELS = {
  ' ': 'Space',
  Escape: 'Esc',
  ArrowUp: '↑',
  ArrowDown: '↓',
}

function buildGroups() {
  const byGroup = {}
  for (const [id, action] of Object.entries(ACTIONS)) {
    if (action.keys.length === 0 && action.pad.length === 0) continue
    const rows = (byGroup[action.group] ||= [])
    rows.push({
      id,
      label: action.label,
      keys: action.keys.map((k) => KEY_LABELS[k] || k),
      pad: action.pad.map(padLabel),
    })
  }
  return GROUP_ORDER.filter((name) => byGroup[name]).map((name) => ({ name, rows: byGroup[name] }))
}

export default {
  name: 'KeyboardHelpModal',
  props: {
    visible: { type: Boolean, default: false },
  },
  emits: ['close'],
  data() {
    return {
      groups: buildGroups(),
      countHint: '{count}',
    }
  },
}
</script>

<style scoped>
.help-box {
  width: 520px;
  max-height: 80vh;
  overflow-y: auto;
}

.help-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.help-header h3 {
  font-size: 14px;
  margin: 0;
}

.help-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.help-table th {
  text-align: left;
  font-size: 11px;
  font-weight: normal;
  color: var(--text-faint);
  padding: 0 4px 4px;
}

.help-table tr + tr td {
  border-top: 1px solid var(--border-light);
}

.help-table td {
  padding: 5px 4px;
  vertical-align: top;
}

.group-row td {
  padding-top: 12px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

.binding {
  white-space: nowrap;
  width: 1%;
}

.key {
  display: inline-block;
  font-family: 'Fira Mono', 'Consolas', monospace;
  background: var(--bg-gutter);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 7px;
  margin: 1px 3px 1px 0;
  font-size: 12px;
  white-space: nowrap;
}

.help-hint {
  margin-top: 12px;
  font-size: 11px;
  color: var(--text-muted);
}
</style>
