"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import type { ImageAnnotation } from "@/lib/api";

interface ImageViewerProps {
    imageUrl: string;
    annotations: ImageAnnotation[];
    width?: number;
    height?: number;
    selectedAnnotation?: string | null;
    onAnnotationClick?: (annotation: ImageAnnotation) => void;
}

export default function ImageViewer({
    imageUrl,
    annotations,
    width,
    height,
    selectedAnnotation,
    onAnnotationClick,
}: ImageViewerProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [zoom, setZoom] = useState(1);
    const [pan, setPan] = useState({ x: 0, y: 0 });
    const [brightness, setBrightness] = useState(100);
    const [contrast, setContrast] = useState(100);
    const [isDragging, setIsDragging] = useState(false);
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
    const [showControls, setShowControls] = useState(true);
    const [imageLoaded, setImageLoaded] = useState(false);
    const [imageDimensions, setImageDimensions] = useState({ w: 0, h: 0 });

    const handleWheel = useCallback((e: React.WheelEvent) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        setZoom((prev) => Math.max(0.25, Math.min(5, prev + delta)));
    }, []);

    const handleMouseDown = useCallback((e: React.MouseEvent) => {
        if (e.button !== 0) return;
        setIsDragging(true);
        setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }, [pan]);

    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        if (!isDragging) return;
        setPan({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
    }, [isDragging, dragStart]);

    const handleMouseUp = useCallback(() => {
        setIsDragging(false);
    }, []);

    const resetView = useCallback(() => {
        setZoom(1);
        setPan({ x: 0, y: 0 });
        setBrightness(100);
        setContrast(100);
    }, []);

    const handleImageLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
        const img = e.currentTarget;
        setImageDimensions({ w: img.naturalWidth, h: img.naturalHeight });
        setImageLoaded(true);
    }, []);

    return (
        <div className="relative flex flex-col gap-3">
            {/* Toolbar */}
            {showControls && (
                <div className="flex items-center gap-3 p-2 rounded-lg bg-[var(--bg-card)] border border-[var(--border-primary)]">
                    {/* Zoom */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}
                            className="w-7 h-7 flex items-center justify-center rounded bg-[var(--bg-tertiary)] hover:bg-[var(--primary)] transition-colors text-sm font-bold"
                        >
                            −
                        </button>
                        <span className="text-xs text-[var(--text-secondary)] min-w-[3rem] text-center font-mono">
                            {Math.round(zoom * 100)}%
                        </span>
                        <button
                            onClick={() => setZoom((z) => Math.min(5, z + 0.25))}
                            className="w-7 h-7 flex items-center justify-center rounded bg-[var(--bg-tertiary)] hover:bg-[var(--primary)] transition-colors text-sm font-bold"
                        >
                            +
                        </button>
                    </div>

                    <div className="w-px h-5 bg-[var(--border-primary)]" />

                    {/* Brightness */}
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-[var(--text-tertiary)]">☀</span>
                        <input
                            type="range"
                            min={20}
                            max={200}
                            value={brightness}
                            onChange={(e) => setBrightness(Number(e.target.value))}
                            className="w-16 h-1 accent-[var(--primary)]"
                        />
                    </div>

                    {/* Contrast */}
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-[var(--text-tertiary)]">◐</span>
                        <input
                            type="range"
                            min={20}
                            max={200}
                            value={contrast}
                            onChange={(e) => setContrast(Number(e.target.value))}
                            className="w-16 h-1 accent-[var(--accent)]"
                        />
                    </div>

                    <div className="w-px h-5 bg-[var(--border-primary)]" />

                    {/* Reset */}
                    <button
                        onClick={resetView}
                        className="px-2 py-1 text-xs rounded bg-[var(--bg-tertiary)] hover:bg-[var(--primary)] transition-colors"
                    >
                        Reset
                    </button>

                    {/* Dimensions info */}
                    {imageLoaded && (
                        <span className="text-xs text-[var(--text-tertiary)] ml-auto font-mono">
                            {imageDimensions.w}×{imageDimensions.h}
                        </span>
                    )}
                </div>
            )}

            {/* Toggle controls */}
            <button
                onClick={() => setShowControls(!showControls)}
                className="absolute top-1 right-1 z-20 w-6 h-6 flex items-center justify-center rounded bg-black/50 text-white/80 text-xs hover:bg-black/70 transition-colors"
                title={showControls ? "Hide controls" : "Show controls"}
            >
                {showControls ? "▲" : "▼"}
            </button>

            {/* Image viewport */}
            <div
                ref={containerRef}
                className="relative overflow-hidden rounded-lg border border-[var(--border-primary)] bg-black cursor-grab active:cursor-grabbing"
                style={{ height: "500px" }}
                onWheel={handleWheel}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
            >
                <div
                    style={{
                        transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                        transformOrigin: "center center",
                        transition: isDragging ? "none" : "transform 0.15s ease-out",
                        filter: `brightness(${brightness}%) contrast(${contrast}%)`,
                        width: "100%",
                        height: "100%",
                        position: "relative",
                    }}
                >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                        src={imageUrl}
                        alt="Medical image"
                        onLoad={handleImageLoad}
                        style={{
                            width: "100%",
                            height: "100%",
                            objectFit: "contain",
                        }}
                    />

                    {/* Annotation overlays */}
                    {imageLoaded &&
                        annotations.map((ann) => {
                            if (ann.annotation_type !== "bbox" || !ann.geometry) return null;
                            const geom = ann.geometry as { x: number; y: number; width: number; height: number };
                            const isSelected = selectedAnnotation === ann.id;

                            return (
                                <div
                                    key={ann.id}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onAnnotationClick?.(ann);
                                    }}
                                    title={ann.label}
                                    style={{
                                        position: "absolute",
                                        left: `${geom.x * 100}%`,
                                        top: `${geom.y * 100}%`,
                                        width: `${geom.width * 100}%`,
                                        height: `${geom.height * 100}%`,
                                        border: `2px solid ${ann.color}`,
                                        backgroundColor: isSelected
                                            ? `${ann.color}30`
                                            : `${ann.color}15`,
                                        borderRadius: "4px",
                                        cursor: "pointer",
                                        transition: "background-color 0.2s",
                                        pointerEvents: "auto",
                                    }}
                                >
                                    {/* Label */}
                                    <span
                                        style={{
                                            position: "absolute",
                                            top: "-20px",
                                            left: "0",
                                            fontSize: "10px",
                                            padding: "1px 4px",
                                            borderRadius: "2px",
                                            backgroundColor: ann.color,
                                            color: "white",
                                            whiteSpace: "nowrap",
                                            maxWidth: "150px",
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                        }}
                                    >
                                        {ann.label.slice(0, 30)}
                                        {ann.confidence != null && (
                                            <span style={{ opacity: 0.8, marginLeft: "4px" }}>
                                                {Math.round(ann.confidence * 100)}%
                                            </span>
                                        )}
                                    </span>
                                </div>
                            );
                        })}
                </div>

                {/* Loading state */}
                {!imageLoaded && (
                    <div className="absolute inset-0 flex items-center justify-center">
                        <div className="w-8 h-8 border-2 border-[var(--primary)] border-t-transparent rounded-full animate-spin" />
                    </div>
                )}
            </div>
        </div>
    );
}
