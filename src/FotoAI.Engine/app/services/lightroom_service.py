"""
Leitura de catálogos do Lightroom Classic (.lrcat), sempre só em leitura.

O .lrcat é uma base SQLite. Ao lado dele, a pasta "<nome> Previews.lrdata" guarda as
pré-visualizações que o Lightroom já gerou: JPEGs sem extensão chamados
"{uuid}-{digest}_{lado maior}", com as edições (cortes, revelação) já aplicadas.
A tabela ImageCacheEntry da previews.db liga cada foto do catálogo (imageId) ao seu uuid/digest.

O FotoAI usa essas pré-visualizações para o CLIP e para as miniaturas, em vez de abrir
os originais (muito mais rápido em RAW). Nunca escreve nada no catálogo.
"""
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from loguru import logger
from app.config.settings import settings
from app.imaging.image_loader import supported_extensions


class LightroomError(Exception):
    """Erro com mensagem pronta a mostrar ao utilizador."""


@dataclass
class LrPhoto:
    lr_image_id: int
    file_path: str
    capture_time: datetime | None
    orientation: str | None
    fingerprint: str | None     # uuid:digest da pré-visualização
    load_path: str | None       # nível para o CLIP / miniatura
    hd_path: str | None         # nível para a vista HD


@dataclass
class CatalogReadResult:
    photos: dict                # file_path -> LrPhoto
    total_in_catalog: int
    with_preview: int
    skipped_virtual_copies: int
    skipped_unsupported: int


def _paths(catalog_path: str):
    cat = Path(catalog_path)
    previews = cat.parent / f"{cat.stem} Previews.lrdata"
    return cat, previews


def is_locked(catalog_path: str) -> bool:
    cat, _ = _paths(catalog_path)
    return any((cat.parent / f"{cat.stem}{suf}").exists() for suf in (".lrcat-lock", ".lrcat.lock"))


def validate_catalog(catalog_path: str) -> None:
    """Verificações rápidas antes de aceitar o pedido (dão mensagens claras à UI)."""
    cat, _ = _paths(catalog_path)
    if cat.suffix.lower() != ".lrcat":
        raise LightroomError("O ficheiro escolhido não é um catálogo do Lightroom (.lrcat).")
    if not cat.is_file():
        raise LightroomError(f"Não encontrei o catálogo {cat}.")
    if is_locked(catalog_path):
        raise LightroomError("O Lightroom está aberto com este catálogo. Fecha o Lightroom e tenta outra vez.")
    try:
        con = _connect_ro(cat)
        con.execute("SELECT COUNT(*) FROM Adobe_images").fetchone()
        con.close()
    except sqlite3.Error as e:
        raise LightroomError(f"Não consegui ler o catálogo ({e}). Abre e fecha o Lightroom e tenta outra vez.")


def _connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _columns(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}


def _parse_capture(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value[:19])
    except ValueError:
        return None
    # 1904 é a "data zero" usada quando a foto não tem data
    return None if dt.year <= 1904 else dt


def _index_preview_files(previews_dir: Path) -> dict:
    """(UUID, DIGEST) -> {lado maior: caminho}. Percorre a pasta uma vez, sem abrir ficheiros."""
    index: dict = {}
    n = 0
    for root, _, files in os.walk(previews_dir):
        for name in files:
            if "." in name or "_" not in name:
                continue
            base, _, dim = name.rpartition("_")
            if len(base) < 38 or base[36] != "-" or not dim.isdigit():
                continue
            key = (base[:36].upper(), base[37:].upper())
            index.setdefault(key, {})[int(dim)] = os.path.join(root, name)
            n += 1
    logger.info(f"[Lightroom] {n} ficheiros de pré-visualização para {len(index)} fotos.")
    return index


