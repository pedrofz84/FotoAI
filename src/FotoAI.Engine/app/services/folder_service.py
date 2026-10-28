"""
Gestão de pastas indexadas sobrepostas.

Cada ficheiro só pode pertencer a uma biblioteca (file_path é único). Por isso:
  - indexar uma subpasta de uma biblioteca existente faz só o sync dessa subpasta, dentro da biblioteca-mãe;
  - indexar uma pasta-mãe de bibliotecas existentes absorve-as (as fotos já indexadas não são refeitas).
"""
import os
from loguru import logger
from sqlalchemy.orm import Session
from app.models.domain import IndexedFolder, PhotoRecord


def norm(path: str) -> str:
    """Normaliza para comparação (Windows: sem distinção de maiúsculas e com \\)."""
    return os.path.normcase(os.path.normpath(path))


def is_inside(child: str, parent: str) -> bool:
    c, p = norm(child), norm(parent)
    if c == p:
        return False
    return c.startswith(p.rstrip("\\/") + os.sep)


def _absorb(db: Session, parent: IndexedFolder, child: IndexedFolder) -> int:
    moved = db.query(PhotoRecord).filter(PhotoRecord.library_id == child.id).update(
        {"library_id": parent.id}, synchronize_session=False)
    logger.info(f"[Pastas] '{child.folder_path}' integrada em '{parent.folder_path}' ({moved} fotos).")
    db.delete(child)
    return moved


def consolidate_folders(db: Session) -> None:
    """Junta bibliotecas que estão dentro de outras (corre no arranque)."""
    folders = db.query(IndexedFolder).all()
    changed = False
    for child in folders:
        parent = next((f for f in folders if f is not child and is_inside(child.folder_path, f.folder_path)), None)
        if parent and db.get(IndexedFolder, child.id) is not None:
            _absorb(db, parent, child)
            changed = True
    if changed:
        db.commit()


def resolve_index_target(db: Session, folder_path: str) -> tuple[IndexedFolder, str]:
    """
    Devolve (biblioteca, pasta_a_percorrer).
    A pasta a percorrer pode ser uma subpasta da biblioteca (sync parcial).
    """
    folders = db.query(IndexedFolder).all()

    same = next((f for f in folders if norm(f.folder_path) == norm(folder_path)), None)
    if same:
        return same, same.folder_path

    parent = next((f for f in folders if is_inside(folder_path, f.folder_path)), None)
    if parent:
        logger.info(f"[Pastas] '{folder_path}' já faz parte de '{parent.folder_path}': sync só da subpasta.")
        return parent, folder_path

    lib = IndexedFolder(folder_path=folder_path)
    db.add(lib)
    db.flush()
    for child in [f for f in folders if is_inside(f.folder_path, folder_path)]:
        _absorb(db, lib, child)
    db.commit()
    db.refresh(lib)
    return lib, folder_path
