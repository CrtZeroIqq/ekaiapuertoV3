/**
 * EKAIA Puerto - Dashboard v2
 * Real-time vehicle tracking with persistence
 */

class EkaiaDashboard {
    constructor() {
        this.ws = null;
        this.reconnectInterval = 3000;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.isConnected = false;
        this.recentPlates = [];
        this.maxRecentPlates = 5;
        this.stats = {
            vehiclesInside: 0,
            entriesToday: 0,
            exitsToday: 0,
            avgDuration: 0
        };
        
        // Load persisted data
        this.loadPersistedData();
        this.init();
    }
    
    init() {
        console.log('EKAIA Dashboard v2.0 initializing...');
        
        this.updateDateTime();
        setInterval(() => this.updateDateTime(), 1000);
        
        this.setupWebSocket();
        this.setupStreamMonitoring();
        this.loadInitialData();
        
        const startTimeEl = document.getElementById('system-start-time');
        if (startTimeEl) {
            startTimeEl.textContent = new Date().toLocaleTimeString('es-CL');
        }
        
        // Restore last detection if available
        this.restoreLastDetection();
        
        console.log('Dashboard initialized');
    }
    
    // ==========================================
    // Persistence
    // ==========================================
    
    loadPersistedData() {
        try {
            const saved = localStorage.getItem('ekaia_dashboard');
            if (saved) {
                const data = JSON.parse(saved);
                this.recentPlates = data.recentPlates || [];
                console.log('Loaded persisted data:', data);
            }
        } catch (e) {
            console.warn('Could not load persisted data:', e);
        }
    }
    
    savePersistedData() {
        try {
            const data = {
                recentPlates: this.recentPlates.slice(0, this.maxRecentPlates),
                lastDetection: this.lastDetection,
                savedAt: new Date().toISOString()
            };
            localStorage.setItem('ekaia_dashboard', JSON.stringify(data));
        } catch (e) {
            console.warn('Could not save persisted data:', e);
        }
    }
    
    restoreLastDetection() {
        try {
            const saved = localStorage.getItem('ekaia_dashboard');
            if (saved) {
                const data = JSON.parse(saved);
                if (data.lastDetection) {
                    this.displayDetection(data.lastDetection, false);
                }
                if (data.recentPlates && data.recentPlates.length > 0) {
                    this.renderRecentPlates();
                }
            }
        } catch (e) {
            console.warn('Could not restore last detection:', e);
        }
    }
    
    // ==========================================
    // WebSocket Connection
    // ==========================================
    
    setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/realtime`;
        
        console.log('Connecting to:', wsUrl);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus(true);
                this.addLogEntry('Conexion establecida con el servidor', 'success');
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleRealtimeUpdate(data);
                } catch (e) {
                    console.error('Error parsing WebSocket data:', e);
                }
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.isConnected = false;
                this.updateConnectionStatus(false);
                
                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    console.log(`Reconnecting... (attempt ${this.reconnectAttempts})`);
                    setTimeout(() => this.setupWebSocket(), this.reconnectInterval);
                } else {
                    this.addLogEntry('Conexion perdida. Recargue la pagina.', 'error');
                }
            };
        } catch (e) {
            console.error('WebSocket setup error:', e);
            setTimeout(() => this.setupWebSocket(), this.reconnectInterval);
        }
    }
    
    handleRealtimeUpdate(data) {
        // Always update stats first
        if (data.stats) {
            this.updateStats(data.stats);
        }
        
        // Update camera status
        if (data.cameras) {
            this.updateCameraStatus(data.cameras);
        }
        
        // Handle new detection
        if (data.detection && data.detection.plate) {
            this.handleNewDetection(data.detection);
        }
    }
    
    // ==========================================
    // UI Updates
    // ==========================================
    
    updateConnectionStatus(connected) {
        const badge = document.getElementById('connection-badge');
        const systemStatus = document.getElementById('system-status');
        
        if (!badge) return;
        
        if (connected) {
            badge.className = 'flex items-center gap-2 px-4 py-2 rounded-full bg-green-500/20 border border-green-500/30 transition-all duration-300';
            badge.innerHTML = `
                <div class="w-2 h-2 rounded-full bg-green-500"></div>
                <span class="text-sm font-medium text-green-400">Conectado</span>
            `;
            if (systemStatus) {
                systemStatus.className = 'absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-surface-800 status-pulse';
            }
        } else {
            badge.className = 'flex items-center gap-2 px-4 py-2 rounded-full bg-red-500/20 border border-red-500/30 transition-all duration-300';
            badge.innerHTML = `
                <div class="w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>
                <span class="text-sm font-medium text-red-400">Desconectado</span>
            `;
            if (systemStatus) {
                systemStatus.className = 'absolute -bottom-1 -right-1 w-4 h-4 bg-red-500 rounded-full border-2 border-surface-800';
            }
        }
    }
    
    updateDateTime() {
        const now = new Date();
        
        const timeEl = document.getElementById('current-time');
        const dateEl = document.getElementById('current-date');
        
        if (timeEl) {
            timeEl.textContent = now.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }
        
        if (dateEl) {
            dateEl.textContent = now.toLocaleDateString('es-CL', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
        }
    }
    
    updateStats(stats) {
        console.log('Updating stats:', stats);
        
        // Direct DOM updates with null checks
        const vehiclesEl = document.getElementById('stat-vehicles-inside');
        const entriesEl = document.getElementById('stat-entries-today');
        const exitsEl = document.getElementById('stat-exits-today');
        const avgDurationEl = document.getElementById('avg-duration');
        
        if (vehiclesEl) {
            const newVal = stats.vehicles_inside ?? 0;
            if (vehiclesEl.textContent !== String(newVal)) {
                vehiclesEl.textContent = newVal;
                this.pulseElement(vehiclesEl);
            }
        }
        
        if (entriesEl) {
            const newVal = stats.entries_today ?? 0;
            if (entriesEl.textContent !== String(newVal)) {
                entriesEl.textContent = newVal;
                this.pulseElement(entriesEl);
            }
        }
        
        if (exitsEl) {
            const newVal = stats.exits_today ?? 0;
            if (exitsEl.textContent !== String(newVal)) {
                exitsEl.textContent = newVal;
                this.pulseElement(exitsEl);
            }
        }
        
        if (avgDurationEl) {
            avgDurationEl.textContent = Math.round(stats.avg_duration_minutes ?? 0);
        }
        
        // Update vehicles table
        if (stats.current_vehicles) {
            this.updateVehiclesTable(stats.current_vehicles);
        }
        
        // Store stats
        this.stats = {
            vehiclesInside: stats.vehicles_inside ?? 0,
            entriesToday: stats.entries_today ?? 0,
            exitsToday: stats.exits_today ?? 0,
            avgDuration: stats.avg_duration_minutes ?? 0
        };
    }
    
    pulseElement(el) {
        el.style.transform = 'scale(1.2)';
        el.style.color = '#14b8a6';
        setTimeout(() => {
            el.style.transform = 'scale(1)';
            el.style.color = '';
        }, 300);
    }
    
    updateCameraStatus(cameras) {
        for (const [name, status] of Object.entries(cameras)) {
            const dot = document.getElementById(`${name}-status-dot`);
            const info = document.getElementById(`${name}-info`);
            const camDot = document.getElementById(`cam-${name}-dot`);
            const detectionsEl = document.getElementById(`${name}-detections`);
            
            if (dot) {
                dot.className = `w-3 h-3 rounded-full ${status.connected ? 'bg-green-500' : 'bg-red-500'}`;
            }
            
            if (info) {
                info.textContent = status.connected ? 'Stream activo' : 'Desconectado';
            }
            
            if (camDot) {
                camDot.className = `w-2 h-2 rounded-full ${status.connected ? 'bg-green-500' : 'bg-red-500'}`;
            }
            
            if (detectionsEl && status.detections_count !== undefined) {
                detectionsEl.textContent = `${status.detections_count} detecciones`;
            }
        }
        
        // Update cameras active count
        const activeCount = Object.values(cameras).filter(c => c.connected).length;
        const camerasActiveEl = document.getElementById('stat-cameras-active');
        if (camerasActiveEl) {
            camerasActiveEl.textContent = activeCount;
        }
    }
    
    handleNewDetection(detection) {
        console.log('New detection:', detection);
        
        // Store and display
        this.lastDetection = detection;
        this.displayDetection(detection, true);
        
        // Add to recent plates
        this.addRecentPlate(detection);
        
        // Add to activity log
        const isEntry = detection.camera === 'entrada';
        const action = isEntry ? 'Entrada' : 'Salida';
        const yoloConf = Math.round((detection.confidence || 0) * 100);
        const ocrConf = Math.round((detection.ocr_confidence || 0) * 100);
        
        this.addLogEntry(
            `${action}: ${detection.plate} (YOLO: ${yoloConf}%, OCR: ${ocrConf}%)`,
            isEntry ? 'entry' : 'exit'
        );
        
        // Show toast
        this.showToast(
            `${action} Detectada`,
            `Patente: ${detection.plate}`,
            isEntry ? 'success' : 'warning'
        );
        
        // Save to localStorage
        this.savePersistedData();
    }
    
    displayDetection(detection, animate = true) {
        const plateText = document.getElementById('plate-text');
        const plateDisplay = document.getElementById('plate-display');
        const plateCamera = document.getElementById('plate-camera');
        const plateTime = document.getElementById('plate-time');
        const yoloBar = document.getElementById('yolo-confidence-bar');
        const yoloText = document.getElementById('yolo-confidence');
        const ocrBar = document.getElementById('ocr-confidence-bar');
        const ocrText = document.getElementById('ocr-confidence');
        
        if (plateText) {
            plateText.textContent = detection.plate || '------';
        }
        
        if (plateDisplay && animate) {
            plateDisplay.style.transform = 'scale(1.05)';
            setTimeout(() => {
                plateDisplay.style.transform = 'scale(1)';
            }, 200);
        }
        
        if (plateCamera) {
            const isEntry = detection.camera === 'entrada';
            plateCamera.innerHTML = `<span class="${isEntry ? 'text-green-400' : 'text-orange-400'}">${isEntry ? 'Entrada' : 'Salida'}</span>`;
        }
        
        if (plateTime) {
            if (detection.timestamp) {
                const time = new Date(detection.timestamp);
                plateTime.textContent = time.toLocaleTimeString('es-CL');
            } else {
                plateTime.textContent = new Date().toLocaleTimeString('es-CL');
            }
        }
        
        // Update confidence bars
        const yoloConf = Math.round((detection.confidence || 0) * 100);
        const ocrConf = Math.round((detection.ocr_confidence || 0) * 100);
        
        if (yoloBar) yoloBar.style.width = `${yoloConf}%`;
        if (yoloText) yoloText.textContent = `${yoloConf}%`;
        if (ocrBar) ocrBar.style.width = `${ocrConf}%`;
        if (ocrText) ocrText.textContent = `${ocrConf}%`;
    }
    
    addRecentPlate(detection) {
        const plate = {
            text: detection.plate,
            camera: detection.camera,
            time: detection.timestamp || new Date().toISOString(),
            confidence: detection.confidence,
            ocr_confidence: detection.ocr_confidence
        };
        
        // Add to front, remove duplicates
        this.recentPlates = this.recentPlates.filter(p => p.text !== plate.text);
        this.recentPlates.unshift(plate);
        this.recentPlates = this.recentPlates.slice(0, this.maxRecentPlates);
        
        this.renderRecentPlates();
    }
    
    renderRecentPlates() {
        const container = document.getElementById('recent-plates');
        if (!container) return;
        
        if (this.recentPlates.length === 0) {
            container.innerHTML = '<div class="text-center text-white/30 text-xs py-3">Sin detecciones</div>';
            return;
        }
        
        container.innerHTML = this.recentPlates.map((plate, index) => {
            const isEntry = plate.camera === 'entrada';
            const icon = isEntry ? 'log-in' : 'log-out';
            const iconColor = isEntry ? 'text-green-400' : 'text-orange-400';
            const bgColor = isEntry ? 'bg-green-500/10' : 'bg-orange-500/10';
            const time = new Date(plate.time).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' });
            
            return `
                <div class="flex items-center justify-between p-2 rounded-lg ${bgColor} ${index === 0 ? 'ring-1 ring-white/20' : ''}">
                    <div class="flex items-center gap-2">
                        <i data-lucide="${icon}" class="w-4 h-4 ${iconColor}"></i>
                        <span class="font-mono font-semibold text-white text-sm">${plate.text}</span>
                    </div>
                    <span class="text-xs text-white/50">${time}</span>
                </div>
            `;
        }).join('');
        
        // Re-initialize icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
    
    updateVehiclesTable(vehicles) {
        const tbody = document.getElementById('vehicles-tbody');
        if (!tbody) return;
        
        if (!vehicles || vehicles.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="px-5 py-8 text-center text-white/30">
                        <i data-lucide="inbox" class="w-10 h-10 mx-auto mb-2 opacity-50"></i>
                        <p class="text-sm">No hay vehiculos en el puerto</p>
                    </td>
                </tr>
            `;
            if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }
        
        tbody.innerHTML = vehicles.map(vehicle => {
            const duration = this.calculateDuration(vehicle.entry_time);
            const durationColor = duration.minutes < 30 ? 'bg-green-500/20 text-green-400' :
                                  duration.minutes < 120 ? 'bg-yellow-500/20 text-yellow-400' :
                                  'bg-red-500/20 text-red-400';
            
            const entryTime = vehicle.entry_time ? 
                new Date(vehicle.entry_time + (vehicle.entry_time.includes('Z') ? '' : '')).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' }) : 
                '--:--';
            
            return `
                <tr class="table-row-hover">
                    <td class="px-5 py-3">
                        <span class="font-mono font-semibold text-white bg-white/10 px-2 py-1 rounded">${vehicle.plate}</span>
                    </td>
                    <td class="px-5 py-3 text-white/70">${entryTime} p. m.</td>
                    <td class="px-5 py-3">
                        <span class="px-2 py-1 rounded text-xs font-medium ${durationColor}">${duration.text}</span>
                    </td>
                    <td class="px-5 py-3">
                        <span class="flex items-center gap-1.5 text-green-400 text-sm">
                            <span class="w-1.5 h-1.5 rounded-full bg-green-400"></span>
                            Dentro
                        </span>
                    </td>
                </tr>
            `;
        }).join('');
    }
    
    calculateDuration(entryTime) {
        if (!entryTime) return { minutes: 0, text: '0 min' };
        
        const now = new Date();
        let entry = new Date(entryTime);
        
        // Handle timezone
        if (!entryTime.endsWith('Z') && !entryTime.includes('+')) {
            entry = new Date(entryTime);
        }
        
        const diffMs = now - entry;
        const diffMins = Math.max(0, Math.floor(diffMs / 60000));
        
        if (diffMins < 60) {
            return { minutes: diffMins, text: `${diffMins} min` };
        } else {
            const hours = Math.floor(diffMins / 60);
            const mins = diffMins % 60;
            return { minutes: diffMins, text: `${hours}h ${mins}m` };
        }
    }
    
    addLogEntry(message, type = 'info') {
        const log = document.getElementById('activity-log');
        if (!log) return;
        
        const icons = {
            success: { icon: 'check-circle', color: 'text-green-400', bg: 'bg-green-500/20' },
            error: { icon: 'alert-circle', color: 'text-red-400', bg: 'bg-red-500/20' },
            entry: { icon: 'log-in', color: 'text-green-400', bg: 'bg-green-500/20' },
            exit: { icon: 'log-out', color: 'text-orange-400', bg: 'bg-orange-500/20' },
            info: { icon: 'info', color: 'text-blue-400', bg: 'bg-blue-500/20' }
        };
        
        const config = icons[type] || icons.info;
        const time = new Date().toLocaleTimeString('es-CL');
        
        const entry = document.createElement('div');
        entry.className = 'flex items-start gap-3 p-3 rounded-xl bg-white/5 log-entry-new';
        entry.innerHTML = `
            <div class="w-8 h-8 rounded-lg ${config.bg} flex items-center justify-center flex-shrink-0">
                <i data-lucide="${config.icon}" class="w-4 h-4 ${config.color}"></i>
            </div>
            <div class="flex-1 min-w-0">
                <p class="text-sm text-white/80">${message}</p>
                <p class="text-xs text-white/40">${time}</p>
            </div>
        `;
        
        // Insert at the beginning (after any existing first element)
        const firstChild = log.children[0];
        if (firstChild) {
            log.insertBefore(entry, firstChild.nextSibling);
        } else {
            log.appendChild(entry);
        }
        
        // Limit entries
        while (log.children.length > 50) {
            log.removeChild(log.lastChild);
        }
        
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
    
    showToast(title, message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;
        
        const colors = {
            success: 'border-green-500/50 bg-green-500/10',
            warning: 'border-orange-500/50 bg-orange-500/10',
            error: 'border-red-500/50 bg-red-500/10',
            info: 'border-blue-500/50 bg-blue-500/10'
        };
        
        const toast = document.createElement('div');
        toast.className = `glass rounded-xl p-4 border ${colors[type] || colors.info} animate-slide-up max-w-sm`;
        toast.innerHTML = `
            <div class="flex items-start gap-3">
                <div class="flex-1">
                    <p class="font-medium text-white text-sm">${title}</p>
                    <p class="text-xs text-white/60 mt-0.5">${message}</p>
                </div>
                <button onclick="this.parentElement.parentElement.remove()" class="text-white/40 hover:text-white">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>
        `;
        
        container.appendChild(toast);
        
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
        
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    }
    
    // ==========================================
    // Stream Monitoring
    // ==========================================
    
    setupStreamMonitoring() {
        const streams = ['entrada', 'salida'];
        
        streams.forEach(name => {
            const img = document.getElementById(`stream-${name}`);
            if (img) {
                img.onerror = () => {
                    console.warn(`Stream ${name} error`);
                    setTimeout(() => {
                        img.src = `/stream/${name}?t=${Date.now()}`;
                    }, 2000);
                };
            }
        });
    }
    
    loadInitialData() {
        fetch('/api/stats')
            .then(res => res.json())
            .then(data => {
                if (data) {
                    this.updateStats(data);
                }
            })
            .catch(err => console.warn('Could not load initial stats:', err));
    }
}

// Global functions
function refreshVehicles() {
    if (window.dashboard) {
        window.dashboard.loadInitialData();
    }
}

function clearLog() {
    const log = document.getElementById('activity-log');
    if (log) {
        log.innerHTML = `
            <div class="flex items-start gap-3 p-3 rounded-xl bg-white/5">
                <div class="w-8 h-8 rounded-lg bg-brand-500/20 flex items-center justify-center flex-shrink-0">
                    <i data-lucide="power" class="w-4 h-4 text-brand-400"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-sm text-white/80">Registro limpiado</p>
                    <p class="text-xs text-white/40">${new Date().toLocaleTimeString('es-CL')}</p>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new EkaiaDashboard();
});