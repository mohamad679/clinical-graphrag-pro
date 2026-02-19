"use client";

import React, { useState, useEffect, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import ChatInterface from "@/components/ChatInterface";
import DocumentUploader from "@/components/DocumentUploader";
import ImageGallery from "@/components/ImageGallery";
import WorkflowPanel from "@/components/WorkflowPanel";
import EvalPanel from "@/components/EvalPanel";
import FineTunePanel from "@/components/FineTunePanel";
import SettingsPanel from "@/components/SettingsPanel";
import { getDocuments, getGraphStats, type DocumentInfo } from "@/lib/api";

// ── Graph Placeholder ───────────────────────────────────

function GraphView() {
  const [stats, setStats] = useState<{
    vector_store: { total_vectors: number; total_chunks: number; total_documents: number };
    knowledge_graph: { nodes: number; edges: number; status: string };
  } | null>(null);

  useEffect(() => {
    getGraphStats().then(setStats).catch(console.error);
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="p-6 border-b" style={{ borderColor: "var(--border)" }}>
        <h2 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
          Knowledge Graph
        </h2>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Visualize relationships in your medical knowledge base
        </p>
      </div>

      <div className="flex-1 flex items-center justify-center p-6">
        {stats ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 w-full max-w-2xl">
            {/* Stats cards */}
            {[
              { label: "Documents", value: stats.vector_store.total_documents, color: "var(--primary)" },
              { label: "Chunks", value: stats.vector_store.total_chunks, color: "var(--accent)" },
              { label: "Vectors", value: stats.vector_store.total_vectors, color: "var(--success)" },
            ].map((stat) => (
              <div key={stat.label} className="glass rounded-xl p-5 text-center animate-fade-in">
                <p className="text-3xl font-bold mb-1" style={{ color: stat.color }}>
                  {stat.value.toLocaleString()}
                </p>
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {stat.label}
                </p>
              </div>
            ))}

            {/* Knowledge Graph placeholder */}
            <div className="sm:col-span-3 glass rounded-xl p-8 text-center mt-2">
              <div
                className="w-16 h-16 mx-auto mb-4 rounded-2xl flex items-center justify-center"
                style={{ background: "var(--bg-tertiary)" }}
              >
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--accent)" }}>
                  <circle cx="12" cy="12" r="3" />
                  <circle cx="19" cy="5" r="2" />
                  <circle cx="5" cy="19" r="2" />
                  <circle cx="5" cy="5" r="2" />
                  <line x1="12" y1="9" x2="7" y2="6" />
                  <line x1="12" y1="9" x2="17" y2="6" />
                  <line x1="12" y1="15" x2="7" y2="18" />
                </svg>
              </div>
              <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                Graph Visualization Coming in Phase 4
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
                Medical entity relationships, drug interactions, and clinical pathways
              </p>
            </div>
          </div>
        ) : (
          <div className="flex gap-1.5">
            <span className="loading-dot w-2 h-2 rounded-full" style={{ background: "var(--text-tertiary)" }} />
            <span className="loading-dot w-2 h-2 rounded-full" style={{ background: "var(--text-tertiary)" }} />
            <span className="loading-dot w-2 h-2 rounded-full" style={{ background: "var(--text-tertiary)" }} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Dashboard Page ─────────────────────────────────

export default function DashboardPage() {
  const [currentView, setCurrentView] = useState<"chat" | "documents" | "images" | "graph" | "workflows" | "evaluation" | "finetune" | "settings">("chat");
  const [currentSessionId, setCurrentSessionId] = useState<string | undefined>();
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await getDocuments();
      setDocuments(data.documents);
    } catch (err) {
      console.error("Failed to load documents:", err);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  function handleNewChat() {
    setCurrentSessionId(undefined);
  }

  function handleSessionSelect(sessionId: string) {
    setCurrentSessionId(sessionId);
    setCurrentView("chat");
  }

  function handleSessionCreated(sessionId: string) {
    setCurrentSessionId(sessionId);
  }

  return (
    <div className="flex h-screen" style={{ background: "var(--bg-primary)" }}>
      {/* Sidebar */}
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        currentSessionId={currentSessionId}
        onSessionSelect={handleSessionSelect}
        onNewChat={handleNewChat}
      />

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden" style={{ background: "var(--bg-primary)" }}>
        {currentView === "chat" && (
          <ChatInterface
            key={currentSessionId || "new"}
            sessionId={currentSessionId}
            onSessionCreated={handleSessionCreated}
          />
        )}

        {currentView === "documents" && (
          <DocumentUploader documents={documents} onDocumentsChange={loadDocuments} />
        )}

        {currentView === "graph" && <GraphView />}

        {currentView === "images" && <ImageGallery />}

        {currentView === "workflows" && <WorkflowPanel />}

        {currentView === "evaluation" && <EvalPanel />}

        {currentView === "finetune" && <FineTunePanel />}

        {currentView === "settings" && <SettingsPanel />}
      </main>
    </div>
  );
}
