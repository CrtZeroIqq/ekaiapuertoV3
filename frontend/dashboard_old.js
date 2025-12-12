/**
 * EKAIA Puerto - Professional Dashboard
 * Real-time vehicle tracking with modern UI
 * © 2025 SEIDEV - Puerto de Iquique
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
        
        this.init();
    }
    
    init() {
        console.log('🚀 EKAIA Dashboard v1.0.0 initializing...');
        
        this.updateDateTime();
        setInterval(() => this.updateDateTime(), 1000);
        
        this.setupWebSocket();
        this.setupStreamMonitoring();
        this.loadInitialData();
        
        // Set system start time
        document.getElementById('system-start-time').textContent = 
            new Date().toLocaleTimeString('es-CL');
        
        console.log('✅ Dashboard initialized');
    }
    
    // ==========================================
    // WebSocket Connection
    // ==========================================
    
    setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/realtime`;
        
        console.log('🔌 Connecting to:', wsUrl);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('✅ WebSocket connected');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus(true);
                this.addLogEntry('Conexión establecida con el servidor', 'success');
                this.showToast('Conectado', 'Conexión establecida con el servidor', 'success');
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
                console.error('❌ WebSocket error:', error);
            };
            
            this.ws.onclose = () => {
                console.log('🔌 WebSocket disconnected');
                this.isConnected = false;
                this.updateConnectionStatus(false);
                
                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    console.log(`Reconnecting... (attempt ${this.reconnectAttempts})`);
                    setTimeout(() => this.setupWebSocket(), this.reconnectInterval);
                } else {
                    this.addLogEntry('Conexión perdida. Recargue la página.', 'error');
                    this.showToast('Error', 'Conexión perdida con el servidor', 'error');
                }
            };
        } catch (e) {
            console.error('WebSocket setup error:', e);
            setTimeout(() => this.setupWebSocket(), this.reconnectInterval);
        }
    }
    
    handleRealtimeUpdate(data) {
        // Update stats
        if (data.stats) {
            this.updateStats(data.stats);
        }
        
        // Update camera status
        if (data.cameras) {
            this.updateCameraStatus(data.cameras);
        }
        
        // Handle new detection
        if (data.detection) {
            this.handleNewDetection(data.detection);
        }
    }
    
    // ==========================================
    // UI Updates
    // ==========================================
    
    updateConnectionStatus(connected) {
        const badge = document.getElementById('connection-badge');
        const text = document.getElementById('connection-text');
        const systemStatus = document.getElementById('system-status');
        
        if (connected) {
            badge.className = 'flex items-center gap-2 px-4 py-2 rounded-full bg-green-500/20 border border-green-500/30 transition-all duration-300';
            badge.innerHTML = `
                <div class="w-2 h-2 rounded-full bg-green-500"></div>
                <span class="text-sm font-medium text-green-400">Conectado</span>
            `;
            systemStatus.className = 'absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-surface-800 status-pulse';
        } else {
            badge.className = 'flex items-center gap-2 px-4 py-2 rounded-full bg-red-500/20 border border-red-500/30 transition-all duration-300';
            badge.innerHTML = `
                <div class="w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>
                <span class="text-sm font-medium text-red-400">Desconectado</span>
            `;
            systemStatus.className = 'absolute -bottom-1 -right-1 w-4 h-4 bg-red-500 rounded-full border-2 border-surface-800';
        }
    }
    
    updateDateTime() {
        const now = new Date();
        
        document.getElementById('current-time').textContent = 
            now.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        
        document.getElementById('current-date').textContent = 
            now.toLocaleDateString('es-CL', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    }
    
    updateStats(stats) {
        // Animate number changes
        this.animateNumber('stat-vehicles-inside', stats.vehicles_inside || 0);
        this.animateNumber('stat-exits-today', stats.exits_today || 0);
        
        document.getElementById('avg-duration').textContent = 
            Math.round(stats.avg_duration_minutes || 0);
        
        // Update vehicles table
        this.updateVehiclesTable(stats.current_vehicles || []);
        
        this.stats = { ...this.stats, ...stats };
    }
    
    animateNumber(elementId, newValue) {
        const element = document.getElementById(elementId);
        const currentValue = parseInt(element.textContent) || 0;
        
        if (currentValue !== newValue) {
            element.style.transform = 'scale(1.2)';
            element.style.color = '#14b8a6';
            
            setTimeout(() => {
                element.textContent = newValue;
                element.style.transform = 'scale(1)';
                element.style.color = '';
            }, 150);
        }
    }
    
    updateCameraStatus(cameras) {
        let activeCount = 0;
        
        // Entrada camera
        const entradaDot = document.getElementById('cam-entrada-dot');
        const entradaStatusDot = document.getElementById('entrada-status-dot');
        const entradaInfo = document.getElementById('entrada-info');
        const entradaDetections = document.getElementById('entrada-detections');
        
        if (cameras.entrada && cameras.entrada.connected) {
            activeCount++;
            entradaDot.className = 'w-2 h-2 rounded-full bg-green-500';
            entradaStatusDot.className = 'w-3 h-3 rounded-full bg-green-500';
            entradaInfo.textContent = 'Stream activo';
            entradaDetections.textContent = `${cameras.entrada.detections_count || 0} detecciones`;
            
            // Handle plate detection
            if (cameras.entrada.plates && cameras.entrada.plates.length > 0) {
                const plate = cameras.entrada.plates[0];
                this.handleNewDetection({
                    camera: 'entrada',
                    plate: plate.text,
                    confidence: plate.confidence,
                    ocr_confidence: plate.ocr_confidence || plate.confidence
                });
            }
        } else {
            entradaDot.className = 'w-2 h-2 rounded-full bg-red-500';
            entradaStatusDot.className = 'w-3 h-3 rounded-full bg-red-500';
            entradaInfo.textContent = 'Desconectado';
            entradaDetections.textContent = 'Sin conexión';
        }
        
        // Salida camera
        const salidaDot = document.getElementById('cam-salida-dot');
        const salidaStatusDot = document.getElementById('salida-status-dot');
        const salidaInfo = document.getElementById('salida-info');
        const salidaDetections = document.getElementById('salida-detections');
        
        if (cameras.salida && cameras.salida.connected) {
            activeCount++;
            salidaDot.className = 'w-2 h-2 rounded-full bg-green-500';
            salidaStatusDot.className = 'w-3 h-3 rounded-full bg-green-500';
            salidaInfo.textContent = 'Stream activo';
            salidaDetections.textContent = `${cameras.salida.detections_count || 0} detecciones`;
            
            // Handle plate detection
            if (cameras.salida.plates && cameras.salida.plates.length > 0) {
                const plate = cameras.salida.plates[0];
                this.handleNewDetection({
                    camera: 'salida',
                    plate: plate.text,
                    confidence: plate.confidence,
                    ocr_confidence: plate.ocr_confidence || plate.confidence
                });
            }
        } else {
            salidaDot.className = 'w-2 h-2 rounded-full bg-red-500';
            salidaStatusDot.className = 'w-3 h-3 rounded-full bg-red-500';
            salidaInfo.textContent = 'Desconectado';
            salidaDetections.textContent = 'Sin conexión';
        }
        
        document.getElementById('stat-cameras-active').textContent = activeCount;
    }
    
    handleNewDetection(detection) {
        if (!detection.plate) return;
        
        // Update plate display
        const plateText = document.getElementById('plate-text');
        const plateDisplay = document.getElementById('plate-display');
        const plateCamera = document.getElementById('plate-camera');
        const plateTime = document.getElementById('plate-time');
        
        // Animate plate change
        plateDisplay.style.transform = 'scale(1.05)';
        plateDisplay.style.boxShadow = '0 0 30px rgba(20, 184, 166, 0.5)';
        
        setTimeout(() => {
            plateText.textContent = detection.plate;
            plateCamera.textContent = detection.camera === 'entrada' ? '📥 Entrada' : '📤 Salida';
            plateTime.textContent = new Date().toLocaleTimeString('es-CL');
            
            plateDisplay.style.transform = 'scale(1)';
            plateDisplay.style.boxShadow = '';
        }, 100);
        
        // Update confidence bars
        const yoloConf = Math.round((detection.confidence || 0) * 100);
        const ocrConf = Math.round((detection.ocr_confidence || 0) * 100);
        
        document.getElementById('yolo-confidence').textContent = `${yoloConf}%`;
        document.getElementById('yolo-confidence-bar').style.width = `${yoloConf}%`;
        
        document.getElementById('ocr-confidence').textContent = `${ocrConf}%`;
        document.getElementById('ocr-confidence-bar').style.width = `${ocrConf}%`;
        
        // Add to recent plates
        this.addRecentPlate(detection);
        
        // Add log entry
        const icon = detection.camera === 'entrada' ? '🚗' : '📤';
        const action = detection.camera === 'entrada' ? 'Entrada' : 'Salida';
        this.addLogEntry(`${icon} ${action}: ${detection.plate}`, detection.camera);
        
        // Show toast for high confidence detections
        if (yoloConf > 70 && ocrConf > 60) {
            this.showToast(
                `${action} Detectada`,
                `Patente: ${detection.plate}`,
                detection.camera === 'entrada' ? 'success' : 'info'
            );
        }
    }
    
    addRecentPlate(detection) {
        // Add to front
        this.recentPlates.unshift({
            plate: detection.plate,
            camera: detection.camera,
            time: new Date(),
            confidence: detection.confidence
        });
        
        // Keep only last N
        this.recentPlates = this.recentPlates.slice(0, this.maxRecentPlates);
        
        // Update UI
        const container = document.getElementById('recent-plates');
        
        if (this.recentPlates.length === 0) {
            container.innerHTML = '<div class="text-center text-white/30 text-sm py-4">Sin detecciones recientes</div>';
            return;
        }
        
        container.innerHTML = this.recentPlates.map((p, i) => `
            <div class="flex items-center justify-between p-3 rounded-xl ${i === 0 ? 'bg-brand-500/20 border border-brand-500/30' : 'bg-white/5'} transition-all duration-300">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg ${p.camera === 'entrada' ? 'bg-green-500/20' : 'bg-orange-500/20'} flex items-center justify-center">
                        <i data-lucide="${p.camera === 'entrada' ? 'log-in' : 'log-out'}" class="w-4 h-4 ${p.camera === 'entrada' ? 'text-green-400' : 'text-orange-400'}"></i>
                    </div>
                    <span class="font-mono font-semibold text-white">${p.plate}</span>
                </div>
                <span class="text-xs text-white/40">${p.time.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
        `).join('');
        
        // Re-init icons
        if (window.lucide) lucide.createIcons();
    }
    
    updateVehiclesTable(vehicles) {
        const tbody = document.getElementById('vehicles-tbody');
        
        if (!vehicles || vehicles.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" class="px-5 py-12 text-center text-white/30">
                        <svg class="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"></path>
                        </svg>
                        <p>No hay vehículos en el puerto</p>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = vehicles.map(v => {
            const entryTime = new Date(v.entry_time);
            const duration = this.calculateDuration(v.entry_time);
            const durationClass = this.getDurationClass(duration.minutes);
            
            return `
                <tr class="table-row-hover">
                    <td class="px-5 py-4">
                        <span class="font-mono font-bold text-white bg-white/10 px-3 py-1 rounded-lg">${v.plate}</span>
                    </td>
                    <td class="px-5 py-4 text-white/70">
                        ${entryTime.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td class="px-5 py-4">
                        <span class="${durationClass} px-2 py-1 rounded-lg text-sm font-medium">
                            ${duration.text}
                        </span>
                    </td>
                    <td class="px-5 py-4">
                        <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-brand-500/20 text-brand-400 text-sm font-medium">
                            <span class="w-1.5 h-1.5 rounded-full bg-brand-400"></span>
                            Dentro
                        </span>
                    </td>
                </tr>
            `;
        }).join('');
    }
    
    calculateDuration(entryTime) {
        const now = new Date();
        const entry = new Date(entryTime);
        const diffMs = now - entry;
        const diffMins = Math.floor(diffMs / 60000);
        
        if (diffMins < 60) {
            return { minutes: diffMins, text: `${diffMins} min` };
        } else {
            const hours = Math.floor(diffMins / 60);
            const mins = diffMins % 60;
            return { minutes: diffMins, text: `${hours}h ${mins}m` };
        }
    }
    
    getDurationClass(minutes) {
        if (minutes < 30) return 'bg-green-500/20 text-green-400';
        if (minutes < 60) return 'bg-yellow-500/20 text-yellow-400';
        if (minutes < 120) return 'bg-orange-500/20 text-orange-400';
        return 'bg-red-500/20 text-red-400';
    }
    
    // ==========================================
    // Activity Log
    // ==========================================
    
    addLogEntry(message, type = 'info') {
        const container = document.getElementById('activity-log');
        const entry = document.createElement('div');
        
        const icons = {
            success: { icon: 'check-circle', color: 'text-green-400', bg: 'bg-green-500/20' },
            error: { icon: 'x-circle', color: 'text-red-400', bg: 'bg-red-500/20' },
            warning: { icon: 'alert-triangle', color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
            entrada: { icon: 'log-in', color: 'text-green-400', bg: 'bg-green-500/20' },
            salida: { icon: 'log-out', color: 'text-orange-400', bg: 'bg-orange-500/20' },
            info: { icon: 'info', color: 'text-brand-400', bg: 'bg-brand-500/20' }
        };
        
        const config = icons[type] || icons.info;
        const time = new Date().toLocaleTimeString('es-CL');
        
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
        
        // Insert at top
        container.insertBefore(entry, container.firstChild);
        
        // Re-init icons
        if (window.lucide) lucide.createIcons();
        
        // Keep max 50 entries
        while (container.children.length > 50) {
            container.removeChild(container.lastChild);
        }
    }
    
    // ==========================================
    // Toast Notifications
    // ==========================================
    
    showToast(title, message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        
        const colors = {
            success: 'border-green-500/50 bg-green-500/10',
            error: 'border-red-500/50 bg-red-500/10',
            warning: 'border-yellow-500/50 bg-yellow-500/10',
            info: 'border-brand-500/50 bg-brand-500/10'
        };
        
        const icons = {
            success: 'check-circle',
            error: 'x-circle',
            warning: 'alert-triangle',
            info: 'info'
        };
        
        const iconColors = {
            success: 'text-green-400',
            error: 'text-red-400',
            warning: 'text-yellow-400',
            info: 'text-brand-400'
        };
        
        toast.className = `glass rounded-xl p-4 border ${colors[type]} animate-slide-up min-w-72 max-w-md`;
        toast.innerHTML = `
            <div class="flex items-start gap-3">
                <i data-lucide="${icons[type]}" class="w-5 h-5 ${iconColors[type]} flex-shrink-0 mt-0.5"></i>
                <div class="flex-1">
                    <h4 class="font-semibold text-white text-sm">${title}</h4>
                    <p class="text-xs text-white/60 mt-0.5">${message}</p>
                </div>
                <button onclick="this.parentElement.parentElement.remove()" class="text-white/40 hover:text-white/60 transition-colors">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>
        `;
        
        container.appendChild(toast);
        
        // Re-init icons
        if (window.lucide) lucide.createIcons();
        
        // Auto remove after 5s
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
        const streams = ['stream-entrada', 'stream-salida'];
        
        streams.forEach(id => {
            const img = document.getElementById(id);
            
            img.onerror = () => {
                console.warn(`⚠️ Stream ${id} error`);
                setTimeout(() => {
                    img.src = img.src.split('?')[0] + '?t=' + Date.now();
                }, 5000);
            };
            
            img.onload = () => {
                console.log(`✅ Stream ${id} loaded`);
            };
        });
    }
    
    // ==========================================
    // Data Loading
    // ==========================================
    
    async loadInitialData() {
        try {
            const response = await fetch('/api/stats');
            if (response.ok) {
                const stats = await response.json();
                this.updateStats(stats);
            }
        } catch (e) {
            console.error('Failed to load initial stats:', e);
        }
    }
}

// ==========================================
// Global Functions
// ==========================================

function refreshVehicles() {
    if (window.dashboard) {
        window.dashboard.loadInitialData();
        window.dashboard.showToast('Actualizado', 'Datos actualizados correctamente', 'success');
    }
}

function clearLog() {
    const container = document.getElementById('activity-log');
    container.innerHTML = `
        <div class="flex items-start gap-3 p-3 rounded-xl bg-white/5">
            <div class="w-8 h-8 rounded-lg bg-brand-500/20 flex items-center justify-center flex-shrink-0">
                <i data-lucide="trash-2" class="w-4 h-4 text-brand-400"></i>
            </div>
            <div class="flex-1 min-w-0">
                <p class="text-sm text-white/80">Registro limpiado</p>
                <p class="text-xs text-white/40">${new Date().toLocaleTimeString('es-CL')}</p>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();
}

// ==========================================
// Initialize
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 EKAIA Puerto Dashboard');
    console.log('📍 Puerto de Iquique - Chile');
    console.log('💻 Desarrollado por SEIDEV');
    
    window.dashboard = new EkaiaDashboard();
});