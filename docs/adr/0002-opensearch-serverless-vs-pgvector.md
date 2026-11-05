# ADR 0002: Amazon OpenSearch Serverless (Vector Engine) vs. Amazon Aurora pgvector

## Status
Accepted

## Context
Retrieval-Augmented Generation (RAG) at enterprise scale requires high-dimensional vector similarity search combined with lexical keyword filtering (Hybrid Search), sub-second query latency, tenant partitioning, and zero-management operational overhead. We compared **Amazon OpenSearch Serverless (Vector Engine)** against **Amazon Aurora PostgreSQL with pgvector**.

## Decision
We adopt **Amazon OpenSearch Serverless (AOSS)** with the Vector Search Collection type as the primary retrieval store for unstructured enterprise corpora.

## Consequences

### Positive
- **Native Hybrid Search:** OpenSearch Serverless natively executes hybrid scoring combining BM25 lexical keyword matching and Approximate k-Nearest Neighbor (k-NN) using Non-Metric Space Library (NMSLIB) / Hierarchical Navigable Small World (HNSW) graphs in a single query pipeline.
- **Auto-Scaling Compute & Storage:** Compute (OpenSearch Compute Units - OCUs) decouples from storage, automatically scaling indexing and search independently without cluster resizing or maintenance windows.
- **Granular Security Policies:** Enforces data access policies, network encryption policies, and VPC endpoints at the collection and index tier.

### Trade-offs
- Minimum baseline cost of 2 OCUs (1 indexing + 1 search OCU) in production.
- For transactional data with relational joins alongside vectors, Aurora PostgreSQL `pgvector` remains a complementary store.
