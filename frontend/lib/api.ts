export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}${path}`,
    options
  );

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const b = body as { detail?: string; message?: string };
    throw new Error(
      b.detail ?? b.message ?? `Request failed: ${res.status}`
    );
  }

  return res.json();
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
