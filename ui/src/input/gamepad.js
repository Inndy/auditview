import { ref } from 'vue'
import { ACTIONS, dispatch, isModalOpen, isTextEntryFocused } from './actions.js'
import { getPref, getBoolPref } from '../prefs.js'

const BINDINGS_PREF = 'gamepad:bindings'
const INPUTS_PREF = 'gamepad:inputs'
const RUMBLE_PREF = 'gamepad:rumble'

const AXIS_DEADZONE = 0.25
const REPEAT_DELAY_MS = 250
const REPEAT_FAST_MIN_MS = 40
const REPEAT_FAST_MAX_MS = 320
const REPEAT_SLOW_MS = 400
const TRIGGER_THRESHOLD = 0.5
const SCROLL_SPEED = 2.2

/**
 * Physical layout of the W3C "standard" gamepad mapping, which is what Steam Input
 * presents for a Steam Controller / Steam Deck and what an Xbox pad reports natively.
 * Overridable via localStorage for pads that report triggers as axes or shuffle indices.
 * Repeat and continuous behavior intentionally live on actions, not physical inputs.
 */
export const DEFAULT_INPUTS = {
  a: { button: 0 },
  b: { button: 1 },
  x: { button: 2 },
  y: { button: 3 },
  lb: { button: 4 },
  rb: { button: 5 },
  lt: { button: 6 },
  rt: { button: 7 },
  back: { button: 8 },
  start: { button: 9 },
  lstick: { button: 10 },
  rstick: { button: 11 },
  dpadUp: { button: 12 },
  dpadDown: { button: 13 },
  dpadLeft: { button: 14 },
  dpadRight: { button: 15 },
  guide: { button: 16 },
  lstickUp: { axis: 1, dir: -1 },
  lstickDown: { axis: 1, dir: 1 },
  lstickLeft: { axis: 0, dir: -1, deadzone: 0.5 },
  lstickRight: { axis: 0, dir: 1, deadzone: 0.5 },
  rstickUp: { axis: 3, dir: -1 },
  rstickDown: { axis: 3, dir: 1 },
}

export const INPUT_LABELS = {
  a: 'A',
  b: 'B',
  x: 'X',
  y: 'Y',
  lb: 'LB',
  rb: 'RB',
  lt: 'LT',
  rt: 'RT',
  back: 'Back',
  start: 'Start',
  lstick: 'L-Stick click',
  rstick: 'R-Stick click',
  dpadUp: 'D-Pad ↑',
  dpadDown: 'D-Pad ↓',
  dpadLeft: 'D-Pad ←',
  dpadRight: 'D-Pad →',
  guide: 'Guide',
  lstickUp: 'L-Stick ↑',
  lstickDown: 'L-Stick ↓',
  lstickLeft: 'L-Stick ←',
  lstickRight: 'L-Stick →',
  rstickUp: 'R-Stick ↑',
  rstickDown: 'R-Stick ↓',
}

export function padLabel(binding) {
  return binding
    .split('+')
    .map((part) => INPUT_LABELS[part] || part)
    .join(' + ')
}

function loadJsonPref(key) {
  const raw = getPref(key)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      console.warn(`gamepad: ignoring auditview:${key} — expected a JSON object`)
      return null
    }
    return parsed
  } catch (e) {
    console.warn(`gamepad: ignoring auditview:${key} — invalid JSON`, e.message)
    return null
  }
}

export class GamepadService {
  constructor() {
    this.status = ref('absent')
    this.info = ref(null)
    this.raw = ref(null)
    this.lastAction = ref(null)

    this.inputs = { ...DEFAULT_INPUTS, ...loadJsonPref(INPUTS_PREF) }
    this.bindings = this._buildBindings()

    this.listeners = {}
    this._rafId = null
    this._padIndex = null
    this._prev = {}
    this._repeatAt = {}
    this._lastFrame = 0
    this._rawSubscribers = 0
    this._onConnect = null
    this._onDisconnect = null
  }

