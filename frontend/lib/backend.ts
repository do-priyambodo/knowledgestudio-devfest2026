export function resolveBackendOrigin(): string {
  const configured =
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://127.0.0.1:8080";
  return configured.replace(/\/+$/, "");
}

export function buildBackendHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const key = process.env.AGENT_API_KEY?.trim();
  if (key) {
    headers["X-API-Key"] = key;
  }
  return headers;
}
