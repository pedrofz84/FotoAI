import os
import threading
import time
import uuid
from typing import NamedTuple
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from loguru import logger
from app.config.settings import settings
from app.db.database import SessionLocal
from app.models.domain import PhotoRecord, IndexedFolder
from app.services.scan_service import scan_directory_tree
from app.services.diff_service import calculate_library_diff, apply_diff_to_db, count_library_records


class WorkItem(NamedTuple):
    photo_id: int
    file_path: str            # original (é o que a UI abre)
    guid: str
    load_path: str            # de onde se lê a imagem: o original ou a pré-visualização do Lightroom
    rotate: int = 0           # graus no sentido dos ponteiros do relógio
    capture_ts: int | None = None


def _rotate(img, degrees: int):
    from PIL import Image
    if degrees == 90:
        return img.transpose(Image.Transpose.ROTATE_270)
    if degrees == 180:
        return img.transpose(Image.Transpose.ROTATE_180)
    if degrees == 270:
        return img.transpose(Image.Transpose.ROTATE_90)
    return img


def _prepare_image(item: WorkItem):
    """
    Corre nas threads de I/O: lê o ficheiro uma única vez, grava a miniatura
    e devolve a imagem reduzida para o CLIP. Não toca na base de dados.
    """
    from app.imaging.image_loader import load_image
    from app.imaging.thumbnailer import save_thumbnail
    try:
        try:
            img = load_image(item.load_path, max_side=settings.CLIP_INPUT_MAX)
        except Exception:
            # Pré-visualização desaparecida: tenta o original
            if item.load_path == item.file_path:
                raise
            img = load_image(item.file_path, max_side=settings.CLIP_INPUT_MAX)
        else:
            img = _rotate(img, item.rotate)
        save_thumbnail(img, item.guid)
        return item, img, None
    except Exception as e:
        return item, None, f"{type(e).__name__}: {e}"


def _work_items(rows) -> list[WorkItem]:
    from app.services.lightroom_service import LR_ORIENTATION_DEGREES
    items = []
    for r in rows:
        rotate = 0
        if r.load_path and settings.LR_APPLY_ORIENTATION:
            rotate = LR_ORIENTATION_DEGREES.get(r.lr_orientation or "", 0)
        ts = int(r.capture_time.replace(tzinfo=timezone.utc).timestamp()) if r.capture_time else None
        items.append(WorkItem(r.id, r.file_path, r.guid_id, r.load_path or r.file_path, rotate, ts))
    return items


def _pending_rows(db, library_id: int):
    rows = db.query(PhotoRecord.id, PhotoRecord.file_path, PhotoRecord.guid_id,
                    PhotoRecord.processing_status, PhotoRecord.load_path,
                    PhotoRecord.lr_orientation, PhotoRecord.capture_time).filter(
        PhotoRecord.library_id == library_id,
        PhotoRecord.processing_status.in_(["PENDING", "FAILED"])
    ).all()
    # Pasta a pasta (leitura sequencial no disco); as que já falharam ficam para o fim
    return sorted(rows, key=lambda p: (p.processing_status == "FAILED", (p.load_path or p.file_path).lower()))


def _remove_cached(guids):
    for g in guids:
        for p in (settings.THUMBNAIL_DIR / f"{g}.webp", settings.PREVIEW_DIR / f"{g}.webp"):
            p.unlink(missing_ok=True)


