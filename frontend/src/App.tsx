import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, bootstrap, upload, ApiError } from "./api/client";
import type {
  Project,
  ProjectDetail,
  Capabilities,
  Document,
  Revision,
  Job,
  Generation,
  GenerationDetail,
} from "./types/app";
import Markdown from "./components/Markdown";
import Dialog from "./components/Dialog";
import NotTutorialNotice from "./components/NotTutorialNotice";
import VerificationSummary, {
  StepBadge,
} from "./components/VerificationSummary";
import {
  notTutorialReason,
  pendingInStep,
  warningLines,
} from "./lib/verification";

const terminal = new Set([
  "succeeded",
  "needs_review",
  "not_tutorial",
  "failed",
  "cancelled",
  "interrupted",
]);
const phaseText: Record<string, string> = {
  queued: "Đang xếp hàng",
  validating: "Kiểm tra video",
  preparing: "Chuẩn bị clip",
  uploading: "Gửi clip tới provider",
  analyzing: "Phân tích video",
  transcribing: "Chép lời nói",
  verifying: "Kiểm chứng",
  assembling: "Ghép tài liệu",
  extracting_evidence: "Trích ảnh bằng chứng",
  saving: "Lưu tài liệu",
  cleaning_up: "Dọn file Google",
  exporting: "Đang xuất file",
  deleting: "Đang xóa",
  succeeded: "Hoàn tất",
  needs_review: "Cần kiểm tra",
  not_tutorial: "Không phải tutorial",
  failed: "Thất bại",
  cancelled: "Đã hủy",
  cancel_requested: "Đang hủy",
  interrupted: "Bị gián đoạn",
};
const kindText: Record<string, string> = {
  validate_asset: "Kiểm tra video",
  analyze: "Tạo tài liệu",
  verify: "Kiểm chứng lại",
  export: "Xuất file",
  extract_evidence: "Chọn ảnh",
  provider_check: "Kiểm tra kết nối",
  delete_project: "Xóa dự án",
};
const stamp = (sec: number) => {
  const s = Math.floor(sec);
  return `${Math.floor(s / 3600)
    .toString()
    .padStart(
      2,
      "0",
    )}:${Math.floor(s / 60) % 60 < 10 ? "0" : ""}${Math.floor(s / 60) % 60}:${(s % 60).toString().padStart(2, "0")}`;
};
const date = (iso: string) => new Date(iso).toLocaleString("vi-VN");

