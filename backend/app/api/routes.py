import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Literal, Annotated
from fastapi import APIRouter, Request, UploadFile, File, Header
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, BaseModel, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.errors import AppError
from app.core.storage import uid, sha256, safe_path
from app.db.models import (
    Project,
    Asset,
    Job,
    Consent,
    Document,
    Revision,
    Generation,
    Evidence,
    Export,
    RemoteFile,
    Chunk,
    ProviderCall,
    now,
)
from app.providers.gemini import PROMPT
from app.providers.structured_schema import analysis_contract_hash
from app.workers.runner import TERMINAL

router = APIRouter(prefix="/api/v1")
NOTICE_VERSION = "2026-10-20.v1"


def public(row, exclude=()):
    if row is None:
        return None
    return {
        c.name: getattr(row, c.name)
        for c in row.__table__.columns
        if c.name
        not in set(exclude)
        | {
            "relative_path",
            "playback_path",
            "thumbnail_path",
            "validated_json_path",
            "timeline_map_json",
            "settings_snapshot_json",
            "lease_owner",
            "lease_expires_at",
            "subprocess_pid",
            "subprocess_signature",
            "result_path",
        }
    }


def project_or_404(s, project_id):
    project = s.get(Project, project_id)
    if not project or project.deleted_at:
        raise AppError("NOT_FOUND", "Không tìm thấy dự án.", 404)
    return project


def resource(s, cls, resource_id):
    row = s.get(cls, resource_id)
    if row is None:
        raise AppError("NOT_FOUND", "Không tìm thấy tài nguyên.", 404)
    if hasattr(row, "project_id"):
        project_or_404(s, row.project_id)
    return row


def dump_job(s, job):
    result = public(job)
    result["warnings"] = json.loads(job.warnings_json)
    result["cleanup_pending"] = s.scalar(
        select(func.count())
        .select_from(RemoteFile)
        .where(RemoteFile.job_id == job.id, RemoteFile.cleanup_state != "deleted")
    )
    result["provider_calls"] = [
        public(c) for c in s.scalars(select(ProviderCall).where(ProviderCall.job_id == job.id))
    ]
    result["is_mock"] = json.loads(job.settings_snapshot_json).get("config", {}).get("ai_provider") == "mock"
    result["export"] = public(s.scalar(select(Export).where(Export.job_id == job.id)))
    return result


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=200)
    output_language: Literal["vi", "en"] = "vi"


class ConsentInput(Input):
    asset_sha256: str = Field(min_length=64, max_length=64)
    notice_version: str


class AnalyzeInput(Input):
    asset_id: str
    mode: Literal["static"] = "static"
    output_language: Literal["vi", "en"] = "vi"
    consent_id: str
    allow_unknown_cost: bool = False
    budget_usd: float = Field(default=1, gt=0, le=100)


class EstimateInput(Input):
    asset_id: str


class SaveInput(Input):
    base_revision: str
    markdown: str = Field(max_length=2_000_000)


class RestoreInput(Input):
    base_revision: str
    revision: str


class ApplyInput(Input):
    base_revision: str
    generation_id: str


class ExportInput(Input):
    revision: str
    format: Literal["md", "zip", "pdf"]


class EvidenceInput(Input):
    asset_id: str
    generation_id: str
    step_id: str
    timestamp: float = Field(ge=0)
    base_revision: str


class RetryInput(Input):
    reason: str = Field(min_length=1, max_length=1000)
    acknowledge_possible_duplicate_cost: bool = False


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/capabilities")
def capabilities(request: Request):
    cfg = request.app.state.settings
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        chromium = Path(p.chromium.executable_path).is_file()
    font = Path(__file__).resolve().parents[1] / "static/fonts/DejaVuSans.ttf"
    return {
        "model": cfg.gemini_model,
        "provider": cfg.ai_provider,
        "provider_ready": bool(cfg.gemini_api_key) or cfg.ai_provider == "mock",
        "processing_mode": "static",
        "ffmpeg_ready": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "pdf_ready": chromium and font.is_file(),
        "max_upload_mb": cfg.max_upload_mb,
        "max_video_seconds": cfg.max_video_seconds,
        "notice_version": NOTICE_VERSION,
        "price_status": "unknown",
        "quota_status": "unknown",
        "terms_checked_at": "2026-10-20",
        "notice": "Video và nội dung cần phân tích sẽ được gửi tới Google khi bạn bấm Tạo tài liệu. "
        "Unpaid services có thể dùng dữ liệu để cải thiện sản phẩm và có người đánh giá; "
        "không gửi dữ liệu nhạy cảm. store=false không thay thế điều khoản xử lý dữ liệu.",
        "terms_url": "https://ai.google.dev/gemini-api/terms",
    }


