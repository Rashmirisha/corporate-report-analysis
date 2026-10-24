"""Manual check with real local embeddings.
Needs Ollama running and: ollama pull nomic-embed-text
Run from the backend folder:  python -m scripts.smoke_chroma
"""
from app.retrieval.chroma_retriever import ChromaRetriever

r = ChromaRetriever(persist_dir="data/chroma_demo")
r.clear("A")
r.index_chunks("A", [
    {"chunk_id": "A-1", "company": "A", "document_name": "demo.pdf", "page": 10,
     "text": "Total revenue from operations was 4,37,927 crore"},
    {"chunk_id": "A-2", "company": "A", "document_name": "demo.pdf", "page": 25,
     "text": "The company has 80,000 employees"},
    {"chunk_id": "A-3", "company": "A", "document_name": "demo.pdf", "page": 60,
     "text": "Risk: rising steel prices may reduce profit"},
])
for hit in r.search("A", "how much money did they earn?", k=2):
    print(hit["score"], "page", hit["page"], "-", hit["text"])