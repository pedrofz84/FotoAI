import os
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


class Settings:
    PROJECT_NAME = "FotoAI.Engine"
    API_V1_STR = "/api/v1"

    # Base Paths (isolados no User Profile para Windows Apps saudáveis)
    LOCAL_APP_DATA = Path(os.getenv("LOCALAPPDATA", os.path.expanduser("~"))) / "FotoAI"
    DB_PATH = LOCAL_APP_DATA / "Database" / "fotosai.db"
    THUMBNAIL_DIR = LOCAL_APP_DATA / "Thumbnails"
    PREVIEW_DIR = LOCAL_APP_DATA / "Previews"
    LOGS_DIR = LOCAL_APP_DATA / "Logs"
    QDRANT_DIR = LOCAL_APP_DATA / "Vectors" / "qdrant_storage"

    # Qdrant em modo servidor (recomendado para bibliotecas grandes).
    # Se não houver servidor a correr, o motor arranca o qdrant.exe que está em
    # src/FotoAI.Engine/qdrant/ (sem Docker). Se não o encontrar, cai para o modo local em QDRANT_DIR.
    # Para forçar o modo local, define FOTOAI_QDRANT_URL=local
    QDRANT_URL = os.getenv("FOTOAI_QDRANT_URL", "http://127.0.0.1:6333")

    # Indexação
    BATCH_SIZE = _env_int("FOTOAI_BATCH_SIZE", 32)          # imagens por chamada ao CLIP
    LOADER_WORKERS = _env_int("FOTOAI_LOADER_WORKERS", max(2, (os.cpu_count() or 4) - 1))
    # Em pastas de rede: leituras em paralelo q.b. para esconder a latência,
    # sem pôr os discos do NAS a saltar entre dezenas de ficheiros ao mesmo tempo
    NETWORK_LOADER_WORKERS = _env_int("FOTOAI_NETWORK_LOADER_WORKERS", 12)
    CLIP_INPUT_MAX = 448     # lado máximo da imagem em RAM antes de ir para o CLIP (ele usa 224)

    # Previews HD só são geradas quando a UI as pede (evita dezenas de GB de cache)
    PREVIEW_ON_DEMAND = True

    @staticmethod
    def is_network_path(path: str) -> bool:
        """UNC (\\\\servidor\\partilha) ou unidade de rede mapeada (ex: Z:)."""
        if path.startswith("\\\\") or path.startswith("//"):
            return True
        if os.name == "nt" and len(path) >= 2 and path[1] == ":":
            try:
                import ctypes
                DRIVE_REMOTE = 4
                return ctypes.windll.kernel32.GetDriveTypeW(path[:2] + "\\") == DRIVE_REMOTE
            except Exception:
                return False
        return False

    def loader_workers_for(self, sample_path: str) -> int:
        if os.getenv("FOTOAI_LOADER_WORKERS"):
            return self.LOADER_WORKERS
        if self.is_network_path(sample_path):
            return self.NETWORK_LOADER_WORKERS
        return self.LOADER_WORKERS

    def init_dirs(self):
        for d in (self.LOCAL_APP_DATA, self.DB_PATH.parent, self.THUMBNAIL_DIR,
                  self.PREVIEW_DIR, self.LOGS_DIR, self.QDRANT_DIR):
            d.mkdir(exist_ok=True, parents=True)


settings = Settings()
settings.init_dirs()
