/**
 * api.ts — Centralized API client for the FastAPI backend.
 */
import { firebaseAuth } from "./firebase";

const BASE_URL = import.meta.env.VITE_API_URL || "";

async function request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const user = firebaseAuth?.currentUser;
  if (user) headers.set("Authorization", `Bearer ${await user.getIdToken()}`);
  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const requestId = res.headers.get("x-request-id");
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
    throw new Error(requestId && res.status >= 500 ? `${detail} (Reference: ${requestId})` : detail);
  }
  return res.json();
}

export interface CurrentUserProfile {
  uid: string;
  email: string;
  can_manage_documents: boolean;
}

export async function getCurrentUser() {
  return request<CurrentUserProfile>("/api/auth/me");
}

// ─── RAG ─────────────────────────────────────────────────────

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("files", file);
  return request<{ results: Array<{ filename: string; status: string; reason?: string; pages?: number; chunks?: number }> }>("/api/rag/upload", { method: "POST", body: form });
}

export async function uploadDocuments(files: File[]) {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  return request<{ results: Array<{ filename: string; status: string; reason?: string; pages?: number; chunks?: number }> }>("/api/rag/upload", { method: "POST", body: form });
}

export interface UploadedDocument {
  filename: string;
  status: "ingested" | "skipped" | "stored";
  pages: number | null;
  chunks: number | null;
  reason: string | null;
  size_bytes: number;
  uploaded_at: string;
}

export async function listUploads() {
  return request<{ uploads: UploadedDocument[] }>("/api/rag/uploads");
}

export async function askQuestion(query: string, retrieverType: string = "similarity") {
  return request<{ answer: string }>("/api/rag/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, retriever_type: retrieverType }),
  });
}

export async function triggerGcsIngestion() {
  return request<{ status: string }>("/api/rag/ingest-gcs", { method: "POST" });
}

// ─── Agent ───────────────────────────────────────────────────

export async function runAudit(requestText: string) {
  return request<{
    risk_result: string;
    tax_result: string;
    control_result: string;
    cfo_memo: string;
  }>("/api/agent/audit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_text: requestText }),
  });
}

// ─── Health ──────────────────────────────────────────────────

export async function healthCheck() {
  return request("/api/health");
}

export interface SystemStatus {
  backend?: {
    status: string;
    uptime: string;
    python_version: string;
    platform: string;
    app_mode?: string;
    vector_store?: string;
  };
  gcp?: { project_id: string; region: string };
  storage?: { gcs_bucket: string; gcs_prefix: string; local_data_dir?: string };
  vector_search?: { index_id: string; endpoint_id: string; stream_update: boolean };
  models?: { embedding: string; llm: string; llm_framework: string };
  ingestion?: { uploads_this_session: number };
}

export async function getSystemStatus() {
  return request<SystemStatus>("/api/status");
}
