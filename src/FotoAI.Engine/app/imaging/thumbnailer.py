from PIL import Image, ImageOps
from loguru import logger
from app.config.settings import settings
from app.imaging.image_loader import load_image

THUMB_SIZE = (300, 300)      # Grelhas do WPF (crop quadrado)
PREVIEW_SIZE = (1920, 1080)  # Lightbox HD


def thumb_path_for(guid_id: str):
    return settings.THUMBNAIL_DIR / f"{guid_id}.webp"


def preview_path_for(guid_id: str):
    return settings.PREVIEW_DIR / f"{guid_id}.webp"


def save_thumbnail(img: Image.Image, guid_id: str) -> None:
    """Grava a miniatura quadrada a partir de uma imagem já carregada e orientada."""
    thumb = ImageOps.fit(img, THUMB_SIZE, Image.Resampling.BICUBIC)
    thumb.save(thumb_path_for(guid_id), "WEBP", quality=75)


def ensure_preview(original_path: str, guid_id: str):
    """Gera a preview HD só quando é pedida. Devolve o caminho ou None."""
    p = preview_path_for(guid_id)
    if p.exists():
        return p
    try:
        img = load_image(original_path, max_side=max(PREVIEW_SIZE))
        img.thumbnail(PREVIEW_SIZE, Image.Resampling.BICUBIC)
        img.save(p, "WEBP", quality=85)
        return p
    except Exception as e:
        logger.error(f"Erro a gerar preview para {original_path}: {e}")
        return None