@router.post("/provider/check", status_code=202)
def provider_check(request: Request):
    with request.app.state.Session.begin() as s:
        job = Job(id=uid(), kind="provider_check")
        s.add(job)
    return public(job)


@router.post("/projects", status_code=201)
def create_project(body: ProjectInput, request: Request):
    with request.app.state.Session.begin() as s:
        row = Project(id=uid(), **body.model_dump())
        s.add(row)
    return public(row)


@router.get("/projects")
def projects(request: Request, cursor: int = 0, limit: int = 50):
    if not 0 <= cursor or not 1 <= limit <= 100:
        raise AppError("PAGINATION_INVALID", "Phân trang không hợp lệ.", 422)
    with request.app.state.Session() as s:
        rows = s.scalars(
            select(Project)
            .where(Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc())
            .offset(cursor)
            .limit(limit + 1)
        ).all()
        return {
            "items": [public(p) for p in rows[:limit]],
            "next_cursor": cursor + limit if len(rows) > limit else None,
        }


@router.get("/projects/{project_id}")
def project_detail(project_id: str, request: Request):
    with request.app.state.Session() as s:
        row = project_or_404(s, project_id)
        result = public(row)
        result["assets"] = [public(a) for a in s.scalars(select(Asset).where(Asset.project_id == project_id))]
        result["document"] = public(s.scalar(select(Document).where(Document.project_id == project_id)))
        jobs = s.scalars(
            select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(30)
        ).all()
        result["jobs"] = [dump_job(s, j) for j in jobs]
        result["cleanup_pending"] = s.scalar(
            select(func.count())
            .select_from(RemoteFile)
            .join(Job)
            .where(Job.project_id == project_id, RemoteFile.cleanup_state != "deleted")
        )
        return result


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectInput, request: Request):
    with request.app.state.Session.begin() as s:
        row = project_or_404(s, project_id)
        row.name, row.output_language, row.updated_at = body.name, body.output_language, now()
    return public(row)


@router.post("/projects/{project_id}/assets", status_code=201)
async def upload_asset(project_id: str, request: Request, file: UploadFile = File(...)):
    cfg = request.app.state.settings
    asset_id = uid()
    relative = f"projects/{project_id}/source/{asset_id}.bin"
    path = safe_path(cfg.data_dir, relative)
    partial = path.with_suffix(".partial")
    with request.app.state.Session() as s:
        project_or_404(s, project_id)
        if s.scalar(select(func.count()).select_from(Asset).where(Asset.project_id == project_id)):
            raise AppError("ASSET_EXISTS", "Mỗi dự án MVP có một video; hãy tạo dự án mới.", 409)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest, count = hashlib.sha256(), 0
    try:
        with partial.open("xb") as stream:
            os.chmod(partial, 0o600)
            while block := await file.read(1024 * 1024):
                count += len(block)
                if count > cfg.max_upload_mb * 1024 * 1024:
                    raise AppError("UPLOAD_TOO_LARGE", "Video vượt giới hạn dung lượng.", 413)
                if count > cfg.max_project_storage_mb * 1024 * 1024:
                    raise AppError("STORAGE_LIMIT", "Dự án vượt giới hạn lưu trữ.", 413)
                if shutil.disk_usage(cfg.data_dir).free < len(block) + 100 * 1024 * 1024:
                    raise AppError("DISK_FULL", "Không đủ dung lượng ổ đĩa để tiếp tục upload.", 503)
                digest.update(block)
                stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        if not count:
            raise AppError("EMPTY_UPLOAD", "File rỗng.", 422)
        os.replace(partial, path)
        name = (file.filename or "video").replace("\\", "/").split("/")[-1]
        name = "".join(c for c in name if ord(c) >= 32)[:200] or "video"
        with request.app.state.Session.begin() as s:
            project_or_404(s, project_id)
            row = Asset(
                id=asset_id,
                project_id=project_id,
                original_name=name,
                relative_path=relative,
                sha256=digest.hexdigest(),
                bytes=count,
            )
            s.add(row)
            s.flush()
            job = Job(id=uid(), project_id=project_id, asset_id=row.id, kind="validate_asset")
            s.add(job)
        return {**public(row), "job_id": job.id}
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        partial.unlink(missing_ok=True)
        await file.close()


