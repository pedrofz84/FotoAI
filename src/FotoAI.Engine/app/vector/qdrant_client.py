import atexit
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointIdsList, HnswConfigDiff
from app.config.settings import settings
from loguru import logger

ENGINE_DIR = Path(__file__).resolve().parents[2]


def _find_qdrant_binary() -> Path | None:
    exe = "qdrant.exe" if sys.platform == "win32" else "qdrant"
    candidates = []
    if os.getenv("FOTOAI_QDRANT_BIN"):
        candidates.append(Path(os.getenv("FOTOAI_QDRANT_BIN")))
    candidates += [ENGINE_DIR / "qdrant" / exe, ENGINE_DIR.parent / "qdrant" / exe]
    return next((c for c in candidates if c.is_file()), None)


def _start_qdrant_server(url: str) -> subprocess.Popen | None:
    """
    Arranca o qdrant.exe nativo (sem Docker) com os dados em %LOCALAPPDATA%\\FotoAI.
    Como o motor Python corre dentro do Job Object da app WPF, este processo filho
    também é terminado quando a app fecha.
    """
    binary = _find_qdrant_binary()
    if not binary:
        return None
    parsed = urlparse(url)
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        return None

    storage = settings.LOCAL_APP_DATA / "Vectors" / "qdrant_server"
    storage.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ,
               QDRANT__STORAGE__STORAGE_PATH=str(storage / "storage"),
               QDRANT__STORAGE__SNAPSHOTS_PATH=str(storage / "snapshots"),
               QDRANT__SERVICE__HOST="127.0.0.1",
               QDRANT__SERVICE__HTTP_PORT=str(parsed.port or 6333),
               QDRANT__SERVICE__GRPC_PORT=str((parsed.port or 6333) + 1),
               QDRANT__TELEMETRY_DISABLED="true",
               QDRANT__LOG_LEVEL="WARN")
    log = open(settings.LOGS_DIR / "qdrant.log", "ab")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    logger.info(f"A arrancar Qdrant nativo: {binary}")
    proc = subprocess.Popen([str(binary)], cwd=str(storage), env=env,
                            stdout=log, stderr=subprocess.STDOUT, creationflags=flags)

    # Esperar até 30s que responda
    # Fecho limpo quando o motor termina normalmente (fora da app WPF não há Job Object)
    def _stop():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    atexit.register(_stop)

    for _ in range(60):
        if proc.poll() is not None:
            logger.error(f"Qdrant terminou ao arrancar (código {proc.returncode}). Ver qdrant.log.")
            return None
        try:
            QdrantClient(url=url, timeout=2).get_collections()
            return proc
        except Exception:
            time.sleep(0.5)
    logger.error("Qdrant não respondeu em 30s.")
    proc.kill()
    return None


class VectorStore:
    COLLECTION_NAME = "fotoai_collection"
    VECTOR_SIZE = 512  # clip-ViT-B-32 / clip-ViT-B-32-multilingual-v1

    def __init__(self):
        self.client: QdrantClient | None = None
        self.mode = None
        self.server_process: subprocess.Popen | None = None

    def _try_server(self, url: str) -> QdrantClient | None:
        try:
            client = QdrantClient(url=url, timeout=10)
            client.get_collections()
            return client
        except Exception:
            return None

    def _connect(self) -> QdrantClient:
        url = settings.QDRANT_URL
        if url and url.lower() != "local":
            # 1. Já há um servidor a correr (outro processo, Docker, etc.)
            client = self._try_server(url)
            # 2. Senão, arranca o qdrant.exe que vem com o motor
            if client is None:
                self.server_process = _start_qdrant_server(url)
                if self.server_process:
                    client = self._try_server(url)
            if client is not None:
                self.mode = "server"
                logger.info(f"Ligado ao servidor Qdrant em {url}.")
                return client
            logger.warning(f"Servidor Qdrant em {url} indisponível e qdrant.exe não encontrado/falhou. "
                           "A usar modo local, que fica lento acima de ~20 mil fotos. "
                           "Coloca o qdrant.exe em src/FotoAI.Engine/qdrant/.")
        self.mode = "local"
        return QdrantClient(path=str(settings.QDRANT_DIR))

    def initialize(self):
        if self.client is None:
            self.client = self._connect()
        try:
            if not self.client.collection_exists(self.COLLECTION_NAME):
                logger.warning(f"Coleção '{self.COLLECTION_NAME}' não existe. A criar...")
                self.client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(size=self.VECTOR_SIZE, distance=Distance.COSINE,
                                                on_disk=True),
                    hnsw_config=HnswConfigDiff(on_disk=True),
                )
            # Índice para filtrar por data de captura (o modo local ignora índices, e não faz mal)
            try:
                from qdrant_client.models import PayloadSchemaType
                info = self.client.get_collection(self.COLLECTION_NAME)
                if "capture_ts" not in (info.payload_schema or {}):
                    self.client.create_payload_index(self.COLLECTION_NAME, field_name="capture_ts",
                                                     field_schema=PayloadSchemaType.INTEGER)
            except Exception as e:
                logger.debug(f"Índice capture_ts não criado: {e}")
            count = self.client.count(self.COLLECTION_NAME, exact=False).count
            logger.info(f"Base vetorial pronta ({self.mode}, ~{count} vetores).")
        except Exception as e:
            logger.error(f"Erro ao inicializar Qdrant: {e}")

    def delete_embeddings(self, guid_list: list[str]):
        if not guid_list:
            return
        try:
            for i in range(0, len(guid_list), 1000):
                self.client.delete(
                    collection_name=self.COLLECTION_NAME,
                    points_selector=PointIdsList(points=guid_list[i:i + 1000]),
                )
        except Exception as e:
            logger.error(f"Erro ao remover vetores órfãos: {e}")


vector_store = VectorStore()
