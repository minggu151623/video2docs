import type { TutorialDraftV2 } from "./tutorial";
export interface Project {
  id: string;
  name: string;
  output_language: "vi" | "en";
  created_at: string;
  updated_at: string;
}
export interface Asset {
  id: string;
  original_name: string;
  sha256: string;
  bytes: number;
  duration_sec: number;
  validation_status: string;
  width: number;
  height: number;
  has_audio: boolean;
}
export interface Job {
  export: {
    id: string;
    format: string;
    state: string;
    document_revision_id: string;
  } | null;
  provider_calls: { estimated_cost_usd: number | null }[];
  id: string;
  kind: string;
  state: string;
  phase: string;
  completed_units: number;
  total_units: number;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  created_at: string;
  cleanup_pending: number;
  is_mock: boolean;
  warnings: JobWarning[];
}
/** Known codes: NOT_TUTORIAL, LATER_CLIP_NOT_TUTORIAL, VERIFICATION_DEGRADED. Others and bare strings are tolerated. */
export type JobWarning = { code: string; [key: string]: unknown } | string;
export interface ProjectDetail extends Project {
  assets: Asset[];
  jobs: Job[];
  cleanup_pending: number;
}
export interface Revision {
  id: string;
  revision_number: number;
  markdown: string;
  generation_id: string | null;
  created_at: string;
  source: string;
}
export interface Document {
  id: string;
  current_revision_id: string;
  revision: Revision;
}
export interface Evidence {
  id: string;
  step_id: string;
  actual_sec: number;
  requested_sec: number;
  status: string;
}
export interface Generation {
  id: string;
  created_at: string;
  quality_status: string;
  job_id: string;
}
export type VerificationStatus =
  "verified" | "unverified" | "not_checkable" | "not_checked";
export interface VerificationItem {
  status: VerificationStatus;
  method: "asr" | "ocr" | "none";
  matched_text: string | null;
  matched_sec: number | null;
  checked_range: [number, number] | null;
  reason: string | null;
}
export type EngineStatus = "ok" | "skipped" | "failed";
/** Written by the backend apart from the draft; item keys look like `steps/{i}/parameters/{j}`. */
export interface Verification {
  items: Record<string, VerificationItem>;
  asr_status: EngineStatus;
  ocr_status: EngineStatus;
  asr_error: string | null;
  ocr_error: string | null;
}
export interface GenerationDetail extends Generation {
  draft: TutorialDraftV2;
  verification: Verification | null;
  evidence: Evidence[];
}
export interface Capabilities {
  model: string;
  provider: string;
  provider_ready: boolean;
  ffmpeg_ready: boolean;
  pdf_ready: boolean;
  max_upload_mb: number;
  max_video_seconds: number;
  notice: string;
  notice_version: string;
  terms_url: string;
}
