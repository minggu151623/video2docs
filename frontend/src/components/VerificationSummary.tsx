import type { GenerationDetail } from "../types/app";
import { asrText, domainLabel, ocrText, summarize } from "../lib/verification";

const statusText: Record<string, string> = {
  succeeded: "Hoàn tất",
  needs_review: "Cần kiểm tra",
};

export function StepBadge({ count }: { count: number }) {
  if (!count) return null;
  return (
    <span className="verify-badge pending">{count} mục chưa kiểm chứng</span>
  );
}

export default function VerificationSummary({
  generation,
  onlyPending,
  onOnlyPending,
  onVerify,
  verifying,
  blocked,
  notice,
}: {
  generation: GenerationDetail;
  onlyPending: boolean;
  onOnlyPending: (value: boolean) => void;
  onVerify: () => void;
  verifying: boolean;
  blocked: boolean;
  notice: { kind: "error" | "info"; text: string } | null;
}) {
  const report = generation.verification;
  const sum = report ? summarize(report) : null;
  const degraded =
    report &&
    (report.asr_status === "failed" || report.ocr_status === "failed");
  return (
    <div className="verify-summary">
      <div className="verify-row">
        <span className="chip" title="Lĩnh vực nhận diện từ video">
          Lĩnh vực: {domainLabel(generation.draft.domain)}
        </span>
        <span className="chip">
          Trạng thái tài liệu:{" "}
          {statusText[generation.quality_status] ?? generation.quality_status}
        </span>
      </div>
      {report && sum ? (
        <>
          <p className="verify-count">
            {sum.total
              ? `${sum.verified}/${sum.total} mục đã kiểm chứng`
              : "Không có mục nào cần kiểm chứng"}
            {sum.quoteMatched > 0 &&
              ` · ${sum.quoteMatched} mục chỉ khớp nguyên văn, câu diễn giải chưa kiểm chứng`}
            {sum.notCheckable > 0 &&
              ` · ${sum.notCheckable} mục không có văn bản để đối chiếu`}
          </p>
          <p className="muted verify-engines">
            {asrText(report)} · {ocrText(report)}
          </p>
          {degraded && (
            <p className="review-label" role="note">
              Kiểm chứng bị giảm do lỗi ASR/OCR; các mục liên quan được ghi là
              chưa kiểm chứng. Bấm Kiểm chứng lại để thử lần nữa.
            </p>
          )}
        </>
      ) : (
        <p className="muted verify-count">Chưa có kết quả kiểm chứng.</p>
      )}
      <div className="verify-row">
        <label className="checkbox verify-filter">
          <input
            type="checkbox"
            checked={onlyPending && !!report}
            disabled={!report}
            onChange={(e) => onOnlyPending(e.target.checked)}
          />
          Chỉ hiện mục chưa kiểm chứng
        </label>
        <button onClick={onVerify} disabled={verifying || blocked}>
          {verifying ? "Đang kiểm chứng…" : "Kiểm chứng lại"}
        </button>
      </div>
      {notice && (
        <p
          className={notice.kind === "error" ? "review-label" : "muted"}
          role={notice.kind === "error" ? "alert" : "status"}
        >
          {notice.text}
        </p>
      )}
    </div>
  );
}
