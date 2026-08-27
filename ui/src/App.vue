<template>
  <RouterView />
</template>

<script>
export default {
  name: 'App',
}
</script>

<style>
/*
 * Theme variables. All colors must reference a variable here — no inline hex
 * literals in component styles. Add a new variable rather than introducing one
 * inline, so dark mode keeps working.
 *
 * Categories:
 *   bg-*       page/panel/row backgrounds
 *   border-*   dividers and outlines
 *   text-*     foreground text (text > dim > muted > faint > gutter)
 *   link/primary  brand color (interactive accents)
 *   danger     destructive/error accent
 *   badge-*    label backgrounds + matching text (todo, orphan)
 *   severity-* P0/P1/P2/NONE issue indicators
 *   status-*   reviewed/partial/connected/error state dots and pills
 *   shadow/overlay  modal scrims
 */
:root {
  /* Backgrounds */
  --bg-base:              #f5f5f5;  /* page */
  --bg-surface:           #ffffff;  /* cards, modals, code area */
  --bg-surface2:          #fafafa;  /* right-pane panels */
  --bg-gutter:            #f8f8f8;  /* code line gutter */
  --bg-hover:             #f0f4ff;  /* row hover */
  --bg-selected:          #cce5ff;  /* selected line/row */
  --bg-reviewed:          #e6ffe6;  /* reviewed line row */
  --bg-reviewed-selected: #b3d9ff;  /* reviewed + selected */
  --bg-gutter-selected:   #b3ccff;  /* gutter on selected line */
  --bg-active-file:       #dce8ff;  /* current file in tree */

  /* Borders */
  --border:               #dddddd;  /* default */
  --border-light:         #f0f0f0;  /* subtle row dividers */
  --border-mid:           #e0e0e0;  /* between sections */

  /* Text (decreasing contrast: text > dim > muted > faint > gutter) */
  --text:                 #333333;
  --text-dim:             #555555;
  --text-muted:           #888888;
  --text-faint:           #aaaaaa;  /* timestamps, empty-state hints */
  --text-gutter:          #999999;  /* line numbers */

  /* Brand */
  --link:                 #0066cc;
  --primary:              #0066cc;
  --primary-hover:        #0052a3;

  /* Destructive */
  --danger:               #dc3545;

  /* Badges (background + paired text color) */
  --badge-todo-bg:        #fff3cd;
  --badge-todo-text:      #856404;
  --badge-orphan-bg:      #f8d7da;
  --badge-orphan-text:    #842029;

  /* Issue severity (P0/P1/P2/NONE dots and pills) */
  --severity-p0:          #dc3545;
  --severity-p1:          #fd7e14;
  --severity-p2:          #0dcaf0;
  --severity-none:        #adb5bd;

  /* Status indicators (file review state, SSE connection, issue resolution) */
  --status-success:       #4caf50;  /* reviewed, connected, resolved */
  --status-warning:       #ff9800;  /* partial, connecting */
  --status-error:         #e53935;  /* disconnected */

  /* Effects */
  --shadow:               rgba(0,0,0,0.18);
  --overlay:              rgba(0,0,0,0.4);
}

html.dark {
  --bg-base:              #1e1e1e;
  --bg-surface:           #252526;
  --bg-surface2:          #2d2d2d;
  --bg-gutter:            #2a2a2a;
  --bg-hover:             #2a2d3e;
  --bg-selected:          #1e3a58;
  --bg-reviewed:          #1a3320;
  --bg-reviewed-selected: #1a2f47;
  --bg-gutter-selected:   #2a3f5f;
  --bg-active-file:       #1e3a5f;
  --border:               #3c3c3c;
  --border-light:         #2a2a2a;
  --border-mid:           #383838;
  --text:                 #d4d4d4;
  --text-dim:             #9d9d9d;
  --text-muted:           #858585;
  --text-faint:           #6e7681;
  --text-gutter:          #6e7681;
  --link:                 #4d9de0;
  --primary:              #4d9de0;
  --primary-hover:        #3a8fd6;
  --danger:               #f1534a;
  --badge-todo-bg:        #3a2e00;
  --badge-todo-text:      #e6b800;
  --badge-orphan-bg:      #3a1a1a;
  --badge-orphan-text:    #f1534a;
  --severity-p0:          #e74c3c;
  --severity-p1:          #ff9f43;
  --severity-p2:          #4dd0e1;
  --severity-none:        #6c757d;
  --status-success:       #66bb6a;
  --status-warning:       #ffa726;
  --status-error:         #ef5350;
  --shadow:               rgba(0,0,0,0.5);
  --overlay:              rgba(0,0,0,0.6);
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg-base);
  color: var(--text);
}

.session-layout {
  height: 100vh;
  overflow: hidden;
}

.file-tree-sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  height: 100%;
}

.code-viewer-main {
  overflow: auto;
  background: var(--bg-surface);
  min-width: 0;
  height: 100%;
}

.code-viewer-main.wrap-lines {
  overflow-x: hidden;
}

.code-viewer-main.wrap-lines table.code-table {
  table-layout: fixed;
  width: 100%;
}

.code-viewer-main.wrap-lines .code-cell {
  white-space: pre-wrap;
  word-break: break-all;
  overflow-wrap: anywhere;
}

.right-panels {
  background: var(--bg-surface2);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 0;
}

