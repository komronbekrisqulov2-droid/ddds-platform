/**
 * DDDS Cloud - Ultra-HD (1080p/1440p/4K 60FPS) WebRTC Live Screen Sharing Engine
 * High-performance dual-engine: WebRTC P2P primary with zero-latency hardware acceleration,
 * and adaptive real-time Canvas Frame Fallback Streamer when WebRTC P2P is firewalled.
 */

class WebRTCBroadcaster {
    constructor(client) {
        this.client = client;
        this.stream = null;
        this.peerConnections = new Map(); // targetClientId -> RTCPeerConnection
        this.pendingCandidates = new Map(); // targetClientId -> RTCIceCandidate[]
        this.isBroadcasting = false;
        this.onStop = null;
        this.needsFallback = true;
        this.verifiedReceivers = new Set();

        // Fallback Canvas Frame Streamer
        this.fallbackCanvas = document.createElement('canvas');
        this.fallbackCtx = this.fallbackCanvas.getContext('2d', { alpha: false });
        this.fallbackVideo = null;
        this.fallbackTimer = null;
        this.fallbackIntervalMs = 250; // ~4 FPS lightweight standby fallback

        this.rtcConfig = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' }
            ],
            iceCandidatePoolSize: 0,
            bundlePolicy: 'max-bundle',
            rtcpMuxPolicy: 'require'
        };

        this.initSignals();
    }

    initSignals() {
        this.client.on('webrtc_signal', async ({ type, payload }) => {
            if (!this.isBroadcasting || !this.stream) return;

            const fromClient = payload.from_client;
            if (!fromClient) return;

            // Screen requests the stream
            if (type === 'WEBRTC_REQUEST_STREAM') {
                console.log(`[WebRTC Broadcaster] Screen ${fromClient} requested stream. Initiating peer connection...`);
                await this.initiatePeerConnection(fromClient);
            }
            // Screen returned answer
            else if (type === 'WEBRTC_ANSWER') {
                if (payload.target_client && this.client.clientId && payload.target_client !== this.client.clientId) return;
                const pc = this.peerConnections.get(fromClient);
                if (pc && pc.signalingState === 'have-local-offer') {
                    try {
                        await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
                        console.log(`[WebRTC Broadcaster] Remote answer set for ${fromClient}`);

                        // Flush queued candidates
                        const pending = this.pendingCandidates.get(fromClient) || [];
                        for (const cand of pending) {
                            await pc.addIceCandidate(new RTCIceCandidate(cand)).catch(() => {});
                        }
                        this.pendingCandidates.delete(fromClient);
                    } catch (e) {
                        console.error('[WebRTC Broadcaster] Error setting remote description:', e);
                    }
                }
            }
            // ICE Candidate from screen
            else if (type === 'WEBRTC_ICE_CANDIDATE') {
                if (payload.target_client && this.client.clientId && payload.target_client !== this.client.clientId) return;
                const pc = this.peerConnections.get(fromClient);
                if (pc && payload.candidate) {
                    if (!pc.remoteDescription) {
                        if (!this.pendingCandidates.has(fromClient)) {
                            this.pendingCandidates.set(fromClient, []);
                        }
                        this.pendingCandidates.get(fromClient).push(payload.candidate);
                    } else {
                        try {
                            await pc.addIceCandidate(new RTCIceCandidate(payload.candidate));
                        } catch (e) {
                            console.warn('[WebRTC Broadcaster] Error adding ICE candidate:', e);
                        }
                    }
                }
            }
            // Screen reports WebRTC video is rendering cleanly
            else if (type === 'WEBRTC_STREAMING_OK') {
                this.verifiedReceivers.add(fromClient);
                console.log(`[WebRTC Broadcaster] Screen ${fromClient} confirmed WebRTC rendering.`);
                // If all active peer connections are rendering WebRTC, stop fallback streaming completely!
                // This eliminates continuous server CPU & WebSocket bandwidth consumption.
                if (this.peerConnections.size > 0 && this.verifiedReceivers.size >= this.peerConnections.size) {
                    this.stopFallbackStreamer();
                    this.needsFallback = false;
                    console.log('[WebRTC Broadcaster] All screens confirmed WebRTC. Fallback streamer paused (0% server load).');
                }
            }
            // Screen reports WebRTC failed, firewalled or stalled -> activate fallback
            else if (type === 'WEBRTC_NEED_FALLBACK') {
                this.verifiedReceivers.delete(fromClient);
                this.needsFallback = true;
                this.fallbackIntervalMs = 250;
                this.restartFallbackInterval();
            }
        });

        // Clean up peer connections when a client leaves
        this.client.on('clients_update', (clients) => {
            if (Array.isArray(clients)) {
                const activeIds = new Set(clients.map(c => c.client_id));
                for (const [targetId, pc] of this.peerConnections.entries()) {
                    if (!activeIds.has(targetId)) {
                        console.log(`[WebRTC Broadcaster] Cleaning up disconnected client ${targetId}`);
                        try { pc.close(); } catch (e) {}
                        this.peerConnections.delete(targetId);
                        this.pendingCandidates.delete(targetId);
                        this.verifiedReceivers.delete(targetId);
                    }
                }
            }
            if (this.isBroadcasting && this.stream) {
                this.client.sendWebRTCSignal('WEBRTC_BROADCAST_START', {
                    broadcaster_id: this.client.clientId
                });
            }
        });
    }

    async startScreenShare() {
        try {
            // First try with system audio; fall back gracefully to video-only if audio is rejected
            try {
                this.stream = await navigator.mediaDevices.getDisplayMedia({
                    video: {
                        cursor: "always",
                        width: { ideal: 1920, max: 3840 },
                        height: { ideal: 1080, max: 2160 },
                        frameRate: { ideal: 60, max: 60 }
                    },
                    audio: true
                });
            } catch (audioErr) {
                console.warn('[WebRTC Broadcaster] Retrying getDisplayMedia without audio:', audioErr);
                this.stream = await navigator.mediaDevices.getDisplayMedia({
                    video: {
                        cursor: "always",
                        width: { ideal: 1920, max: 3840 },
                        height: { ideal: 1080, max: 2160 },
                        frameRate: { ideal: 60, max: 60 }
                    },
                    audio: false
                });
            }

            this.isBroadcasting = true;
            this.needsFallback = true;
            this.verifiedReceivers.clear();

            // Preserve maximum detail for text & slides
            const videoTrack = this.stream.getVideoTracks()[0];
            if (videoTrack) {
                if ('contentHint' in videoTrack) {
                    videoTrack.contentHint = 'detail';
                }
                videoTrack.onended = () => this.stopScreenShare();
            }

            // Ensure DOM-attached fallback video element exists so Chromium compositor stays active
            this.setupFallbackVideo();
            // Fallback streamer is kept on standby and only activated if a receiver requests it via WEBRTC_NEED_FALLBACK
            this.stopFallbackStreamer();

            // Set media mode on server to screenshare
            this.client.setMediaType('screenshare');

            // Announce stream is live so all screens request their feed
            this.client.sendWebRTCSignal('WEBRTC_BROADCAST_START', {
                broadcaster_id: this.client.clientId
            });

            return { success: true, stream: this.stream };
        } catch (err) {
            console.error('[WebRTC Broadcaster] Failed to capture display:', err);
            return { success: false, error: err.message };
        }
    }

    setupFallbackVideo() {
        if (!this.fallbackVideo) {
            // Use live-video-preview if present in DOM, or create a hidden DOM-attached element
            const domPreview = document.getElementById('live-video-preview');
            if (domPreview) {
                this.fallbackVideo = domPreview;
            } else {
                this.fallbackVideo = document.createElement('video');
                this.fallbackVideo.muted = true;
                this.fallbackVideo.playsInline = true;
                this.fallbackVideo.autoplay = true;
                this.fallbackVideo.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:320px;height:180px;opacity:0.01;pointer-events:none;z-index:-1;';
                document.body.appendChild(this.fallbackVideo);
            }
        }
        this.fallbackVideo.srcObject = this.stream;
        this.fallbackVideo.play().catch(() => {});
    }

    startFallbackStreamer() {
        if (this.fallbackTimer) return;
        if (!this.stream) return;

        let isEncoding = false;
        this.fallbackTimer = setInterval(() => {
            if (!this.isBroadcasting || isEncoding) return;
            if (!this.fallbackVideo || this.fallbackVideo.readyState < 2 || this.fallbackVideo.videoWidth === 0) return;

            isEncoding = true;
            try {
                const vw = this.fallbackVideo.videoWidth;
                const vh = this.fallbackVideo.videoHeight;
                // Target: 960px width for fast, crisp, low-bandwidth WebSocket frame transmission
                const maxW = 960;
                const scale = Math.min(1.0, maxW / vw);
                const targetW = Math.round(vw * scale);
                const targetH = Math.round(vh * scale);

                if (this.fallbackCanvas.width !== targetW || this.fallbackCanvas.height !== targetH) {
                    this.fallbackCanvas.width = targetW;
                    this.fallbackCanvas.height = targetH;
                }

                this.fallbackCtx.drawImage(this.fallbackVideo, 0, 0, targetW, targetH);
                const dataUrl = this.fallbackCanvas.toDataURL('image/jpeg', 0.55);
                this.client.sendCanvasFallbackFrame(dataUrl);
            } catch (e) {
                console.warn('[WebRTC Broadcaster] Fallback frame encode error:', e);
            } finally {
                isEncoding = false;
            }
        }, this.fallbackIntervalMs);
    }

    restartFallbackInterval() {
        if (this.fallbackTimer) {
            clearInterval(this.fallbackTimer);
            this.fallbackTimer = null;
        }
        if (this.isBroadcasting && this.stream) {
            this.startFallbackStreamer();
        }
    }

    stopFallbackStreamer() {
        if (this.fallbackTimer) {
            clearInterval(this.fallbackTimer);
            this.fallbackTimer = null;
        }
    }

    async initiatePeerConnection(targetClientId) {
        if (!this.stream) return;

        let pc = this.peerConnections.get(targetClientId);
        if (pc) {
            try { pc.close(); } catch (e) {}
        }

        pc = new RTCPeerConnection(this.rtcConfig);
        this.peerConnections.set(targetClientId, pc);
        this.pendingCandidates.set(targetClientId, []);

        // Add all tracks cleanly
        this.stream.getTracks().forEach(track => {
            try {
                if (pc.addTransceiver) {
                    pc.addTransceiver(track, {
                        direction: 'sendonly',
                        streams: [this.stream]
                    });
                } else {
                    pc.addTrack(track, this.stream);
                }
            } catch (e) {
                try { pc.addTrack(track, this.stream); } catch (err2) {
                    console.error('[WebRTC Broadcaster] Add track error:', err2);
                }
            }
        });

        pc.onicecandidate = (event) => {
            if (event.candidate) {
                const candData = event.candidate.toJSON ? event.candidate.toJSON() : {
                    candidate: event.candidate.candidate,
                    sdpMid: event.candidate.sdpMid,
                    sdpMLineIndex: event.candidate.sdpMLineIndex
                };
                this.client.sendWebRTCSignal('WEBRTC_ICE_CANDIDATE', {
                    target_client: targetClientId,
                    candidate: candData
                });
            }
        };

        pc.oniceconnectionstatechange = () => {
            console.log(`[WebRTC Broadcaster] ICE state with ${targetClientId}:`, pc.iceConnectionState);
            if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected') {
                this.needsFallback = true;
                this.startFallbackStreamer();
            }
        };

        try {
            const offer = await pc.createOffer({
                offerToReceiveAudio: false,
                offerToReceiveVideo: false
            });
            await pc.setLocalDescription(offer);

            // Safe sender bitrate optimization
            try {
                const senders = pc.getSenders();
                const vSender = senders.find(s => s.track && s.track.kind === 'video');
                if (vSender && vSender.getParameters) {
                    const params = vSender.getParameters();
                    if (params) {
                        params.degradationPreference = 'maintain-resolution';
                        if (!params.encodings || params.encodings.length === 0) {
                            params.encodings = [{}];
                        }
                        params.encodings[0].maxBitrate = 20000000;
                        vSender.setParameters(params).catch(() => {});
                    }
                }
            } catch (optErr) {}

            this.client.sendWebRTCSignal('WEBRTC_OFFER', {
                target_client: targetClientId,
                sdp: {
                    type: pc.localDescription.type,
                    sdp: pc.localDescription.sdp
                }
            });
        } catch (offerErr) {
            console.error('[WebRTC Broadcaster] Error creating offer:', offerErr);
        }
    }

    stopScreenShare() {
        this.isBroadcasting = false;
        this.stopFallbackStreamer();
        this.verifiedReceivers.clear();

        if (this.stream) {
            this.stream.getTracks().forEach(t => t.stop());
            this.stream = null;
        }

        if (this.fallbackVideo && this.fallbackVideo.id !== 'live-video-preview') {
            this.fallbackVideo.srcObject = null;
        }

        this.peerConnections.forEach(pc => {
            try { pc.close(); } catch (e) {}
        });
        this.peerConnections.clear();
        this.pendingCandidates.clear();

        this.client.sendWebRTCSignal('WEBRTC_STOP', {});
        this.client.setMediaType('slides');

        if (typeof this.onStop === 'function') {
            this.onStop();
        }
    }
}


