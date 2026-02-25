import os
import logging
from langchain_community.graphs import Neo4jGraph
from langchain.chains import GraphCypherQAChain
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jpassword")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "google").lower()

def get_neo4j_graph_chain() -> GraphCypherQAChain:
    """Returns a GraphCypherQAChain ready to answer clinical questions using Neo4j."""
    
    logger.info("Connecting to Neo4j to build CypherQAChain...")
    try:
        # 1. Connect to the Neo4j Database
        graph = Neo4jGraph(
            url=NEO4J_URI, 
            username=NEO4J_USER, 
            password=NEO4J_PASSWORD
        )
        
        # 2. Automatically refresh the schema so the LLM knows what Node Labels and Edges exist
        graph.refresh_schema()

        # 3. Instantiate the LLM 
        if LLM_PROVIDER == "groq":
            llm = ChatGroq(model_name="llama3-70b-8192", temperature=0)
        else:
            llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0)

        # 4. Create the LangChain Cypher QA Chain
        chain = GraphCypherQAChain.from_llm(
            llm=llm, 
            graph=graph, 
            verbose=True,
            allow_dangerous_requests=True,
            return_intermediate_steps=True
        )
        
        return chain
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j Graph Cypher QA Chain: {e}")
        raise

# Singleton-like instantiation to avoid hitting DB schema refresh aggressively on every request
_chain_instance = None

def get_shared_chain():
    global _chain_instance
    if _chain_instance is None:
        _chain_instance = get_neo4j_graph_chain()
    return _chain_instance

async def query_neo4j_graph_async(query: str) -> dict:
    """Execute a question against the Neo4j database using Cypher."""
    try:
        chain = get_shared_chain()
        # The chain.invoke is synchronous by default unless we use ainvoke
        response = await chain.ainvoke({"query": query})
        
        steps = response.get("intermediate_steps", [])
        cypher_query = ""
        db_results = ""
        
        for step in steps:
            if "query" in step:
                cypher_query = step["query"]
            if "context" in step:
                db_results = step["context"]
                
        return {
            "answer": response.get("result", ""),
            "generated_cypher": cypher_query,
            "database_results": db_results
        }
    except Exception as e:
        logger.error(f"Error querying Neo4j Temporal Graph: {e}")
        return {"error": str(e)}
