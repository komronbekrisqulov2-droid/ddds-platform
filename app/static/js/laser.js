/**
 * DDDS Cloud - Ultra-Low Latency Laser Pointer System
 * Normalized (0.0 to 1.0) coordinates for resolution-independent cross-screen rendering.
 */

class LaserDisplay {
    constructor(containerElement) {
        this.container = containerElement || document.body;
        this.laserEl = null;
        this.pulseEl = null;
        this.active = false;
        this.x = 0.5;
        this.y = 0.5;
        this.fadeTimeout = null;

        this.createElements();
    }

    createElements() {
        this.laserEl = document.createElement('div');
        this.laserEl.className = 'ddds-laser-dot';
        this.laserEl.style.display = 'none';

        this.pulseEl = document.createElement('div');
        this.pulseEl.className = 'ddds-laser-pulse';
        this.laserEl.appendChild(this.pulseEl);

        this.container.appendChild(this.laserEl);
    }

    update(active, normX, normY, color = '#ff2a5f', relativeElement = null) {
        if (!this.laserEl) return;

        if (!active) {
            this.active = false;
            if (this.fadeTimeout) clearTimeout(this.fadeTimeout);
            this.fadeTimeout = setTimeout(() => {
                if (!this.active) this.laserEl.style.display = 'none';
            }, 300);
            return;
        }

        this.active = true;
        if (this.fadeTimeout) clearTimeout(this.fadeTimeout);
        this.laserEl.style.display = 'block';

        let pixelX, pixelY;
        if (relativeElement && relativeElement.offsetWidth > 0 && relativeElement.offsetHeight > 0) {
            const rect = relativeElement.getBoundingClientRect();
            pixelX = rect.left + (normX * rect.width);
            pixelY = rect.top + (normY * rect.height);
        } else {
            pixelX = normX * window.innerWidth;
            pixelY = normY * window.innerHeight;
        }

        this.laserEl.style.left = `${pixelX}px`;
        this.laserEl.style.top = `${pixelY}px`;
        this.laserEl.style.backgroundColor = color;
        this.pulseEl.style.borderColor = color;
    }
}

class LaserTouchController {
    constructor(padElement, onMoveCallback) {
        this.pad = padElement;
        this.onMove = onMoveCallback;
        this.isDown = false;
        this.activePointerId = null;
        this.lastX = 0.5;
        this.lastY = 0.5;
        this.rafId = null;
        this.pendingCoord = null;

        this.init();
    }

    init() {
        if (!this.pad) return;

        // Pointer / Touch events
        this.pad.addEventListener('pointerdown', (e) => this.handlePointerDown(e), { passive: false });
        window.addEventListener('pointermove', (e) => this.handlePointerMove(e), { passive: false });
        window.addEventListener('pointerup', (e) => this.handlePointerUp(e));
        window.addEventListener('pointercancel', (e) => this.handlePointerUp(e));

        // Touch feedback indicator on the mobile touchpad
        this.touchDot = document.createElement('div');
        this.touchDot.className = 'touch-indicator-dot';
        this.touchDot.style.display = 'none';
        this.pad.appendChild(this.touchDot);
    }

    handlePointerDown(e) {
        e.preventDefault();
        this.isDown = true;
        this.activePointerId = e.pointerId;
        this.pad.setPointerCapture(e.pointerId);
        this.updateCoord(e, true);
    }

    handlePointerMove(e) {
        if (!this.isDown || e.pointerId !== this.activePointerId) return;
        e.preventDefault();
        this.updateCoord(e, true);
    }

    handlePointerUp(e) {
        if (!this.isDown || e.pointerId !== this.activePointerId) return;
        this.isDown = false;
        this.activePointerId = null;
        if (this.touchDot) this.touchDot.style.display = 'none';
        if (this.onMove) {
            this.onMove(false, this.lastX, this.lastY);
        }
    }

    updateCoord(e, active) {
        const rect = this.pad.getBoundingClientRect();
        const touchX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
        const touchY = Math.max(0, Math.min(rect.height, e.clientY - rect.top));

        const normX = touchX / rect.width;
        const normY = touchY / rect.height;

        this.lastX = normX;
        this.lastY = normY;

        // Show local indicator on touchpad
        if (this.touchDot) {
            this.touchDot.style.display = 'block';
            this.touchDot.style.left = `${touchX}px`;
            this.touchDot.style.top = `${touchY}px`;
        }

        // Throttle transmission using requestAnimationFrame
        this.pendingCoord = { active, x: normX, y: normY };
        if (!this.rafId) {
            this.rafId = requestAnimationFrame(() => {
                if (this.pendingCoord && this.onMove) {
                    this.onMove(this.pendingCoord.active, this.pendingCoord.x, this.pendingCoord.y);
                }
                this.pendingCoord = null;
                this.rafId = null;
            });
        }
    }
}