  /**
   * Build, from ACTIONS[*].pad plus any localStorage override, an index of
   * terminal input id -> candidate bindings, most-specific (most modifiers) first.
   * Held-input behavior follows the action through custom remaps. Most-specific-wins
   * is what keeps `back+a` from also firing plain `a`.
   */
  _buildBindings() {
    const override = loadJsonPref(BINDINGS_PREF) || {}
    const byInput = {}
    for (const [id, action] of Object.entries(ACTIONS)) {
      const pads = Object.hasOwn(override, id) ? override[id] : action.pad
      for (const binding of Array.isArray(pads) ? pads : [pads]) {
        if (typeof binding !== 'string' || binding === '') continue
        const parts = binding.split('+')
        const inputId = parts.pop()
        if (!this.inputs[inputId]) {
          console.warn(`gamepad: binding "${binding}" names unknown input "${inputId}"`)
          continue
        }
        const list = (byInput[inputId] ||= [])
        const existing = list.find((c) => c.binding === binding)
        if (existing) {
          existing.ids.push(id)
          if (existing.repeat !== action.padRepeat || existing.continuous !== Boolean(action.padContinuous)) {
            console.warn(`gamepad: actions sharing "${binding}" disagree on held-input behavior`)
          }
        } else {
          list.push({
            binding,
            mods: parts,
            ids: [id],
            repeat: action.padRepeat,
            continuous: Boolean(action.padContinuous),
          })
        }
      }
    }
    for (const list of Object.values(byInput)) {
      list.sort((a, b) => b.mods.length - a.mods.length)
    }
    for (const id of Object.keys(override)) {
      if (!ACTIONS[id]) console.warn(`gamepad: override names unknown action ${id}`)
    }
    return byInput
  }

  reloadBindings() {
    this.inputs = { ...DEFAULT_INPUTS, ...loadJsonPref(INPUTS_PREF) }
    this.bindings = this._buildBindings()
  }

  on(event, cb) {
    const arr = (this.listeners[event] ||= [])
    arr.push(cb)
    return () => {
      const i = arr.indexOf(cb)
      if (i !== -1) arr.splice(i, 1)
    }
  }

  _emit(event, payload) {
    for (const cb of (this.listeners[event] || []).slice()) {
      try {
        cb(payload)
      } catch (e) {
        console.error(`gamepad: listener for ${event} threw`, e)
      }
    }
  }

  /**
   * The raw snapshot is only published while something is watching it — the test
   * page — so the normal review path does not pay for reactive churn every frame.
   */
  subscribeRaw() {
    this._rawSubscribers += 1
    return () => {
      this._rawSubscribers = Math.max(0, this._rawSubscribers - 1)
      if (this._rawSubscribers === 0) this.raw.value = null
    }
  }

  start() {
    if (this._onConnect) return
    this._onConnect = (e) => this._attach(e.gamepad)
    this._onDisconnect = (e) => {
      if (e.gamepad.index === this._padIndex) this._detach()
    }
    window.addEventListener('gamepadconnected', this._onConnect)
    window.addEventListener('gamepaddisconnected', this._onDisconnect)
    // Firefox reports pads that connected before this listener was installed.
    for (const pad of navigator.getGamepads?.() || []) {
      if (pad) {
        this._attach(pad)
        break
      }
    }
  }

  stop() {
    if (this._onConnect) window.removeEventListener('gamepadconnected', this._onConnect)
    if (this._onDisconnect) window.removeEventListener('gamepaddisconnected', this._onDisconnect)
    this._onConnect = null
    this._onDisconnect = null
    this._detach()
  }

  _attach(pad) {
    if (this._padIndex !== null) return
    this._padIndex = pad.index
    this.status.value = 'connected'
    this.info.value = {
      id: pad.id,
      mapping: pad.mapping || '(non-standard)',
      index: pad.index,
      buttons: pad.buttons.length,
      axes: pad.axes.length,
    }
    this._prev = {}
    this._repeatAt = {}
    this._lastFrame = 0
    this._emit('connect', this.info.value)
    this._loop()
  }

  _detach() {
    if (this._rafId !== null) cancelAnimationFrame(this._rafId)
    this._rafId = null
    this._padIndex = null
    this.status.value = 'absent'
    this.info.value = null
    this.raw.value = null
    this._prev = {}
    this._repeatAt = {}
    this._emit('disconnect', null)
  }