@router.get("/assets/{asset_id}")
def asset_detail(asset_id: str, request: Request):
    with request.app.state.Session() as s:
        return public(resource(s, Asset, asset_id))


@router.get("/assets/{asset_id}/media")
def media(asset_id: str, request: Request):
    with request.app.state.Session() as s:
        asset = resource(s, Asset, asset_id)
        if asset.validation_status != "validated":
            raise AppError("ASSET_NOT_VALIDATED", "Video chưa qua kiểm tra.", 409)
        return FileResponse(
            safe_path(request.app.state.settings.data_dir, asset.playback_path), media_type="video/mp4"
        )


@router.get("/assets/{asset_id}/thumbnail")
def thumbnail(asset_id: str, request: Request):
    with request.app.state.Session() as s:
        asset = resource(s, Asset, asset_id)
        if not asset.thumbnail_path:
            raise AppError("THUMBNAIL_PENDING", "Thumbnail chưa sẵn sàng.", 404)
        return FileResponse(
            safe_path(request.app.state.settings.data_dir, asset.thumbnail_path), media_type="image/png"
        )


@router.post("/projects/{project_id}/consents", status_code=201)
def consent(project_id: str, body: ConsentInput, request: Request):
    with request.app.state.Session.begin() as s:
        project_or_404(s, project_id)
        asset = s.scalar(
            select(Asset).where(Asset.project_id == project_id, Asset.sha256 == body.asset_sha256)
        )
        if not asset or body.notice_version != NOTICE_VERSION:
            raise AppError("CONSENT_MISMATCH", "Asset hash hoặc phiên bản thông báo không khớp.", 422)
        row = Consent(
            id=uid(),
            project_id=project_id,
            asset_sha256=body.asset_sha256,
            notice_version=body.notice_version,
            provider=request.app.state.settings.ai_provider,
        )
        s.add(row)
    return public(row)


@router.post("/projects/{project_id}/estimates")
def estimate(project_id: str, body: EstimateInput, request: Request):
    with request.app.state.Session() as s:
        project_or_404(s, project_id)
        asset = resource(s, Asset, body.asset_id)
        if asset.project_id != project_id:
            raise AppError("ASSET_MISMATCH", "Video không thuộc dự án.", 422)
    return {
        "estimated_cost_usd": None,
        "quota_status": "unknown",
        "price_status": "unknown",
        "message": "Chưa đủ dữ liệu để ước tính. Cần xác nhận chi phí chưa xác định trước mỗi job.",
    }


