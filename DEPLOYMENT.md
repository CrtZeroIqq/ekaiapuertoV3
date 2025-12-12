# 🚀 EKAIA Puerto - Guía de Deployment Producción

## 📋 Checklist Pre-Deployment

### 1. Hardware Verificado
- [x] NVIDIA RTX 5070 (sm_120)
- [x] WSL2 Ubuntu 24.04
- [x] CUDA 12.4+ instalado
- [x] 16GB+ RAM recomendado
- [x] 50GB+ espacio disco

### 2. Modelo YOLO
```bash
# Verificar modelo existe
ls -lh /home/seidgc/ekaia-engine/models/patentes.pt

# Test rápido
python3 -c "
from ultralytics import YOLO
model = YOLO('/home/seidgc/ekaia-engine/models/patentes.pt')
print('✅ Modelo cargado correctamente')
print(f'Classes: {model.names}')
"
```

### 3. Cámaras RTSP
```bash
# Test entrada
ffplay -rtsp_transport tcp "rtsp://admin:PASSWORD@192.168.88.107:554/cam/realmonitor?channel=1&subtype=0"

# Test salida
ffplay -rtsp_transport tcp "rtsp://admin:PASSWORD@192.168.88.108:554/cam/realmonitor?channel=1&subtype=0"

# Si no funciona, verificar:
# - Credenciales admin:password correctas
# - Cámaras en misma red (192.168.88.x)
# - Puerto 554 abierto
# - Subtype=0 (main stream) o =1 (sub stream para menor bandwidth)
```

---

## 🔧 Instalación Paso a Paso

### Opción A: Script Automatizado (Recomendado)

```bash
# 1. Clonar repo
git clone <repo-url>
cd ekaia_puerto

# 2. Ejecutar setup
bash scripts/setup.sh

# 3. Configurar .env
nano .env
# Editar: DB_PASSWORD, RTSP_ENTRADA, RTSP_SALIDA

# 4. Iniciar
bash scripts/start.sh
```

### Opción B: Manual

```bash
# 1. Python virtual env
python3 -m venv venv
source venv/bin/activate

# 2. PyTorch CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 3. Requirements
pip install -r requirements.txt

# 4. MySQL
docker-compose up -d mysql

# 5. Init DB
python3 -c "
import asyncio
from app.config import get_settings
from app.models import DatabaseManager

async def init():
    settings = get_settings()
    db = DatabaseManager(settings.database_url)
    await db.init_db()

asyncio.run(init())
"

# 6. Start server
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## ⚙️ Configuración Avanzada

### .env Producción

```bash
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=ekaia
DB_PASSWORD=SuperSecurePassword123!
DB_NAME=ekaia_puerto

# RTSP Cameras - IMPORTANTE: Ajustar credenciales reales
RTSP_ENTRADA=rtsp://admin:Dahua2024@192.168.88.107:554/cam/realmonitor?channel=1&subtype=0
RTSP_SALIDA=rtsp://admin:Dahua2024@192.168.88.108:554/cam/realmonitor?channel=1&subtype=0

# YOLO
YOLO_MODEL_PATH=/home/seidgc/ekaia-engine/models/patentes.pt
YOLO_CONFIDENCE=0.5  # Bajar a 0.4 si hay muchos false negatives
YOLO_DEVICE=0  # 0 = primera GPU, cpu = sin GPU

# OCR
OCR_LANG=en
OCR_GPU=True

# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=1  # MANTENER EN 1 (GPU exclusivity)

# Cloudflare Tunnel (opcional)
CF_TUNNEL_TOKEN=eyJhIjoiX...tu_token_aqui
```

### Optimizar RTSP para Baja Latencia

Editar `app/services/rtsp_stream.py`:

```python
# Línea 46-50, ajustar según network:
self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 1 = mínima latencia
# Si hay frames dropped, subir a 2-3

# Usar substream para ahorrar bandwidth
# Cambiar subtype=0 a subtype=1 en RTSP URL
```

### Optimizar OCR Performance

Editar `app/services/ocr_service.py`:

```python
# Línea 34-38
rec_batch_num=6,  # Reducir a 3-4 si GPU memory bajo
det_db_thresh=0.3,  # Subir a 0.4 para más precisión, menos recall
```

---

## 🌐 Cloudflare Tunnel Setup

### Crear Tunnel

```bash
# 1. Login cloudflare
cloudflared tunnel login

# 2. Crear tunnel
cloudflared tunnel create ekaia-puerto

# 3. Configurar route
cloudflared tunnel route dns ekaia-puerto ekaia.seidev.cl

# 4. Obtener token
cloudflared tunnel token ekaia-puerto

# 5. Agregar token a .env
echo "CF_TUNNEL_TOKEN=<token>" >> .env

# 6. Start tunnel
docker-compose up -d cloudflared
```

### Verificar

```bash
# Check tunnel status
docker logs ekaia_tunnel

