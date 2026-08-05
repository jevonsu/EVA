"""Wiki-style knowledge base (pages + keyword search)."""

from app.knowledge.store import KnowledgeStore, get_knowledge_store

__all__ = ["KnowledgeStore", "get_knowledge_store"]
