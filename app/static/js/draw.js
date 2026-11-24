/**
 * DDDS Cloud - Multi-Screen Synced Annotation & Canvas Engine
 * High-performance freehand drawing with normalized resolution scaling.
 */

class DrawingEngine {
    constructor(canvasElement, onStrokeEndCallback) {
        this.canvas = canvasElement;
        this.ctx = canvasElement.getContext('2d');
        this.onStrokeEnd = onStrokeEndCallback;
        
        this.isDrawing = false;
        this.currentStroke = null;
        this.strokes = []; // List of all completed strokes
        
        this.activeTool = 'pen'; // 'pen', 'highlighter', 'eraser'
        this.activeColor = '#ff2a5f';
        this.activeWidth = 4;
        this.interactive = true; // Can user draw on this canvas?

        this.init();
    }

    init() {
        this.resize();
        window.addEventListener('resize', () => {
            this.resize();
            this.redrawAll();
        });

        // Pointer event listeners (supports mouse, stylus pen, finger touch)
        this.canvas.addEventListener('pointerdown', (e) => this.handlePointerDown(e));
        window.addEventListener('pointermove', (e) => this.handlePointerMove(e));
        window.addEventListener('pointerup', (e) => this.handlePointerUp(e));
        window.addEventListener('pointercancel', (e) => this.handlePointerUp(e));
    }

    setInteractive(interactive) {
        this.interactive = interactive;
        this.canvas.style.pointerEvents = interactive ? 'auto' : 'none';
    }

    resize() {
        const rect = this.canvas.parentElement ? this.canvas.parentElement.getBoundingClientRect() : { width: window.innerWidth, height: window.innerHeight };
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
    }

    handlePointerDown(e) {
        if (!this.interactive || e.button !== 0) return;
        this.isDrawing = true;
        this.canvas.setPointerCapture(e.pointerId);

        const pt = this.getNormalizedPoint(e);
        this.currentStroke = {
            id: 'str_' + Math.random().toString(36).substr(2, 9),
            tool: this.activeTool,
            color: this.activeColor,
            width: this.activeWidth,
            points: [pt],
            screen_target: 'both'
        };

        this.ctx.beginPath();
        this.ctx.moveTo(pt[0] * this.canvas.width, pt[1] * this.canvas.height);
    }

    handlePointerMove(e) {
        if (!this.isDrawing || !this.currentStroke) return;
        const pt = this.getNormalizedPoint(e);
        this.currentStroke.points.push(pt);

        // Immediate local draw for zero lag
        this.renderStrokeSegment(this.currentStroke, pt);
    }

    handlePointerUp(e) {
        if (!this.isDrawing || !this.currentStroke) return;
        this.isDrawing = false;
        this.strokes.push(this.currentStroke);

        if (this.onStrokeEnd) {
            this.onStrokeEnd(this.currentStroke);
        }
        this.currentStroke = null;
    }

    getNormalizedPoint(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left)) / rect.width;
        const y = Math.max(0, Math.min(rect.height, e.clientY - rect.top)) / rect.height;
        return [parseFloat(x.toFixed(4)), parseFloat(y.toFixed(4))];
    }

    renderStrokeSegment(stroke, newPoint) {
        const w = this.canvas.width;
        const h = this.canvas.height;
        const pts = stroke.points;
        if (pts.length < 2) return;

        const pPrev = pts[pts.length - 2];
        const pCurr = newPoint;

        this.ctx.save();
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';

        if (stroke.tool === 'eraser') {
            this.ctx.globalCompositeOperation = 'destination-out';
            this.ctx.lineWidth = stroke.width * 5;
        } else if (stroke.tool === 'highlighter') {
            this.ctx.globalCompositeOperation = 'source-over';
            this.ctx.globalAlpha = 0.35;
            this.ctx.strokeStyle = stroke.color;
            this.ctx.lineWidth = stroke.width * 4;
        } else {
            this.ctx.globalCompositeOperation = 'source-over';
            this.ctx.globalAlpha = 1.0;
            this.ctx.strokeStyle = stroke.color;
            this.ctx.lineWidth = stroke.width;
        }

        this.ctx.beginPath();
        this.ctx.moveTo(pPrev[0] * w, pPrev[1] * h);
        this.ctx.lineTo(pCurr[0] * w, pCurr[1] * h);
        this.ctx.stroke();
        this.ctx.restore();
    }

    renderFullStroke(stroke) {
        const w = this.canvas.width;
        const h = this.canvas.height;
        const pts = stroke.points;
        if (!pts || pts.length === 0) return;

        this.ctx.save();
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';

        if (stroke.tool === 'eraser') {
            this.ctx.globalCompositeOperation = 'destination-out';
            this.ctx.lineWidth = (stroke.width || 4) * 5;
        } else if (stroke.tool === 'highlighter') {
            this.ctx.globalCompositeOperation = 'source-over';
            this.ctx.globalAlpha = 0.35;
            this.ctx.strokeStyle = stroke.color || '#fbbf24';
            this.ctx.lineWidth = (stroke.width || 4) * 4;
        } else {
            this.ctx.globalCompositeOperation = 'source-over';
            this.ctx.globalAlpha = 1.0;
            this.ctx.strokeStyle = stroke.color || '#ff2a5f';
            this.ctx.lineWidth = stroke.width || 4;
        }

        this.ctx.beginPath();
        this.ctx.moveTo(pts[0][0] * w, pts[0][1] * h);
        for (let i = 1; i < pts.length; i++) {
            this.ctx.lineTo(pts[i][0] * w, pts[i][1] * h);
        }
        this.ctx.stroke();
        this.ctx.restore();
    }

    addRemoteStroke(stroke) {
        this.strokes.push(stroke);
        this.renderFullStroke(stroke);
    }

    syncAllStrokes(strokeList) {
        this.strokes = strokeList || [];
        this.redrawAll();
    }

    clear() {
        this.strokes = [];
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }

    redrawAll() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        for (const stroke of this.strokes) {
            this.renderFullStroke(stroke);
        }
    }
}

