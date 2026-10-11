import { auth } from "@clerk/nextjs/server";

const API = process.env.SENTINEL_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Server-side fetch to the Sentinel API with the caller's Clerk session token. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const session = await auth();
  if (!session.isAuthenticated) return session.redirectToSignIn();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const token = await session.getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (process.env.SENTINEL_AUTH_MODE === "dev" && session.userId) {
    // Local development: an API running AUTH_MODE=dev trusts these headers instead.
    headers.set("x-dev-user", session.userId);
    if (session.orgId) headers.set("x-dev-org", session.orgId);
    if (session.orgRole) headers.set("x-dev-role", session.orgRole);
  }
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError(503, `The Compliance Sentinel API at ${API} is not reachable.`);
  }
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** FastAPI errors look like {"detail": "..."}; fall back to the raw body or status text. */
async function errorDetail(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const { detail } = JSON.parse(text);
    if (typeof detail === "string") return detail;
  } catch {}
  return text || res.statusText;
}

/** True when the API says the resource does not exist (or the id is not even well-formed). */
export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 422);
}

export async function apiRaw(path: string): Promise<Response> {
  const session = await auth();
  if (!session.isAuthenticated) return new Response("Not signed in", { status: 401 });
  const headers = new Headers();
  const token = await session.getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (process.env.SENTINEL_AUTH_MODE === "dev" && session.userId) {
    headers.set("x-dev-user", session.userId);
    if (session.orgId) headers.set("x-dev-org", session.orgId);
    if (session.orgRole) headers.set("x-dev-role", session.orgRole);
  }
  return fetch(`${API}${path}`, { headers, cache: "no-store" });
}

export async function roles() {
  const { has } = await auth();
  const isAdmin = has({ role: "org:admin" });
  return { isAdmin, canApprove: isAdmin || has({ role: "org:auditor" }) };
}
