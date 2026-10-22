import { useState } from "react";
import Dialog from "./Dialog";

export default function NotTutorialNotice({
  reason,
  busy,
  providerReady,
  initialBudget,
  onAnalyze,
}: {
  reason: string | null;
  busy: boolean;
  providerReady: boolean;
  initialBudget: string;
  onAnalyze: (budgetUsd: number) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false),
    [consent, setConsent] = useState(false),
    [cost, setCost] = useState(false),
    [budget, setBudget] = useState(initialBudget);
  const close = () => {
    setOpen(false);
    setConsent(false);
    setCost(false);
  };
  return (
    <section
      className="not-tutorial"
      aria-label="Video không phải video hướng dẫn"
    >
      <h2>Video này không được nhận là video hướng dẫn</h2>
      <p>Lý do: {reason ?? "Mô hình không nêu lý do."}</p>
      <p className="muted">
        Quá trình đã dừng sau đoạn đầu để tránh tốn chi phí cho các đoạn sau.
        Chưa có tài liệu nào được tạo từ lần chạy này.
      </p>
      <button
        className="primary"
        onClick={() => setOpen(true)}
        disabled={busy || !providerReady}
      >
        Vẫn phân tích toàn bộ
      </button>
      {open && (
        <Dialog title="Phân tích toàn bộ video?" onClose={close}>
          <p>
            Đoạn đầu không giống video hướng dẫn. Nếu tiếp tục, toàn bộ video
            được gửi lại tới provider để phân tích. Chi phí chưa thể ước tính và
            request đã gửi có thể phát sinh phí thêm kể cả khi bạn hủy local.
            Kết quả có thể không phải là một tài liệu hướng dẫn. Tiếp tục?
          </p>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            Gửi lại video này tới provider để phân tích toàn bộ.
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={cost}
              onChange={(e) => setCost(e.target.checked)}
            />
            Chấp nhận có thể tính phí thêm, chưa xác định trước.
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
          <div className="dialog-actions">
            <button onClick={close}>Giữ nguyên</button>
            <button
              className="primary"
              disabled={busy || !consent || !cost || Number(budget) <= 0}
              onClick={async () => {
                if (await onAnalyze(Number(budget))) close();
              }}
            >
              Xác nhận phân tích toàn bộ
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