def _pick_levels(levels: dict) -> tuple[str, str]:
    dims = sorted(levels)
    clip = next((d for d in dims if d >= settings.LR_CLIP_MIN_SIDE), dims[-1])
    hd = next((d for d in dims if d >= settings.LR_HD_MIN_SIDE), dims[-1])
    return levels[clip], levels[hd]


def _read_preview_map(previews_dir: Path) -> dict:
    """imageId -> (uuid, digest), das fotos e da imagem de capa dos vídeos."""
    db = previews_dir / "previews.db"
    if not db.is_file():
        logger.warning(f"[Lightroom] Sem previews.db em {previews_dir}; vão ler-se os originais.")
        return {}
    con = _connect_ro(db)
    try:
        rows = con.execute("SELECT imageId, uuid, digest FROM ImageCacheEntry").fetchall()
    finally:
        con.close()
    return {int(i): (str(u).upper(), str(d).upper()) for i, u, d in rows}


def read_catalog(catalog_path: str) -> CatalogReadResult:
    cat, previews_dir = _paths(catalog_path)
    validate_catalog(catalog_path)

    con = _connect_ro(cat)
    try:
        img_cols = _columns(con, "Adobe_images")
        sel_orient = "i.orientation" if "orientation" in img_cols else "NULL"
        sel_master = "i.masterImage" if "masterImage" in img_cols else "NULL"
        rows = con.execute(f"""
            SELECT i.id_local, i.captureTime, i.fileFormat, {sel_orient}, {sel_master},
                   r.absolutePath, fo.pathFromRoot, f.baseName, f.extension
            FROM Adobe_images i
            JOIN AgLibraryFile f        ON i.rootFile = f.id_local
            JOIN AgLibraryFolder fo     ON f.folder = fo.id_local
            JOIN AgLibraryRootFolder r  ON fo.rootFolder = r.id_local
        """).fetchall()
    finally:
        con.close()

    preview_map = _read_preview_map(previews_dir)
    preview_files = _index_preview_files(previews_dir) if previews_dir.is_dir() else {}
    by_uuid = {}
    for (u, _d), levels in preview_files.items():
        by_uuid.setdefault(u, levels)   # pré-visualização antiga serve se a atual não existir

    exts = supported_extensions()
    photos: dict = {}
    virtual = unsupported = with_preview = 0

    for (img_id, capture, fmt, orient, master, root, rel, base, ext) in rows:
        if master:  # cópia virtual: o mesmo ficheiro que a original
            virtual += 1
            continue
        name = f"{base}.{ext}" if ext else base
        path = os.path.normpath(os.path.join(root or "", rel or "", name))
        if path in photos:
            continue

        fingerprint = load_path = hd_path = None
        key = preview_map.get(int(img_id))
        if key:
            levels = preview_files.get(key) or by_uuid.get(key[0])
            if levels:
                load_path, hd_path = _pick_levels(levels)
                fingerprint = f"{key[0]}:{key[1]}"
                with_preview += 1

        # Sem pré-visualização só se aproveitam os formatos que o FotoAI sabe abrir (vídeos não)
        if not load_path and os.path.splitext(name)[1].lower() not in exts:
            unsupported += 1
            continue

        photos[path] = LrPhoto(
            lr_image_id=int(img_id),
            file_path=path,
            capture_time=_parse_capture(capture),
            orientation=orient if isinstance(orient, str) else None,
            fingerprint=fingerprint,
            load_path=load_path,
            hd_path=hd_path,
        )

    logger.info(f"[Lightroom] Catálogo {cat.name}: {len(rows)} itens, {len(photos)} a usar, "
                f"{with_preview} com pré-visualização, {virtual} cópias virtuais, "
                f"{unsupported} sem pré-visualização e em formato não suportado.")
    return CatalogReadResult(photos, len(rows), with_preview, virtual, unsupported)


# Orientação do Lightroom -> rotação em graus no sentido dos ponteiros do relógio
LR_ORIENTATION_DEGREES = {"AB": 0, "BC": 90, "CD": 180, "DA": 270}