# Test externo
curl https://ekaia.seidev.cl/health
```

---

## 📊 Monitoreo y Logs

### Logs Estructurados

```bash
# Crear directorio
mkdir -p logs

# Modificar app/main.py logging:
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/ekaia.log'),
        logging.StreamHandler()
    ]
)
```

### Prometheus Metrics (Opcional)

```bash
# Instalar
pip install prometheus-client

# Agregar a app/main.py:
from prometheus_client import Counter, Histogram, generate_latest

detections_total = Counter('detections_total', 'Total detections', ['camera', 'class'])
detection_duration = Histogram('detection_duration_seconds', 'Detection time')

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

---

## 🔒 Seguridad Producción

### 1. MySQL Hardening

```sql
-- Crear usuario dedicado
CREATE USER 'ekaia'@'localhost' IDENTIFIED BY 'SuperSecurePassword123!';
GRANT SELECT, INSERT, UPDATE ON ekaia_puerto.* TO 'ekaia'@'localhost';
FLUSH PRIVILEGES;

-- Deshabilitar root remoto
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1');
```

### 2. Firewall

```bash
# UFW
sudo ufw allow 8000/tcp  # API
sudo ufw allow 3306/tcp  # MySQL (solo si necesitas acceso externo)
sudo ufw enable

# iptables
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
```

### 3. HTTPS con Reverse Proxy

```nginx
# /etc/nginx/sites-available/ekaia
server {
    listen 443 ssl http2;
    server_name ekaia.seidev.cl;

    ssl_certificate /etc/letsencrypt/live/ekaia.seidev.cl/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ekaia.seidev.cl/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 4. Rate Limiting

```python
# app/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/api/detect/{camera}")
@limiter.limit("10/minute")
async def detect(request: Request, camera: str):
    ...
```

---

## 🔄 Systemd Service (Auto-start)

```bash
# /etc/systemd/system/ekaia.service
[Unit]
Description=EKAIA Puerto Service
After=network.target mysql.service

[Service]
Type=simple
User=seidgc
WorkingDirectory=/home/seidgc/ekaia_puerto
Environment="PATH=/home/seidgc/ekaia_puerto/venv/bin"
ExecStart=/home/seidgc/ekaia_puerto/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Activar
sudo systemctl daemon-reload
sudo systemctl enable ekaia
sudo systemctl start ekaia
sudo systemctl status ekaia
```

---

## 📈 Performance Tuning

### GPU Optimization

```python
# app/services/yolo_detector.py
# Agregar después de línea 35:

torch.backends.cudnn.benchmark = True  # Auto-tune kernels
torch.backends.cuda.matmul.allow_tf32 = True  # Faster matmul

# Para multi-stream inference:
self.model.to(device)
torch.cuda.set_device(int(device))
```

### Database Connection Pool

```python
# app/models/database.py línea 98
self.engine = create_async_engine(
    database_url,
    pool_size=20,  # Aumentar si muchos requests concurrentes
    max_overflow=40,
    pool_pre_ping=True,
    pool_recycle=3600  # Reciclar connections cada hora
)
```

### WebSocket Optimization

```python
# app/api/websocket.py
# Reducir frecuencia si CPU alto:
await asyncio.sleep(3)  # En vez de 2s
```

---

## 🐛 Troubleshooting Avanzado

### Error: CUDA Out of Memory

```python
# Reducir resolución input en yolo_detector.py
results = self.model.predict(
    frame,
    imgsz=640,  # Reducir a 480 o 320 si OOM
    ...
)
```

### Error: MySQL Connection Pool Exhausted

```bash
# Aumentar max_connections
docker exec -it ekaia_mysql mysql -uroot -p

mysql> SET GLOBAL max_connections = 300;
mysql> SHOW VARIABLES LIKE 'max_connections';
```

### Error: RTSP Buffering/Lag

```python
# app/services/rtsp_stream.py
# Usar UDP en vez de TCP (menor latencia, menos confiable)
self.rtsp_url = rtsp_url.replace('rtsp://', 'rtspt://') if 'rtspt' not in rtsp_url else rtsp_url

# O agregar parámetros FFmpeg
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;udp'
```

---

## 📦 Backup y Restore

### Backup Automático

```bash
# /home/seidgc/backup_ekaia.sh
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
docker exec ekaia_mysql mysqldump -uroot -p$DB_PASSWORD ekaia_puerto > /backups/ekaia_$DATE.sql
find /backups -name "ekaia_*.sql" -mtime +7 -delete  # Keep 7 days
```

```bash
# Crontab
crontab -e
0 2 * * * /home/seidgc/backup_ekaia.sh  # Daily 2 AM
```

### Restore

```bash
docker exec -i ekaia_mysql mysql -uroot -p$DB_PASSWORD ekaia_puerto < /backups/ekaia_20240315.sql
```

---

## 📞 Soporte

**Issues:** https://github.com/seidev/ekaia_puerto/issues
**Email:** soporte@seidev.cl
**Docs:** https://ekaia.seidev.cl/docs