@router.post("/projects/{project_id}/jobs", status_code=202)
def enqueue(
    project_id: str,
    body: AnalyzeInput,
    request: Request,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200, alias="Idempotency-Key")],
):
    cfg = request.app.state.settings
    canonical = json.dumps(body.model_dump(), sort_keys=True)
    request_hash = sha256(canonical.encode())
    with request.app.state.Session.begin() as s:
        project_or_404(s, project_id)
        existing = s.scalar(
            select(Job).where(
                Job.project_id == project_id, Job.kind == "analyze", Job.idempotency_key == idempotency_key
            )
        )
        if existing:
            if existing.request_hash != request_hash:
                raise AppError("IDEMPOTENCY_CONFLICT", "Key này đã dùng cho nội dung khác.", 409)
            return JSONResponse(
                dump_job(s, existing), 202, headers={"Location": f"/api/v1/jobs/{existing.id}"}
            )
        asset = resource(s, Asset, body.asset_id)
        consent = s.get(Consent, body.consent_id)
        if asset.project_id != project_id or asset.validation_status != "validated":
            raise AppError("ASSET_NOT_VALIDATED", "Video chưa được kiểm tra hoặc sai dự án.", 409)
        if (
            not consent
            or consent.project_id != project_id
            or consent.asset_sha256 != asset.sha256
            or consent.notice_version != NOTICE_VERSION
            or consent.provider != cfg.ai_provider
        ):
            raise AppError("CONSENT_REQUIRED", "Cần xác nhận gửi video trước khi tạo tài liệu.", 422)
        if not body.allow_unknown_cost:
            raise AppError("COST_UNKNOWN", "Cần chấp nhận chi phí chưa xác định.", 422)
        if cfg.ai_provider == "gemini" and not cfg.gemini_api_key:
            raise AppError("API_KEY_MISSING", "Chưa cấu hình GEMINI_API_KEY ở backend.", 503)
        snapshot = {
            "config": cfg.snapshot(),
            "prompt_sha256": sha256(PROMPT.read_bytes()),
            "schema_version": "2.0",
            "analysis_contract_sha256": analysis_contract_hash(),
            "asset_sha256": asset.sha256,
            **body.model_dump(),
        }
        job = Job(
            id=uid(),
            project_id=project_id,
            asset_id=asset.id,
            kind="analyze",
            settings_snapshot_json=json.dumps(snapshot),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        s.add(job)
        try:
            s.flush()
        except IntegrityError:
            raise AppError("JOB_IN_PROGRESS", "Dự án đang có một job tạo tài liệu.", 409)
        response = dump_job(s, job)
    return JSONResponse(response, 202, headers={"Location": f"/api/v1/jobs/{job.id}"})


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, request: Request):
    with request.app.state.Session() as s:
        job = s.get(Job, job_id)
        if not job:
            raise AppError("NOT_FOUND", "Không tìm thấy job.", 404)
        return dump_job(s, job)


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel(job_id: str, request: Request):
    with request.app.state.Session.begin() as s:
        job = s.get(Job, job_id)
        if not job:
            raise AppError("NOT_FOUND", "Không tìm thấy job.", 404)
        if job.kind == "delete_project":
            raise AppError("DELETE_IN_PROGRESS", "Không thể hủy xóa dự án.", 409)
        if job.state not in TERMINAL:
            job.cancel_requested_at = now()
            job.state = "cancelled" if job.state in ("queued", "retry_wait") else "cancel_requested"
            if job.state == "cancelled":
                job.finished_at = now()
        return dump_job(s, job)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: str, body: RetryInput, request: Request):
    cfg = request.app.state.settings
    with request.app.state.Session.begin() as s:
        old = resource(s, Job, job_id)
        if old.state not in ("failed", "interrupted", "cancelled") or old.kind not in (
            "analyze",
            "validate_asset",
        ):
            raise AppError("RETRY_NOT_ALLOWED", "Job này không thể thử lại bằng thao tác này.", 409)
        ambiguous = old.error_code in ("UNKNOWN_OUTCOME", "UPLOAD_OUTCOME_UNKNOWN")
        if ambiguous and not body.acknowledge_possible_duplicate_cost:
            raise AppError(
                "DUPLICATE_COST_CONFIRMATION",
                "Request trước chưa rõ kết quả; cần xác nhận khả năng tính phí lại.",
                422,
            )
        active = s.scalar(
            select(Job.id).where(
                Job.project_id == old.project_id, Job.state.in_(["queued", "running", "cancel_requested"])
            )
        )
        if active:
            raise AppError("JOB_IN_PROGRESS", "Đợi job hiện tại kết thúc trước khi thử lại.", 409)
        snapshot = json.loads(old.settings_snapshot_json)
        compatible = (
            old.kind == "analyze"
            and snapshot.get("config") == cfg.snapshot()
            and snapshot.get("prompt_sha256") == sha256(PROMPT.read_bytes())
            and snapshot.get("analysis_contract_sha256") == analysis_contract_hash()
        )
        if old.kind == "analyze" and not compatible:
            raise AppError(
                "SETTINGS_CHANGED", "Cấu hình đã đổi; hãy tạo job mới với consent và ngân sách mới.", 409
            )
        new = Job(
            id=uid(),
            project_id=old.project_id,
            asset_id=old.asset_id,
            kind=old.kind,
            settings_snapshot_json=old.settings_snapshot_json,
            retry_of=old.id,
        )
        s.add(new)
        s.flush()
        if compatible:
            for c in s.scalars(select(Chunk).where(Chunk.job_id == old.id).order_by(Chunk.index)):
                s.add(
                    Chunk(
                        job_id=new.id,
                        index=c.index,
                        start_sec=c.start_sec,
                        end_sec=c.end_sec,
                        duration_sec=c.duration_sec,
                        media_sha256=c.media_sha256,
                        state=c.state if c.state == "validated" else "queued",
                        result_path=c.result_path,
                        result_sha256=c.result_sha256,
                    )
                )
        return public(new)


