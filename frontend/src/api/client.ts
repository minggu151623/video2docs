let csrf = "";
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function bootstrap() {
  const response = await fetch("/api/v1/session", {
    credentials: "same-origin",
  });
  if (!response.ok)
    throw new Error("Không mở được phiên local. Hãy tải lại trang.");
  csrf = (await response.json()).csrf_token;
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(
      error.error?.code ?? "HTTP_ERROR",
      error.error?.message ?? "Không kết nối được backend.",
      response.status,
    );
  }
  return response.json();
}
export function upload(
  projectId: string,
  file: File,
  progress: (n: number) => void,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/projects/${projectId}/assets`);
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        progress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      const data = JSON.parse(xhr.responseText);
      xhr.status < 300
        ? resolve(data)
        : reject(
            new ApiError(
              data.error?.code,
              data.error?.message ?? "Upload thất bại.",
              xhr.status,
            ),
          );
    };
    xhr.onerror = () => reject(new Error("Mất kết nối khi upload."));
    const data = new FormData();
    data.append("file", file);
    xhr.send(data);
  });
}