class WebRTCReceiver {
    constructor(client, videoElement, fallbackCanvasElement, loaderElement = null) {
        this.client = client;
        this.videoEl = videoElement;
        this.fallbackCanvas = fallbackCanvasElement;
        this.fallbackCtx = this.fallbackCanvas ? this.fallbackCanvas.getContext('2d') : null;
        this.loaderEl = loaderElement;
        this.peerConnection = null;
        this.videoStream = null;
        this.audioStream = null;
        this.audioEl = null;
        this.pendingCandidates = [];
        this.isConnecting = false;
        this.connectTimeout = null;
        this.hasRenderedWebRTC = false;

        this.rtcConfig = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' }
            ],
            iceCandidatePoolSize: 0,
            bundlePolicy: 'max-bundle',
            rtcpMuxPolicy: 'require'
        };

        this.init();
    }

    init() {
        // Broadcaster announces stream start -> request feed
        this.client.on('webrtc_signal', async ({ type, payload }) => {
            if (type === 'WEBRTC_BROADCAST_START') {
                console.log('[WebRTC Receiver] Broadcast started by', payload.broadcaster_id);
                this.requestStream(payload.broadcaster_id);
            }
            else if (type === 'WEBRTC_OFFER') {
                if (payload.target_client && this.client.clientId && payload.target_client !== this.client.clientId) return;
                await this.handleOffer(payload);
            }
            else if (type === 'WEBRTC_ICE_CANDIDATE') {
                if (payload.target_client && this.client.clientId && payload.target_client !== this.client.clientId) return;
                if (!this.peerConnection || !this.peerConnection.remoteDescription) {
                    if (payload.candidate) this.pendingCandidates.push(payload.candidate);
                } else if (payload.candidate) {
                    try {
                        await this.peerConnection.addIceCandidate(new RTCIceCandidate(payload.candidate));
                    } catch (e) {
                        console.warn('[WebRTC Receiver] Error adding ICE candidate:', e);
                    }
                }
            }
            else if (type === 'WEBRTC_STOP') {
                this.stopReceiver();
            }
        });

        // State Catch-Up: check if screenshare is active
        this.client.on('sync_state', ({ state }) => {
            if (state.active_media_type === 'screenshare') {
                if (!this.hasRenderedWebRTC && !this.isConnecting) {
                    this.requestStream();
                }
            } else {
                if (this.peerConnection) {
                    this.stopReceiver();
                }
            }
        });

        // Universal Canvas Fallback Streamer Handler
        this.client.on('canvas_fallback_frame', (payload) => {
            this.handleFallbackFrame(payload);
        });
    }

    requestStream(broadcasterId = null, force = false) {
        if (!force && (this.isConnecting || (this.peerConnection && this.peerConnection.connectionState === 'connected'))) {
            return;
        }
        this.isConnecting = true;
        if (this.loaderEl && !this.hasRenderedWebRTC) {
            this.loaderEl.style.display = 'flex';
        }

        this.client.sendWebRTCSignal('WEBRTC_REQUEST_STREAM', {
            screen_id: this.client.clientId,
            role: this.client.role,
            broadcaster_id: broadcasterId
        });

        clearTimeout(this.connectTimeout);
        this.connectTimeout = setTimeout(() => {
            if (!this.hasRenderedWebRTC) {
                console.warn('[WebRTC Receiver] WebRTC connection taking time, requesting fallback frame stream');
                this.isConnecting = false;
                this.client.sendWebRTCSignal('WEBRTC_NEED_FALLBACK', {
                    screen_id: this.client.clientId
                });
            }
        }, 5000);
    }

    async handleOffer(payload) {
        if (!payload.sdp) return;
        const senderClient = payload.from_client;

        const earlyCandidates = [...this.pendingCandidates];
        this.pendingCandidates = [];

        if (this.peerConnection) {
            try { this.peerConnection.close(); } catch (e) {}
        }

        // Initialize decoupled streams
        if (this.videoStream) {
            this.videoStream.getTracks().forEach(t => { try { t.stop(); } catch(e){} });
        }
        this.videoStream = new MediaStream();

        if (this.audioStream) {
            this.audioStream.getTracks().forEach(t => { try { t.stop(); } catch(e){} });
        }
        this.audioStream = new MediaStream();

        // Ensure independent audio element exists
        if (!this.audioEl) {
            this.audioEl = document.getElementById('webrtc-stream-audio');
            if (!this.audioEl) {
                this.audioEl = document.createElement('audio');
                this.audioEl.id = 'webrtc-stream-audio';
                this.audioEl.style.display = 'none';
                document.body.appendChild(this.audioEl);
            }
        }
        this.audioEl.autoplay = true;
        this.audioEl.srcObject = this.audioStream;
        // Screen 2 is muted to avoid acoustic feedback; Screen 1 plays audio
        this.audioEl.muted = (this.client.role === 'screen_2');

        if (this.videoEl) {
            // CRITICAL: Video element MUST ALWAYS remain muted!
            // Decoupling audio from video guarantees Chromium Autoplay Policy never freezes video after 2 seconds!
            this.videoEl.muted = true;
            this.videoEl.playsInline = true;
            this.videoEl.autoplay = true;
            this.videoEl.srcObject = this.videoStream;
        }

        this.peerConnection = new RTCPeerConnection(this.rtcConfig);

        this.peerConnection.ontrack = (event) => {
            console.log(`[WebRTC Receiver] Track received: ${event.track.kind}`, event.track);

            if (event.track.kind === 'video' && this.videoEl) {
                // Ensure fresh MediaStream with track directly attached
                this.videoStream = new MediaStream([event.track]);
                this.videoEl.srcObject = this.videoStream;
                this.videoEl.muted = true;
                this.videoEl.playsInline = true;
                this.videoEl.autoplay = true;
                this.videoEl.style.display = 'block';

                let framesCount = 0;
                const checkFrame = () => {
                    if (this.videoEl && this.videoEl.videoWidth > 0 && this.videoEl.readyState >= 2) {
                        framesCount++;
                        if (framesCount >= 2) {
                            this.hasRenderedWebRTC = true;
                            this.isConnecting = false;
                            if (this.fallbackCanvas) this.fallbackCanvas.style.display = 'none';
                            if (this.loaderEl) this.loaderEl.style.display = 'none';
                            this.client.sendWebRTCSignal('WEBRTC_STREAMING_OK', {});
                        }
                    }
                };

                this.videoEl.onplaying = checkFrame;
                this.videoEl.ontimeupdate = checkFrame;
                if ('requestVideoFrameCallback' in this.videoEl) {
                    const rvfc = () => {
                        checkFrame();
                        if (this.videoEl && this.videoStream) this.videoEl.requestVideoFrameCallback(rvfc);
                    };
                    this.videoEl.requestVideoFrameCallback(rvfc);
                }

                this.videoEl.play().catch(e => console.warn('[WebRTC Receiver] play() rejection:', e));

                // Active Health Watchdog: Ensures video track remains healthy without false alarms on static slides
                clearInterval(this.watchdogTimer);
                this.watchdogTimer = setInterval(() => {
                    if (!this.peerConnection) return;
                    if (this.peerConnection.iceConnectionState === 'failed' || this.peerConnection.iceConnectionState === 'disconnected') {
                        console.warn('[WebRTC Receiver] ICE connection disconnected, activating fallback');
                        if (this.fallbackCanvas) this.fallbackCanvas.style.display = 'block';
                        this.client.sendWebRTCSignal('WEBRTC_NEED_FALLBACK', {
                            screen_id: this.client.clientId
                        });
                    } else if (this.videoEl && this.videoEl.videoWidth > 0 && this.hasRenderedWebRTC) {
                        // Keep fallback canvas hidden as long as WebRTC video is rendering
                        if (this.fallbackCanvas) this.fallbackCanvas.style.display = 'none';
                    }
                }, 2000);

                event.track.onunmute = () => {
                    this.videoEl.play().catch(() => {});
                    checkFrame();
                };
            } else if (event.track.kind === 'audio') {
                this.audioStream.addTrack(event.track);
                if (this.audioEl && !this.audioEl.muted) {
                    this.audioEl.play().catch(err => {
                        console.warn('[WebRTC Receiver] Audio autoplay paused by policy, click unmute:', err);
                    });
                }
                const unmuteBtn = document.getElementById('btn-unmute-stream');
                if (unmuteBtn) {
                    unmuteBtn.style.display = 'inline-flex';
                    if (this.audioEl && this.audioEl.muted) {
                        unmuteBtn.textContent = "🔇 Ovoz O'chiq";
                        unmuteBtn.style.borderColor = '#ef4444';
                        unmuteBtn.style.color = '#ef4444';
                    } else {
                        unmuteBtn.textContent = "🔊 Ovoz Faol";
                        unmuteBtn.style.borderColor = '#10b981';
                        unmuteBtn.style.color = '#10b981';
                    }
                }
            }
        };

        this.peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                const candData = event.candidate.toJSON ? event.candidate.toJSON() : {
                    candidate: event.candidate.candidate,
                    sdpMid: event.candidate.sdpMid,
                    sdpMLineIndex: event.candidate.sdpMLineIndex
                };
                this.client.sendWebRTCSignal('WEBRTC_ICE_CANDIDATE', {
                    target_client: senderClient,
                    candidate: candData
                });
            }
        };

        this.peerConnection.oniceconnectionstatechange = () => {
            console.log('[WebRTC Receiver] ICE Connection State:', this.peerConnection.iceConnectionState);
            if (this.peerConnection.iceConnectionState === 'failed' || this.peerConnection.iceConnectionState === 'disconnected') {
                this.client.sendWebRTCSignal('WEBRTC_NEED_FALLBACK', {
                    screen_id: this.client.clientId
                });
            }
        };
        this.peerConnection.onconnectionstatechange = () => {
            console.log('[WebRTC Receiver] Connection State:', this.peerConnection.connectionState);
            if (this.peerConnection.connectionState === 'connected') {
                this.isConnecting = false;
            }
        };

        try {
            await this.peerConnection.setRemoteDescription(new RTCSessionDescription(payload.sdp));

            // Flush queued candidates
            for (const cand of earlyCandidates) {
                try {
                    await this.peerConnection.addIceCandidate(new RTCIceCandidate(cand));
                } catch (e) {}
            }
            for (const cand of this.pendingCandidates) {
                try {
                    await this.peerConnection.addIceCandidate(new RTCIceCandidate(cand));
                } catch (e) {}
            }
            this.pendingCandidates = [];

            const answer = await this.peerConnection.createAnswer({
                offerToReceiveVideo: true,
                offerToReceiveAudio: true
            });
            await this.peerConnection.setLocalDescription(answer);

            this.client.sendWebRTCSignal('WEBRTC_ANSWER', {
                target_client: senderClient,
                sdp: {
                    type: this.peerConnection.localDescription.type,
                    sdp: this.peerConnection.localDescription.sdp
                }
            });
        } catch (err) {
            console.error('[WebRTC Receiver] Error in handleOffer:', err);
        }
    }

    toggleAudio() {
        if (!this.audioEl) return false;
        this.audioEl.muted = !this.audioEl.muted;
        if (!this.audioEl.muted) {
            this.audioEl.play().catch(() => {});
        }
        return !this.audioEl.muted;
    }

    handleFallbackFrame(payload) {
        if (!payload || !payload.frame) return;
        // If WebRTC is actively playing video frames, skip canvas drawing to save CPU
        if (this.hasRenderedWebRTC && this.videoEl && !this.videoEl.paused && this.videoEl.readyState >= 2) {
            return;
        }

        if (!this.fallbackCanvas || !this.fallbackCtx) return;

        const img = new Image();
        img.onload = () => {
            if (this.hasRenderedWebRTC && this.videoEl && !this.videoEl.paused && this.videoEl.readyState >= 2) {
                return;
            }
            if (this.fallbackCanvas.width !== img.width || this.fallbackCanvas.height !== img.height) {
                this.fallbackCanvas.width = img.width;
                this.fallbackCanvas.height = img.height;
            }
            this.fallbackCtx.drawImage(img, 0, 0);
            this.fallbackCanvas.style.display = 'block';
            if (this.videoEl && !this.hasRenderedWebRTC) {
                this.videoEl.style.display = 'none';
            }
            if (this.loaderEl) {
                this.loaderEl.style.display = 'none';
            }
        };
        img.src = payload.frame;
    }

    stopReceiver() {
        if (this.peerConnection) {
            try { this.peerConnection.close(); } catch (e) {}
            this.peerConnection = null;
        }
        if (this.videoStream) {
            this.videoStream.getTracks().forEach(t => { try { t.stop(); } catch(e){} });
            this.videoStream = null;
        }
        if (this.audioStream) {
            this.audioStream.getTracks().forEach(t => { try { t.stop(); } catch(e){} });
            this.audioStream = null;
        }
        if (this.audioEl) {
            this.audioEl.srcObject = null;
        }
        this.pendingCandidates = [];
        this.isConnecting = false;
        this.hasRenderedWebRTC = false;
        clearTimeout(this.connectTimeout);
        clearInterval(this.watchdogTimer);
        this.watchdogTimer = null;

        if (this.videoEl) {
            this.videoEl.srcObject = null;
            this.videoEl.style.display = 'none';
        }
        if (this.fallbackCanvas) {
            this.fallbackCanvas.style.display = 'none';
        }
        if (this.loaderEl) {
            this.loaderEl.style.display = 'none';
        }
        const unmuteBtn = document.getElementById('btn-unmute-stream');
        if (unmuteBtn) unmuteBtn.style.display = 'none';
    }
}
