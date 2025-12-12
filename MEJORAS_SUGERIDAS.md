# 💡 EKAIA Puerto - Mejoras Sugeridas

## ⚠️ Consideraciones Críticas

### 1. Modelo YOLO - Validación

```bash
# ANTES de producción, validar modelo
python3 << EOF
from ultralytics import YOLO
import torch

model = YOLO('/home/seidgc/ekaia-engine/models/patentes.pt')

print("📊 Información del Modelo:")
print(f"Classes: {model.names}")
print(f"Device: {model.device}")
print(f"Task: {model.task}")

# Test inference
import numpy as np
dummy = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
results = model.predict(dummy, verbose=False)
print(f"✅ Inference OK")
EOF
```

**Esperado:**
```
Classes: {0: 'vehicle', 1: 'plate'}
Device: cuda:0
Task: detect
```

**Si el modelo tiene nombres diferentes**, editar `app/services/yolo_detector.py`:

```python
CLASS_NAMES = {
    0: "tu_clase_vehiculo",  # Ajustar
    1: "tu_clase_patente"    # Ajustar
}
```

---

### 2. RTSP URLs - Formato Dahua

Las cámaras Dahua típicamente usan:

```bash
# Main stream (alta calidad, ~4Mbps)
rtsp://admin:password@192.168.88.107:554/cam/realmonitor?channel=1&subtype=0

# Sub stream (baja calidad, ~1Mbps) - RECOMENDADO para producción
rtsp://admin:password@192.168.88.107:554/cam/realmonitor?channel=1&subtype=1
```

**Recomendación:** Usar `subtype=1` para:
- Menor uso de bandwidth
- Más estabilidad
- Latencia similar
- Suficiente para detección (320p-480p)

**Si las URLs no funcionan**, probar:

```bash
# Opción 2: ONVIF path
rtsp://admin:password@192.168.88.107:554/onvif1

# Opción 3: H264 path
rtsp://admin:password@192.168.88.107:554/h264/ch1/main/av_stream

# Test con VLC
vlc rtsp://admin:password@192.168.88.107:554/cam/realmonitor?channel=1&subtype=1
```

---

### 3. OCR - Patentes Chilenas

El sistema está optimizado para formatos chilenos. **Si tienes otro país**, ajustar patterns:

```python
# app/services/ocr_service.py línea 22-26

# Para Perú (ABC-123)
PATTERNS = [
    r'^[A-Z]{3}-\d{3}$',
]

# Para Argentina (AB123CD)
PATTERNS = [
    r'^[A-Z]{2}\d{3}[A-Z]{2}$',
]

# Para México (ABC-12-34)
PATTERNS = [
    r'^[A-Z]{3}-\d{2}-\d{2}$',
]
```

---

## 🚀 Optimizaciones Prioritarias

### 1. Detección Automática Continua

**Actual:** Se detecta solo cuando hay request a `/api/detect`

**Mejora:** Worker background que detecta 24/7

```python
# app/services/detection_worker.py
import asyncio
from app.services import get_stream_manager, get_detector, get_ocr_service
from app.models import DatabaseManager
from app.services.tracker import VehicleTracker
from app.config import get_settings

async def continuous_detection():
    """Worker que detecta continuamente en ambas cámaras"""
    settings = get_settings()
    db_manager = DatabaseManager(settings.database_url)

    detector = get_detector(
        settings.yolo_model_path,
        settings.yolo_device,
        settings.yolo_confidence
    )
    ocr = get_ocr_service(use_gpu=settings.ocr_gpu)
    stream_manager = get_stream_manager()

    while True:
        for camera_name in ["entrada", "salida"]:
            stream = stream_manager.get_stream(camera_name)

            if stream and stream.is_alive():
                frame = stream.get_latest_frame()

                if frame is not None:
                    # Detectar
                    plate_detections = detector.detect_plates(frame)

                    async for db in db_manager.get_session():
                        tracker = VehicleTracker(db)

                        for plate_det in plate_detections:
                            plate_text, ocr_conf = ocr.extract_from_bbox(
                                frame, plate_det.bbox
                            )

                            if plate_text and ocr_conf > 0.6:
                                # Registrar
                                if camera_name == "entrada":
                                    await tracker.register_entry(
                                        plate_text, plate_det.confidence
                                    )
                                else:
                                    await tracker.register_exit(
                                        plate_text, plate_det.confidence
                                    )

                                # Log
                                await tracker.log_detection(
                                    camera=camera_name,
                                    plate=plate_text,
                                    confidence=plate_det.confidence,
                                    bbox=plate_det.bbox,
                                    ocr_text=plate_text
                                )

                        break

        # Esperar antes de siguiente iteración
        await asyncio.sleep(2)

# Agregar en app/main.py lifespan:
async def lifespan(app: FastAPI):
    # ... existing code ...

    # Start detection worker
    asyncio.create_task(continuous_detection())

    yield
    # ... existing shutdown ...
```

