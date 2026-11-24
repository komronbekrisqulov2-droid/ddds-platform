/**
 * DDDS Cloud - Authoritative WebSocket & State Sync Client
 * Handles auto-reconnect, state catch-up, latency heartbeat, and event dispatch.
 */
class DDDSClient {
    constructor(roomId, role, authToken = null) {
        this.roomId = roomId;
        this.role = role;
        this.socket = null;
        this.version = 0;
        this.state = null;
        this.clientId = null;
        this.listeners = new Map();
        this.reconnectAttempts = 0;
        this.maxReconnectDelay = 8000;
        this.pingInterval = null;
        this.latency = 0;
        this.isConnected = false;
        this.authToken = authToken;
        this.isTerminated = false;

        this.init();
    }

    init() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const tokenQuery = this.authToken ? `?token=${encodeURIComponent(this.authToken)}` : '';
        this.wsUrl = `${protocol}//${host}/ws/${this.roomId}/${this.role}${tokenQuery}`;
        this.connect();
    }

    connect() {
        if (this.socket && (this.socket.readyState === WebSocket.CONNECTING || this.socket.readyState === WebSocket.OPEN)) {
            return;
        }

        try {
            this.socket = new WebSocket(this.wsUrl);
        } catch (e) {
            console.error('[DDDS] WebSocket connection failed:', e);
            this.scheduleReconnect();
            return;
        }

        this.socket.onopen = () => {
            console.log(`[DDDS] Connected to Room: ${this.roomId} as ${this.role}`);
            this.isConnected = true;
            this.reconnectAttempts = 0;
            if (this.authToken) {
                this.sendRaw({ type: 'AUTH', token: this.authToken });
            }
            this.startHeartbeat();
            this.emit('connection_change', { status: 'connected', latency: this.latency });
        };

        this.socket.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                this.handleMessage(msg);
            } catch (err) {
                console.error('[DDDS] Malformed WebSocket message:', err, event.data);
            }
        };

        this.socket.onclose = (event) => {
            console.warn('[DDDS] Socket closed:', event);
            this.isConnected = false;
            this.stopHeartbeat();
            this.emit('connection_change', { status: 'disconnected' });
            if (event.code === 4004 || event.reason === 'ROOM_DELETED') {
                console.warn('[DDDS] Room not found or was deleted. Stopping reconnection.');
                this.isTerminated = true;
                this.emit('room_deleted', { code: event.code, reason: event.reason });
                return;
            }
            if (!this.isTerminated) {
                this.scheduleReconnect();
            }
        };

        this.socket.onerror = (err) => {
            console.error('[DDDS] Socket error:', err);
        };
    }

    scheduleReconnect() {
        const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxReconnectDelay);
        this.reconnectAttempts++;
        console.log(`[DDDS] Reconnecting in ${Math.round(delay)}ms...`);
        setTimeout(() => this.connect(), delay);
    }

    startHeartbeat() {
        this.stopHeartbeat();
        this.pingInterval = setInterval(() => {
            if (this.isConnected && this.socket.readyState === WebSocket.OPEN) {
                this.sendRaw({
                    type: 'PING',
                    timestamp: Date.now() / 1000
                });
            }
        }, 2500);
    }

    stopHeartbeat() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    handleMessage(msg) {
        const type = msg.type;

        if (type === 'PONG') {
            const clientSentAt = msg.client_sent_at;
            const now = Date.now() / 1000;
            this.latency = Math.max(1, Math.round((now - clientSentAt) * 1000));
            this.emit('pong', { latency: this.latency });
            return;
        }

        if (type === 'SYNC_STATE') {
            const newVersion = msg.version || 0;
            // Authoritative state update / catch-up
            this.version = newVersion;
            this.state = msg.state;
            if (msg.client_id) this.clientId = msg.client_id;
            this.emit('sync_state', { state: this.state, reason: msg.reason, version: newVersion });
            return;
        }

        if (type === 'LASER_MOVE') {
            this.emit('laser_move', msg.payload);
            return;
        }

        if (type === 'DRAW_STROKE') {
            this.emit('draw_stroke', msg.payload);
            return;
        }

        if (type === 'CLEAR_DRAWINGS') {
            this.emit('clear_drawings', msg.payload);
            return;
        }

        if (type === 'VIDEO_SYNC') {
            this.emit('video_sync', msg.payload);
            return;
        }

        if (type.startsWith('WEBRTC_')) {
            this.emit('webrtc_signal', { type, payload: msg.payload });
            return;
        }

        if (type === 'CANVAS_FALLBACK_FRAME') {
            this.emit('canvas_fallback_frame', msg.payload);
            return;
        }

        if (type === 'SHOW_BANNER') {
            this.emit('show_banner', msg.payload);
            return;
        }

        if (type === 'RELOAD_PAGE') {
            console.log('[DDDS] Reload requested by admin');
            window.location.reload();
            return;
        }

        if (type === 'RGB_TEST') {
            this.emit('rgb_test', msg.payload);
            return;
        }

        if (type === 'CLIENT_JOINED' || type === 'CLIENT_LEFT') {
            this.emit('clients_update', msg.payload);
            return;
        }

        // Catch-all
        this.emit(type, msg.payload);
    }

    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    emit(event, data) {
        const cbs = this.listeners.get(event);
        if (cbs) {
            cbs.forEach(cb => {
                try {
                    cb(data);
                } catch (e) {
                    console.error(`[DDDS] Error in listener for "${event}":`, e);
                }
            });
        }
    }

    sendRaw(obj) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(obj));
        }
    }

    sendAuth(token) {
        this.authToken = token;
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.sendRaw({
                type: 'AUTH',
                token: token
            });
        }
    }

    // High-level action methods
    changeSlide(index, target = 'both') {
        this.sendRaw({
            type: 'CHANGE_SLIDE',
            payload: { index, target }
        });
    }

    nextSlide() {
        this.sendRaw({ type: 'NEXT_SLIDE', payload: {} });
    }

    prevSlide() {
        this.sendRaw({ type: 'PREV_SLIDE', payload: {} });
    }

    setDisplayMode(mode) {
        this.sendRaw({
            type: 'SET_DISPLAY_MODE',
            payload: { mode }
        });
    }

    setMediaType(mediaType) {
        this.sendRaw({
            type: 'SET_MEDIA_TYPE',
            payload: { media_type: mediaType }
        });
    }

    toggleBlackout(blackout) {
        this.sendRaw({
            type: 'TOGGLE_BLACKOUT',
            payload: { blackout }
        });
    }

    sendLaser(active, x, y, color = '#ff2a5f') {
        this.sendRaw({
            type: 'LASER_MOVE',
            payload: { active, x, y, color }
        });
    }

    sendStroke(stroke) {
        this.sendRaw({
            type: 'DRAW_STROKE',
            payload: stroke
        });
    }

    clearDrawings() {
        this.sendRaw({ type: 'CLEAR_DRAWINGS', payload: {} });
    }

    sendVideoCommand(isPlaying, currentTime, playbackRate = 1.0) {
        this.sendRaw({
            type: 'VIDEO_COMMAND',
            payload: {
                is_playing: isPlaying,
                current_time: currentTime,
                playback_rate: playbackRate
            }
        });
    }

    sendWebRTCSignal(type, payload) {
        this.sendRaw({
            type: type,
            payload: payload
        });
    }

    sendCanvasFallbackFrame(base64Frame) {
        this.sendRaw({
            type: 'CANVAS_FALLBACK_FRAME',
            payload: { frame: base64Frame }
        });
    }

    sendQuickBanner(text, duration = 10) {
        this.sendRaw({
            type: 'QUICK_BANNER',
            payload: { text, duration }
        });
    }

    toggleLock(locked) {
        this.sendRaw({
            type: 'TOGGLE_LOCK',
            payload: { locked }
        });
    }

    toggleTouchLock(touchLocked = null) {
        this.sendRaw({
            type: 'TOGGLE_TOUCH_LOCK',
            payload: { touch_locked: touchLocked }
        });
    }

    resync() {
        this.sendRaw({ type: 'RESYNC' });
    }

    reloadScreens() {
        this.sendRaw({ type: 'RELOAD_SCREENS' });
    }

    triggerRgbTest() {
        this.sendRaw({ type: 'RGB_TEST' });
    }
}

