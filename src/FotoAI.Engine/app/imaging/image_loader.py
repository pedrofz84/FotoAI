"""
Carregamento unificado de imagens: JPEG/PNG/WebP/TIFF, HEIC (telemóveis) e RAW de câmara.

Para RAW usa a pré-visualização JPEG embutida pelo fabricante (rápido, sem revelar o RAW).
Se a pré-visualização for minúscula (comum em câmaras antigas) revela o RAW em meia resolução.
Aplica sempre a orientação EXIF, para o CLIP e as miniaturas verem a foto direita.
"""
import io
import os
import time
from PIL import Image, ImageOps
from loguru import logger

# Limite generoso para evitar DecompressionBomb (aprox 150 Megapixeis)
Image.MAX_IMAGE_PIXELS = 150_000_000

RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng",
    ".orf", ".rw2", ".raf", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc",
    ".mrw", ".mos", ".iiq", ".rwl",
}
HEIF_EXTENSIONS = {".heic", ".heif"}
STANDARD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# Abaixo disto a pré-visualização embutida não chega para o CLIP; revela-se o RAW.
MIN_EMBEDDED_PREVIEW = 400

_heif_ok = False
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _heif_ok = True
except ImportError:
    logger.warning("pillow-heif não instalado: ficheiros HEIC serão ignorados.")

try:
    import rawpy
    _raw_ok = True
except ImportError:
    rawpy = None
    _raw_ok = False
    logger.warning("rawpy não instalado: ficheiros RAW serão ignorados.")


def supported_extensions() -> set[str]:
    exts = set(STANDARD_EXTENSIONS)
    if _heif_ok:
        exts |= HEIF_EXTENSIONS
    if _raw_ok:
        exts |= RAW_EXTENSIONS
    return exts


def _orient_from_raw_flip(img: Image.Image, flip: int) -> Image.Image:
    # LibRaw 'flip': 0 normal, 3 180º, 5 90º CCW, 6 90º CW
    if flip == 3:
        return img.transpose(Image.Transpose.ROTATE_180)
    if flip == 5:
        return img.transpose(Image.Transpose.ROTATE_90)
    if flip == 6:
        return img.transpose(Image.Transpose.ROTATE_270)
    return img


RETRIES = 3


def _read_all(path: str) -> io.BytesIO:
    """
    Lê o ficheiro inteiro numa só operação e confirma que chegou completo
    (em SMB, sob carga, uma leitura pode devolver menos bytes sem dar erro).
    Usado para JPEG/PNG/HEIC, que têm de ser lidos todos de qualquer forma.
    """
    last = None
    for attempt in range(RETRIES):
        try:
            expected = os.stat(path).st_size
            with open(path, "rb") as f:
                data = f.read()
            if len(data) == expected:
                return io.BytesIO(data)
            last = IOError(f"leitura incompleta ({len(data)} de {expected} bytes)")
        except OSError as e:
            last = e
        time.sleep(0.5 * (attempt + 1))
    raise last


def _open_raw(path: str):
    """
    Abre o RAW pelo caminho: o LibRaw só lê o cabeçalho e a pré-visualização embutida,
    em vez dos 15-30 MB do ficheiro inteiro. Erros de I/O (rede) têm nova tentativa;
    'formato não suportado' não, porque é do ficheiro e repetir só faz perder tempo.
    """
    last = None
    for attempt in range(RETRIES):
        try:
            return rawpy.imread(path)
        except rawpy.LibRawFileUnsupportedError:
            raise
        except (rawpy.LibRawIOError, OSError) as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last


def _tiff_orientation(data: bytes) -> int:
    """Orientação EXIF guardada no cabeçalho TIFF de RAWs como CR2/NEF/ARW/DNG."""
    try:
        with Image.open(io.BytesIO(data)) as tif:
            return int(tif.getexif().get(0x0112, 1))
    except Exception:
        return 1


def _largest_embedded_jpeg(path: str) -> Image.Image:
    """
    Último recurso para RAWs que o LibRaw não reconhece: quase todos os formatos RAW
    trazem uma pré-visualização JPEG completa lá dentro. Procura-a e usa a maior.
    """
    data = _read_all(path).getvalue()
    best, best_area = None, 0
    start = 0
    for _ in range(64):  # limite de candidatos
        off = data.find(b"\xff\xd8\xff", start)
        if off < 0:
            break
        start = off + 3
        try:
            cand = Image.open(io.BytesIO(data[off:]))
            if cand.format != "JPEG":
                continue
            area = cand.size[0] * cand.size[1]
            if area > best_area:
                best, best_area = cand, area
        except Exception:
            continue
    if best is None or max(best.size) < MIN_EMBEDDED_PREVIEW:
        raise RuntimeError("RAW não suportado pelo LibRaw e sem pré-visualização JPEG utilizável")
    best.load()
    orient = best.getexif().get(0x0112, 1)
    if orient == 1:
        orient = _tiff_orientation(data)
    if orient != 1:
        exif = best.getexif()
        exif[0x0112] = orient
        best.info["exif"] = exif.tobytes()
        best = ImageOps.exif_transpose(best)
    return best


def _load_raw(path: str) -> Image.Image:
    try:
        raw_ctx = _open_raw(path)
    except rawpy.LibRawFileUnsupportedError:
        return _largest_embedded_jpeg(path)
    with raw_ctx as raw:
        flip = getattr(raw.sizes, "flip", 0)
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                img = Image.open(io.BytesIO(thumb.data))
                img.load()
                if max(img.size) >= MIN_EMBEDDED_PREVIEW:
                    # O JPEG embutido costuma trazer EXIF próprio; se não trouxer, usa o flip do RAW
                    if img.getexif().get(0x0112, 1) != 1:
                        return ImageOps.exif_transpose(img)
                    return _orient_from_raw_flip(img, flip)
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                img = Image.fromarray(thumb.data)
                if max(img.size) >= MIN_EMBEDDED_PREVIEW:
                    return _orient_from_raw_flip(img, flip)
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            pass
        # Fallback: revelar o RAW (half_size é ~4x mais rápido e chega para pesquisa)
        rgb = raw.postprocess(half_size=True, use_camera_wb=True, no_auto_bright=False)
        return Image.fromarray(rgb)  # postprocess já aplica a rotação


def load_image(path: str, max_side: int | None = None) -> Image.Image:
    """Devolve uma PIL.Image RGB, orientada, opcionalmente reduzida para max_side."""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTENSIONS:
        if not _raw_ok:
            raise RuntimeError("rawpy não instalado")
        img = _load_raw(path)
    else:
        img = Image.open(_read_all(path))
        if max_side and img.format == "JPEG":
            # draft() faz o decoder JPEG descodificar já reduzido (muito mais rápido em fotos grandes)
            img.draft("RGB", (max_side, max_side))
        img = ImageOps.exif_transpose(img)

    if img.mode != "RGB":
        img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.BICUBIC)
    return img
