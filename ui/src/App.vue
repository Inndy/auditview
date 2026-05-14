<template>
  <RouterView />
</template>

<script>
export default {
  name: 'App',
}
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #f5f5f5;
  color: #333;
}

.session-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.file-tree-sidebar {
  width: 260px;
  min-width: 180px;
  background: #fff;
  border-right: 1px solid #ddd;
  overflow-y: auto;
  flex-shrink: 0;
}

.code-viewer-main {
  flex: 1;
  overflow: auto;
  background: #fff;
}

.right-panels {
  width: 320px;
  min-width: 220px;
  background: #fafafa;
  border-left: 1px solid #ddd;
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
  border-bottom: 1px solid #f0f0f0;
}

table.code-table tr.reviewed {
  background: #e6ffe6;
}

table.code-table tr.selected {
  background: #cce5ff;
}

table.code-table tr.reviewed.selected {
  background: #b3d9ff;
}

.gutter-cell {
  width: 52px;
  min-width: 52px;
  text-align: right;
  padding: 0 8px;
  color: #999;
  user-select: none;
  cursor: pointer;
  font-size: 12px;
  background: #f8f8f8;
  border-right: 1px solid #e0e0e0;
  vertical-align: top;
  line-height: 1.5;
}

.gutter-cell.gutter-selected {
  background: #b3ccff;
  color: #333;
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
  border-bottom: 1px solid #e0e0e0;
}

.panel-section h3 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.note-card {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.note-card .note-meta {
  font-size: 11px;
  color: #888;
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
  background: #fff3cd;
  color: #856404;
}

.badge-orphan {
  background: #f8d7da;
  color: #842029;
}

.coverage-bar-wrap {
  height: 6px;
  background: #e0e0e0;
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
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-box {
  background: #fff;
  border-radius: 6px;
  padding: 20px;
  width: 480px;
  max-width: 90vw;
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
}

.modal-box h3 {
  margin-bottom: 12px;
  font-size: 15px;
}

.modal-box textarea {
  width: 100%;
  min-height: 100px;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 13px;
  resize: vertical;
  font-family: inherit;
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
  border: 1px solid #ccc;
  cursor: pointer;
  font-size: 13px;
  background: #fff;
}

button.btn-primary {
  background: #0066cc;
  color: #fff;
  border-color: #0066cc;
}

button.btn-primary:hover {
  background: #0052a3;
}

button.btn-danger {
  background: #dc3545;
  color: #fff;
  border-color: #dc3545;
}

a {
  color: #0066cc;
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}
</style>
