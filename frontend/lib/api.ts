export class ApiError extends Error {
  errorCode?: string;
  description?: string;
  constructor(message: string, errorCode?: string, description?: string) {
    super(message);
    this.errorCode = errorCode;
    this.description = description;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL}${path}`,
      options
    );
  } catch (err) {
    throw new ApiError("서버에 연결하지 못했습니다.", "NET-001");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const b = body as { detail?: string; message?: string; error_code?: string; description?: string };
    throw new ApiError(
      b.detail ?? b.message ?? `요청에 실패했습니다. (HTTP ${res.status})`,
      b.error_code,
      b.description
    );
  }

  return res.json();
}

export async function apiPost<T = unknown>(
  path: string,
  body?: unknown
): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiPatch<T = unknown>(
  path: string,
  body: unknown
): Promise<T> {
  return apiFetch<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiPut<T = unknown>(
  path: string,
  body: unknown
): Promise<T> {
  return apiFetch<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