@router.get("/projects/{project_id}/generations")
def generations(project_id: str, request: Request):
    with request.app.state.Session() as s:
        project_or_404(s, project_id)
        rows = s.scalars(
            select(Generation)
            .where(Generation.project_id == project_id)
            .order_by(Generation.created_at.desc())
        ).all()
        return {"items": [public(g) for g in rows]}


@router.get("/generations/{generation_id}")
def generation_detail(generation_id: str, request: Request):
    with request.app.state.Session() as s:
        generation = resource(s, Generation, generation_id)
        draft = json.loads(
            safe_path(request.app.state.settings.data_dir, generation.validated_json_path).read_bytes()
        )
        evidence = s.scalars(select(Evidence).where(Evidence.generation_id == generation.id)).all()
        return {**public(generation), "draft": draft, "evidence": [public(e) for e in evidence]}


@router.get("/projects/{project_id}/document")
def document(project_id: str, request: Request):
    with request.app.state.Session() as s:
        project_or_404(s, project_id)
        doc = s.scalar(select(Document).where(Document.project_id == project_id))
        return {**public(doc), "revision": public(s.get(Revision, doc.current_revision_id))} if doc else None


def checked_document(s, document_id):
    return resource(s, Document, document_id)


@router.put("/documents/{document_id}")
def save_document(document_id: str, body: SaveInput, request: Request):
    from app.services.documents import create_revision

    with request.app.state.Session.begin() as s:
        doc = checked_document(s, document_id)
        return public(create_revision(s, doc, body.base_revision, body.markdown, "user"))


@router.get("/documents/{document_id}/revisions")
def revisions(document_id: str, request: Request, cursor: int = 0):
    with request.app.state.Session() as s:
        checked_document(s, document_id)
        rows = s.scalars(
            select(Revision)
            .where(Revision.document_id == document_id)
            .order_by(Revision.revision_number.desc())
            .offset(max(0, cursor))
            .limit(51)
        ).all()
        return {
            "items": [public(r, ("markdown",)) for r in rows[:50]],
            "next_cursor": cursor + 50 if len(rows) > 50 else None,
        }


@router.post("/documents/{document_id}/restore")
def restore(document_id: str, body: RestoreInput, request: Request):
    from app.services.documents import create_revision

    with request.app.state.Session.begin() as s:
        doc = checked_document(s, document_id)
        revision = s.get(Revision, body.revision)
        if not revision or revision.document_id != document_id:
            raise AppError("NOT_FOUND", "Không tìm thấy revision.", 404)
        return public(
            create_revision(s, doc, body.base_revision, revision.markdown, "restore", revision.generation_id)
        )


@router.post("/documents/{document_id}/apply-generation")
def apply_generation(document_id: str, body: ApplyInput, request: Request):
    from app.services.documents import create_revision

    with request.app.state.Session.begin() as s:
        doc = checked_document(s, document_id)
        generation = resource(s, Generation, body.generation_id)
        if generation.project_id != doc.project_id:
            raise AppError("GENERATION_MISMATCH", "Generation không thuộc dự án.", 422)
        if generation.quality_status not in ("succeeded", "needs_review"):
            raise AppError("GENERATION_INCOMPLETE", "Generation chưa hoàn tất.", 409)
        path = safe_path(
            request.app.state.settings.data_dir,
            f"projects/{doc.project_id}/generations/{generation.id}/document.md",
        )
        if not path.is_file():
            raise AppError("GENERATION_INCOMPLETE", "Generation chưa hoàn tất.", 409)
        return public(create_revision(s, doc, body.base_revision, path.read_text(), "ai", generation.id))