class JobRunner:
    def __init__(self):
        self.state = "IDLE"
        self.current_library_id = None
        self.current_folder_path = None
        self.total_queue_size = 0
        self.processed_count = 0
        self.error_count = 0
        self.started_at = None
        self._cancel = threading.Event()
        # Para a UI
        self.scan_found = 0
        self.last_summary = None
        self.last_error = None
        self._rate_t0 = None
        self._rate_done0 = 0
        self.rate = 0.0
        self.phase_message = None   # mensagem própria da fase (ex.: leitura do catálogo Lightroom)

    def trigger_library_indexing(self, library_id: int, folder_path: str, library_root: str | None = None):
        """folder_path pode ser uma subpasta de library_root (sync parcial)."""
        if self.state not in ("IDLE", "FAILED"):
            logger.warning("Trigger recusado, já há um job em curso.")
            return False
        self._cancel.clear()
        self.scan_found = 0
        self.total_queue_size = 0
        self.processed_count = 0
        self.error_count = 0
        self.last_error = None
        self.rate = 0.0
        self.state = "SCANNING"
        self.current_library_id = library_id
        self.current_folder_path = folder_path
        scope = folder_path if library_root and folder_path != library_root else None
        threading.Thread(target=self._orchestrator_daemon, args=(library_id, folder_path, scope),
                         daemon=True).start()
        return True

    def cancel(self):
        self._cancel.set()

    def _set_folder_status(self, library_id: int, status: str, scanned: bool = False):
        with SessionLocal() as db:
            folder = db.get(IndexedFolder, library_id)
            if folder:
                folder.scan_status = status
                if scanned:
                    folder.last_scanned = datetime.utcnow()
                db.commit()

    def _orchestrator_daemon(self, library_id: int, folder_path: str, scope: str | None = None):
        from app.vector.qdrant_client import vector_store
        try:
            self._set_folder_status(library_id, "SCANNING")
            fs_state = scan_directory_tree(folder_path, progress=self._on_scan_progress)
            self.scan_found = len(fs_state)

            # Disco externo desligado: não apagar a biblioteca inteira por engano
            if not fs_state:
                with SessionLocal() as db:
                    existing = count_library_records(db, library_id, scope)
                if existing:
                    logger.warning(f"Scan vazio para {folder_path} mas existem {existing} registos. "
                                   "Disco desligado? Sincronização abortada sem apagar nada.")
                    self.last_summary = (f"A pasta {folder_path} está vazia ou inacessível "
                                         "(disco desligado?). Nada foi apagado.")
                    self._set_folder_status(library_id, "IDLE")
                    self.state = "IDLE"
                    return

            self.state = "DB_SYNC"
            self._set_folder_status(library_id, "DB_SYNC")
            with SessionLocal() as db:
                diff = calculate_library_diff(db, library_id, fs_state, scope=scope)

                guids_to_del = [rec.guid_id for rec in diff.to_delete]
                if guids_to_del:
                    logger.info(f"A apagar {len(guids_to_del)} vetores obsoletos no Qdrant...")
                    vector_store.delete_embeddings(guids_to_del)
                    _remove_cached(guids_to_del)

                # Fotos editadas: a preview antiga deixa de servir
                for rec, _, _ in diff.to_update:
                    (settings.PREVIEW_DIR / f"{rec.guid_id}.webp").unlink(missing_ok=True)

                apply_diff_to_db(db, library_id, diff)

                # Inclui PENDING de jobs que crasharam e FAILED para nova tentativa
                items = _work_items(_pending_rows(db, library_id))

            self._run_queue(library_id, _short_name(folder_path), items, removed=len(guids_to_del))

        except Exception as e:
            logger.exception(f"Falha no orchestrator: {e}")
            self.last_error = f"{type(e).__name__}: {e}"
            self._set_folder_status(library_id, "FAILED")
            self.state = "FAILED"

    def _run_queue(self, library_id: int, name: str, items: list, removed: int = 0, note: str = ""):
        self.total_queue_size = len(items)
        self.processed_count = 0
        self.error_count = 0
        if not items:
            logger.info("Sincronização terminada. Nada para indexar.")
            self.last_summary = (f"{name}: está tudo atualizado"
                                 + (f" ({_n(removed)} fotos removidas)" if removed else "") + "." + note)
        else:
            self.state = "INDEXING"
            self._set_folder_status(library_id, "INDEXING")
            self._machine_learning_pipeline(items)
            verb = "cancelada" if self._cancel.is_set() else "concluída"
            self.last_summary = (f"Indexação de {name} {verb}: {_n(self.processed_count)} fotos indexadas"
                                 + (f", {_n(self.error_count)} com erro (ver log)" if self.error_count else "")
                                 + "." + note)
        self._set_folder_status(library_id, "IDLE", scanned=True)
        self.state = "IDLE"

    # ---------- Catálogo Lightroom ----------

    def trigger_lightroom_indexing(self, library_id: int, catalog_path: str):
        if self.state not in ("IDLE", "FAILED"):
            logger.warning("Trigger recusado, já há um job em curso.")
            return False
        self._cancel.clear()
        self.scan_found = 0
        self.total_queue_size = 0
        self.processed_count = 0
        self.error_count = 0
        self.last_error = None
        self.rate = 0.0
        self.state = "SCANNING"
        self.phase_message = f"A ler o catálogo {_short_name(catalog_path)}..."
        self.current_library_id = library_id
        self.current_folder_path = catalog_path
        threading.Thread(target=self._lightroom_daemon, args=(library_id, catalog_path), daemon=True).start()
        return True

    def _lightroom_daemon(self, library_id: int, catalog_path: str):
        from app.vector.qdrant_client import vector_store
        from app.services.lightroom_service import read_catalog
        try:
            self._set_folder_status(library_id, "SCANNING")
            result = read_catalog(catalog_path)
            cat = result.photos
            self.scan_found = len(cat)
            name = _short_name(catalog_path)

            if not cat:
                self.last_summary = f"O catálogo {name} não tem fotos que o FotoAI consiga ler. Nada foi alterado."
                self._set_folder_status(library_id, "IDLE")
                self.state = "IDLE"
                return

            self.state = "DB_SYNC"
            self.phase_message = f"A comparar {_n(len(cat))} fotos do catálogo com a base de dados..."
            self._set_folder_status(library_id, "DB_SYNC")
            with SessionLocal() as db:
                existing = {r.file_path: r for r in
                            db.query(PhotoRecord).filter(PhotoRecord.library_id == library_id)}

                # Fotos que já pertencem a uma pasta indexada à parte ficam onde estão
                new_paths = [p for p in cat if p not in existing]
                taken = set()
                for i in range(0, len(new_paths), 500):
                    chunk = new_paths[i:i + 500]
                    taken.update(p for (p,) in db.query(PhotoRecord.file_path).filter(
                        PhotoRecord.file_path.in_(chunk), PhotoRecord.library_id != library_id))
                if taken:
                    logger.warning(f"[Lightroom] {len(taken)} fotos já pertencem a uma pasta indexada; ficam nessa pasta.")

                # Removidas do catálogo
                gone = [r for p, r in existing.items() if p not in cat]
                guids_to_del = [r.guid_id for r in gone]
                if guids_to_del:
                    logger.info(f"[Lightroom] {len(guids_to_del)} fotos saíram do catálogo; a apagar vetores.")
                    vector_store.delete_embeddings(guids_to_del)
                    _remove_cached(guids_to_del)
                    for r in gone:
                        db.delete(r)

                added = changed = 0
                for path, ph in cat.items():
                    rec = existing.get(path)
                    if rec is None:
                        if path in taken:
                            continue
                        db.add(PhotoRecord(
                            library_id=library_id, file_path=path, file_name=os.path.basename(path),
                            guid_id=str(uuid.uuid4()), processing_status="PENDING",
                            capture_time=ph.capture_time, lr_image_id=ph.lr_image_id,
                            lr_fingerprint=ph.fingerprint, lr_orientation=ph.orientation,
                            load_path=ph.load_path, hd_path=ph.hd_path))
                        added += 1
                        continue
                    # Foto editada no Lightroom (pré-visualização nova) ou rodada: volta a indexar
                    if rec.lr_fingerprint != ph.fingerprint or rec.lr_orientation != ph.orientation:
                        if rec.processing_status == "INDEXED":
                            changed += 1
                        rec.processing_status = "PENDING"
                        rec.error_message = None
                        _remove_cached([rec.guid_id])
                    rec.capture_time = ph.capture_time
                    rec.lr_image_id = ph.lr_image_id
                    rec.lr_fingerprint = ph.fingerprint
                    rec.lr_orientation = ph.orientation
                    rec.load_path = ph.load_path
                    rec.hd_path = ph.hd_path
                db.commit()
                logger.info(f"[Lightroom] +{added} novas | ~{changed} editadas | -{len(gone)} removidas")
                items = _work_items(_pending_rows(db, library_id))

            note = ""
            if taken:
                note += f" {_n(len(taken))} fotos já estavam numa pasta indexada à parte."
            no_prev = len(cat) - result.with_preview
            if no_prev:
                note += f" {_n(no_prev)} sem pré-visualização no Lightroom (lidas do original)."
            self.phase_message = None
            self._run_queue(library_id, name, items, removed=len(guids_to_del), note=note)

        except Exception as e:
            from app.services.lightroom_service import LightroomError
            if isinstance(e, LightroomError):
                logger.error(f"[Lightroom] {e}")
                self.last_error = str(e)
            else:
                logger.exception(f"Falha na importação do Lightroom: {e}")
                self.last_error = f"{type(e).__name__}: {e}"
            self._set_folder_status(library_id, "FAILED")
            self.state = "FAILED"
        finally:
            self.phase_message = None

    def _on_scan_progress(self, n: int):
        self.scan_found = n

    def _machine_learning_pipeline(self, items: list[tuple]):
        """
        Pipeline contínuo:
          - várias threads leem e descodificam fotos sem parar (janela deslizante, sem esperar pelo lote);
          - assim que há BATCH_SIZE fotos prontas, o modelo codifica-as numa só chamada,
            com 1 upsert ao Qdrant e 1 commit ao SQLite, enquanto as threads continuam a ler.
        """
        bs = settings.BATCH_SIZE
        workers = settings.loader_workers_for(items[0].load_path) if items else settings.LOADER_WORKERS
        window = max(workers * 3, bs * 2)
        self.started_at = time.time()
        self._rate_t0 = None
        self._rate_done0 = 0
        logger.info(f"A indexar {len(items)} fotos em lotes de {bs} "
                    f"({workers} threads de leitura, {window} ficheiros em voo)...")

        source = iter(items)
        inflight = set()
        ready = []
        batch_no = 0
        pool = ThreadPoolExecutor(max_workers=workers)

        def refill():
            while len(inflight) < window:
                item = next(source, None)
                if item is None:
                    return
                inflight.add(pool.submit(_prepare_image, item))

        try:
            refill()
            while inflight or ready:
                if self._cancel.is_set():
                    logger.warning("Indexação cancelada pelo utilizador.")
                    break
                if inflight:
                    done, _ = wait(inflight, timeout=1.0, return_when=FIRST_COMPLETED)
                    for f in done:
                        inflight.discard(f)
                        ready.append(f.result())
                    refill()
                # Processa quando há um lote cheio, ou o que sobra no fim
                while len(ready) >= bs or (ready and not inflight):
                    chunk, ready = ready[:bs], ready[bs:]
                    self._process_batch(chunk, batch_no)
                    batch_no += 1
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _process_batch(self, prepared: list, batch_no: int):
        from app.imaging.ml_pipeline import ml_pipeline
        from app.vector.qdrant_client import vector_store
        from qdrant_client.models import PointStruct

        ok = [(item, img) for item, img, err in prepared if img is not None]
        failed = {item.photo_id: err for item, img, err in prepared if img is None}

        indexed_ids = []
        if ok:
            try:
                vectors = ml_pipeline.encode_pil_images([img for _, img in ok], batch_size=len(ok))
                points = []
                for (item, _), vec in zip(ok, vectors):
                    payload = {"photo_id": item.photo_id, "file_path": item.file_path}
                    if item.capture_ts is not None:
                        payload["capture_ts"] = item.capture_ts   # para filtros por data no futuro
                    points.append(PointStruct(id=item.guid, vector=vec, payload=payload))
                vector_store.client.upsert(collection_name=vector_store.COLLECTION_NAME,
                                           points=points, wait=True)
                indexed_ids = [item.photo_id for item, _ in ok]
            except Exception as e:
                logger.error(f"Lote {batch_no} falhou no modelo/Qdrant: {e}")
                for item, _ in ok:
                    failed[item.photo_id] = f"{type(e).__name__}: {e}"

        now = datetime.utcnow()
        with SessionLocal() as db:
            if indexed_ids:
                db.query(PhotoRecord).filter(PhotoRecord.id.in_(indexed_ids)).update(
                    {"processing_status": "INDEXED", "indexed_date": now, "error_message": None},
                    synchronize_session=False)
            for pid, err in failed.items():
                db.query(PhotoRecord).filter(PhotoRecord.id == pid).update(
                    {"processing_status": "FAILED", "error_message": err[:500]},
                    synchronize_session=False)
            db.commit()

        self.processed_count += len(indexed_ids)
        self.error_count += len(failed)

        # Velocidade medida a partir do 1º lote (exclui o tempo de carregar o modelo)
        done_now = self.processed_count + self.error_count
        if self._rate_t0 is None:
            self._rate_t0, self._rate_done0 = time.time(), done_now
        else:
            dt = time.time() - self._rate_t0
            if dt > 0:
                self.rate = (done_now - self._rate_done0) / dt

        if batch_no % 20 == 0 or done_now == self.total_queue_size:
            eta_min = (self.total_queue_size - done_now) / self.rate / 60 if self.rate > 0 else 0
            logger.info(f"[Indexação] {done_now}/{self.total_queue_size} "
                        f"({self.rate:.1f} fotos/s, faltam ~{eta_min:.0f} min, {self.error_count} erros)")

    def get_status(self) -> dict:
        from app.imaging.ml_pipeline import ml_pipeline
        model = ml_pipeline.get_status()
        model_busy = model["state"] in ("downloading", "loading")
        name = _short_name(self.current_folder_path) if self.current_folder_path else ""
        progress, eta = -1.0, None
        phase = self.state

        if phase in ("SCANNING", "DB_SYNC") and self.phase_message:
            msg = self.phase_message
        elif phase == "SCANNING":
            msg = f"A procurar fotos em {name}... {_n(self.scan_found)} encontradas"
        elif phase == "DB_SYNC":
            msg = f"A comparar {_n(self.scan_found)} fotos com a base de dados..."
        elif phase == "INDEXING":
            total = self.total_queue_size
            done = self.processed_count + self.error_count
            progress = done / total if total else 0.0
            if model_busy:
                phase = "MODEL"
                msg = f"{model['message']} · depois indexa {_n(total)} fotos"
                progress = model.get("progress", -1)
            elif done == 0:
                msg = f"A começar a indexar {_n(total)} fotos de {name}..."
            else:
                if self.rate > 0:
                    eta = int((total - done) / self.rate)
                msg = (f"A indexar {name}: {_n(done)} de {_n(total)} fotos"
                       + (f" · {self.rate:.1f}".replace(".", ",") + f" fotos/s · faltam {_fmt_eta(eta)}" if eta is not None else "")
                       + (f" · {_n(self.error_count)} erros" if self.error_count else ""))
        elif phase == "FAILED":
            msg = f"A indexação falhou: {self.last_error}"
        else:  # IDLE
            if model_busy:
                phase = "MODEL"
                msg = model["message"]
                progress = model.get("progress", -1)
            elif model["state"] == "error":
                phase = "FAILED"
                msg = model["message"]
            else:
                total_indexed = _count_indexed()
                msg = (f"{self.last_summary} Total na biblioteca: {_n(total_indexed)} fotos."
                       if self.last_summary else f"Pronto · {_n(total_indexed)} fotos indexadas")

        return {
            "is_running": self.state not in ("IDLE", "FAILED"),
            "current_folder": self.current_folder_path or "None",
            "total_files_found": self.total_queue_size,
            "files_processed": self.processed_count,
            "errors": self.error_count,
            "phase": phase,
            "message": msg,
            "progress": progress,
            "eta_seconds": eta,
        }


def _n(x: int) -> str:
    """Números à portuguesa: 12 345"""
    return f"{x:,}".replace(",", " ")


def _short_name(path: str) -> str:
    if not path:
        return ""
    return os.path.basename(path.rstrip("\\/")) or path


def _fmt_eta(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 60:
        return "menos de 1 min"
    if seconds < 3600:
        return f"~{seconds // 60} min"
    h, m = divmod(seconds // 60, 60)
    return f"~{h} h {m:02d} min"


def _count_indexed() -> int:
    try:
        with SessionLocal() as db:
            return db.query(PhotoRecord).filter(PhotoRecord.processing_status == "INDEXED").count()
    except Exception:
        return 0


job_manager = JobRunner()
