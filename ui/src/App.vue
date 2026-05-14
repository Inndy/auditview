<template>
  <RouterView />
</template>

<script>
export default {
  name: 'App',
}
</script>

<style>
:root {
  --bg-base:              #f5f5f5;
  --bg-surface:           #ffffff;
  --bg-surface2:          #fafafa;
  --bg-gutter:            #f8f8f8;
  --bg-hover:             #f0f4ff;
  --bg-reviewed:          #e6ffe6;
  --bg-selected:          #cce5ff;
  --bg-reviewed-selected: #b3d9ff;
  --bg-gutter-selected:   #b3ccff;
  --bg-active-file:       #dce8ff;
  --border:               #dddddd;
  --border-light:         #f0f0f0;
  --border-mid:           #e0e0e0;
  --text:                 #333333;
  --text-muted:           #888888;
  --text-dim:             #555555;
  --text-gutter:          #999999;
  --link:                 #0066cc;
  --primary:              #0066cc;
  --primary-hover:        #0052a3;
  --danger:               #dc3545;
  --badge-todo-bg:        #fff3cd;
  --badge-todo-text:      #856404;
  --badge-orphan-bg:      #f8d7da;
  --badge-orphan-text:    #842029;
  --shadow:               rgba(0,0,0,0.18);
  --overlay:              rgba(0,0,0,0.4);
}

html.dark {
  --bg-base:              #1e1e1e;
  --bg-surface:           #252526;
  --bg-surface2:          #2d2d2d;
  --bg-gutter:            #2a2a2a;
  --bg-hover:             #2a2d3e;
  --bg-reviewed:          #1a3320;
  --bg-selected:          #1e3a58;
  --bg-reviewed-selected: #1a2f47;
  --bg-gutter-selected:   #2a3f5f;
  --bg-active-file:       #1e3a5f;
  --border:               #3c3c3c;
  --border-light:         #2a2a2a;
  --border-mid:           #383838;
  --text:                 #d4d4d4;
  --text-muted:           #858585;
  --text-dim:             #9d9d9d;
  --text-gutter:          #6e7681;
  --link:                 #4d9de0;
  --primary:              #4d9de0;
  --primary-hover:        #3a8fd6;
  --danger:               #f1534a;
  --badge-todo-bg:        #3a2e00;
  --badge-todo-text:      #e6b800;
  --badge-orphan-bg:      #3a1a1a;
  --badge-orphan-text:    #f1534a;
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
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.file-tree-sidebar {
  width: 260px;
  min-width: 180px;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  flex-shrink: 0;
}

.code-viewer-main {
  flex: 1;
  overflow: auto;
  background: var(--bg-surface);
}

.right-panels {
  width: 320px;
  min-width: 220px;
  background: var(--bg-surface2);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  flex-shrink: 0;
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

.gutter-cell {
  width: 52px;
  min-width: 52px;
  text-align: right;
  padding: 0 8px;
  color: var(--text-gutter);
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
  background: var(--border-mid);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 2px;
}

.coverage-bar-fill {
  height: 100%;
  background: #4caf50;
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

button {
  padding: 6px 14px;
  border-radius: 4px;
  border: 1px solid var(--border);
  cursor: pointer;
  font-size: 13px;
  background: var(--bg-surface);
  color: var(--text);
}

button.btn-primary {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

button.btn-primary:hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
}

button.btn-danger {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
}

a {
  color: var(--link);
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}
</style>
