# ChromaDB notes

## What is ChromaDB?
- ChromaDB is an open-source **vector database**. It stores text as **embeddings** (lists of numbers that capture meaning) and finds the most similar items for a query.
- It runs locally in Python, so it fits the project requirement of **local and zero-cost**.

## Why we need it
- Current retrieval uses **TF-IDF**, which matches exact words only.
- Example: the question "how much money did the company earn?" may miss a page that says "total revenue from operations".
- ChromaDB retrieves by **meaning**, so it can find the right page even when the words differ.

## Key concepts
- **Embedding:** a numeric representation of a text's meaning.
- **Collection:** a group of stored chunks, similar to a table.
- **Metadata:** extra details stored with each chunk (company, page number, document name, chunk ID).
- **Query:** a question is converted into an embedding, and Chroma returns the closest chunks.

## Planned architecture
PDF → page-aware chunks → embeddings (Ollama `nomic-embed-text`) → ChromaDB → semantic retrieval → Company A/B agent → comparison agent → dashboard

## Requirements for the implementation
- Company A and Company B must stay **isolated** (separate collections).
- Evidence IDs must still point back to the original PDF chunks.
- Page numbers must be preserved.
- The existing agent interface must stay unchanged.
- **TF-IDF stays as a fallback.** It will not be deleted.
- Everything stays local: Ollama + ChromaDB, no paid APIs.

## Planned work
1. Build a `ChromaRetriever` that follows the same interface as the TF-IDF retriever.
2. Store chunks with their metadata (company, page, document, chunk ID).
3. Add a config switch between TF-IDF and ChromaDB, with fallback to TF-IDF.
4. Compare both retrievers on the same questions (revenue, profit, risks, strategy).
5. Check that page numbers are correct and that no Company A results appear in Company B queries.
6. Write tests for isolation, evidence IDs and fallback.

---

# Project Notes: Corporate Report Analysis & Decision Support System

## Overview
A system that analyzes and compares two companies' annual reports (Tata Motors and Mahindra) and presents the results with page-level evidence.

## Tech stack
- Backend: Python + FastAPI
- Frontend: React + Vite + Tailwind
- Local LLM: Ollama with qwen2.5:3b
- Retrieval: TF-IDF (current), ChromaDB (planned)

## Modules
1. **Document Ingestion & Processing:** upload two annual reports, extract text and tables, create page-aware chunks with metadata.
2. **Information Retrieval:** TF-IDF as the baseline, ChromaDB semantic retrieval as the planned enhancement.
3. **Company Analysis & Comparison:** two independent agents analyze each company, then a comparison step identifies differences, strengths, weaknesses and risks.
4. **Evidence & Decision-Support Dashboard:** shows results with page-level evidence.

## Current status
- Ingestion, agents, comparison and dashboard are implemented.
- The dashboard still needs a final end-to-end test with the real reports.
- ChromaDB retrieval is not implemented yet.

## Team tasks
- Person 1: dashboard end-to-end testing
- Person 2: ChromaDB / RAG retrieval
- Person 3: AI agent output quality
- Person 4: testing and documentation