export default function App() {
  const [ready, setReady] = useState(false),
    [cap, setCap] = useState<Capabilities | null>(null),
    [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(
      location.hash.slice(1) || null,
    ),
    [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false),
    [name, setName] = useState(""),
    [language, setLanguage] = useState<"vi" | "en">("vi"),
    [file, setFile] = useState<File | null>(null),
    [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [doc, setDoc] = useState<Document | null>(null),
    [text, setText] = useState(""),
    [saveState, setSaveState] = useState("Đã lưu"),
    [conflict, setConflict] = useState(false),
    [preview, setPreview] = useState(true),
    [editor, setEditor] = useState(true);
  const dirty = useRef(false),
    revisionRef = useRef<string | null>(null),
    textRef = useRef(""),
    saveInFlight = useRef(false),
    lastJobStates = useRef(""),
    verifyTarget = useRef<string | null>(null),
    currentProject = useRef(projectId);
  const [generations, setGenerations] = useState<Generation[]>([]),
    [generation, setGeneration] = useState<GenerationDetail | null>(null),
    [history, setHistory] = useState<Revision[] | null>(null);
  const [consented, setConsented] = useState(false),
    [unknownCost, setUnknownCost] = useState(false),
    [budget, setBudget] = useState("1.00"),
    [deleteOpen, setDeleteOpen] = useState(false),
    [image, setImage] = useState<string | null>(null),
    [rename, setRename] = useState(false);
  const [frameStep, setFrameStep] = useState<string | null>(null),
    [frameTime, setFrameTime] = useState("0"),
    [checkJob, setCheckJob] = useState<Job | null>(null),
    [exports, setExports] = useState<
      Record<string, { state: string; url?: string; error?: string }>
    >({});
  const [onlyPending, setOnlyPending] = useState(false),
    [verifyJob, setVerifyJob] = useState<Job | null>(null),
    [verifyNotice, setVerifyNotice] = useState<{
      kind: "error" | "info";
      text: string;
    } | null>(null);
  const video = useRef<HTMLVideoElement>(null);

  const report = useCallback((err: unknown) => {
    setError(
      err instanceof Error ? err.message : "Đã xảy ra lỗi. Thử tải lại trang.",
    );
    setBusy(false);
  }, []);
  const list = useCallback(async () => {
    const result = await api("/projects?limit=100");
    setProjects(result.items);
  }, []);
  const loadDocument = useCallback(async (id: string, force = false) => {
    const document = await api<Document | null>(`/projects/${id}/document`);
    if (currentProject.current !== id) return;
    if (document && (force || !dirty.current)) {
      setDoc(document);
      setText(document.revision.markdown);
      textRef.current = document.revision.markdown;
      revisionRef.current = document.revision.id;
      dirty.current = false;
      setSaveState("Đã lưu");
      setConflict(false);
    } else if (!document) {
      setDoc(null);
      setText("");
      textRef.current = "";
      revisionRef.current = null;
    }
  }, []);
  const refresh = useCallback(
    async (id: string) => {
      const [p, gs] = await Promise.all([
        api<ProjectDetail>(`/projects/${id}`),
        api(`/projects/${id}/generations`),
      ]);
      if (currentProject.current !== id) return;
      setDetail(p);
      setGenerations(gs.items);
      const states = p.jobs.map((j) => j.id + j.state).join(",");
      if (states !== lastJobStates.current) {
        lastJobStates.current = states;
        await loadDocument(id);
      }
    },
    [loadDocument],
  );
  useEffect(() => {
    bootstrap()
      .then(async () => {
        await list();
        setCap(await api("/capabilities"));
        setReady(true);
      })
      .catch(report);
  }, [list, report]);
  useEffect(() => {
    currentProject.current = projectId;
    location.hash = projectId ?? "";
    setDetail(null);
    setDoc(null);
    setText("");
    setGeneration(null);
    setGenerations([]);
    setError("");
    setMessage("");
    setConsented(false);
    setUnknownCost(false);
    setConflict(false);
    setExports({});
    setVerifyJob(null);
    setVerifyNotice(null);
    setOnlyPending(false);
    dirty.current = false;
    revisionRef.current = null;
    lastJobStates.current = "";
    if (!ready || !projectId) return;
    refresh(projectId).catch(report);
    let disposed = false,
      timer: number;
    const poll = async () => {
      if (disposed) return;
      try {
        await refresh(projectId);
      } catch (err) {
        if (!disposed) report(err);
      }
      if (!disposed)
        timer = window.setTimeout(poll, document.hidden ? 10000 : 2000);
    };
    timer = window.setTimeout(poll, 2000);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [projectId, ready, refresh, report]);
  useEffect(() => {
    if (!doc?.revision.generation_id) return;
    let disposed = false;
    api<GenerationDetail>(`/generations/${doc.revision.generation_id}`)
      .then((value) => {
        if (!disposed) setGeneration(value);
      })
      .catch((err) => {
        if (!disposed) report(err);
      });
    return () => {
      disposed = true;
    };
  }, [doc?.revision.id, report]);
  useEffect(() => {
    if (!dirty.current || !doc || conflict) return;
    const timer = setTimeout(() => {
      void save();
    }, 1000);
    return () => clearTimeout(timer);
  }, [text, doc, conflict]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);
  async function save() {
    if (!doc || !dirty.current || saveInFlight.current || conflict) return;
    saveInFlight.current = true;
    setSaveState("Đang lưu…");
    const savedText = textRef.current,
      base = revisionRef.current;
    try {
      const r = await api<Revision>(`/documents/${doc.id}`, "PUT", {
        base_revision: base,
        markdown: savedText,
      });
      if (currentProject.current !== projectId) return;
      revisionRef.current = r.id;
      setDoc({ ...doc, revision: r, current_revision_id: r.id });
      dirty.current = textRef.current !== savedText;
      setSaveState(dirty.current ? "Chờ lưu…" : "Đã lưu");
    } catch (err) {
      setSaveState("Lưu thất bại");
      if (err instanceof ApiError && err.status === 409) setConflict(true);
      else report(err);
    } finally {
      saveInFlight.current = false;
    }
  }
  const chooseProject = (id: string | null) => {
    if (
      dirty.current &&
      !window.confirm("Có thay đổi chưa lưu. Chuyển dự án sẽ bỏ bản local này?")
    )
      return;
    setProjectId(id);
    setCreating(false);
  };
  const seek = (seconds: number) => {
    if (video.current) {
      video.current.currentTime = seconds;
      video.current.focus();
    }
    setFrameTime(seconds.toFixed(3));
  };
  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !file) return;
    setBusy(true);
    setError("");
    setUploadProgress(0);
    try {
      const p = await api<Project>("/projects", "POST", {
        name: name.trim(),
        output_language: language,
      });
      setProjectId(p.id);
      setCreating(false);
      await list();
      await upload(p.id, file, setUploadProgress);
      await refresh(p.id);
      setName("");
      setFile(null);
    } catch (err) {
      report(err);
    } finally {
      setBusy(false);
      setUploadProgress(null);
    }
  }
  async function addFile(e: FormEvent) {
    e.preventDefault();
    if (!projectId || !file) return;
    setBusy(true);
    setUploadProgress(0);
    try {
      await upload(projectId, file, setUploadProgress);
      await refresh(projectId);
      setFile(null);
    } catch (err) {
      report(err);
    } finally {
      setBusy(false);
      setUploadProgress(null);
    }
  }
  const asset = detail?.assets[0];
  const active = detail?.jobs.find((j) => !terminal.has(j.state));
  const latestAnalysis = detail?.jobs.find((j) => j.kind === "analyze");
  const stopped =
    latestAnalysis?.state === "not_tutorial" ? latestAnalysis : null;
  async function generate() {
    if (!consented || !unknownCost) return;
    if ((await startAnalysis(false, Number(budget))) === null) {
      setConsented(false);
      setUnknownCost(false);
    }
  }
  /** Enqueue an analysis. Resolves to null on success, else the error message; with `inline` the
   * caller shows that message itself (inside a dialog) instead of the page-level notice. */
  async function startAnalysis(
    skipGate: boolean,
    budgetUsd: number,
    inline = false,
  ): Promise<string | null> {
    if (!detail || !asset || !cap) return "Chưa có video hợp lệ để phân tích.";
    setBusy(true);
    setError("");
    try {
      const c = await api(`/projects/${detail.id}/consents`, "POST", {
        asset_sha256: asset.sha256,
        notice_version: cap.notice_version,
      });
      await api(`/projects/${detail.id}/estimates`, "POST", {
        asset_id: asset.id,
      });
      await api(
        `/projects/${detail.id}/jobs`,
        "POST",
        {
          asset_id: asset.id,
          mode: "static",
          output_language: detail.output_language,
          consent_id: c.id,
          allow_unknown_cost: true,
          budget_usd: budgetUsd,
          ...(skipGate ? { skip_tutorial_gate: true } : {}),
        },
        { "Idempotency-Key": crypto.randomUUID() },
      );
      await refresh(detail.id).catch(report);
      return null;
    } catch (err) {
      if (!inline) report(err);
      return err instanceof Error
        ? err.message
        : "Đã xảy ra lỗi. Thử tải lại trang.";
    } finally {
      setBusy(false);
    }
  }
  async function reverify() {
    if (!generation) return;
    setVerifyNotice(null);
    try {
      verifyTarget.current = generation.id;
      setVerifyJob(
        await api<Job>(`/generations/${generation.id}/verify`, "POST"),
      );
    } catch (err) {
      setVerifyNotice({
        kind: "error",
        text:
          err instanceof Error ? err.message : "Không bắt đầu được kiểm chứng.",
      });
    }
  }
  async function retry(job: Job) {
    const ambiguous = ["UNKNOWN_OUTCOME", "UPLOAD_OUTCOME_UNKNOWN"].includes(
      job.error_code ?? "",
    );
    if (
      ambiguous &&
      !window.confirm(
        "Request trước chưa rõ kết quả. Thử lại có thể tính phí thêm. Tiếp tục?",
      )
    )
      return;
    try {
      await api(`/jobs/${job.id}/retry`, "POST", {
        reason: "Người dùng chủ động thử lại",
        acknowledge_possible_duplicate_cost: ambiguous,
      });
      await refresh(projectId!);
    } catch (err) {
      report(err);
    }
  }
  async function restore(revision: string) {
    if (!doc) return;
    try {
      await api(`/documents/${doc.id}/restore`, "POST", {
        base_revision: revisionRef.current,
        revision,
      });
      await loadDocument(projectId!, true);
      setHistory(null);
    } catch (err) {
      report(err);
    }
  }
  async function applyGeneration(id: string) {
    if (!doc) return;
    if (dirty.current) {
      setError("Lưu bản hiện tại trước khi áp dụng generation.");
      return;
    }
    try {
      await api(`/documents/${doc.id}/apply-generation`, "POST", {
        base_revision: revisionRef.current,
        generation_id: id,
      });
      await loadDocument(projectId!, true);
      setMessage("Đã áp dụng generation vào revision mới.");
    } catch (err) {
      report(err);
    }
  }
  async function exportFile(format: string) {
    if (!doc || dirty.current) {
      setError("Chờ lưu bản sửa trước khi xuất file.");
      return;
    }
    setExports((x) => ({ ...x, [format]: { state: "running" } }));
    const exportingProject = projectId;
    try {
      const result = await api(`/documents/${doc.id}/exports`, "POST", {
        revision: revisionRef.current,
        format,
      });
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const ex = await api(`/exports/${result.id}`);
        if (currentProject.current !== exportingProject) return;
        if (ex.state === "succeeded") {
          setExports((x) => ({
            ...x,
            [format]: { state: "succeeded", url: ex.download_url },
          }));
          return;
        }
        if (terminal.has(ex.job.state)) {
          throw new Error(ex.job.error_message ?? "Xuất file thất bại.");
        }
      }
      throw new Error(
        "Export vẫn đang chạy. Xem trạng thái job hoặc thử lại sau.",
      );
    } catch (err) {
      if (currentProject.current !== exportingProject) return;
      setExports((x) => ({
        ...x,
        [format]: {
          state: "failed",
          error: err instanceof Error ? err.message : "Lỗi export",
        },
      }));
    }
  }
  async function deleteProject() {
    if (!projectId) return;
    setBusy(true);
    try {
      const job = await api(`/projects/${projectId}`, "DELETE");
      setDeleteOpen(false);
      chooseProject(null);
      await list();
      setMessage(
        `Đã khóa dự án. Job xóa ${job.id} đang dọn dữ liệu; cleanup Google có thể còn chờ.`,
      );
      setCheckJob(job);
    } catch (err) {
      report(err);
    } finally {
      setBusy(false);
    }
  }
  async function connection() {
    setBusy(true);
    try {
      const job = await api("/provider/check", "POST", {});
      setCheckJob(job);
    } catch (err) {
      report(err);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!checkJob || terminal.has(checkJob.state)) return;
    const timer = setInterval(
      () => api<Job>(`/jobs/${checkJob.id}`).then(setCheckJob).catch(report),
      2000,
    );
    return () => clearInterval(timer);
  }, [checkJob, report]);
  useEffect(() => {
    if (!verifyJob || terminal.has(verifyJob.state)) return;
    const timer = setInterval(
      () =>
        api<Job>(`/jobs/${verifyJob.id}`)
          .then(setVerifyJob)
          .catch((err) => {
            setVerifyJob(null);
            setVerifyNotice({ kind: "error", text: err.message });
          }),
      2000,
    );
    return () => clearInterval(timer);
  }, [verifyJob]);
  useEffect(() => {
    if (!verifyJob || !terminal.has(verifyJob.state)) return;
    const job = verifyJob,
      target = verifyTarget.current,
      owner = currentProject.current;
    setVerifyJob(null);
    if (job.state !== "succeeded" || !target) {
      setVerifyNotice({
        kind: "error",
        text: job.error_message ?? "Kiểm chứng không hoàn tất.",
      });
      return;
    }
    api<GenerationDetail>(`/generations/${target}`)
      .then((value) => {
        if (currentProject.current !== owner) return;
        setGeneration((old) => (old?.id === target ? value : old));
        setVerifyNotice({ kind: "info", text: "Đã kiểm chứng lại." });
      })
      .catch((err) => setVerifyNotice({ kind: "error", text: err.message }));
  }, [verifyJob]);
  async function replaceFrame() {
    if (!generation || !asset || !frameStep || !doc || !projectId) return;
    if (dirty.current) {
      setError("Lưu tài liệu trước khi chọn lại ảnh.");
      return;
    }
    try {
      await api(`/projects/${projectId}/evidence`, "POST", {
        asset_id: asset.id,
        generation_id: generation.id,
        step_id: frameStep,
        timestamp: Number(frameTime),
        base_revision: revisionRef.current,
      });
      setFrameStep(null);
      await refresh(projectId);
    } catch (err) {
      report(err);
    }
  }
  if (!ready)
    return (
      <main className="boot">
        <h1>Video2docs</h1>
        <p role="status">{error || "Đang mở phiên local và đọc cấu hình…"}</p>
        {error && <button onClick={() => location.reload()}>Tải lại</button>}
      </main>
    );
  return (
    <div className="app-shell">
      <aside className="library" aria-label="Thư viện dự án">
        <div className="brand">
          Video<span>2</span>docs
        </div>
        <p className="library-note">Từ video đến tài liệu</p>
        <button
          className="primary new-project"
          onClick={() => {
            if (dirty.current && !window.confirm("Rời bản sửa chưa lưu?"))
              return;
            chooseProject(null);
            setCreating(true);
          }}
        >
          Tạo dự án mới
        </button>
        <h2>
          Dự án của bạn <span>{projects.length}</span>
        </h2>
        <nav>
          {projects.length ? (
            projects.map((p) => (
              <button
                key={p.id}
                aria-current={projectId === p.id ? "page" : undefined}
                className="project-link"
                onClick={() => chooseProject(p.id)}
              >
                <strong>{p.name}</strong>
                <span>
                  {new Date(p.updated_at).toLocaleDateString("vi-VN")} ·{" "}
                  {p.output_language.toUpperCase()}
                </span>
              </button>
            ))
          ) : (
            <p className="muted">
              Chưa có dự án. Chọn video đầu tiên để tạo bản nháp.
            </p>
          )}
        </nav>
        <div className="system-info">
          <strong>Lưu trên máy này</strong>
          <p>
            {cap?.provider === "mock" ? "MOCK · Dữ liệu tổng hợp" : cap?.model}
          </p>
          <p>
            Static · {cap?.max_upload_mb} MiB ·{" "}
            {Math.round((cap?.max_video_seconds ?? 0) / 60)} phút
          </p>
          <button onClick={connection} disabled={busy || !cap?.provider_ready}>
            Kiểm tra kết nối
          </button>
          {!cap?.provider_ready && (
            <p className="warning-text">
              Chưa có API key. Cấu hình GEMINI_API_KEY ở backend rồi khởi động
              lại.
            </p>
          )}
          <p>
            FFmpeg: {cap?.ffmpeg_ready ? "Sẵn sàng" : "Chưa cài"}
            <br />
            PDF: {cap?.pdf_ready ? "Sẵn sàng" : "Thiếu Chromium/font"}
          </p>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="muted">Không gian tài liệu</span>
            <h1>
              {detail?.name ?? (creating ? "Tạo dự án" : "Thư viện video")}
            </h1>
          </div>
          {detail && (
            <div className="top-actions">
              <button
                onClick={() => {
                  setName(detail.name);
                  setLanguage(detail.output_language);
                  setRename(true);
                }}
              >
                Đổi tên
              </button>
              <button
                className="danger subtle"
                onClick={() => setDeleteOpen(true)}
              >
                Xóa dự án
              </button>
            </div>
          )}
        </header>
        {error && (
          <div className="notice error" role="alert">
            <span>{error}</span>
            <button onClick={() => setError("")}>Đóng lỗi</button>
          </div>
        )}
        {message && (
          <div className="notice" role="status">
            {message}
            <button onClick={() => setMessage("")}>Đóng thông báo</button>
          </div>
        )}
        {checkJob && (
          <div className="notice" role="status">
            <span>
              {kindText[checkJob.kind]}:{" "}
              {phaseText[checkJob.state] ?? checkJob.state}.{" "}
              {checkJob.error_message}{" "}
              {checkJob.cleanup_pending
                ? `Cleanup Google còn chờ: ${checkJob.cleanup_pending}`
                : ""}{" "}
              {checkJob.state === "succeeded" &&
              checkJob.kind === "provider_check"
                ? "Metadata model đã phản hồi; video smoke chưa được kiểm tra."
                : ""}
            </span>
            <button onClick={() => setCheckJob(null)}>Đóng trạng thái</button>
          </div>
        )}
        {cap?.provider === "mock" && (
          <div className="mock-banner">
            Chế độ MOCK: kiểm thử luồng ứng dụng bằng dữ liệu tổng hợp. Không
            phân tích nội dung video.
          </div>
        )}
        {uploadProgress !== null && (
          <div className="notice" role="status">
            <div className="grow">
              Upload local: {uploadProgress}%{" "}
              <progress max="100" value={uploadProgress} />
            </div>
          </div>
        )}
        {!projectId && (
          <section className="create-area">
            <div className="intro">
              <p className="section-number">01 / Nguồn</p>
              <h2>
                Giữ lại hướng dẫn,
                <br />
                từng bước một.
              </h2>
              <p>
                Video hướng dẫn: nấu ăn, sửa chữa, phần mềm… Tạo bản nháp có mốc
                thời gian, ảnh nguồn và chỗ để bạn kiểm tra, chỉnh sửa.
              </p>
              <p className="muted">
                MP4, MOV hoặc WebM. Video được lưu local; chỉ gửi đến Google sau
                khi bạn xác nhận tạo tài liệu.
              </p>
            </div>
            <form className="upload-form" onSubmit={create}>
              <h3>Dự án mới</h3>
              <label>
                Tên dự án
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={200}
                  required
                  placeholder="Tên tutorial của bạn"
                />
              </label>
              <label>
                Ngôn ngữ tài liệu
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value as "vi" | "en")}
                >
                  <option value="vi">Tiếng Việt</option>
                  <option value="en">English</option>
                </select>
              </label>
              <label className="file-picker">
                Video nguồn
                <input
                  type="file"
                  accept=".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm"
                  required
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                <small>
                  Tối đa {cap?.max_upload_mb} MiB,{" "}
                  {Math.round((cap?.max_video_seconds ?? 0) / 60)} phút.
                </small>
              </label>
              <button
                className="primary"
                type="submit"
                disabled={busy || !file || !name.trim()}
              >
                Lưu video vào dự án
              </button>
            </form>
          </section>
        )}
        {projectId && !detail && (
          <p role="status" className="loading-text">
            Đang tải dự án…
          </p>
        )}
        {detail && (
          <>
            {detail.cleanup_pending > 0 && (
              <div className="notice warning">
                Chưa xác nhận xóa {detail.cleanup_pending} file Google. Worker
                sẽ thử cleanup có giới hạn.
              </div>
            )}
            {stopped && (
              <NotTutorialNotice
                key={stopped.id}
                reason={notTutorialReason(stopped.warnings)}
                busy={busy}
                providerReady={!!cap?.provider_ready}
                initialBudget={budget}
                onAnalyze={(usd) => startAnalysis(true, usd, true)}
              />
            )}
            <div className="work-grid">
              <section className="source-pane" aria-label="Video và bằng chứng">
                <div className="pane-heading">
                  <span className="section-number">01 / Nguồn</span>
                  <span className="muted">
                    {detail.output_language === "vi" ? "Tiếng Việt" : "English"}
                  </span>
                </div>
                {asset?.validation_status === "validated" ? (
                  <>
                    <video
                      key={asset.id}
                      ref={video}
                      controls
                      preload="metadata"
                      src={`/api/v1/assets/${asset.id}/media`}
                      poster={`/api/v1/assets/${asset.id}/thumbnail`}
                      onTimeUpdate={() => {
                        if (!frameStep)
                          setFrameTime(
                            (video.current?.currentTime ?? 0).toFixed(3),
                          );
                      }}
                    />
                    <div className="video-meta">
                      <strong>{asset.original_name}</strong>
                      <span>
                        {stamp(asset.duration_sec)} ·{" "}
                        {(asset.bytes / 1024 / 1024).toFixed(1)} MiB ·{" "}
                        {asset.width}×{asset.height}
                        {!asset.has_audio ? " · Không có audio" : ""}
                      </span>
                    </div>
                  </>
                ) : asset ? (
                  <div className="video-placeholder">
                    <h3>
                      {asset.validation_status === "failed"
                        ? "Video chưa hợp lệ"
                        : "Đang kiểm tra video"}
                    </h3>
                    <p>{asset.original_name}</p>
                    <p>Chỉ video qua kiểm tra mới có thể được gửi phân tích.</p>
                  </div>
                ) : (
                  <form className="upload-form compact" onSubmit={addFile}>
                    <h3>Chọn video cho dự án</h3>
                    <label>
                      Video nguồn
                      <input
                        type="file"
                        accept=".mp4,.mov,.webm"
                        required
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                      />
                    </label>
                    <button
                      type="submit"
                      className="primary"
                      disabled={busy || !file}
                    >
                      Upload local
                    </button>
                  </form>
                )}
                {active && (
                  <div className="job-status" role="status">
                    <strong>
                      {kindText[active.kind]} ·{" "}
                      {phaseText[active.phase] ?? active.phase}
                    </strong>
                    <p>
                      {active.total_units
                        ? `${active.completed_units}/${active.total_units} đoạn hoàn tất · `
                        : ""}
                      {active.started_at
                        ? `${Math.max(0, Math.round((Date.now() - new Date(active.started_at).getTime()) / 1000))} giây đã chạy`
                        : "Đợi worker local"}
                    </p>
                    {active.phase === "analyzing" && (
                      <p className="muted">Đang chờ provider trả kết quả.</p>
                    )}
                    <button
                      onClick={async () => {
                        try {
                          await api(`/jobs/${active.id}/cancel`, "POST");
                          setMessage(
                            "Đã yêu cầu hủy local. Request đang chạy ở Google vẫn có thể phát sinh phí.",
                          );
                          await refresh(detail.id);
                        } catch (err) {
                          report(err);
                        }
                      }}
                    >
                      Hủy job
                    </button>
                  </div>
                )}
                {asset?.validation_status === "validated" && !active && (
                  <details className="generation-settings" open={!doc}>
                    <summary>
                      {doc ? "Tạo bản generation mới" : "Tạo tài liệu từ video"}
                    </summary>
                    <p>
                      {cap?.notice}{" "}
                      <a href={cap?.terms_url} target="_blank" rel="noreferrer">
                        Điều khoản Google
                      </a>{" "}
                      (kiểm tra 20/10/2026).
                    </p>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={consented}
                        onChange={(e) => setConsented(e.target.checked)}
                      />
                      Tôi đồng ý gửi video này đến provider đã hiển thị.
                    </label>
                    <p className="muted">
                      Chưa đủ dữ liệu để ước tính chi phí. Quota chưa biết. Ngân
                      sách dưới đây là giới hạn mềm.
                    </p>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={unknownCost}
                        onChange={(e) => setUnknownCost(e.target.checked)}
                      />
                      Tiếp tục với chi phí chưa xác định.
                    </label>
                    <label className="budget">
                      Ngân sách mềm (USD)
                      <input
                        type="number"
                        step="0.01"
                        min="0.01"
                        max="100"
                        value={budget}
                        onChange={(e) => setBudget(e.target.value)}
                      />
                    </label>
                    <button
                      className="primary"
                      onClick={generate}
                      disabled={
                        busy ||
                        !consented ||
                        !unknownCost ||
                        !cap?.provider_ready ||
                        Number(budget) <= 0
                      }
                    >
                      {doc ? "Tạo generation mới" : "Tạo tài liệu"}
                    </button>
                    {doc && (
                      <p className="muted">
                        Bản mới được lưu riêng. Bạn chọn áp dụng sau khi kiểm
                        tra.
                      </p>
                    )}
                  </details>
                )}
                {generation && (
                  <div className="steps">
                    <div className="pane-heading">
                      <h2>Các bước nguồn</h2>
                      <span>{generation.draft.steps.length} bước</span>
                    </div>
                    <VerificationSummary
                      generation={generation}
                      onlyPending={onlyPending}
                      onOnlyPending={setOnlyPending}
                      onVerify={reverify}
                      verifying={!!verifyJob}
                      blocked={!!active}
                      notice={verifyNotice}
                    />
                    {generation.draft.steps.length === 0 && (
                      <p>
                        Video chưa có thao tác hướng dẫn quan sát được. Xem mục
                        Điểm chưa rõ trong tài liệu.
                      </p>
                    )}
                    {onlyPending &&
                      generation.verification &&
                      !generation.draft.steps.some((_, i) =>
                        pendingInStep(generation.verification, i),
                      ) && (
                        <p className="muted" role="status">
                          Không có bước nào còn mục chưa kiểm chứng.
                        </p>
                      )}
                    {generation.draft.steps.map((s, i) =>
                      onlyPending &&
                      generation.verification &&
                      !pendingInStep(generation.verification, i) ? null : (
                        <div className="step" key={s.local_id}>
                          <div className="step-top">
                            <span className="step-number">
                              {(i + 1).toString().padStart(2, "0")}
                            </span>
                            <button
                              className="timestamp"
                              onClick={() => seek(s.start_sec)}
                            >
                              {stamp(s.start_sec)}
                            </button>
                            <StepBadge
                              count={pendingInStep(generation.verification, i)}
                            />
                          </div>
                          <h3>{s.title}</h3>
                          {s.needs_review && (
                            <p className="review-label">
                              Cần kiểm tra: {s.review_reason}
                            </p>
                          )}
                          <ul>
                            {s.actions.map((a, k) => (
                              <li key={k}>{a}</li>
                            ))}
                          </ul>
                          <div className="evidence-list">
                            {generation.evidence
                              .filter((e) => e.step_id === s.local_id)
                              .slice(-1)
                              .map((e) => (
                                <button
                                  className="evidence-button"
                                  key={e.id}
                                  onClick={() => {
                                    seek(e.actual_sec);
                                    setImage(`/api/v1/evidence/${e.id}/image`);
                                  }}
                                >
                                  <img
                                    src={`/api/v1/evidence/${e.id}/image`}
                                    alt={`Ảnh nguồn tại ${stamp(e.actual_sec)}`}
                                  />
                                  <span>
                                    {stamp(e.actual_sec)} · Chưa kiểm tra bằng
                                    mắt
                                  </span>
                                </button>
                              ))}
                          </div>
                          <button
                            onClick={() => {
                              setFrameStep(s.local_id);
                              setFrameTime(
                                (
                                  video.current?.currentTime ?? s.start_sec
                                ).toFixed(3),
                              );
                            }}
                          >
                            Chọn lại ảnh
                          </button>
                        </div>
                      ),
                    )}
                  </div>
                )}
                {detail.jobs.length > 0 && (
                  <details className="job-history">
                    <summary>Lịch sử xử lý ({detail.jobs.length})</summary>
                    {detail.jobs.map((j) => (
                      <div className="job-row" key={j.id}>
                        <strong>
                          {kindText[j.kind]} · {phaseText[j.state]}
                        </strong>
                        <small>{date(j.created_at)}</small>
                        {j.export?.state === "succeeded" && (
                          <p>
                            <a
                              href={`/api/v1/exports/${j.export.id}/download`}
                              download
                            >
                              Tải .{j.export.format} của revision{" "}
                              {j.export.document_revision_id.slice(0, 8)}
                            </a>
                          </p>
                        )}
                        {j.provider_calls?.length > 0 && (
                          <p>
                            {j.provider_calls.length} lượt AI ·{" "}
                            {j.provider_calls.every(
                              (c) => c.estimated_cost_usd !== null,
                            )
                              ? `Chi phí tham chiếu: $${j.provider_calls.reduce((sum, c) => sum + (c.estimated_cost_usd ?? 0), 0).toFixed(5)}`
                              : "Chi phí/usage còn chưa xác định"}
                          </p>
                        )}
                        {j.state === "not_tutorial" && (
                          <p>
                            Đã dừng sau đoạn đầu; không phân tích các đoạn sau.
                          </p>
                        )}
                        {warningLines(j.warnings).map((line) => (
                          <p className="muted" key={line}>
                            {line}
                          </p>
                        ))}
                        {j.error_message && (
                          <p role="alert">
                            {j.error_code}: {j.error_message}
                          </p>
                        )}
                        {["failed", "interrupted", "cancelled"].includes(
                          j.state,
                        ) &&
                          ["analyze", "validate_asset"].includes(j.kind) && (
                            <button
                              disabled={!!active}
                              onClick={() => retry(j)}
                            >
                              Thử lại job
                            </button>
                          )}
                      </div>
                    ))}
                  </details>
                )}
              </section>
              <section className="document-pane" aria-label="Tài liệu">
                <div className="pane-heading">
                  <span className="section-number">02 / Tài liệu</span>
                  <span
                    role="status"
                    className={conflict ? "warning-text" : "muted"}
                  >
                    {doc
                      ? `${saveState} · Revision ${doc.revision.revision_number}`
                      : "Chưa có bản nháp"}
                  </span>
                </div>
                {doc ? (
                  <>
                    <div className="document-toolbar">
                      <div>
                        <button
                          aria-pressed={editor}
                          onClick={() => setEditor(!editor)}
                        >
                          Markdown
                        </button>
                        <button
                          aria-pressed={preview}
                          onClick={() => setPreview(!preview)}
                        >
                          Xem trước
                        </button>
                      </div>
                      <button
                        onClick={async () => {
                          try {
                            setHistory(
                              (await api(`/documents/${doc.id}/revisions`))
                                .items,
                            );
                          } catch (err) {
                            report(err);
                          }
                        }}
                      >
                        Lịch sử revision
                      </button>
                    </div>
                    {conflict && (
                      <div className="notice warning" role="alert">
                        <div>
                          <strong>Xung đột với bản đã lưu ở tab khác.</strong>
                          <p>
                            Bản local vẫn ở editor. Sao chép trước khi tải bản
                            mới.
                          </p>
                          <button
                            onClick={() =>
                              navigator.clipboard
                                .writeText(text)
                                .then(() =>
                                  setMessage("Đã sao chép bản local."),
                                )
                                .catch(report)
                            }
                          >
                            Sao chép bản local
                          </button>{" "}
                          <button
                            onClick={() =>
                              loadDocument(detail.id, true).catch(report)
                            }
                          >
                            Tải bản đã lưu
                          </button>
                        </div>
                      </div>
                    )}
                    <div
                      className={`editor-area ${editor && preview ? "split" : ""}`}
                    >
                      {editor && (
                        <label className="editor-label">
                          <span className="sr-only">Nội dung Markdown</span>
                          <textarea
                            aria-label="Nội dung Markdown"
                            spellCheck={false}
                            value={text}
                            onChange={(e) => {
                              setText(e.target.value);
                              textRef.current = e.target.value;
                              dirty.current = true;
                              setSaveState("Chờ lưu…");
                            }}
                          />
                        </label>
                      )}
                      {preview && (
                        <Markdown
                          text={text}
                          onSeek={seek}
                          onImage={setImage}
                        />
                      )}
                    </div>
                    {!editor && !preview && (
                      <p className="empty-editor">
                        Bật Markdown hoặc Xem trước để đọc tài liệu.
                      </p>
                    )}
                    {saveState === "Lưu thất bại" && !conflict && (
                      <button onClick={save}>Thử lưu lại</button>
                    )}
                    <div className="export-bar">
                      <div>
                        <h3>Xuất bản đã lưu</h3>
                        <p className="muted">
                          Markdown riêng không mang theo ảnh. Chọn ZIP để có đủ
                          tài liệu và ảnh.
                        </p>
                      </div>
                      <div className="export-actions">
                        {["md", "zip", "pdf"].map((fmt) => (
                          <div key={fmt}>
                            <button
                              disabled={
                                exports[fmt]?.state === "running" ||
                                dirty.current ||
                                conflict
                              }
                              onClick={() => exportFile(fmt)}
                            >
                              {exports[fmt]?.state === "running"
                                ? "Đang xuất…"
                                : `Xuất .${fmt}`}
                            </button>
                            {exports[fmt]?.url && (
                              <a
                                href={exports[fmt].url}
                                download={`document.${fmt}`}
                              >
                                Tải .{fmt}
                              </a>
                            )}
                            {exports[fmt]?.error && (
                              <p className="warning-text" role="alert">
                                {exports[fmt].error}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                    {generations.length > 0 && (
                      <details className="generations">
                        <summary>
                          Các bản generation ({generations.length})
                        </summary>
                        {generations.map((g) => (
                          <div className="generation-row" key={g.id}>
                            <span>
                              {date(g.created_at)} ·{" "}
                              {phaseText[g.quality_status] ??
                                "Đang hoàn thiện generation"}
                            </span>
                            <button
                              onClick={() =>
                                api<GenerationDetail>(`/generations/${g.id}`)
                                  .then((value) => {
                                    if (currentProject.current === detail.id)
                                      setGeneration(value);
                                  })
                                  .catch(report)
                              }
                            >
                              Xem bước nguồn
                            </button>
                            <button
                              disabled={
                                dirty.current ||
                                !["succeeded", "needs_review"].includes(
                                  g.quality_status,
                                ) ||
                                g.id === doc.revision.generation_id
                              }
                              onClick={() => applyGeneration(g.id)}
                            >
                              Áp dụng bản này
                            </button>
                          </div>
                        ))}
                      </details>
                    )}
                  </>
                ) : (
                  <div className="document-empty">
                    <div className="page-outline" aria-hidden="true">
                      Aa
                    </div>
                    <h2>Tài liệu bắt đầu từ video của bạn.</h2>
                    <p>
                      {stopped
                        ? "Chưa có tài liệu vì video không được nhận là video hướng dẫn. Xem lý do ở phía trên."
                        : active
                          ? "Worker đang xử lý. Bạn có thể rời trang và mở lại dự án để xem tiến độ."
                          : "Sau khi video qua kiểm tra, xác nhận gửi phân tích và bấm Tạo tài liệu."}
                    </p>
                    <p className="muted">
                      Bản nháp sẽ có các bước, mốc thời gian và ảnh thật từ
                      nguồn. Nội dung chưa chắc chắn được đánh dấu để kiểm tra.
                    </p>
                  </div>
                )}
              </section>
            </div>
          </>
        )}
        <footer>
          Video và bản sửa lưu local · Nội dung gửi Google khi tạo tài liệu ·
          Luôn kiểm tra ảnh, định lượng và lệnh trước khi sử dụng
        </footer>
      </main>
      {deleteOpen && (
        <Dialog title="Xóa dự án này?" onClose={() => setDeleteOpen(false)}>
          <p>
            Thao tác xóa video, tài liệu và ảnh local. Job đang chạy sẽ bị hủy
            trước khi dọn file. Cleanup Google được theo dõi riêng.
          </p>
          <div className="dialog-actions">
            <button onClick={() => setDeleteOpen(false)}>Giữ dự án</button>
            <button className="danger" onClick={deleteProject} disabled={busy}>
              Xóa dữ liệu dự án
            </button>
          </div>
        </Dialog>
      )}
      {rename && (
        <Dialog title="Thông tin dự án" onClose={() => setRename(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api(`/projects/${detail!.id}`, "PATCH", {
                  name,
                  output_language: language,
                });
                setRename(false);
                await refresh(detail!.id);
                await list();
              } catch (err) {
                report(err);
              }
            }}
          >
            <label>
              Tên dự án
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
                required
              />
            </label>
            <label>
              Ngôn ngữ cho generation tiếp theo
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value as "vi" | "en")}
              >
                <option value="vi">Tiếng Việt</option>
                <option value="en">English</option>
              </select>
            </label>
            <button className="primary" type="submit">
              Lưu thông tin
            </button>
          </form>
        </Dialog>
      )}
      {history && (
        <Dialog title="Lịch sử revision" onClose={() => setHistory(null)}>
          <p>Khôi phục sẽ tạo revision mới và giữ nguyên lịch sử.</p>
          {history.map((r) => (
            <div className="history-row" key={r.id}>
              <span>
                Revision {r.revision_number} · {r.source}
                <small>{date(r.created_at)}</small>
              </span>
              <button
                disabled={r.id === revisionRef.current || dirty.current}
                onClick={() => restore(r.id)}
              >
                Khôi phục
              </button>
            </div>
          ))}
        </Dialog>
      )}
      {image && (
        <Dialog title="Ảnh minh chứng từ video" onClose={() => setImage(null)}>
          <img
            className="full-image"
            src={image}
            alt="Ảnh trích thực từ video nguồn"
          />
          <p className="muted">
            Ảnh nguồn chưa được xác nhận bằng mắt. Kiểm tra secret hoặc dữ liệu
            cá nhân trước khi xuất.
          </p>
        </Dialog>
      )}
      {frameStep && (
        <Dialog
          title="Chọn lại ảnh bằng timestamp"
          onClose={() => setFrameStep(null)}
        >
          <p>
            Chọn mốc trên player rồi nhập số giây. FFmpeg trích từ video, không
            gọi AI.
          </p>
          <label>
            Timestamp (giây)
            <input
              type="number"
              min="0"
              max={(asset?.duration_sec ?? 1) - 0.001}
              step="0.001"
              value={frameTime}
              onChange={(e) => setFrameTime(e.target.value)}
            />
          </label>
          <div className="dialog-actions">
            <button onClick={() => seek(Number(frameTime))}>
              Xem mốc trên video
            </button>
            <button className="primary" onClick={replaceFrame}>
              Áp dụng ảnh vào revision mới
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
