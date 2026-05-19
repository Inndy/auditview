import { ref } from 'vue';

export class SSEClient {
  constructor() {
    this.sid = null;
    this.listeners = {};
    this.es = null;
    this.status = ref('disconnected');
    this._retryDelay = 1000;
    this._retryTimer = null;
    this._shutdownAt = null;
  }

  on(event, cb) {
    const arr = (this.listeners[event] ||= []);
    arr.push(cb);
    return () => {
      const i = arr.indexOf(cb);
      if (i !== -1) arr.splice(i, 1);
    };
  }

  setSessionId(sid) {
    this._close();
    this.sid = sid;
    if (sid) {
      this._setStatus('connecting');
      this._open();
    } else {
      this._setStatus('disconnected');
    }
  }

  _close() {
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
    const es = new EventSource(`/api/sessions/${this.sid}/events`);
    this.es = es;

    es.onopen = () => {
      this._retryDelay = 1000;
      this._setStatus('connected');
    };

    es.onmessage = (e) => this._dispatch('message', e);

    for (const name of ['file_changed', 'heartbeat', 'annotation_changed']) {
      es.addEventListener(name, (e) => {
        let data = {};
        try { data = JSON.parse(e.data); } catch { /* heartbeat may be empty */ }
        this._dispatch(name, data);
      });
    }

    es.addEventListener('shutdown', () => {
      this._dispatch('shutdown', {});
      this._close();
      this._setStatus('shutdown');
      this._shutdownAt = Date.now();
    });

    es.onerror = () => {
      if (this.status.value === 'shutdown' && this._shutdownAt !== null && Date.now() - this._shutdownAt < 10000) return;
      this._shutdownAt = null;
      this._scheduleRetry(this._retryDelay, 'disconnected');
      this._retryDelay = Math.min(this._retryDelay * 2, 30000);
    };
  }

  _scheduleRetry(ms, status) {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this._setStatus(status);
    this._retryTimer = setTimeout(() => {
      this._retryTimer = null;
      this._setStatus('connecting');
      this._open();
    }, ms);
  }

  _setStatus(s) {
    this.status.value = s;
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
