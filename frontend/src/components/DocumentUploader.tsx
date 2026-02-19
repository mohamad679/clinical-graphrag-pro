"use client";

import React, { useState, useCallback } from "react";
import { uploadDocument, getDocuments, deleteDocument, type DocumentInfo } from "@/lib/api";

// ── Icons ───────────────────────────────────────────────

const UploadIcon = () => (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
);

const FileIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
    </svg>
);

const TrashIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="3 6 5 6 21 6" />
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
);

const CheckCircleIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
);

// ── Component ───────────────────────────────────────────

interface DocumentUploaderProps {
    documents: DocumentInfo[];
    onDocumentsChange: () => void;
}

export default function DocumentUploader({ documents, onDocumentsChange }: DocumentUploaderProps) {
    const [dragOver, setDragOver] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState("");
    const [error, setError] = useState("");

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setDragOver(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setDragOver(false);
    }, []);

    const handleDrop = useCallback(
        async (e: React.DragEvent) => {
            e.preventDefault();
            setDragOver(false);
            const files = Array.from(e.dataTransfer.files);
            if (files.length > 0) {
                await handleUpload(files[0]);
            }
        },
        [],
    );

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files;
        if (files && files.length > 0) {
            await handleUpload(files[0]);
        }
        e.target.value = ""; // reset for re-upload
    };

    async function handleUpload(file: File) {
        setError("");
        setUploading(true);
        setUploadProgress(`Uploading ${file.name}...`);

        try {
            const result = await uploadDocument(file);
            setUploadProgress(`✅ ${result.message}`);
            onDocumentsChange();
            setTimeout(() => setUploadProgress(""), 3000);
        } catch (err: any) {
            setError(err.message || "Upload failed");
            setUploadProgress("");
        } finally {
            setUploading(false);
        }
    }

    async function handleDelete(docId: string) {
        try {
            await deleteDocument(docId);
            onDocumentsChange();
        } catch (err: any) {
            setError(err.message || "Delete failed");
        }
    }

    function formatSize(bytes: number): string {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="p-6 border-b" style={{ borderColor: "var(--border)" }}>
                <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
                    Documents
                </h2>
                <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                    Upload medical documents for RAG-powered analysis
                </p>
            </div>

            {/* Drop Zone */}
            <div className="p-6">
                <div
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    className="rounded-xl p-8 text-center cursor-pointer transition-all"
                    style={{
                        border: `2px dashed ${dragOver ? "var(--primary)" : "var(--border)"}`,
                        background: dragOver ? "rgba(99, 102, 241, 0.05)" : "var(--bg-secondary)",
                    }}
                    onClick={() => document.getElementById("file-upload")?.click()}
                >
                    <div
                        className="mx-auto mb-3"
                        style={{ color: dragOver ? "var(--primary)" : "var(--text-tertiary)" }}
                    >
                        <UploadIcon />
                    </div>
                    <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                        {uploading ? uploadProgress : "Drop files here or click to upload"}
                    </p>
                    <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
                        Supports PDF, TXT, MD, CSV — Max 50MB
                    </p>
                    <input
                        id="file-upload"
                        type="file"
                        accept=".pdf,.txt,.md,.csv"
                        onChange={handleFileSelect}
                        className="hidden"
                    />
                </div>

                {/* Upload progress */}
                {uploading && (
                    <div className="mt-3">
                        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-tertiary)" }}>
                            <div
                                className="h-full rounded-full"
                                style={{
                                    background: "linear-gradient(90deg, var(--primary), var(--accent))",
                                    width: "60%",
                                    animation: "pulse-dot 1.5s ease-in-out infinite",
                                }}
                            />
                        </div>
                    </div>
                )}

                {/* Error */}
                {error && (
                    <div
                        className="mt-3 p-3 rounded-lg text-sm animate-fade-in"
                        style={{ background: "rgba(239, 68, 68, 0.1)", color: "var(--error)", border: "1px solid rgba(239, 68, 68, 0.2)" }}
                    >
                        {error}
                    </div>
                )}

                {/* Success message */}
                {!uploading && uploadProgress && (
                    <div
                        className="mt-3 p-3 rounded-lg text-sm animate-fade-in"
                        style={{ background: "rgba(16, 185, 129, 0.1)", color: "var(--success)", border: "1px solid rgba(16, 185, 129, 0.2)" }}
                    >
                        {uploadProgress}
                    </div>
                )}
            </div>

            {/* Document List */}
            <div className="flex-1 overflow-y-auto px-6 pb-6">
                <p
                    className="text-xs font-medium uppercase tracking-wider mb-3"
                    style={{ color: "var(--text-tertiary)" }}
                >
                    Uploaded ({documents.length})
                </p>

                {documents.length === 0 && (
                    <div className="text-center py-8">
                        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                            No documents uploaded yet
                        </p>
                    </div>
                )}

                <div className="space-y-2">
                    {documents.map((doc) => (
                        <div
                            key={doc.id}
                            className="glass glass-hover rounded-lg p-3 flex items-center gap-3 animate-fade-in"
                        >
                            <div
                                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                                style={{ background: "var(--bg-tertiary)", color: "var(--accent)" }}
                            >
                                <FileIcon />
                            </div>
                            <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                                    {doc.filename}
                                </p>
                                <div className="flex items-center gap-2 mt-0.5">
                                    <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                                        {formatSize(doc.file_size)}
                                    </span>
                                    <span style={{ color: "var(--text-tertiary)" }}>·</span>
                                    <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                                        {doc.chunk_count} chunks
                                    </span>
                                    {doc.status === "ready" && (
                                        <span style={{ color: "var(--success)" }}>
                                            <CheckCircleIcon />
                                        </span>
                                    )}
                                </div>
                            </div>
                            <button
                                onClick={() => handleDelete(doc.id)}
                                className="p-2 rounded-lg transition-all opacity-50 hover:opacity-100"
                                style={{ color: "var(--error)" }}
                            >
                                <TrashIcon />
                            </button>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
