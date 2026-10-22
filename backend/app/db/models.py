from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, UniqueConstraint, Index, text
from sqlalchemy.orm import declarative_base
from app.core.storage import uid

Base = declarative_base()


def now():
    return datetime.now(timezone.utc).isoformat()


class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False)
    output_language = Column(String, nullable=False, default="vi")
    created_at = Column(String, default=now, nullable=False)
    updated_at = Column(String, default=now, nullable=False)
    deleted_at = Column(String)


class Asset(Base):
    __tablename__ = "assets"
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(ForeignKey("projects.id"), nullable=False, index=True)
    original_name = Column(String, nullable=False)
    relative_path = Column(String, nullable=False)
    sha256 = Column(String, nullable=False)
    bytes = Column(Integer, nullable=False)
    mime_type = Column(String)
    duration_sec = Column(Float)
    width = Column(Integer)
    height = Column(Integer)
    has_audio = Column(Integer)
    validation_status = Column(String, default="pending", nullable=False)
    timeline_map_json = Column(Text, default="{}", nullable=False)
    playback_path = Column(String)
    thumbnail_path = Column(String)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(ForeignKey("projects.id"), index=True)
    asset_id = Column(ForeignKey("assets.id"))
    kind = Column(String, nullable=False)
    state = Column(String, default="queued", nullable=False, index=True)
    phase = Column(String, default="queued", nullable=False)
    completed_units = Column(Integer, default=0, nullable=False)
    total_units = Column(Integer, default=0, nullable=False)
    settings_snapshot_json = Column(Text, nullable=False, default="{}")
    idempotency_key = Column(String)
    request_hash = Column(String)
    retry_of = Column(ForeignKey("jobs.id"))
    cancel_requested_at = Column(String)
    lease_owner = Column(String)
    lease_expires_at = Column(Float)
    heartbeat_at = Column(String)
    subprocess_pid = Column(Integer)
    subprocess_signature = Column(String)
    attempt = Column(Integer, default=0, nullable=False)
    error_code = Column(String)
    error_message = Column(String)
    warnings_json = Column(Text, default="[]", nullable=False)
    created_at = Column(String, default=now, nullable=False)
    started_at = Column(String)
    finished_at = Column(String)
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "idempotency_key"),
        Index(
            "one_active_analysis",
            "project_id",
            unique=True,
            sqlite_where=text(
                "kind='analyze' AND state IN ('queued','running','retry_wait','cancel_requested')"
            ),
        ),
    )


class Chunk(Base):
    __tablename__ = "job_chunks"
    id = Column(String, primary_key=True, default=uid)
    job_id = Column(ForeignKey("jobs.id"), nullable=False, index=True)
    index = Column(Integer, nullable=False)
    start_sec = Column(Float, nullable=False)
    end_sec = Column(Float, nullable=False)
    duration_sec = Column(Float)
    media_sha256 = Column(String)
    state = Column(String, default="queued", nullable=False)
    result_path = Column(String)
    result_sha256 = Column(String)
    attempt_count = Column(Integer, default=0, nullable=False)
    __table_args__ = (UniqueConstraint("job_id", "index"),)


class ProviderCall(Base):
    __tablename__ = "provider_calls"
    id = Column(String, primary_key=True, default=uid)
    job_id = Column(ForeignKey("jobs.id"), nullable=False, index=True)
    chunk_id = Column(ForeignKey("job_chunks.id"))
    purpose = Column(String, nullable=False)
    attempt = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    requested_model = Column(String, nullable=False)
    returned_model = Column(String)
    provider_request_id = Column(String)
    started_at = Column(String, default=now, nullable=False)
    finished_at = Column(String)
    usage_json = Column(Text)
    estimated_cost_usd = Column(Float)
    price_snapshot_id = Column(ForeignKey("price_snapshots.id"))
    error_code = Column(String)


class RemoteFile(Base):
    __tablename__ = "remote_files"
    id = Column(String, primary_key=True, default=uid)
    job_id = Column(ForeignKey("jobs.id"), nullable=False, index=True)
    provider_file_name = Column(String, nullable=False)
    expires_at = Column(String)
    cleanup_state = Column(String, default="pending", nullable=False)
    next_cleanup_at = Column(Float, default=0)
    last_error = Column(String)
    attempts = Column(Integer, default=0, nullable=False)


class Generation(Base):
    __tablename__ = "generations"
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(ForeignKey("projects.id"), nullable=False, index=True)
    job_id = Column(ForeignKey("jobs.id"), nullable=False)
    schema_version = Column(String, default="2.0", nullable=False)
    prompt_version = Column(String, default="tutorial_v2", nullable=False)
    pipeline_version = Column(String, default="0.1.0", nullable=False)
    validated_json_path = Column(String, nullable=False)
    created_at = Column(String, default=now, nullable=False)
    quality_status = Column(String, nullable=False)


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(ForeignKey("projects.id"), unique=True, nullable=False)
    current_revision_id = Column(ForeignKey("document_revisions.id", use_alter=True))
    created_at = Column(String, default=now, nullable=False)
    updated_at = Column(String, default=now, nullable=False)


class Revision(Base):
    __tablename__ = "document_revisions"
    id = Column(String, primary_key=True, default=uid)
    document_id = Column(ForeignKey("documents.id"), nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    base_revision_id = Column(ForeignKey("document_revisions.id"))
    generation_id = Column(ForeignKey("generations.id"))
    markdown = Column(Text, nullable=False)
    content_sha256 = Column(String, nullable=False)
    source = Column(String, nullable=False)
    created_at = Column(String, default=now, nullable=False)
    __table_args__ = (UniqueConstraint("document_id", "revision_number"),)


class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(ForeignKey("projects.id"), nullable=False, index=True)
    generation_id = Column(ForeignKey("generations.id"), nullable=False)
    step_id = Column(String, nullable=False)
    asset_id = Column(ForeignKey("assets.id"), nullable=False)
    requested_sec = Column(Float, nullable=False)
    actual_sec = Column(Float, nullable=False)
    relative_path = Column(String, nullable=False)
    sha256 = Column(String, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    status = Column(String, default="unverified", nullable=False)
    human_verified_at = Column(String)


class Export(Base):
    __tablename__ = "exports"
    id = Column(String, primary_key=True, default=uid)
    job_id = Column(ForeignKey("jobs.id"), nullable=False)
    document_revision_id = Column(ForeignKey("document_revisions.id"), nullable=False)
    format = Column(String, nullable=False)
    state = Column(String, default="queued", nullable=False)
    relative_path = Column(String)
    sha256 = Column(String)
    created_at = Column(String, default=now, nullable=False)


class Consent(Base):
    __tablename__ = "consents"
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(ForeignKey("projects.id"), nullable=False)
    asset_sha256 = Column(String, nullable=False)
    notice_version = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    accepted_at = Column(String, default=now, nullable=False)


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    id = Column(String, primary_key=True, default=uid)
    model = Column(String, nullable=False)
    tier = Column(String, nullable=False)
    effective_from = Column(String, nullable=False)
    effective_to = Column(String, nullable=False)
    input_rate = Column(Float, nullable=False)
    output_rate = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="USD")
    source_url = Column(String, nullable=False)
    checked_at = Column(String, nullable=False)