**Beneficios:**
- Detección automática sin intervención
- No se pierden vehículos
- Dashboard siempre actualizado

---

### 2. Deduplicación de Detecciones

**Problema:** Misma patente puede detectarse múltiples veces en segundos

**Solución:** Cooldown period

```python
# app/services/tracker.py

class VehicleTracker:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.recent_detections = {}  # {plate: timestamp}
        self.cooldown_seconds = 30  # No registrar misma patente en 30s

    async def register_entry(self, plate: str, confidence: float, camera: str = "entrada"):
        """Register entry with cooldown"""
        now = datetime.utcnow()

        # Check cooldown
        last_seen = self.recent_detections.get(f"{plate}_{camera}")
        if last_seen:
            delta = (now - last_seen).total_seconds()
            if delta < self.cooldown_seconds:
                logger.info(f"⏳ {plate} en cooldown ({delta:.1f}s)")
                return None

        # Update cooldown
        self.recent_detections[f"{plate}_{camera}"] = now

        # ... existing logic ...
```

---

### 3. Notificaciones en Tiempo Real

**Casos de uso:**
- Vehículo permanece >2 horas en puerto
- Patente en blacklist
- Capacidad máxima alcanzada

```python
# app/services/notifications.py
import smtplib
from email.mime.text import MIMEText

class NotificationService:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.email_from = "ekaia@seidev.cl"
        self.email_to = ["admin@seidev.cl"]

    async def alert_long_stay(self, plate: str, duration_minutes: float):
        """Alerta cuando vehículo permanece mucho tiempo"""
        if duration_minutes > 120:  # 2 horas
            subject = f"⚠️ Vehículo {plate} - Permanencia prolongada"
            body = f"""
            El vehículo {plate} lleva {duration_minutes:.0f} minutos en el puerto.

            Revisar situación.
            """

            await self.send_email(subject, body)

    async def send_email(self, subject: str, body: str):
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = self.email_from
        msg['To'] = ', '.join(self.email_to)

        # Enviar (async)
        # ... implementar con aiosmtplib
```

**Integrar en tracker:**

```python
# app/services/tracker.py
from app.services.notifications import NotificationService

class VehicleTracker:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.notifier = NotificationService()

    async def register_exit(self, plate: str, confidence: float, camera: str = "salida"):
        # ... existing code ...

        # Alerta si permanencia prolongada
        if record.duration_minutes and record.duration_minutes > 120:
            await self.notifier.alert_long_stay(plate, record.duration_minutes)
```

---

### 4. Estadísticas Avanzadas

```python
# app/api/detection.py

@router.get("/api/analytics/hourly")
async def get_hourly_stats(db: AsyncSession = Depends(get_db)):
    """Estadísticas por hora del día"""
    query = """
    SELECT
        HOUR(entry_time) as hour,
        COUNT(*) as entries,
        AVG(duration_minutes) as avg_duration
    FROM vehicle_records
    WHERE DATE(entry_time) = CURDATE()
    GROUP BY HOUR(entry_time)
    ORDER BY hour
    """
    result = await db.execute(text(query))
    return {"hourly_stats": [dict(row) for row in result]}

@router.get("/api/analytics/top-plates")
async def get_frequent_plates(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Patentes más frecuentes"""
    query = text("""
    SELECT
        plate,
        COUNT(*) as visits,
        AVG(duration_minutes) as avg_duration
    FROM vehicle_records
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    GROUP BY plate
    ORDER BY visits DESC
    LIMIT :limit
    """)
    result = await db.execute(query, {"limit": limit})
    return {"top_plates": [dict(row) for row in result]}
```

---

### 5. Dashboard - Gráficos

**Agregar Chart.js para visualizaciones:**

```html
<!-- frontend/index.html -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<div class="charts-section">
    <canvas id="hourly-chart"></canvas>
    <canvas id="duration-chart"></canvas>
</div>
```

```javascript
// frontend/dashboard.js

class Dashboard {
    // ... existing code ...

    setupCharts() {
        // Hourly entries chart
        fetch('/api/analytics/hourly')
            .then(r => r.json())
            .then(data => {
                new Chart(document.getElementById('hourly-chart'), {
                    type: 'line',
                    data: {
                        labels: data.hourly_stats.map(s => s.hour + ':00'),
                        datasets: [{
                            label: 'Entradas por Hora',
                            data: data.hourly_stats.map(s => s.entries),
                            borderColor: 'rgb(75, 192, 192)',
                            tension: 0.1
                        }]
                    }
                });
            });
    }
}
```