@router.get("/evidence/{evidence_id}/image")
def image(evidence_id: str, request: Request):
    with request.app.state.Session() as s:
        item = resource(s, Evidence, evidence_id)
        return FileResponse(
            safe_path(request.app.state.settings.data_dir, item.relative_path), media_type="image/png"
        )


@router.post("/projects/{project_id}/evidence", status_code=202)
def new_evidence(project_id: str, body: EvidenceInput, request: Request):
    with request.app.state.Session.begin() as s:
        project_or_404(s, project_id)
        asset, generation = resource(s, Asset, body.asset_id), resource(s, Generation, body.generation_id)
        if (
            asset.project_id != project_id
            or generation.project_id != project_id
            or body.timestamp >= asset.duration_sec
        ):
            raise AppError("TIMESTAMP_INVALID", "Video, generation hoặc timestamp không hợp lệ.", 422)
        draft = json.loads(
            safe_path(request.app.state.settings.data_dir, generation.validated_json_path).read_bytes()
        )
        if body.step_id not in [x["local_id"] for x in draft["steps"]]:
            raise AppError("STEP_INVALID", "Không tìm thấy bước nguồn.", 422)
        doc = s.scalar(select(Document).where(Document.project_id == project_id))
        if not doc or body.base_revision != doc.current_revision_id:
            raise AppError("REVISION_CONFLICT", "Tài liệu đã thay đổi.", 409)
        job = Job(
            id=uid(),
            project_id=project_id,
            asset_id=asset.id,
            kind="extract_evidence",
            settings_snapshot_json=body.model_dump_json(),
        )
        s.add(job)
        s.flush()
        return public(job)


@router.post("/documents/{document_id}/exports", status_code=202)
def export_document(document_id: str, body: ExportInput, request: Request):
    with request.app.state.Session.begin() as s:
        doc = checked_document(s, document_id)
        revision = s.get(Revision, body.revision)
        if not revision or revision.document_id != doc.id:
            raise AppError("REVISION_MISMATCH", "Revision không thuộc tài liệu.", 422)
        job = Job(id=uid(), project_id=doc.project_id, kind="export")
        s.add(job)
        s.flush()
        export = Export(id=uid(), job_id=job.id, document_revision_id=revision.id, format=body.format)
        s.add(export)
        s.flush()
        return public(export)


@router.get("/exports/{export_id}")
def export_detail(export_id: str, request: Request):
    with request.app.state.Session() as s:
        row = s.get(Export, export_id)
        if not row:
            raise AppError("NOT_FOUND", "Không tìm thấy bản xuất.", 404)
        job = resource(s, Job, row.job_id)
        return {
            **public(row),
            "job": dump_job(s, job),
            "download_url": f"/api/v1/exports/{row.id}/download" if row.state == "succeeded" else None,
        }


@router.get("/exports/{export_id}/download")
def download(export_id: str, request: Request):
    with request.app.state.Session() as s:
        row = s.get(Export, export_id)
        if not row:
            raise AppError("NOT_FOUND", "Không tìm thấy bản xuất.", 404)
        resource(s, Job, row.job_id)
        if row.state != "succeeded":
            raise AppError("EXPORT_NOT_READY", "File chưa xuất xong.", 409)
        return FileResponse(
            safe_path(request.app.state.settings.data_dir, row.relative_path),
            filename=f"document.{row.format}",
            media_type={
                "md": "text/markdown; charset=utf-8",
                "zip": "application/zip",
                "pdf": "application/pdf",
            }[row.format],
        )


@router.delete("/projects/{project_id}", status_code=202)
def delete_project(project_id: str, request: Request):
    with request.app.state.Session.begin() as s:
        project = s.get(Project, project_id)
        if not project:
            raise AppError("NOT_FOUND", "Không tìm thấy dự án.", 404)
        if project.deleted_at:
            job = s.scalar(select(Job).where(Job.project_id == project_id, Job.kind == "delete_project"))
            return public(job)
        project.deleted_at = now()
        jobs = s.scalars(select(Job).where(Job.project_id == project_id, Job.state.not_in(TERMINAL))).all()
        for job in jobs:
            job.cancel_requested_at = now()
            job.state = "cancelled" if job.state == "queued" else "cancel_requested"
        deletion = Job(id=uid(), project_id=project_id, kind="delete_project")
        s.add(deletion)
        s.flush()
        return public(deletion)
