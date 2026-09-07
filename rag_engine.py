import os
import glob
from sentence_transformers import SentenceTransformer, util

# Initialize model (all-MiniLM-L6-v2 is fast and small)
model = None

# Cache for loaded texts and embeddings
knowledge_texts = []
knowledge_embeddings = None

def load_knowledge_base():
    global model, knowledge_texts, knowledge_embeddings
    
    if model is None:
        print("Loading RAG Embedding Model (all-MiniLM-L6-v2)...")
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
    policies_dir = "governance_policies"
    if not os.path.exists(policies_dir):
        return

    # Clear cache
    knowledge_texts = []
    
    # Read all text and md files
    for file_path in glob.glob(os.path.join(policies_dir, "*.md")) + glob.glob(os.path.join(policies_dir, "*.txt")):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Split by double newline to treat each section/paragraph as a separate chunk
            chunks = [chunk.strip() for chunk in content.split("\n\n") if len(chunk.strip()) > 10]
            knowledge_texts.extend(chunks)
            
    if knowledge_texts:
        print(f"Loaded {len(knowledge_texts)} chunks into RAG Knowledge Base.")
        knowledge_embeddings = model.encode(knowledge_texts, convert_to_tensor=True)

def retrieve_relevant_policy(query: str, top_k: int = 1) -> str:
    """
    Search the knowledge base for policies relevant to the query (e.g. entity name like 'IBAN').
    """
    global model, knowledge_texts, knowledge_embeddings
    
    if not knowledge_texts or knowledge_embeddings is None:
        load_knowledge_base()
        
    if not knowledge_texts:
        return "" # No policies found
        
    # Embed the query
    query_embedding = model.encode(query, convert_to_tensor=True)
    
    # Calculate cosine similarity
    hits = util.semantic_search(query_embedding, knowledge_embeddings, top_k=top_k)
    
    if hits and len(hits[0]) > 0:
        best_match_idx = hits[0][0]['corpus_id']
        score = hits[0][0]['score']
        
        # Only return if it's somewhat relevant (e.g. score > 0.1)
        print(f"RAG Engine: Found best match with score {score:.2f}")
        if score > 0.1:
            print(f"RAG Engine: Injecting policy context: {knowledge_texts[best_match_idx][:50]}...")
            return knowledge_texts[best_match_idx]
            
    print("RAG Engine: No relevant policy found.")
    return ""