table.code-table {
  border-collapse: collapse;
  width: 100%;
  font-family: 'Fira Mono', 'Consolas', 'Monaco', monospace;
  font-size: 13px;
}

table.code-table tr {
  border-bottom: 1px solid var(--border-light);
}

table.code-table tr.reviewed {
  background: var(--bg-reviewed);
}

table.code-table tr.selected {
  background: var(--bg-selected);
}

table.code-table tr.reviewed.selected {
  background: var(--bg-reviewed-selected);
}

table.code-table tr.cursor td:first-child {
  box-shadow: inset 3px 0 0 var(--text);
}

table.code-table tr.anchor td:first-child {
  box-shadow: inset 3px 0 0 var(--status-warning);
}

table.code-table tr.cursor.anchor td:first-child {
  box-shadow: inset 3px 0 0 var(--text);
}

.gutter-cell {
  width: 52px;
  min-width: 52px;
  text-align: right;
  padding: 0 8px;
  color: var(--text-gutter);
  -webkit-user-select: none;
  user-select: none;
  cursor: pointer;
  font-size: 12px;
  background: var(--bg-gutter);
  border-right: 1px solid var(--border-mid);
  vertical-align: top;
  line-height: 1.5;
}

.gutter-cell.gutter-selected {
  background: var(--bg-gutter-selected);
  color: var(--text);
}

.code-cell {
  padding: 0 8px;
  white-space: pre;
  line-height: 1.5;
  vertical-align: top;
}

.code-cell code {
  font-family: inherit;
  font-size: inherit;
}

.panel-section {
  padding: 12px;
  border-bottom: 1px solid var(--border-mid);
}

.panel-section h3 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.note-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-mid);
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.note-card .note-meta {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.note-card .note-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  margin-left: 4px;
}

.badge-todo {
  background: var(--badge-todo-bg);
  color: var(--badge-todo-text);
}

.badge-orphan {
  background: var(--badge-orphan-bg);
  color: var(--badge-orphan-text);
}

.coverage-bar-wrap {
  height: 6px;
  background: var(--bg-base);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 2px;
}

.coverage-bar-fill {
  height: 100%;
  background: var(--status-success);
  border-radius: 3px;
  transition: width 0.3s;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-box {
  background: var(--bg-surface);
  border-radius: 6px;
  padding: 20px;
  width: 480px;
  max-width: 90vw;
  box-shadow: 0 8px 32px var(--shadow);
}

.modal-box h3 {
  margin-bottom: 12px;
  font-size: 15px;
}

.modal-box textarea {
  width: 100%;
  min-height: 100px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
  resize: vertical;
  font-family: inherit;
  background: var(--bg-surface);
  color: var(--text);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

/*
 * Button system. The bare <button> baseline is equivalent to `.btn` — use
 * `.btn` only on non-button elements (links, etc.) that need the same look.
 *
 * Pick exactly one variant per button:
 *   filled:   .btn-primary  .btn-danger
 *   outlined: .btn-outline-primary  .btn-outline-success  .btn-outline-danger  .btn-outline-muted
 *   minimal:  .btn-ghost    .btn-icon    .btn-link
 *   (no variant) = default outlined neutral
 *
 * Optional modifiers:
 *   .btn-sm     smaller padding/font
 *   .btn-block  width: 100%
 */
.btn,
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.2;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.btn:hover:not(:disabled),
button:hover:not(:disabled) {
  background: var(--bg-hover);
}

.btn:disabled,
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
}

.btn-danger {
  background: var(--danger);
  border-color: var(--danger);
  color: #fff;
}

.btn-danger:hover:not(:disabled) {
  background: var(--danger);
  border-color: var(--danger);
  opacity: 0.9;
}

.btn-outline-primary {
  background: transparent;
  border-color: var(--primary);
  color: var(--primary);
}
.btn-outline-primary:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
}

.btn-outline-success {
  background: transparent;
  border-color: var(--status-success);
  color: var(--status-success);
}
.btn-outline-success:hover:not(:disabled) {
  background: var(--status-success);
  color: #fff;
}

.btn-outline-danger {
  background: transparent;
  border-color: var(--danger);
  color: var(--danger);
}
.btn-outline-danger:hover:not(:disabled) {
  background: var(--danger);
  color: #fff;
}

.btn-outline-muted {
  background: transparent;
  border-color: var(--text-muted);
  color: var(--text-muted);
}
.btn-outline-muted:hover:not(:disabled) {
  background: var(--text-muted);
  color: #fff;
}

.btn-ghost {
  background: transparent;
  border-color: transparent;
}

.btn-icon {
  background: transparent;
  border-color: transparent;
  padding: 0;
  width: 28px;
  height: 28px;
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1;
}
.btn-icon:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text);
}

.btn-icon.btn-sm {
  width: 20px;
  height: 20px;
  font-size: 12px;
  padding: 0;
}

.btn-link {
  background: none;
  border: none;
  padding: 0;
  color: var(--primary);
  font-weight: 500;
  font-size: inherit;
  white-space: normal;
  text-align: left;
}
.btn-link:hover:not(:disabled) {
  background: none;
  text-decoration: underline;
}

.btn-sm {
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 3px;
}

.btn-block {
  width: 100%;
}

a {
  color: var(--link);
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}
</style>