  _pad() {
    // Chrome hands out immutable snapshots, so the list must be re-read every frame.
    return (navigator.getGamepads?.() || [])[this._padIndex] || null
  }

  _loop() {
    this._rafId = requestAnimationFrame((now) => {
      const pad = this._pad()
      if (!pad) {
        this._detach()
        return
      }
      const dt = this._lastFrame ? Math.min(now - this._lastFrame, 100) : 16
      this._lastFrame = now
      this._poll(pad, now, dt)
      this._loop()
    })
  }

  /** Analog value of a binding id in [0,1], and whether it counts as pressed. */
  _read(pad, spec) {
    if (spec.button !== undefined) {
      const b = pad.buttons[spec.button]
      if (!b) return { value: 0, pressed: false }
      const value = typeof b === 'object' ? b.value : b
      const pressed = typeof b === 'object' ? b.pressed || value >= TRIGGER_THRESHOLD : value >= TRIGGER_THRESHOLD
      return { value, pressed }
    }
    const raw = pad.axes[spec.axis]
    if (raw === undefined) return { value: 0, pressed: false }
    const dz = spec.deadzone ?? AXIS_DEADZONE
    const signed = raw * spec.dir
    if (signed <= dz) return { value: 0, pressed: false }
    return { value: (signed - dz) / (1 - dz), pressed: true }
  }

  _poll(pad, now, dt) {
    if (this._rawSubscribers > 0) {
      this.raw.value = {
        buttons: pad.buttons.map((b) => (
          typeof b === 'object' ? { pressed: b.pressed, value: b.value } : { pressed: b >= 0.5, value: b }
        )),
        axes: [...pad.axes],
      }
    }

    const state = {}
    for (const [id, spec] of Object.entries(this.inputs)) {
      state[id] = this._read(pad, spec)
    }

    for (const [inputId, candidates] of Object.entries(this.bindings)) {
      const spec = this.inputs[inputId]
      const cur = state[inputId]
      if (!spec || !cur) continue
      const chosen = candidates.find((c) => c.mods.every((m) => state[m]?.pressed))

      if (chosen?.continuous) {
        if (cur.pressed && chosen) {
          this._run(chosen.ids, { value: cur.value * spec.dir * SCROLL_SPEED, dt })
        }
        continue
      }

      const was = this._prev[inputId] || false
      this._prev[inputId] = cur.pressed
      if (!cur.pressed) {
        delete this._repeatAt[inputId]
        continue
      }
      if (!chosen) continue

      if (!was) {
        this._repeatAt[inputId] = chosen.repeat ? now + REPEAT_DELAY_MS : Infinity
        this._run(chosen.ids, {})
      } else if (chosen.repeat && now >= (this._repeatAt[inputId] ?? Infinity)) {
        const interval = chosen.repeat === 'slow'
          ? REPEAT_SLOW_MS
          : REPEAT_FAST_MAX_MS - (REPEAT_FAST_MAX_MS - REPEAT_FAST_MIN_MS) * cur.value
        this._repeatAt[inputId] = now + interval
        this._run(chosen.ids, {})
      }
    }
  }

  _run(ids, params) {
    const modal = isModalOpen()
    for (const id of ids) {
      const action = ACTIONS[id]
      if (!action) continue
      // Gamepad input has no event target, so the keyboard's e.target guard has to
      // become an activeElement check. Dialog actions are exempt: the caret is
      // normally inside the dialog's own text field.
      if (!modal && isTextEntryFocused()) continue
      if (dispatch(id, params)) {
        if (!action.padContinuous) this.lastAction.value = id
        this._emit('action', { id, params })
        return
      }
    }
  }

  rumble(durationMs = 60, strength = 0.4) {
    if (!getBoolPref(RUMBLE_PREF, true)) return
    const pad = this._pad()
    const actuator = pad?.vibrationActuator
    if (!actuator?.playEffect) return
    actuator
      .playEffect('dual-rumble', {
        duration: durationMs,
        strongMagnitude: strength,
        weakMagnitude: strength,
      })
      .catch(() => {})
  }
}

export const gamepad = new GamepadService()
