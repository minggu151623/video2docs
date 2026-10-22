import argparse
import json
import logging
import os
import shutil
import threading
import time
import subprocess
import signal
from sqlalchemy import select, update, func
from pydantic import ValidationError
from app.core.config import get_settings, Settings
from app.core.errors import AppError
from app.core.storage import uid, sha256, file_hash, atomic_write, safe_path
from app.db.session import create_db, migrate
from app.db.models import (
    Project,
    Asset,
    Job,
    Chunk,
    ProviderCall,
    RemoteFile,
    Generation,
    Document,
    Revision,
    Evidence,
    Export,
    PriceSnapshot,
    now,
)
from app.providers import get_provider
from app.schemas.tutorial_v2 import TutorialDraftV2, load_draft
from app.services.media import plan_chunks, probe, encode, extract_frame
from app.services.documents import assemble, render_markdown, create_revision, has_review_claims
from app.services.analysis import clip_metadata, evidence_timestamp, repair_payload
from app.providers.timecodes import TimecodeError
from app.services.exports import build_export
from app.services.budget import check_budget, cost

TERMINAL = {"succeeded", "needs_review", "failed", "cancelled", "interrupted"}
LOG = logging.getLogger("video2docs.worker")


def process_identity(pid):
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
        capture_output=True,
        text=True,
        timeout=2,
        env={**os.environ, "LC_ALL": "C"},
    )
    return result.stdout.strip() if result.returncode == 0 else ""


class Cancellation:
    def __init__(self, worker, job_id):
        self.worker, self.job_id = worker, job_id

    def __call__(self):
        self.worker.check(self.job_id)

    def register_process(self, pid):
        identity = process_identity(pid) if pid else None
        with self.worker.Session.begin() as s:
            s.execute(
                update(Job)
                .where(Job.id == self.job_id, Job.lease_owner == self.worker.owner)
                .values(
                    subprocess_pid=pid, subprocess_signature=sha256(identity.encode()) if identity else None
                )
            )


