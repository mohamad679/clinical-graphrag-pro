"""
Temporal Knowledge Graph Service using NetworkX.
Provides an in-memory graph (with disk persistence) capable of time-bound relationship queries.
"""

import os
import json
import logging
import networkx as nx
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

GRAPH_DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "temporal_graph.json")


class TemporalGraphService:
    def __init__(self):
        self.graph = nx.MultiDiGraph()
        self._load_graph()

    def _ensure_data_dir(self):
        os.makedirs(os.path.dirname(GRAPH_DATA_FILE), exist_ok=True)

    def _load_graph(self):
        """Load the edge-link-node graph from disk if it exists."""
        if os.path.exists(GRAPH_DATA_FILE):
            try:
                with open(GRAPH_DATA_FILE, "r") as f:
                    data = json.load(f)
                    self.graph = nx.node_link_graph(data, directed=True, multigraph=True)
                logger.info(f"Loaded temporal graph with {self.graph.number_of_nodes()} nodes.")
            except Exception as e:
                logger.error(f"Failed to load graph: {e}")
                self.graph = nx.MultiDiGraph()
        else:
            logger.info("No existing graph found. Starting fresh.")

    def save_graph(self):
        """Persist the graph to disk."""
        self._ensure_data_dir()
        try:
            data = nx.node_link_data(self.graph)
            with open(GRAPH_DATA_FILE, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved temporal graph with {self.graph.number_of_nodes()} nodes.")
        except Exception as e:
            logger.error(f"Failed to save graph: {e}")

    def add_entity(self, node_id: str, label: str, properties: dict | None = None):
        """Add a clinical entity node (e.g., Patient, Drug, Disease)."""
        props = properties or {}
        props["label"] = label
        self.graph.add_node(node_id, **props)
        self.save_graph()

    def add_temporal_relation(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        start_date: str,
        end_date: str | None = None,
        properties: dict | None = None
    ):
        """
        Add a directed edge between two entities with mandatory chronological bounds.
        Dates should ideally be ISO formats (YYYY-MM-DD).
        """
        props = properties or {}
        props["type"] = relationship_type
        props["start_date"] = start_date
        props["end_date"] = end_date
        
        # Ensure nodes exist
        if not self.graph.has_node(source_id):
            self.add_entity(source_id, "Unknown", {})
        if not self.graph.has_node(target_id):
            self.add_entity(target_id, "Unknown", {})
            
        self.graph.add_edge(source_id, target_id, **props)
        self.save_graph()

    def query_temporal_state(self, entity_id: str, target_date_str: str) -> dict:
        """
        Given an entity and a date, return the sub-graph of active relationships on that exact date.
        This allows the LLM to understand conditions/meds that were active historically.
        """
        if not self.graph.has_node(entity_id):
            return {"error": f"Entity '{entity_id}' not found in the knowledge graph."}

        try:
            target_date = datetime.fromisoformat(target_date_str.replace("Z", "+00:00"))
        except ValueError:
            return {"error": "target_date must be in ISO format (YYYY-MM-DD)."}

        active_edges = []
        
        # Check all outgoing edges
        for out_edge in self.graph.out_edges(entity_id, data=True):
            _, target, attrs = out_edge
            if self._is_active_on_date(attrs, target_date):
                target_data = self.graph.nodes[target]
                active_edges.append({
                    "relationship": attrs.get("type"),
                    "target_entity": target,
                    "target_label": target_data.get("label", "Unknown"),
                    "start_date": attrs.get("start_date"),
                    "end_date": attrs.get("end_date")
                })
                
        # Check all incoming edges
        for in_edge in self.graph.in_edges(entity_id, data=True):
            source, _, attrs = in_edge
            if self._is_active_on_date(attrs, target_date):
                source_data = self.graph.nodes[source]
                active_edges.append({
                    "relationship": f"IS_{attrs.get('type')}_OF",
                    "source_entity": source,
                    "source_label": source_data.get("label", "Unknown"),
                    "start_date": attrs.get("start_date"),
                    "end_date": attrs.get("end_date")
                })

        return {
            "entity": entity_id,
            "target_date": target_date_str,
            "active_relationships": active_edges,
            "total_active": len(active_edges)
        }

    def _is_active_on_date(self, edge_attrs: dict, target_date: datetime) -> bool:
        """Helper to determine if a temporal edge spans the target date."""
        start_str = edge_attrs.get("start_date")
        if not start_str:
            return True # If no temporal bound, assume always active
            
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if target_date < start_dt:
                return False
                
            end_str = edge_attrs.get("end_date")
            if end_str:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if target_date > end_dt:
                    return False
                    
            return True
        except ValueError:
            return True # Malformed date, default to active


temporal_graph_service = TemporalGraphService()
