import { ref } from 'vue';

export class SSEClient {
  constructor() {
    this.sid = null;
    this.listeners = {};
    this.es = null;
    this.retryDelay = 1000;
    this._stopped = true;
    this._retryTimer = null;
    this.status = ref('disconnected');
  }

  on(event, cb) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(cb);
    return () => {
      const arr = this.listeners[event];
      if (!arr) return;
      const i = arr.indexOf(cb);
      if (i !== -1) arr.splice(i, 1);
    };
  }

  connect(sessionId) {
    if (this.es && this.sid === sessionId && !this._stopped) return;
    this._teardown();
    this.sid = sessionId;
    this._stopped = false;
    this._setStatus('connecting');
    this._open();
  }

  disconnect() {
    this._stopped = true;
    this._teardown();
    this._setStatus('disconnected');
  }

  _teardown() {
    if (this._retryTimer !== null) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
    if (this.es) {
      this.es.close();
      this.es = null;
    }
  }

  _open() {
    if (this._stopped) return;

    this.es = new EventSource(`/api/sessions/${this.sid}/events`);

    this.es.onmessage = (e) => {
      this._dispatch('message', e);
    };

    for (const eventName of ['file_changed', 'heartbeat']) {
      this.es.addEventListener(eventName, (e) => {
        let data = {};
        try { data = JSON.parse(e.data); } catch { /* non-JSON heartbeat */ }
        this._dispatch(eventName, data);
      });
    }

    this.es.addEventListener('shutdown', () => {
      this._dispatch('shutdown', {});
      if (this.es) {
        this.es.close();
        this.es = null;
      }
      this._setStatus('shutdown');
      if (!this._stopped) {
        this._retryTimer = setTimeout(() => {
          this._retryTimer = null;
          if (!this._stopped) {
            this._setStatus('connecting');
            this._open();
          }
        }, 5000);
      }
    });

    this.es.onerror = () => {
      if (this.es) {
        this.es.close();
        this.es = null;
      }
      if (!this._stopped && this.status.value !== 'shutdown') {
        this._setStatus('disconnected');
        this._retryTimer = setTimeout(() => {
          this._retryTimer = null;
          if (this._stopped) return;
          this._setStatus('connecting');
          this._open();
        }, this.retryDelay);
        this.retryDelay = Math.min(this.retryDelay * 2, 30000);
      }
    };

    this.es.onopen = () => {
      this.retryDelay = 1000;
      this._setStatus('connected');
    };
  }

  _setStatus(status) {
    this.status.value = status;
  }

  _dispatch(event, data) {
    const cbs = this.listeners[event];
    if (!cbs) return;
    for (const cb of cbs.slice()) {
      try {
        const ret = cb(data);
        if (ret && typeof ret.then === 'function') {
          ret.catch((e) => console.error(`SSE ${event} handler error:`, e));
        }
      } catch (e) {
        console.error(`SSE ${event} handler error:`, e);
      }
    }
  }
}

export const sseClient = new SSEClient();
