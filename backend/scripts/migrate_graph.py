import json
import logging
import os
from neo4j import GraphDatabase

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# File paths and DB Config
GRAPH_DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "temporal_graph.json")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jpassword")

class GraphMigrator:
    def __init__(self, uri, user, password):
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            logger.info("Successfully connected to Neo4j.")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j at {uri}: {e}")
            raise

    def close(self):
        self.driver.close()

    def load_networkx_data(self):
        """Load the NetworkX node-link data from the JSON file."""
        if not os.path.exists(GRAPH_DATA_FILE):
            logger.error(f"Graph data file not found at {GRAPH_DATA_FILE}")
            return None
        
        try:
            with open(GRAPH_DATA_FILE, "r") as f:
                data = json.load(f)
                logger.info(f"Loaded JSON graph data with {len(data.get('nodes', []))} nodes and {len(data.get('links', []))} links.")
                return data
        except Exception as e:
            logger.error(f"Failed to read graph data: {e}")
            return None

    def prep_nodes(self, nodes_data):
        """Prepare nodes for insertion, separating them by label for efficient UNWIND."""
        nodes_by_label = {}
        for node in nodes_data:
            # NetworkX stores node ID in 'id', but it might be under a different key depending on export.
            # Usually node_link_data puts it in 'id'.
            node_id = node.get("id")
            if not node_id:
                continue
                
            label = node.get("label", "Entity")
            
            # Clean properties (remove id and label as they are handled explicitly)
            props = {k: v for k, v in node.items() if k not in ("id", "label") and v is not None}
            props['id'] = node_id # Ensure ID is a property for merging
            
            if label not in nodes_by_label:
                nodes_by_label[label] = []
            
            nodes_by_label[label].append(props)
            
        return nodes_by_label

    def prep_edges(self, edges_data):
        """Prepare edges for insertion, grouping by relationship type."""
        edges_by_type = {}
        for edge in edges_data:
            source = edge.get("source")
            target = edge.get("target")
            rel_type = edge.get("type", "RELATED_TO")
            
            if not source or not target:
                continue
                
            # Clean properties
            props = {k: v for k, v in edge.items() if k not in ("source", "target", "type") and v is not None}
            
            if rel_type not in edges_by_type:
                edges_by_type[rel_type] = []
                
            edges_by_type[rel_type].append({
                "source": source,
                "target": target,
                **props
            })
            
        return edges_by_type

    def create_constraints(self):
        """Create constraints to ensure Node IDs are unique for fast merging."""
        logger.info("Setting up constraints/indexes...")
        
        # We don't know all labels upfront dynamically in APOC easily without it, 
        # but we know the standard ones. We will just ensure index on :Entity(id) generally,
        # but native Cypher requires specific labels. We will run it on the unique labels found.
        pass

    def execute_migration(self):
        data = self.load_networkx_data()
        if not data:
            return

        nodes = data.get("nodes", [])
        edges = data.get("links", [])
        
        nodes_grouped = self.prep_nodes(nodes)
        edges_grouped = self.prep_edges(edges)
        
        # Setup constraints based on found labels
        with self.driver.session() as session:
            for label in nodes_grouped.keys():
                # Neo4j 5 syntax for constraints
                query = f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                try:
                    session.run(query)
                except Exception as e:
                    logger.warning(f"Could not create constraint for {label}: {e}")

        logger.info("Starting Bulk Node Insertion...")
        with self.driver.session() as session:
            for label, batch in nodes_grouped.items():
                # Highly efficient UNWIND approach
                # We use MERGE so it's idempotent (safe to run multiple times)
                query = f"""
                UNWIND $batch AS row
                MERGE (n:{label} {{id: row.id}})
                SET n += row
                """
                session.run(query, batch=batch)
                logger.info(f"Inserted {len(batch)} nodes of type ':{label}'.")

        logger.info("Starting Bulk Edge Insertion...")
        with self.driver.session() as session:
            for rel_type, batch in edges_grouped.items():
                query = f"""
                UNWIND $batch AS row
                // Match source and target nodes based on ID (indexes make this fast)
                MATCH (source {{id: row.source}})
                MATCH (target {{id: row.target}})
                MERGE (source)-[r:{rel_type}]->(target)
                SET r += row
                // Remove source/target properties from the relationship itself
                REMOVE r.source, r.target 
                """
                try:
                    session.run(query, batch=batch)
                    logger.info(f"Inserted {len(batch)} relationships of type ':{rel_type}'.")
                except Exception as e:
                    logger.error(f"Failed to insert relationships of type ':{rel_type}': {e}")
                    
        logger.info("Migration completely successfully!")

if __name__ == "__main__":
    logger.info("Initializing Neo4j Migration Script")
    try:
        migrator = GraphMigrator(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        migrator.execute_migration()
    except Exception as e:
        logger.error(f"Migration aborted due to error: {e}")
    finally:
        if 'migrator' in locals():
            migrator.close()
