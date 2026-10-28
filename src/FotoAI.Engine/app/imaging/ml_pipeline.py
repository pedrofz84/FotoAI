import os
import threading
from pathlib import Path
from loguru import logger

# Tamanho aproximado de cada modelo no disco (para mostrar progresso do download)
MODEL_SIZES_MB = {
    "clip-ViT-B-32": 605,
    "clip-ViT-B-32-multilingual-v1": 540,
}
MODEL_LABELS = {
    "clip-ViT-B-32": "modelo de imagem",
    "clip-ViT-B-32-multilingual-v1": "modelo de texto",
}


def _hf_model_dir(name: str) -> Path | None:
    try:
        from huggingface_hub import constants
        cache = Path(constants.HF_HUB_CACHE)
    except Exception:
        cache = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return cache / f"models--sentence-transformers--{name}"


def _is_cached(name: str) -> bool:
    d = _hf_model_dir(name)
    snaps = d / "snapshots" if d else None
    return bool(snaps and snaps.is_dir() and any(snaps.iterdir()))


def _downloaded_mb(name: str) -> float:
    d = _hf_model_dir(name)
    blobs = d / "blobs" if d else None
    if not blobs or not blobs.is_dir():
        return 0.0
    total = 0
    for f in blobs.iterdir():
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total / 1_048_576


class MLPipeline:
    def __init__(self):
        # O CLIP original da OpenAI não percebe português.
        # Imagens usam o ViT-B-32 original e o texto o modelo multilingue destilado (mesmo espaço vetorial).
        self.img_model_name = "clip-ViT-B-32"
        self.text_model_name = "clip-ViT-B-32-multilingual-v1"
        self._img_model = None
        self._text_model = None
        self._lock = threading.Lock()
        self.device = None
        # Estado visível na UI
        self._loading_name = None       # modelo a carregar neste momento
        self._loading_download = False  # True se não estava em cache
        self._error = None

    # ---------- estado ----------
    def get_status(self) -> dict:
        if self._error:
            return {"state": "error", "message": f"Erro ao carregar o modelo de IA: {self._error}"}
        name = self._loading_name
        if name:
            label = MODEL_LABELS.get(name, name)
            if self._loading_download:
                mb = _downloaded_mb(name)
                total = MODEL_SIZES_MB.get(name)
                prog = min(mb / total, 0.99) if total else -1
                return {"state": "downloading", "progress": prog,
                        "message": f"A descarregar o {label} (só da primeira vez): "
                                   f"{mb:.0f} de ~{total} MB"}
            return {"state": "loading", "progress": -1,
                    "message": f"A carregar o {label} para a memória..."}
        if self._img_model is not None and self._text_model is not None:
            return {"state": "ready", "message": f"Modelo de IA pronto ({self.device.upper()})"}
        return {"state": "not_loaded", "message": "Modelo de IA ainda não carregado"}

    def preload(self):
        """Carrega os dois modelos em segundo plano no arranque, para a UI mostrar o progresso."""
        def _run():
            try:
                self._load_text_model()
                self._load_img_model()
                logger.info("Modelos de IA prontos.")
            except Exception as e:
                logger.exception(f"Falha ao pré-carregar modelos: {e}")
        threading.Thread(target=_run, daemon=True).start()

    # ---------- carregamento ----------
    def _pick_device(self) -> str:
        if self.device is None:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
                logger.info(f"GPU detetada: {torch.cuda.get_device_name(0)}")
            else:
                self.device = "cpu"
                logger.warning("Sem GPU CUDA: a indexação vai correr no CPU (mais lento). "
                               "Instala o torch com CUDA para acelerar.")
        return self.device

    def _load(self, name: str):
        from sentence_transformers import SentenceTransformer
        self._loading_download = not _is_cached(name)
        self._loading_name = name
        self._error = None
        try:
            dev = self._pick_device()
            verb = "A descarregar e carregar" if self._loading_download else "A carregar"
            logger.info(f"{verb} {name} em {dev}...")
            return SentenceTransformer(name, device=dev)
        except Exception as e:
            self._error = f"{type(e).__name__}: {e}"
            raise
        finally:
            self._loading_name = None

    def _load_img_model(self):
        with self._lock:
            if self._img_model is None:
                self._img_model = self._load(self.img_model_name)

    def _load_text_model(self):
        with self._lock:
            if self._text_model is None:
                self._text_model = self._load(self.text_model_name)

    # ---------- inferência ----------
    def encode_pil_images(self, images: list, batch_size: int = 32) -> list[list[float]]:
        """Codifica várias imagens PIL (RGB, já orientadas) numa só passagem pelo modelo."""
        if not images:
            return []
        self._load_img_model()
        import torch
        with torch.inference_mode():
            feats = self._img_model.encode(images, batch_size=batch_size,
                                           convert_to_numpy=True, show_progress_bar=False)
        return feats.tolist()

    def encode_pil_image(self, pil_image) -> list[float]:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(pil_image).convert("RGB")
        return self.encode_pil_images([img], batch_size=1)[0]

    def encode_image(self, image_path: str) -> list[float]:
        from app.imaging.image_loader import load_image
        from app.config.settings import settings
        img = load_image(image_path, max_side=settings.CLIP_INPUT_MAX)
        return self.encode_pil_images([img], batch_size=1)[0]

    def encode_text(self, text: str) -> list[float]:
        self._load_text_model()
        import torch
        with torch.inference_mode():
            features = self._text_model.encode(text, convert_to_numpy=True, show_progress_bar=False)
        return features.tolist()


# Instância lazy-loaded
ml_pipeline = MLPipeline()
