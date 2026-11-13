/**
 * Domain-agnostic API Origin Resolver for Dual-Publishing (Cloud Run + GKE Autopilot).
 *
 * - On local development (`localhost` / `127.0.0.1`): uses `NEXT_PUBLIC_API_URL` or `http://localhost:8000`.
 * - On Google Cloud Run (`*.run.app`, where frontend and backend are separate origins): uses `NEXT_PUBLIC_API_URL`.
 * - On GKE Autopilot / Custom Domain Ingress (where `/api`, `/ws`, and `/health` route on the same host as `/`):
 *   automatically returns `window.location.origin` with zero hardcoded domain names.
 */
export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const isLocal = host === "localhost" || host === "127.0.0.1";
    const isCloudRunDefault = host.endsWith(".run.app");
    if (
      process.env.NEXT_PUBLIC_FORCE_API_URL !== "true" &&
      !isLocal &&
      !isCloudRunDefault
    ) {
      return window.location.origin;
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}