class Worker:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.engine, self.Session = create_db(self.settings)
        self.owner = uid()
        self.stop = threading.Event()
        self.last_resource_check = 0

    def recover(self):
        with self.Session.begin() as s:
            stale = s.scalars(
                select(Job).where(
                    Job.state.in_(["running", "cancel_requested"]), Job.lease_expires_at < time.time()
                )
            ).all()
            for job in stale:
                if job.subprocess_pid and job.subprocess_signature:
                    identity = process_identity(job.subprocess_pid)
                    if (
                        identity
                        and sha256(identity.encode()) == job.subprocess_signature
                        and f"projects/{job.project_id}/" in identity
                        and "ffmpeg" in identity
                    ):
                        try:
                            os.killpg(job.subprocess_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                job.subprocess_pid, job.subprocess_signature = None, None
                calls = s.scalars(
                    select(ProviderCall).where(ProviderCall.job_id == job.id, ProviderCall.status == "sent")
                ).all()
                for call in calls:
                    call.status, call.error_code = "unknown_outcome", "UNKNOWN_OUTCOME"
                job.state, job.phase, job.finished_at = "interrupted", "interrupted", now()
                job.error_code = "UNKNOWN_OUTCOME" if calls else "WORKER_RESTARTED"
                job.error_message = "Worker bị gián đoạn. Checkpoint được giữ; cần chủ động thử lại."
                job.lease_owner, job.lease_expires_at = None, None
            active = s.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.state.in_(["running", "cancel_requested"]), Job.lease_expires_at >= time.time())
            )
        if not active:
            for partial in self.settings.data_dir.rglob("*.partial"):
                if not partial.is_symlink() and time.time() - partial.stat().st_mtime > 86400:
                    partial.unlink(missing_ok=True)

    def claim(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            active = conn.execute(
                select(Job.id).where(
                    Job.state.in_(["running", "cancel_requested"]), Job.lease_expires_at >= time.time()
                )
            ).first()
            if active:
                conn.rollback()
                return None
            candidate = conn.execute(
                select(Job.id).where(Job.state == "queued").order_by(Job.created_at).limit(1)
            ).first()
            if not candidate:
                conn.rollback()
                return None
            conn.execute(
                update(Job)
                .where(Job.id == candidate.id, Job.state == "queued")
                .values(
                    state="running",
                    started_at=now(),
                    lease_owner=self.owner,
                    lease_expires_at=time.time() + 60,
                    heartbeat_at=now(),
                    attempt=Job.attempt + 1,
                )
            )
            conn.commit()
            return candidate.id

    def heartbeat(self, job_id, done):
        while not done.wait(10):
            try:
                with self.Session.begin() as s:
                    s.execute(
                        update(Job)
                        .where(Job.id == job_id, Job.lease_owner == self.owner)
                        .values(heartbeat_at=now(), lease_expires_at=time.time() + 60)
                    )
            except Exception:
                LOG.warning("Heartbeat delayed for job %s", job_id)

    def check(self, job_id):
        with self.Session() as s:
            job = s.get(Job, job_id)
            if job.lease_owner != self.owner or (job.lease_expires_at or 0) < time.time():
                raise AppError("LEASE_LOST", "Worker đã mất lease.", 409)
            project = s.get(Project, job.project_id) if job.project_id else None
            if job.cancel_requested_at or (project and project.deleted_at and job.kind != "delete_project"):
                raise AppError("CANCELLED", "Đã hủy xử lý. Request Google đã gửi vẫn có thể tính phí.")
            from datetime import datetime, timezone

            if (
                datetime.now(timezone.utc) - datetime.fromisoformat(job.started_at)
            ).total_seconds() > self.settings.job_timeout_seconds:
                raise AppError("JOB_TIMEOUT", "Job vượt giới hạn thời gian.", 503)
            if job.kind != "delete_project" and time.monotonic() - self.last_resource_check > 1:
                self.last_resource_check = time.monotonic()
                if shutil.disk_usage(self.settings.data_dir).free < 100 * 1024 * 1024:
                    raise AppError("DISK_FULL", "Ổ đĩa còn dưới 100 MiB. Dừng xử lý để giữ dữ liệu.", 503)
                if job.project_id:
                    root = safe_path(self.settings.data_dir, f"projects/{job.project_id}")
                    used = sum(
                        p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()
                    )
                    if used > self.settings.max_project_storage_mb * 1024 * 1024:
                        raise AppError("STORAGE_LIMIT", "Dự án vượt giới hạn lưu trữ.", 413)

    def phase(self, job_id, phase, completed=None, total=None):
        self.check(job_id)
        with self.Session.begin() as s:
            values = {"phase": phase}
            if completed is not None:
                values["completed_units"] = completed
            if total is not None:
                values["total_units"] = total
            s.execute(update(Job).where(Job.id == job_id, Job.lease_owner == self.owner).values(**values))

    def validate(self, job):
        self.phase(job.id, "validating")
        with self.Session() as s:
            asset = s.get(Asset, job.asset_id)
        try:
            path = safe_path(self.settings.data_dir, asset.relative_path)
            details = probe(path, self.settings)
            playback_rel = f"projects/{job.project_id}/derived/{asset.id}.mp4"
            playback = safe_path(self.settings.data_dir, playback_rel)
            self.phase(job.id, "preparing")
            encode(path, playback, 0, details["duration_sec"], Cancellation(self, job.id))
            if abs(probe(playback, self.settings)["duration_sec"] - details["duration_sec"]) > 0.5:
                raise AppError(
                    "MEDIA_OUTPUT_LIMIT",
                    "Bản playback bị thiếu thời lượng. Tách video hoặc giảm độ phân giải.",
                    422,
                )
            thumb_rel = f"projects/{job.project_id}/derived/{asset.id}.png"
            extract_frame(
                playback, safe_path(self.settings.data_dir, thumb_rel), 0, Cancellation(self, job.id)
            )
            if file_hash(path) != asset.sha256:
                raise AppError("SOURCE_CHANGED", "Hash nguồn bị thay đổi; đã dừng.", 422)
            with self.Session.begin() as s:
                s.execute(
                    update(Asset)
                    .where(Asset.id == asset.id)
                    .values(
                        **details,
                        playback_path=playback_rel,
                        thumbnail_path=thumb_rel,
                        validation_status="validated",
                    )
                )
        except BaseException:
            with self.Session.begin() as s:
                s.execute(update(Asset).where(Asset.id == asset.id).values(validation_status="failed"))
            raise
        return "succeeded"

    def cleanup(self, job_id=None, provider=None):
        with self.Session() as s:
            query = select(RemoteFile).where(
                RemoteFile.cleanup_state != "deleted",
                RemoteFile.attempts < 5,
                RemoteFile.next_cleanup_at <= time.time(),
            )
            if job_id:
                query = query.where(RemoteFile.job_id == job_id)
            else:
                query = query.join(Job).where(Job.state.in_(TERMINAL))
            records = s.scalars(query).all()
        if not records:
            return
        owned = provider is None
        if owned:
            try:
                provider = get_provider(self.settings)
            except AppError:
                return
        try:
            for record in records:
                try:
                    provider.delete(record.provider_file_name)
                    state, error = "deleted", None
                except Exception:
                    state, error = "pending", "REMOTE_CLEANUP_FAILED"
                with self.Session.begin() as s:
                    s.execute(
                        update(RemoteFile)
                        .where(RemoteFile.id == record.id)
                        .values(
                            cleanup_state=state,
                            last_error=error,
                            attempts=record.attempts + 1,
                            next_cleanup_at=time.time() + min(3600, 30 * 2**record.attempts),
                        )
                    )
        finally:
            if owned:
                provider.close()

    def analyze(self, job):
        cfg = Settings(**{**self.settings.model_dump(), **json.loads(job.settings_snapshot_json)["config"]})
        snapshot = json.loads(job.settings_snapshot_json)
        provider = get_provider(cfg)
        with self.Session() as s:
            asset = s.get(Asset, job.asset_id)
        source = safe_path(cfg.data_dir, asset.playback_path)
        plan = plan_chunks(asset.duration_sec, cfg.chunk_seconds, cfg.chunk_overlap_seconds)
        with self.Session.begin() as s:
            existing = s.scalars(select(Chunk).where(Chunk.job_id == job.id)).all()
            if not existing:
                for index, (start, end) in enumerate(plan):
                    s.add(Chunk(job_id=job.id, index=index, start_sec=start, end_sec=end))
        with self.Session() as s:
            chunks = s.scalars(select(Chunk).where(Chunk.job_id == job.id).order_by(Chunk.index)).all()
        self.phase(job.id, "preparing", sum(c.state == "validated" for c in chunks), len(chunks))
        parts, repairs = [], 0
        try:
            for index, chunk in enumerate(chunks):
                self.check(job.id)
                if chunk.state == "validated" and chunk.result_path:
                    path = safe_path(cfg.data_dir, chunk.result_path)
                    if file_hash(path) != chunk.result_sha256:
                        raise AppError("CHECKPOINT_CHANGED", "Checkpoint không khớp hash.", 422)
                    draft = load_draft(path.read_bytes(), chunk.duration_sec)
                    parts.append((chunk.start_sec, draft))
                    continue
                clip_rel = f"projects/{job.project_id}/derived/{job.id}/{chunk.id}.mp4"
                clip = safe_path(cfg.data_dir, clip_rel)
                self.phase(job.id, "preparing")
                encode(source, clip, chunk.start_sec, chunk.end_sec, Cancellation(self, job.id))
                measured = probe(clip, cfg)["duration_sec"]
                if abs(measured - (chunk.end_sec - chunk.start_sec)) > 0.5:
                    raise AppError("MEDIA_OUTPUT_LIMIT", "Chunk bị cắt thiếu do giới hạn output media.", 422)
                chunk.duration_sec = min(measured, chunk.end_sec - chunk.start_sec)
                with self.Session.begin() as s:
                    s.execute(
                        update(Chunk)
                        .where(Chunk.id == chunk.id)
                        .values(
                            media_sha256=file_hash(clip), duration_sec=chunk.duration_sec, state="prepared"
                        )
                    )
                self.phase(job.id, "uploading")

                def record_remote(name, expires):
                    with self.Session.begin() as s:
                        s.add(RemoteFile(job_id=job.id, provider_file_name=name, expires_at=expires))

                reference = provider.upload(clip, record_remote, lambda: self.check(job.id))
                repair = None
                while True:
                    self.phase(job.id, "analyzing")
                    with self.Session() as s:
                        attempts = s.scalar(
                            select(func.count())
                            .select_from(ProviderCall)
                            .where(ProviderCall.job_id == job.id)
                        )
                        known_cost = (
                            s.scalar(
                                select(func.sum(ProviderCall.estimated_cost_usd)).where(
                                    ProviderCall.job_id == job.id
                                )
                            )
                            or 0
                        )
                    check_budget(
                        attempts,
                        len(chunks) - index,
                        cfg.max_generation_attempts,
                        known_cost,
                        None,
                        snapshot["budget_usd"],
                        snapshot["allow_unknown_cost"],
                    )
                    call_id = uid()
                    with self.Session.begin() as s:
                        s.add(
                            ProviderCall(
                                id=call_id,
                                job_id=job.id,
                                chunk_id=chunk.id,
                                purpose="repair" if repair else "analyze",
                                attempt=attempts + 1,
                                status="sent",
                                requested_model=cfg.gemini_model,
                            )
                        )
                        s.execute(
                            update(Chunk)
                            .where(Chunk.id == chunk.id)
                            .values(attempt_count=Chunk.attempt_count + 1)
                        )
                    try:
                        result = provider.analyze(
                            reference,
                            chunk.duration_sec,
                            snapshot["output_language"],
                            clip_metadata(asset.original_name, index, chunks, asset.duration_sec, parts),
                            repair,
                        )
                    except AppError as exc:
                        with self.Session.begin() as s:
                            s.execute(
                                update(ProviderCall)
                                .where(ProviderCall.id == call_id)
                                .values(
                                    status="unknown_outcome" if exc.code == "UNKNOWN_OUTCOME" else "failed",
                                    error_code=exc.code,
                                    finished_at=now(),
                                )
                            )
                        raise
                    with self.Session.begin() as s:
                        price = s.scalar(
                            select(PriceSnapshot)
                            .where(
                                PriceSnapshot.model == cfg.gemini_model,
                                PriceSnapshot.tier == "standard",
                                PriceSnapshot.effective_from <= now()[:10],
                                PriceSnapshot.effective_to >= now()[:10],
                            )
                            .limit(1)
                        )
                        s.execute(
                            update(ProviderCall)
                            .where(ProviderCall.id == call_id)
                            .values(
                                status="received",
                                returned_model=result["model"],
                                provider_request_id=result["request_id"],
                                usage_json=json.dumps(result["usage"])
                                if result["usage"] is not None
                                else None,
                                estimated_cost_usd=cost(result["usage"], price, now()[:10]),
                                price_snapshot_id=price.id if price else None,
                                finished_at=now(),
                                error_code=result["error"],
                            )
                        )
                    self.check(job.id)
                    if result["error"]:
                        raise AppError(
                            result["error"],
                            "Provider không trả bản đầy đủ. Hãy kiểm tra quota hoặc chia clip nhỏ hơn.",
                            422,
                        )
                    try:
                        draft = TutorialDraftV2.model_validate_json(
                            provider.decode(result["text"]), context={"duration": chunk.duration_sec}
                        )
                        if draft.language != snapshot["output_language"]:
                            raise ValueError("Output language mismatch")
                        break
                    except (ValidationError, ValueError) as exc:
                        errors = (
                            [
                                {
                                    "loc": [
                                        str(provider.field_names.get(part, part))[:80] for part in e["loc"]
                                    ],
                                    "type": e["type"],
                                    "message": e["msg"][:300],
                                }
                                for e in exc.errors(
                                    include_input=False, include_context=False, include_url=False
                                )[:50]
                            ]
                            if isinstance(exc, ValidationError)
                            else [
                                {
                                    "loc": [str(part)[:80] for part in exc.loc],
                                    "type": exc.kind,
                                    "message": exc.message[:300],
                                }
                            ]
                            if isinstance(exc, TimecodeError)
                            else [
                                {
                                    "loc": ["language"],
                                    "type": "value_error",
                                    "message": "Output language must match output_language.",
                                }
                            ]
                        )
                        with self.Session.begin() as s:
                            s.execute(
                                update(ProviderCall)
                                .where(ProviderCall.id == call_id)
                                .values(status="invalid", error_code="SCHEMA_INVALID")
                            )
                            current_job = s.get(Job, job.id)
                            current_job.warnings_json = json.dumps(
                                json.loads(current_job.warnings_json)
                                + [{"code": "SCHEMA_INVALID", "attempt": attempts + 1, "fields": errors}]
                            )
                        if repairs >= cfg.max_json_repair_requests:
                            raise AppError(
                                "SCHEMA_INVALID",
                                "JSON sai schema sau giới hạn repair; checkpoint còn được giữ.",
                                422,
                            )
                        repairs += 1
                        repair = repair_payload(chunk.duration_sec, errors, result["text"])
                rel = f"projects/{job.project_id}/derived/results/{chunk.id}.json"
                content = draft.model_dump_json(by_alias=True).encode()
                atomic_write(safe_path(cfg.data_dir, rel), content)
                with self.Session.begin() as s:
                    s.execute(
                        update(Chunk)
                        .where(Chunk.id == chunk.id)
                        .values(result_path=rel, result_sha256=sha256(content), state="validated")
                    )
                parts.append((chunk.start_sec, draft))
                self.cleanup(job.id, provider)
                clip.unlink(missing_ok=True)
                self.phase(job.id, "analyzing", index + 1, len(chunks))
            self.phase(job.id, "assembling")
            draft = assemble(parts, asset.duration_sec, cfg.max_steps)
            generation_id = uid()
            json_rel = f"projects/{job.project_id}/generations/{generation_id}/draft.json"
            atomic_write(safe_path(cfg.data_dir, json_rel), draft.model_dump_json(by_alias=True).encode())
            with self.Session.begin() as s:
                generation = Generation(
                    id=generation_id,
                    project_id=job.project_id,
                    job_id=job.id,
                    validated_json_path=json_rel,
                    quality_status="processing",
                    created_at=now(),
                )
                s.add(generation)
            self.phase(job.id, "extracting_evidence")
            evidence, warnings = {}, []
            for step in draft.steps:
                self.check(job.id)
                visual = next((sp for sp in step.evidence_spans if sp.source in ("visual", "both")), None)
                if visual is None:
                    continue
                if len(evidence) >= cfg.max_screenshots:
                    step.needs_review, step.review_reason = True, "Chưa có ảnh do giới hạn số ảnh."
                    continue
                timestamp, conflicted = evidence_timestamp(step, asset.duration_sec)
                if timestamp is None:
                    step.needs_review, step.review_reason = (
                        True,
                        "Không có mốc ảnh nằm trong bằng chứng của bước.",
                    )
                    warnings.append({"code": "EVIDENCE_TIMESTAMP_CONFLICT", "step_id": step.local_id})
                    continue
                if conflicted:
                    step.needs_review, step.review_reason = (
                        True,
                        "Mốc ảnh đề xuất nằm ngoài bằng chứng; đã dùng frame cuối của khoảng bằng chứng.",
                    )
                    warnings.append(
                        {
                            "code": "EVIDENCE_TIMESTAMP_CONFLICT",
                            "step_id": step.local_id,
                            "fallback_sec": timestamp,
                        }
                    )
                try:
                    item = self.make_evidence(job, asset, generation_id, step.local_id, timestamp)
                    evidence[step.local_id] = item
                except AppError as exc:
                    if exc.code in ("CANCELLED", "LEASE_LOST", "JOB_TIMEOUT"):
                        raise
                    step.needs_review, step.review_reason = True, "Trích ảnh thất bại; hãy chọn mốc khác."
                    warnings.append(exc.code)
            quality = (
                "needs_review"
                if draft.uncertainties or has_review_claims(draft) or any(s.needs_review for s in draft.steps)
                else "succeeded"
            )
            atomic_write(safe_path(cfg.data_dir, json_rel), draft.model_dump_json(by_alias=True).encode())
            markdown = render_markdown(
                draft,
                asset,
                "mock-fixture" if cfg.ai_provider == "mock" else cfg.gemini_model,
                generation,
                evidence,
            )
            atomic_write(
                safe_path(cfg.data_dir, f"projects/{job.project_id}/generations/{generation_id}/document.md"),
                markdown.encode(),
            )
            self.phase(job.id, "saving")
            with self.Session.begin() as s:
                s.execute(
                    update(Generation).where(Generation.id == generation_id).values(quality_status=quality)
                )
                document = s.scalar(select(Document).where(Document.project_id == job.project_id))
                if document is None:
                    document = Document(id=uid(), project_id=job.project_id)
                    s.add(document)
                    s.flush()
                    create_revision(s, document, None, markdown, "ai", generation_id)
                current_job = s.get(Job, job.id)
                current_job.warnings_json = json.dumps(json.loads(current_job.warnings_json) + warnings)
            return quality
        finally:
            try:
                self.cleanup(job.id, provider)
            finally:
                provider.close()

    def make_evidence(self, job, asset, generation_id, step_id, timestamp):
        rel = f"projects/{job.project_id}/evidence/{uid()}.png"
        path = safe_path(self.settings.data_dir, rel)
        actual, width, height = extract_frame(
            safe_path(self.settings.data_dir, asset.playback_path),
            path,
            timestamp,
            Cancellation(self, job.id),
        )
        with self.Session.begin() as s:
            item = Evidence(
                id=uid(),
                project_id=job.project_id,
                generation_id=generation_id,
                step_id=step_id,
                asset_id=asset.id,
                requested_sec=timestamp,
                actual_sec=actual,
                relative_path=rel,
                sha256=file_hash(path),
                width=width,
                height=height,
            )
            s.add(item)
        return item

    def extract(self, job):
        settings = json.loads(job.settings_snapshot_json)
        with self.Session() as s:
            asset, generation = s.get(Asset, job.asset_id), s.get(Generation, settings["generation_id"])
        self.phase(job.id, "extracting_evidence")
        item = self.make_evidence(job, asset, generation.id, settings["step_id"], settings["timestamp"])
        self.check(job.id)
        with self.Session.begin() as s:
            document = s.scalar(select(Document).where(Document.project_id == job.project_id))
            base = settings["base_revision"]
            revision = s.get(Revision, base)
            if not revision or revision.document_id != document.id:
                raise AppError("REVISION_CONFLICT", "Revision không tồn tại.", 409)
            old_images = s.scalars(
                select(Evidence).where(
                    Evidence.generation_id == generation.id, Evidence.step_id == settings["step_id"]
                )
            ).all()
            markdown = revision.markdown
            for old in old_images:
                if old.id != item.id:
                    markdown = markdown.replace(f"assets/{old.id}.png", f"assets/{item.id}.png")
            if f"assets/{item.id}.png" not in markdown:
                markdown += f"\n\n![Frame {item.actual_sec:.3f}](assets/{item.id}.png)\n"
            markdown += f"\n\n*Ảnh chọn lại: {settings['step_id']}, {item.actual_sec:.3f} giây; chưa kiểm tra bằng mắt.*\n"
            create_revision(s, document, base, markdown, "user")
        return "needs_review"

    def export(self, job):
        self.phase(job.id, "exporting")
        with self.Session() as s:
            export = s.scalar(select(Export).where(Export.job_id == job.id))
            revision = s.get(Revision, export.document_revision_id)
            result = build_export(s, self.settings, revision, job.project_id, export.format)
        self.check(job.id)
        rel = f"projects/{job.project_id}/exports/{export.id}.{export.format}"
        atomic_write(safe_path(self.settings.data_dir, rel), result)
        with self.Session.begin() as s:
            s.execute(
                update(Export)
                .where(Export.id == export.id)
                .values(state="succeeded", relative_path=rel, sha256=sha256(result))
            )
        return "succeeded"

    def delete(self, job):
        self.phase(job.id, "deleting")
        self.cleanup()
        directory = safe_path(self.settings.data_dir, f"projects/{job.project_id}")
        if directory.exists():
            shutil.rmtree(directory)
        with self.Session.begin() as s:
            doc_ids = select(Document.id).where(Document.project_id == job.project_id)
            s.execute(
                update(Revision)
                .where(Revision.document_id.in_(doc_ids))
                .values(markdown="[Đã xóa]", content_sha256=sha256(b""))
            )
            s.execute(
                update(Asset).where(Asset.project_id == job.project_id).values(original_name="[Đã xóa]")
            )
            s.execute(update(Project).where(Project.id == job.project_id).values(name="[Đã xóa]"))
        return "succeeded"

    def execute(self, job_id):
        done = threading.Event()
        heartbeat = threading.Thread(target=self.heartbeat, args=(job_id, done), daemon=True)
        heartbeat.start()
        state, error = "succeeded", None
        try:
            with self.Session() as s:
                job = s.get(Job, job_id)
            self.check(job_id)
            if job.kind == "provider_check":
                provider = get_provider(self.settings)
                try:
                    result = provider.check()
                    with self.Session.begin() as s:
                        s.execute(
                            update(Job).where(Job.id == job.id).values(warnings_json=json.dumps([result]))
                        )
                finally:
                    provider.close()
            else:
                state = {
                    "validate_asset": self.validate,
                    "analyze": self.analyze,
                    "extract_evidence": self.extract,
                    "export": self.export,
                    "delete_project": self.delete,
                }[job.kind](job)
        except AppError as exc:
            error = exc
            state = (
                "cancelled"
                if exc.code == "CANCELLED"
                else ("interrupted" if exc.code in ("UNKNOWN_OUTCOME", "LEASE_LOST") else "failed")
            )
        except Exception:
            error = AppError(
                "INTERNAL_ERROR", "Job thất bại. Kiểm tra cài đặt và thử lại từ checkpoint.", 500
            )
            LOG.error("Unhandled worker failure for job %s", job_id, exc_info=False)
            state = "failed"
        finally:
            done.set()
            heartbeat.join(timeout=2)
            with self.Session.begin() as s:
                s.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.lease_owner == self.owner)
                    .values(
                        state=state,
                        phase=state,
                        finished_at=now(),
                        lease_owner=None,
                        lease_expires_at=None,
                        error_code=error.code if error else None,
                        error_message=error.message if error else None,
                    )
                )
                if error and error.details:
                    record = s.get(Job, job_id)
                    record.warnings_json = json.dumps(
                        json.loads(record.warnings_json)
                        + [{"code": error.code, "diagnostics": error.details}]
                    )
                if state in ("failed", "cancelled", "interrupted"):
                    s.execute(update(Export).where(Export.job_id == job_id).values(state="failed"))
            derived = (
                safe_path(self.settings.data_dir, f"projects/{job.project_id}/derived/{job.id}")
                if job.project_id
                else None
            )
            if derived and derived.exists():
                shutil.rmtree(derived)

    def once(self):
        self.recover()
        self.cleanup()
        job_id = self.claim()
        if job_id:
            self.execute(job_id)
        return job_id

    def run(self):
        while not self.stop.is_set():
            if not self.once():
                self.stop.wait(1)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = Worker()
    migrate(worker.settings)
    worker.once() if args.once else worker.run()


if __name__ == "__main__":
    main()
