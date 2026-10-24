import type { Domain } from "../types/tutorial";
import type { JobWarning, Verification, VerificationItem } from "../types/app";

export const domainText: Record<Domain, string> = {
  software: "Phần mềm",
  cooking: "Nấu ăn",
  repair: "Sửa chữa",
  craft: "Thủ công",
  fitness: "Thể thao",
  beauty: "Làm đẹp",
  gardening: "Làm vườn",
  music: "Âm nhạc",
  other: "Khác",
};
export const domainLabel = (domain: string) =>
  domainText[domain as Domain] ?? domainText.other;

/** A quote_matched claim still needs a person: only its quote was found (ruling P2). */
const needsCheck = (item: VerificationItem) =>
  item.status === "unverified" ||
  item.status === "not_checked" ||
  item.status === "quote_matched";

export function summarize(verification: Verification) {
  const items = Object.values(verification.items);
  const checkable = items.filter((i) => i.status !== "not_checkable");
  return {
    verified: checkable.filter((i) => i.status === "verified").length,
    quoteMatched: checkable.filter((i) => i.status === "quote_matched").length,
    total: checkable.length,
    notCheckable: items.length - checkable.length,
  };
}

/** Unverified, not-checked or quote-matched items of step `index`; 0 when there is no report. */
export function pendingInStep(
  verification: Verification | null,
  index: number,
): number {
  if (!verification) return 0;
  const prefix = `steps/${index}/`;
  return Object.entries(verification.items).filter(
    ([path, item]) => path.startsWith(prefix) && needsCheck(item),
  ).length;
}

export function warningCode(warning: JobWarning): string {
  return typeof warning === "string" ? warning : String(warning?.code ?? "");
}

const engineText = (name: string, status: string, error: string | null) =>
  status === "failed"
    ? `${name} lỗi${error ? ` (${error})` : ""}`
    : status === "skipped"
      ? `${name} không chạy`
      : `${name} đã chạy`;
export const asrText = (v: Verification) =>
  engineText("ASR", v.asr_status, v.asr_error);
export const ocrText = (v: Verification) =>
  engineText("OCR", v.ocr_status, v.ocr_error);

/** Vietnamese lines for job warnings; unknown codes collapse into one line. */
export function warningLines(warnings: JobWarning[] | null | undefined) {
  const lines: string[] = [],
    other = new Set<string>();
  for (const warning of warnings ?? []) {
    const code = warningCode(warning);
    const data: Record<string, unknown> =
      typeof warning === "string" ? {} : warning;
    if (code === "NOT_TUTORIAL")
      lines.push(`Video không giống video hướng dẫn: ${data.reason ?? ""}`);
    else if (code === "LATER_CLIP_NOT_TUTORIAL")
      lines.push(
        `Đoạn ${data.clip_index ?? "?"} không giống hướng dẫn; đã ghi nhận và vẫn tiếp tục.`,
      );
    else if (code === "VERIFICATION_DEGRADED") {
      const part = (name: string, status: unknown, error: unknown) =>
        `${name} ${status === "failed" ? "lỗi" : status === "ok" ? "đã chạy" : "không chạy"}${error ? ` (${String(error)})` : ""}`;
      lines.push(
        `Kiểm chứng bị giảm: ${part("ASR", data.asr, data.asr_error)}, ${part("OCR", data.ocr, data.ocr_error)}.`,
      );
    } else if (code) other.add(code);
  }
  if (other.size) lines.push(`Cảnh báo khác: ${[...other].join(", ")}`);
  return lines;
}

export function notTutorialReason(warnings: JobWarning[] | null | undefined) {
  for (const warning of warnings ?? [])
    if (warningCode(warning) === "NOT_TUTORIAL" && typeof warning !== "string")
      return typeof warning.reason === "string" ? warning.reason : null;
  return null;
}
