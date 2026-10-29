import React, { useState, useRef, useCallback, useEffect } from "react";
import {
  Upload,
  FileText,
  X,
  CheckCircle,
  AlertTriangle,
  XCircle,
  CloudUpload,
  HardDrive,
  Loader2,
  Play,
  Trash2,
  Database,
  RefreshCw,
} from "lucide-react";
import { getSystemStatus, listUploads, uploadDocument, triggerGcsIngestion, type UploadedDocument } from "@/lib/api";

function formatBytes(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

type FileStatus =
  | { state: "idle" }
  | { state: "uploading" }
  | { state: "done"; pages: number; chunks: number }
  | { state: "skipped"; reason: string }
  | { state: "error"; reason: string };

interface StagedFile {
  file: File;
  status: FileStatus;
}

type IngestionTab = "local" | "cloud";

export default function DocumentUploadTab() {
  const [activeTab, setActiveTab] = useState<IngestionTab>("local");
  const [dragActive, setDragActive] = useState(false);
  const [stagedFiles, setStagedFiles] = useState<StagedFile[]>([]);
  const [gcsLoading, setGcsLoading] = useState(false);
  const [gcsResult, setGcsResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [storedDocuments, setStoredDocuments] = useState<UploadedDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [storageTarget, setStorageTarget] = useState<string | null>(null);
  const [storageConfigError, setStorageConfigError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshStoredDocuments = useCallback(async () => {
    setDocumentsLoading(true);
    try {
      const response = await listUploads();
      setStoredDocuments(response.uploads);
      setDocumentsError(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setDocumentsError(message);
    } finally {
      setDocumentsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshStoredDocuments();
    void getSystemStatus()
      .then((status) => {
        const bucket = status.storage?.gcs_bucket;
        const prefix = status.storage?.gcs_prefix ?? "";
        const localUploadDir = status.storage?.local_data_dir
          ? `${status.storage.local_data_dir}/uploads`
          : null;
        setStorageTarget(
          bucket ? `gs://${bucket}/${prefix}` : localUploadDir ?? "Not configured",
        );
        setStorageConfigError(null);
      })
      .catch((err: unknown) => {
        setStorageConfigError(err instanceof Error ? err.message : "Unknown error");
      });
  }, [refreshStoredDocuments]);

  const isAnyUploading = stagedFiles.some((f) => f.status.state === "uploading");
  const hasIdle = stagedFiles.some((f) => f.status.state === "idle");
  const allDone = stagedFiles.length > 0 && stagedFiles.every((f) => f.status.state !== "idle" && f.status.state !== "uploading");

  const addFiles = useCallback((incoming: FileList | null) => {
    if (!incoming) return;
    const pdfs = Array.from(incoming).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    setStagedFiles((prev) => {
      const existing = new Set(prev.map((f) => f.file.name));
      const fresh: StagedFile[] = pdfs
        .filter((f) => !existing.has(f.name))
        .map((f) => ({ file: f, status: { state: "idle" } }));
      return [...prev, ...fresh];
    });
  }, []);

  const removeFile = (name: string) =>
    setStagedFiles((prev) => prev.filter((f) => f.file.name !== name));

  const clearAll = () => setStagedFiles([]);

  const setFileStatus = (name: string, status: FileStatus) =>
    setStagedFiles((prev) =>
      prev.map((f) => (f.file.name === name ? { ...f, status } : f))
    );

  const handleIngest = async () => {
    const idleFiles = stagedFiles.filter((f) => f.status.state === "idle");
    for (const staged of idleFiles) {
      setFileStatus(staged.file.name, { state: "uploading" });
      try {
        const res = await uploadDocument(staged.file);
        const result = res.results?.[0];
        if (!result) {
          setFileStatus(staged.file.name, { state: "error", reason: "No response from server." });
          continue;
        }
        if (result.status === "ingested") {
          setFileStatus(staged.file.name, {
            state: "done",
            pages: result.pages ?? 0,
            chunks: result.chunks ?? 0,
          });
        } else if (result.status === "skipped") {
          setFileStatus(staged.file.name, {
            state: "skipped",
            reason: result.reason ?? "No extractable text.",
          });
        } else {
          setFileStatus(staged.file.name, { state: "error", reason: "Unknown status." });
        }
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Unknown error";
        setFileStatus(staged.file.name, { state: "error", reason: message });
      }
    }
    await refreshStoredDocuments();
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    addFiles(e.dataTransfer.files);
  };

  const handleGCSIngest = async () => {
    setGcsLoading(true);
    setGcsResult(null);
    try {
      const data = await triggerGcsIngestion();
      setGcsResult({ ok: true, message: data.status });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setGcsResult({ ok: false, message });
    } finally {
      setGcsLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto animate-fade-in space-y-6">
      {/* Header & Tabs */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold font-heading text-card-foreground">Document Ingestion</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Populate the Aldermoor procurement knowledge base — supplier contracts, tariff schedules, IFRS reports, and compliance policies.
          </p>
        </div>

        <div className="flex bg-muted/50 p-1 rounded-xl border border-border w-fit">
          <button
            onClick={() => setActiveTab("local")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === "local"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Upload className="w-4 h-4" />
            Local Files
          </button>
          <button
            onClick={() => setActiveTab("cloud")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === "cloud"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Database className="w-4 h-4" />
            Cloud Storage
          </button>
        </div>
      </div>

      <div className="relative">
        {activeTab === "local" ? (
          <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              <div className="p-6">
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={onDrop}
                  onClick={() => fileRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all
                    ${dragActive ? "border-primary bg-primary/5 scale-[0.99]" : "border-border hover:border-primary/30 hover:bg-muted/30"}`}
                >
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".pdf"
                    multiple
                    className="hidden"
                    onChange={(e) => addFiles(e.target.files)}
                  />
                  <div className="flex flex-col items-center gap-4">
                    <div className={`w-14 h-14 rounded-full flex items-center justify-center transition-colors ${dragActive ? "bg-primary/20" : "bg-muted"}`}>
                      <CloudUpload className={`w-7 h-7 ${dragActive ? "text-primary" : "text-muted-foreground"}`} />
                    </div>
                    <div>
                      <p className="text-base font-semibold text-card-foreground">Choose files or drag and drop</p>
                      <p className="text-sm text-muted-foreground mt-1">PDF documents only · Server-enforced file, request, and page limits</p>
                    </div>
                  </div>
                </div>

                {/* Staged file list */}
                {stagedFiles.length > 0 && (
                  <div className="mt-8 space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground/70 flex items-center gap-2">
                        Queue <span className="w-5 h-5 flex items-center justify-center bg-muted rounded-full text-[10px] text-foreground font-extrabold">{stagedFiles.length}</span>
                      </h3>
                      {!isAnyUploading && (
                        <button
                          onClick={clearAll}
                          className="text-xs font-medium text-muted-foreground hover:text-destructive flex items-center gap-1.5 transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" /> Clear all
                        </button>
                      )}
                    </div>

                    <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2 scrollbar-thin">
                      {stagedFiles.map(({ file, status }) => (
                        <div
                          key={file.name}
                          className={`flex items-center gap-3 p-4 rounded-xl border transition-all duration-300
                            ${status.state === "done"    ? "border-success/30 bg-success/5"
                            : status.state === "error"   ? "border-destructive/30 bg-destructive/5"
                            : status.state === "skipped" ? "border-amber-500/30 bg-amber-500/5"
                            : status.state === "uploading"? "border-primary/30 bg-primary/5 shadow-inner"
                            : "border-border bg-card hover:bg-muted/20"}`}
                        >
                          <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 transition-colors
                            ${status.state === "done" ? "bg-success/10" : status.state === "error" ? "bg-destructive/10" : "bg-muted"}`}>
                            {status.state === "idle"      && <FileText className="w-5 h-5 text-muted-foreground" />}
                            {status.state === "uploading" && <Loader2 className="w-5 h-5 text-primary animate-spin" />}
                            {status.state === "done"      && <CheckCircle className="w-5 h-5 text-success" />}
                            {status.state === "skipped"   && <AlertTriangle className="w-5 h-5 text-amber-500" />}
                            {status.state === "error"     && <XCircle className="w-5 h-5 text-destructive" />}
                          </div>

                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold text-card-foreground truncate">{file.name}</p>
                            <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2">
                              {status.state === "idle" && formatBytes(file.size)}
                              {status.state === "uploading" && "Analyzing & indexing…"}
                              {status.state === "done" && (
                                <>
                                  <span className="text-success">{status.pages} pages</span>
                                  <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                                  <span className="text-success">{status.chunks} chunks indexed</span>
                                </>
                              )}
                              {status.state === "skipped" && <span className="text-amber-600">{status.reason}</span>}
                              {status.state === "error" && <span className="text-destructive font-medium">{status.reason}</span>}
                            </p>
                          </div>

                          <div className="shrink-0 flex items-center gap-3">
                            <span className={`text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-md
                              ${status.state === "idle"      ? "bg-muted text-muted-foreground"
                              : status.state === "uploading" ? "bg-primary/20 text-primary"
                              : status.state === "done"      ? "bg-success/20 text-success"
                              : status.state === "skipped"   ? "bg-amber-500/20 text-amber-600"
                              : "bg-destructive/20 text-destructive"}`}>
                              {status.state === "uploading" ? "running" : status.state}
                            </span>
                            {status.state === "idle" && !isAnyUploading && (
                              <button
                                onClick={() => removeFile(file.name)}
                                className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-all"
                              >
                                <X className="w-4 h-4" />
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>

                    {hasIdle && (
                      <button
                        onClick={handleIngest}
                        disabled={isAnyUploading}
                        className="w-full relative group flex items-center justify-center gap-2.5 px-6 py-4 rounded-xl bg-primary text-primary-foreground text-sm font-bold transition-all hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed shadow-xl shadow-primary/20 overflow-hidden"
                      >
                        <div className="absolute inset-0 bg-white/10 translate-y-full group-hover:translate-y-0 transition-transform" />
                        {isAnyUploading ? (
                          <><Loader2 className="w-5 h-5 animate-spin" /> Batch Processing {stagedFiles.filter(f => f.status.state === "uploading").length} / {stagedFiles.length}…</>
                        ) : (
                          <><Play className="w-5 h-5 fill-current" /> Initialize Ingestion ({stagedFiles.filter(f => f.status.state === "idle").length} Files)</>
                        )}
                      </button>
                    )}

                    {allDone && !hasIdle && (
                      <div className="p-4 rounded-xl bg-success/10 border border-success/30 text-sm text-success font-semibold flex items-center gap-3 animate-in fade-in zoom-in-95 duration-500">
                        <div className="w-8 h-8 rounded-full bg-success/20 flex items-center justify-center shrink-0">
                          <CheckCircle className="w-5 h-5" />
                        </div>
                        All files processed. Aldermoor knowledge base updated.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <section className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              <div className="flex items-center justify-between gap-4 border-b border-border px-6 py-4">
                <div>
                  <h3 className="text-sm font-bold uppercase tracking-wider text-card-foreground">
                    Stored documents
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    PDFs saved in configured storage, including documents from previous sessions.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-semibold text-foreground">
                    {storedDocuments.length}
                  </span>
                  <button
                    type="button"
                    onClick={() => void refreshStoredDocuments()}
                    disabled={documentsLoading}
                    aria-label="Refresh stored documents"
                    className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                  >
                    <RefreshCw className={`h-4 w-4 ${documentsLoading ? "animate-spin" : ""}`} />
                  </button>
                </div>
              </div>

              <div className="divide-y divide-border/70">
                {documentsError && (
                  <p role="alert" className="px-6 py-4 text-sm text-destructive">
                    Could not load stored documents: {documentsError}
                  </p>
                )}
                {documentsLoading && storedDocuments.length === 0 && (
                  <p className="px-6 py-5 text-sm text-muted-foreground">Loading saved documents…</p>
                )}
                {!documentsLoading && !documentsError && storedDocuments.length === 0 && (
                  <p className="px-6 py-5 text-sm text-muted-foreground">
                    No documents have been saved yet. Upload a PDF above to index it.
                  </p>
                )}
                {storedDocuments.map((document) => (
                  <div
                    key={document.filename}
                    className="flex flex-col gap-2 px-6 py-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <FileText className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-card-foreground">
                          {document.filename}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {formatBytes(document.size_bytes)} ·{" "}
                          {new Date(document.uploaded_at).toLocaleString()}
                        </p>
                        {document.reason && (
                          <p className="mt-1 text-xs text-amber-600">{document.reason}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3 pl-8 sm:pl-0">
                      <span className="text-xs text-muted-foreground">
                        {document.pages !== null && document.chunks !== null
                          ? `${document.pages} pages · ${document.chunks} chunks`
                          : "Ingestion details unavailable"}
                      </span>
                      <span className={`rounded-md px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest ${
                        document.status === "ingested"
                          ? "bg-success/20 text-success"
                          : document.status === "skipped"
                            ? "bg-amber-500/20 text-amber-600"
                            : "bg-muted text-muted-foreground"
                      }`}>
                        {document.status === "stored" ? "Saved" : document.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        ) : (
          <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
              <div className="p-8">
                <div className="flex items-start gap-5 mb-8">
                  <div className="w-14 h-14 rounded-2xl bg-secondary/50 flex items-center justify-center shrink-0">
                    <Database className="w-7 h-7 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold font-heading text-card-foreground">Cloud Sync</h3>
                    <p className="text-sm text-muted-foreground mt-1 max-w-lg">
                      Synchronize the vector index with documents already in the GCS bucket.
                      Re-scans the bucket and indexes any new procurement documents.
                    </p>
                  </div>
                </div>

                <div className="p-6 rounded-xl bg-muted/40 border border-border/50 mb-8 divide-y divide-border/50">
                  <div className="pb-4">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Target Directory</p>
                    <p className="text-sm font-mono text-card-foreground">
                      {storageTarget ?? "Loading storage configuration…"}
                    </p>
                    {storageConfigError && (
                      <p role="alert" className="mt-1 text-xs text-destructive">
                        Could not load storage configuration: {storageConfigError}
                      </p>
                    )}
                  </div>
                  <div className="pt-4 pb-4">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Processing Mode</p>
                    <p className="text-sm font-medium text-card-foreground">Delta Sync (Stream Update: Enabled)</p>
                  </div>
                  <div className="pt-4">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Estimated Capacity</p>
                    <p className="text-sm font-medium text-card-foreground">Up to 10k documents / shard</p>
                  </div>
                </div>

                <button
                  className={`w-full flex items-center justify-center gap-3 px-6 py-4 rounded-xl text-sm font-bold transition-all shadow-lg
                    ${gcsLoading 
                      ? "bg-secondary text-secondary-foreground cursor-not-allowed opacity-80" 
                      : "bg-secondary text-secondary-foreground hover:bg-secondary/80 hover:scale-[1.01] active:scale-[0.99] shadow-secondary/10"}`}
                  disabled={gcsLoading}
                  onClick={handleGCSIngest}
                >
                  {gcsLoading ? (
                    <><Loader2 className="w-5 h-5 animate-spin" /> Synchronizing Repository…</>
                  ) : (
                    <><HardDrive className="w-5 h-5" /> Start Global GCS Ingestion</>
                  )}
                </button>

                {gcsResult && (
                  <div className={`mt-6 p-4 rounded-xl text-sm font-semibold flex items-center gap-3 animate-in fade-in zoom-in-95
                    ${gcsResult.ok ? "bg-success/10 border border-success/30 text-success" : "bg-destructive/10 border border-destructive/30 text-destructive"}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 
                      ${gcsResult.ok ? "bg-success/20" : "bg-destructive/20"}`}>
                      {gcsResult.ok ? <CheckCircle className="w-5 h-5" /> : <XCircle className="w-5 h-5 text-destructive" />}
                    </div>
                    {gcsResult.message}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
