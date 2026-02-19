"use client";

import { useState, useCallback, useEffect } from "react";
import type { MedicalImageInfo } from "@/lib/api";
import {
    uploadImage,
    getImages,
    deleteImage,
    analyzeImage,
    getImage,
    getImageFileUrl,
} from "@/lib/api";
import ImageViewer from "./ImageViewer";
import AnalysisPanel from "./AnalysisPanel";

interface ImageGalleryProps {
    onImageSelect?: (image: MedicalImageInfo) => void;
}

/* Format file size */
function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ImageGallery({ onImageSelect }: ImageGalleryProps) {
    const [images, setImages] = useState<MedicalImageInfo[]>([]);
    const [selectedImage, setSelectedImage] = useState<MedicalImageInfo | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    const [error, setError] = useState("");
    const [hoveredAnnotation, setHoveredAnnotation] = useState<string | null>(null);

    // Load images on mount
    useEffect(() => {
        loadImages();
    }, []);

    const loadImages = async () => {
        try {
            const data = await getImages();
            setImages(data.images);
        } catch {
            // Backend may not be running
        }
    };

    const handleUpload = useCallback(async (files: FileList | File[]) => {
        const file = files[0];
        if (!file) return;

        const allowed = [".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".dcm"];
        const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
        if (!allowed.includes(ext)) {
            setError(`Unsupported file type: ${ext}`);
            return;
        }

        setIsUploading(true);
        setError("");
        try {
            await uploadImage(file);
            await loadImages();
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Upload failed");
        } finally {
            setIsUploading(false);
        }
    }, []);

    const handleAnalyze = useCallback(async (imageId: string) => {
        setIsAnalyzing(true);
        try {
            await analyzeImage(imageId);
            // Refresh the image to get analysis results
            const updated = await getImage(imageId);
            setSelectedImage(updated);
            await loadImages();
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Analysis failed");
        } finally {
            setIsAnalyzing(false);
        }
    }, []);

    const handleDelete = useCallback(async (imageId: string) => {
        try {
            await deleteImage(imageId);
            if (selectedImage?.id === imageId) setSelectedImage(null);
            await loadImages();
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "Delete failed");
        }
    }, [selectedImage]);

    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            setDragOver(false);
            handleUpload(e.dataTransfer.files);
        },
        [handleUpload]
    );

    // ── Detail View ─────────────────────────────────────
    if (selectedImage) {
        return (
            <div className="flex flex-col h-full">
                {/* Header */}
                <div className="flex items-center gap-3 p-4 border-b border-[var(--border-primary)]">
                    <button
                        onClick={() => setSelectedImage(null)}
                        className="w-8 h-8 flex items-center justify-center rounded-lg bg-[var(--bg-tertiary)] hover:bg-[var(--primary)] transition-colors"
                    >
                        ←
                    </button>
                    <div className="flex-1 min-w-0">
                        <h2 className="text-sm font-semibold text-[var(--text-primary)] truncate">
                            {selectedImage.original_filename}
                        </h2>
                        <div className="flex items-center gap-3 text-xs text-[var(--text-tertiary)]">
                            <span>{formatSize(selectedImage.file_size)}</span>
                            {selectedImage.modality && (
                                <span className="px-1.5 py-0.5 rounded bg-[var(--primary)]/20 text-[var(--primary)]">
                                    {selectedImage.modality}
                                </span>
                            )}
                            <span
                                className={`px-1.5 py-0.5 rounded ${selectedImage.analysis_status === "completed"
                                        ? "bg-emerald-500/20 text-emerald-400"
                                        : selectedImage.analysis_status === "analyzing"
                                            ? "bg-amber-500/20 text-amber-400"
                                            : selectedImage.analysis_status === "failed"
                                                ? "bg-red-500/20 text-red-400"
                                                : "bg-white/10 text-white/50"
                                    }`}
                            >
                                {selectedImage.analysis_status}
                            </span>
                        </div>
                    </div>

                    {selectedImage.analysis_status === "pending" && (
                        <button
                            onClick={() => handleAnalyze(selectedImage.id)}
                            disabled={isAnalyzing}
                            className="btn-primary text-xs"
                        >
                            {isAnalyzing ? "Analyzing..." : "🔬 Analyze"}
                        </button>
                    )}
                </div>

                {/* Content */}
                <div className="flex-1 overflow-auto p-4">
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        {/* Image viewer */}
                        <div>
                            <ImageViewer
                                imageUrl={getImageFileUrl(selectedImage.filename)}
                                annotations={selectedImage.annotations}
                                width={selectedImage.width}
                                height={selectedImage.height}
                                selectedAnnotation={hoveredAnnotation}
                            />
                        </div>

                        {/* Analysis panel */}
                        <div className="overflow-auto max-h-[600px] custom-scrollbar">
                            {selectedImage.analysis_result ? (
                                <AnalysisPanel
                                    analysis={selectedImage.analysis_result}
                                    annotations={selectedImage.annotations}
                                    isAnalyzing={isAnalyzing}
                                    onAnnotationHover={setHoveredAnnotation}
                                    onReanalyze={() => handleAnalyze(selectedImage.id)}
                                />
                            ) : isAnalyzing ? (
                                <AnalysisPanel
                                    analysis={{
                                        summary: "",
                                        modality_detected: "",
                                        body_part_detected: "",
                                        findings: [],
                                        recommendations: [],
                                        differential_diagnosis: [],
                                        model_used: "",
                                    }}
                                    annotations={[]}
                                    isAnalyzing={true}
                                />
                            ) : (
                                <div className="glass-card p-6 flex flex-col items-center justify-center gap-3 min-h-[200px]">
                                    <div className="text-4xl">🔬</div>
                                    <p className="text-sm text-[var(--text-secondary)] text-center">
                                        Click <strong>Analyze</strong> to run AI vision analysis
                                    </p>
                                    <p className="text-xs text-[var(--text-tertiary)] text-center">
                                        Detects findings, generates annotations, and provides
                                        differential diagnosis
                                    </p>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    // ── Gallery View ────────────────────────────────────
    return (
        <div className="flex flex-col h-full">
            {/* Upload area */}
            <div
                className={`m-4 p-6 rounded-xl border-2 border-dashed transition-all duration-200 ${dragOver
                        ? "border-[var(--primary)] bg-[var(--primary)]/10"
                        : "border-[var(--border-secondary)] hover:border-[var(--primary)]/50"
                    }`}
                onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
            >
                <div className="flex flex-col items-center gap-2">
                    <div className="text-3xl">{isUploading ? "⏳" : "🏥"}</div>
                    <p className="text-sm text-[var(--text-secondary)]">
                        {isUploading
                            ? "Uploading..."
                            : "Drop medical images here or click to browse"}
                    </p>
                    <p className="text-xs text-[var(--text-tertiary)]">
                        PNG, JPEG, TIFF, DICOM up to 100MB
                    </p>
                    {!isUploading && (
                        <label className="btn-primary text-xs cursor-pointer mt-1">
                            Browse Files
                            <input
                                type="file"
                                className="hidden"
                                accept=".png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.dcm"
                                onChange={(e) => e.target.files && handleUpload(e.target.files)}
                            />
                        </label>
                    )}
                </div>
            </div>

            {error && (
                <div className="mx-4 mb-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-sm text-red-400">
                    {error}
                    <button
                        onClick={() => setError("")}
                        className="ml-2 text-red-300 hover:text-white"
                    >
                        ✕
                    </button>
                </div>
            )}

            {/* Image grid */}
            <div className="flex-1 overflow-auto px-4 pb-4">
                {images.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
                        <div className="text-5xl opacity-30">🩻</div>
                        <p className="text-sm text-[var(--text-tertiary)]">
                            No images uploaded yet
                        </p>
                    </div>
                ) : (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        {images.map((img) => (
                            <div
                                key={img.id}
                                className="group relative glass-card p-2 cursor-pointer hover:border-[var(--primary)]/50 transition-all duration-200"
                                onClick={() => {
                                    setSelectedImage(img);
                                    onImageSelect?.(img);
                                }}
                            >
                                {/* Thumbnail */}
                                <div className="relative aspect-square rounded-lg overflow-hidden bg-black/50 mb-2">
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                        src={getImageFileUrl(img.filename)}
                                        alt={img.original_filename}
                                        className="w-full h-full object-cover"
                                    />

                                    {/* Status overlay */}
                                    <div className="absolute top-1 right-1">
                                        <span
                                            className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${img.analysis_status === "completed"
                                                    ? "bg-emerald-500 text-white"
                                                    : img.analysis_status === "analyzing"
                                                        ? "bg-amber-500 text-white"
                                                        : img.analysis_status === "failed"
                                                            ? "bg-red-500 text-white"
                                                            : "bg-white/20 text-white/80"
                                                }`}
                                        >
                                            {img.analysis_status === "completed"
                                                ? "✓"
                                                : img.analysis_status === "analyzing"
                                                    ? "⋯"
                                                    : img.analysis_status === "failed"
                                                        ? "✗"
                                                        : "○"}
                                        </span>
                                    </div>

                                    {/* Delete button */}
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleDelete(img.id);
                                        }}
                                        className="absolute top-1 left-1 w-5 h-5 flex items-center justify-center rounded bg-red-500/80 text-white text-xs opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                                    >
                                        ✕
                                    </button>

                                    {/* Annotation count */}
                                    {img.annotations.length > 0 && (
                                        <div className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded-full bg-[var(--accent)] text-white text-[9px] font-bold">
                                            {img.annotations.length}
                                        </div>
                                    )}
                                </div>

                                {/* Info */}
                                <div className="px-1">
                                    <p className="text-xs text-[var(--text-primary)] truncate font-medium">
                                        {img.original_filename}
                                    </p>
                                    <div className="flex items-center gap-2 mt-0.5">
                                        <span className="text-[10px] text-[var(--text-tertiary)]">
                                            {formatSize(img.file_size)}
                                        </span>
                                        {img.modality && (
                                            <span className="text-[10px] text-[var(--primary)] font-mono">
                                                {img.modality}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
