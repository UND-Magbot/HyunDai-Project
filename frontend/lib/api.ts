export async function apiFetch(path: string) {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}${path}`
  );
  return res.json();
}
