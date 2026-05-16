export class SSEClient {
  constructor(sessionId) {
    this.sid = sessionId;
    this.listeners = {};
    this.es = null;
    this.retryDelay = 1000;
    this._stopped = false;
    this.status = 'disconnected';
  }

  on(event, cb) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(cb);
  }

  connect() {
    this._stopped = false;
    this._setStatus('connecting');
    this._open();
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
        setTimeout(() => {
          if (!this._stopped) {
            this._setStatus('connecting');
            this._open();
          }
        }, 5000);
      }
    });

    this.es.onerror = () => {
      this.es.close();
      this.es = null;
      if (!this._stopped && this.status !== 'shutdown') {
        this._setStatus('disconnected');
        setTimeout(() => {
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
    this.status = status;
    this._dispatch('status', { status });
  }

  _dispatch(event, data) {
    if (this.listeners[event]) {
      for (const cb of this.listeners[event]) {
        cb(data);
      }
    }
  }

  disconnect() {
    this._stopped = true;
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this._setStatus('disconnected');
  }
}
