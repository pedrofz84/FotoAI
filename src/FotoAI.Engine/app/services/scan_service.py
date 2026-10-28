import os
from loguru import logger
from typing import Dict, Tuple
from app.imaging.image_loader import supported_extensions

SUPPORTED_EXTENSIONS = supported_extensions()

# Pastas que não interessam (caches do Lightroom, lixo do sistema)
SKIP_DIR_SUFFIXES = (".lrdata", ".lrcat-data")
SKIP_DIR_NAMES = {"$RECYCLE.BIN", "System Volume Information", ".git"}


def scan_directory_tree(root_path: str, progress=None) -> Dict[str, Tuple[int, float]]:
    """
    Realiza um os.walk rápido para recolher o estado real do sistema de ficheiros.
    Ignora permissões com excepções silenciadas.
    Retorna Dict[Absolute_Path, (Size_Bytes, Modified_Time)]
    """
    logger.info(f"[ScanService] A iniciar scan em: {root_path} (extensões: {len(SUPPORTED_EXTENSIONS)})")
    current_state = {}

    try:
        if not os.path.exists(root_path):
            logger.warning(f"[ScanService] Caminho não encontrado/removido do disco: {root_path}")
            return current_state

        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIR_NAMES and not d.lower().endswith(SKIP_DIR_SUFFIXES)]
            for f in filenames:
                if f.startswith("._"):  # metadados macOS
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    full_path = os.path.join(dirpath, f)
                    try:
                        stat = os.stat(full_path)
                        current_state[full_path] = (stat.st_size, stat.st_mtime)
                        if progress and len(current_state) % 200 == 0:
                            progress(len(current_state))
                    except Exception as e:
                        logger.error(f"[ScanService] Falha ao ler stat de {full_path}: {e}")
    except Exception as e:
        logger.error(f"[ScanService] Falha no scan (disco desligado?): {e}")

    logger.info(f"[ScanService] O Scan revelou {len(current_state)} imagens suportadas.")
    return current_state
