"""
EKAIA Puerto - Configuration Management
Loads environment variables and provides typed settings
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings with validation"""

    # Database
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "ekaia"
    db_password: str
    db_name: str = "ekaia_puerto"

    # RTSP Streams
    rtsp_entrada: str
    rtsp_salida: str

    # YOLO
    yolo_model_path: str = "/home/seidgc/ekaia-engine/models/patentes.pt"
    yolo_confidence: float = 0.5
    yolo_device: str = "0"  # GPU

    # OCR
    ocr_lang: str = "en"
    ocr_gpu: bool = True

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4

    # Cloudflare
    cf_tunnel_token: str = ""

    @property
    def database_url(self) -> str:
        """MySQL connection URL"""
        return f"mysql+aiomysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton"""
    return Settings()
