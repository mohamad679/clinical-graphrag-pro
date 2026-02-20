"use client";

import React, { useState, useEffect, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import ChatInterface from "@/components/ChatInterface";
import WorkflowPanel from "@/components/WorkflowPanel";
import EvalPanel from "@/components/EvalPanel";
import FineTunePanel from "@/components/FineTunePanel";
import SettingsPanel from "@/components/SettingsPanel";
import GraphPanel from "@/components/GraphPanel";

// ── Main Dashboard Page ─────────────────────────────────

export default function DashboardPage() {
  const [currentView, setCurrentView] = useState<"chat" | "graph" | "workflows" | "evaluation" | "finetune" | "settings">("chat");
  const [currentSessionId, setCurrentSessionId] = useState<string | undefined>();
  const [chatKey, setChatKey] = useState(0);

  function handleNewChat() {
    setCurrentSessionId(undefined);
    setChatKey((prev) => prev + 1);
  }

  function handleSessionSelect(sessionId: string) {
    setCurrentSessionId(sessionId);
    setChatKey((prev) => prev + 1);
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
            key={`chat-${chatKey}`}
            sessionId={currentSessionId}
            onSessionCreated={handleSessionCreated}
          />
        )}

        {currentView === "graph" && <GraphPanel />}

        {currentView === "workflows" && <WorkflowPanel />}

        {currentView === "evaluation" && <EvalPanel />}

        {currentView === "finetune" && <FineTunePanel />}

        {currentView === "settings" && <SettingsPanel />}
      </main>
    </div>
  );
}