---

## 🔒 Seguridad Adicional

### 1. Autenticación Básica

```python
# app/api/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, "ekaia2024")

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Proteger endpoints
@router.get("/api/vehicles/inside")
async def get_vehicles_inside(
    username: str = Depends(verify_credentials),
    db: AsyncSession = Depends(get_db)
):
    # ... existing code ...
```

---

### 2. Rate Limiting Avanzado

```bash
pip install slowapi redis
```

```python
# app/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="redis://localhost:6379"  # O memory://
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@router.post("/api/detect/{camera}")
@limiter.limit("10/minute")
async def detect_on_camera(request: Request, camera: str):
    # ... existing code ...
```

---

## 📱 Mobile App (Opcional)

### React Native Expo

```bash
npx create-expo-app ekaia-mobile
cd ekaia-mobile
```

```javascript
// App.js
import React, { useEffect, useState } from 'react';
import { View, Text, Image, FlatList } from 'react-native';

export default function App() {
    const [vehicles, setVehicles] = useState([]);

    useEffect(() => {
        // WebSocket connection
        const ws = new WebSocket('wss://ekaia.seidev.cl/ws/realtime');

        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.stats && data.stats.current_vehicles) {
                setVehicles(data.stats.current_vehicles);
            }
        };

        return () => ws.close();
    }, []);

    return (
        <View>
            <Text>Vehículos en Puerto: {vehicles.length}</Text>
            <FlatList
                data={vehicles}
                renderItem={({ item }) => (
                    <View>
                        <Text>{item.plate}</Text>
                        <Text>{item.duration_minutes} min</Text>
                    </View>
                )}
            />
        </View>
    );
}
```

---

## 🎯 Roadmap Recomendado

### Fase 1: Estabilización (Semana 1-2)
- [x] Deployment inicial
- [ ] Validar detecciones 24h
- [ ] Ajustar confidence thresholds
- [ ] Optimizar OCR accuracy
- [ ] Configurar backups MySQL

### Fase 2: Automatización (Semana 3-4)
- [ ] Worker detección continua
- [ ] Deduplicación de patentes
- [ ] Alertas email/SMS
- [ ] Dashboard analytics

### Fase 3: Escalabilidad (Mes 2)
- [ ] Multi-cámara support (4+ cámaras)
- [ ] Redis caching
- [ ] Load balancing
- [ ] Prometheus metrics

### Fase 4: Features Avanzados (Mes 3+)
- [ ] Vehicle classification (truck/car/bus)
- [ ] Integración ERP/SAP
- [ ] Mobile app
- [ ] BI dashboards (Metabase/Grafana)
- [ ] Video recording on events

---

## 📞 Soporte y Contacto

**Documentación:**
- README.md - Guía general
- DEPLOYMENT.md - Instalación producción
- ARCHITECTURE.md - Diseño técnico
- Este archivo - Mejoras sugeridas

**Issues:**
- GitHub Issues para bugs
- Email soporte@seidev.cl

**Community:**
- Discord (crear canal EKAIA)
- Wiki para FAQ

---

## ⚡ Quick Wins (Implementar Ya)

### 1. Logging Mejorado

```python
# app/main.py
import logging
from logging.handlers import RotatingFileHandler

# File handler con rotación
file_handler = RotatingFileHandler(
    'logs/ekaia.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

logger = logging.getLogger()
logger.addHandler(file_handler)
```

### 2. Health Check Completo

```python
@app.get("/health/detailed")
async def detailed_health():
    """Health check con diagnóstico"""
    stream_manager = get_stream_manager()

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "database": await check_db_connection(),
            "gpu": torch.cuda.is_available(),
            "streams": {
                "entrada": stream_manager.get_stream("entrada").is_alive(),
                "salida": stream_manager.get_stream("salida").is_alive()
            },
            "models": {
                "yolo": os.path.exists(settings.yolo_model_path),
                "ocr": True  # OCR se carga dinámicamente
            }
        }
    }
```

### 3. Graceful Shutdown

```python
# app/main.py
import signal

def handle_shutdown(signum, frame):
    logger.info("🛑 Received shutdown signal")
    # Cleanup
    stream_manager = get_stream_manager()
    stream_manager.stop_all()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)
```

---

¡Sistema EKAIA listo para producción! 🚀
