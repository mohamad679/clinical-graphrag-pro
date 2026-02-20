"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import dynamic from "next/dynamic";
import { getGraphVisualization } from "@/lib/api";

// Dynamically import ForceGraph3D to avoid SSR issues
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), { ssr: false });

export default function GraphPanel() {
    const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

    useEffect(() => {
        getGraphVisualization()
            .then((data) => {
                if (!data.nodes || data.nodes.length === 0) {
                    setError("Graph is empty. Please seed the graph or add entities first.");
                } else {
                    setGraphData(data);
                }
            })
            .catch((err) => {
                console.error("Failed to fetch graph data", err);
                setError("Failed to load Knowledge Graph data. Is the backend running?");
            });
    }, []);

    useEffect(() => {
        if (!containerRef.current) return;
        const resizeObserver = new ResizeObserver((entries) => {
            for (let entry of entries) {
                setDimensions({
                    width: entry.contentRect.width,
                    height: entry.contentRect.height,
                });
            }
        });
        resizeObserver.observe(containerRef.current);
        return () => resizeObserver.disconnect();
    }, []);

    const getNodeColor = useCallback((node: any) => {
        switch (node.label) {
            case "Patient": return "#3b82f6"; // Blue
            case "Disease": return "#ef4444"; // Red
            case "Drug": return "#10b981";    // Green
            default: return "#8b5cf6";       // Purple
        }
    }, []);

    return (
        <div className="flex flex-col h-full bg-[#000000]">
            <div className="p-6 border-b" style={{ borderColor: "var(--border)" }}>
                <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
                    Interactive 3D Knowledge Graph
                </h2>
                <p className="text-sm mt-1 flex items-center gap-4" style={{ color: "var(--text-secondary)" }}>
                    <span>Fly through clinical entities and relationships in realtime.</span>

                    {graphData && (
                        <div className="flex gap-3 ml-auto text-xs">
                            <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500"></span> Patient</div>
                            <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500"></span> Disease</div>
                            <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500"></span> Drug</div>
                        </div>
                    )}
                </p>
            </div>

            <div className="flex-1 relative" ref={containerRef}>
                {error ? (
                    <div className="absolute inset-0 flex items-center justify-center text-[var(--error)] p-8 text-center bg-[#0a0a0a]">
                        <p>{error}</p>
                    </div>
                ) : !graphData ? (
                    <div className="absolute inset-0 flex items-center justify-center bg-[#0a0a0a]">
                        <div className="flex gap-1.5">
                            <span className="loading-dot w-2 h-2 rounded-full bg-blue-500" />
                            <span className="loading-dot w-2 h-2 rounded-full bg-red-500" style={{ animationDelay: "0.2s" }} />
                            <span className="loading-dot w-2 h-2 rounded-full bg-green-500" style={{ animationDelay: "0.4s" }} />
                        </div>
                    </div>
                ) : (
                    <ForceGraph3D
                        width={dimensions.width}
                        height={dimensions.height}
                        graphData={graphData}
                        nodeLabel={(node: any) => `${node.label}: ${node.name}`}
                        nodeColor={getNodeColor}
                        nodeRelSize={6}
                        linkColor={() => "rgba(255, 255, 255, 0.2)"}
                        linkOpacity={0.2}
                        linkWidth={1}
                        linkDirectionalArrowLength={3.5}
                        linkDirectionalArrowRelPos={1}
                        backgroundColor="#0a0a0a"
                        onNodeClick={(node: any) => {
                            // Focus camera on clicked node
                            // Note: We'd need a ref to the graph instance to trigger cameraPosition
                            console.log("Clicked node:", node);
                        }}
                    />
                )}
            </div>
        </div>
    );
}
