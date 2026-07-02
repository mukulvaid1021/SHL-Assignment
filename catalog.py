# catalog.py
import json
import os
import numpy as np
from typing import List, Dict, Tuple, Optional
from models import CatalogItem, Recommendation
from scraper import get_hardcoded_catalog, build_full_text
import logging
import re

logger = logging.getLogger(__name__)


class CatalogManager:
    """Manages the SHL catalog with multiple retrieval strategies."""

    def __init__(self):
        self.items: List[Dict] = []
        self.embeddings: Optional[np.ndarray] = None
        self._embedding_model = None
        self.load_catalog()

    def load_catalog(self):
        """Load catalog from file or build from scratch."""
        catalog_path = "catalog_data.json"
        if os.path.exists(catalog_path):
            with open(catalog_path, "r") as f:
                self.items = json.load(f)
            logger.info(f"Loaded {len(self.items)} items from {catalog_path}")
        else:
            self.items = get_hardcoded_catalog()
            with open(catalog_path, "w") as f:
                json.dump(self.items, f, indent=2)
            logger.info(f"Built catalog with {len(self.items)} items")

        # Ensure all items have full_text
        for item in self.items:
            if not item.get("full_text"):
                item["full_text"] = build_full_text(item)

    def get_all_items_summary(self) -> str:
        """Get a compact summary of all catalog items for LLM context."""
        lines = []
        for item in self.items:
            line = f"- {item['name']} | Type: {item['test_type']} | {item.get('description', '')[:80]}"
            lines.append(line)
        return "\n".join(lines)

    def get_all_items_for_context(self) -> str:
        """Get detailed catalog for LLM context."""
        lines = []
        for i, item in enumerate(self.items):
            keywords = ", ".join(item.get("keywords", []))
            categories = ", ".join(item.get("categories", []))
            duration = item.get("duration", "N/A")
            remote = item.get("remote_testing", "N/A")
            adaptive = item.get("adaptive_testing", "N/A")
            lines.append(
                f"[{i}] Name: {item['name']}\n"
                f"    URL: {item['url']}\n"
                f"    Type: {item['test_type']} | Duration: {duration} | Remote: {remote} | Adaptive: {adaptive}\n"
                f"    Description: {item.get('description', 'N/A')}\n"
                f"    Categories: {categories}\n"
                f"    Keywords: {keywords}"
            )
        return "\n\n".join(lines)

    def search(self, query: str, filters: Optional[Dict] = None, top_k: int = 10) -> List[Dict]:
        """Search catalog using keyword matching and scoring."""
        query_lower = query.lower()
        query_terms = set(re.findall(r'\b\w+\b', query_lower))

        scored_items = []
        for item in self.items:
            score = self._score_item(item, query_lower, query_terms, filters)
            if score > 0:
                scored_items.append((score, item))

        # Sort by score descending
        scored_items.sort(key=lambda x: x[0], reverse=True)

        return [item for score, item in scored_items[:top_k]]

    def _score_item(self, item: Dict, query_lower: str, query_terms: set, filters: Optional[Dict] = None) -> float:
        """Score a catalog item against a search query."""
        score = 0.0

        # Apply filters first
        if filters:
            if "test_type" in filters and filters["test_type"]:
                if item.get("test_type") not in filters["test_type"]:
                    return 0.0
            if "remote_testing" in filters and filters["remote_testing"]:
                if item.get("remote_testing") != filters["remote_testing"]:
                    return 0.0

        name_lower = item.get("name", "").lower()
        desc_lower = item.get("description", "").lower()
        keywords = [k.lower() for k in item.get("keywords", [])]
        categories = [c.lower() for c in item.get("categories", [])]
        full_text = item.get("full_text", "").lower()

        # Exact name match (highest weight)
        for term in query_terms:
            if term in name_lower:
                score += 10.0

        # Keyword match
        for term in query_terms:
            for keyword in keywords:
                if term in keyword or keyword in term:
                    score += 5.0
                    break

        # Category match
        for term in query_terms:
            for cat in categories:
                if term in cat or cat in term:
                    score += 3.0
                    break

        # Description match
        for term in query_terms:
            if len(term) > 2 and term in desc_lower:
                score += 2.0

        # Semantic matching for common patterns
        score += self._semantic_boost(query_lower, item)

        return score

    def _semantic_boost(self, query: str, item: Dict) -> float:
        """Provide semantic score boosts for common patterns."""
        boost = 0.0
        name = item.get("name", "").lower()
        keywords = [k.lower() for k in item.get("keywords", [])]
        categories = [c.lower() for c in item.get("categories", [])]
        test_type = item.get("test_type", "")

        # Role-based matching
        role_mappings = {
            "developer": ["programming", "technology", "software", "developer"],
            "software engineer": ["programming", "technology", "developer"],
            "data scientist": ["data science", "machine learning", "python", "statistics", "analytics"],
            "data analyst": ["data", "analytics", "sql", "excel", "power bi", "tableau"],
            "data engineer": ["data", "sql", "python", "big data", "hadoop", "spark"],
            "devops": ["devops", "docker", "kubernetes", "ci/cd", "aws", "azure", "linux"],
            "frontend": ["frontend", "javascript", "react", "angular", "html", "css"],
            "backend": ["backend", "api", "server", "database", "java", "python", "node"],
            "fullstack": ["frontend", "backend", "javascript", "api", "database"],
            "qa": ["testing", "qa", "selenium", "manual testing", "quality"],
            "tester": ["testing", "qa", "selenium", "manual testing", "quality"],
            "manager": ["leadership", "management", "stakeholder", "decision making"],
            "leader": ["leadership", "management", "executive", "strategic"],
            "sales": ["sales", "negotiation", "client", "revenue", "prospecting"],
            "customer service": ["customer service", "call center", "client", "communication"],
            "accountant": ["accounting", "finance", "financial", "bookkeeping"],
            "analyst": ["analytical", "data", "analysis", "reasoning"],
            "admin": ["administrative", "clerical", "data entry", "typing", "office"],
            "executive": ["leadership", "management", "strategic", "executive"],
            "graduate": ["graduate", "entry level", "general ability"],
            "intern": ["entry level", "general ability", "screening"],
            "engineer": ["engineering", "technical", "mechanical", "design"],
            "designer": ["design", "creative", "spatial", "visualization"],
            "project manager": ["project management", "planning", "stakeholder", "risk"],
            "consultant": ["analytical", "communication", "problem solving", "client"],
            "marketer": ["marketing", "digital marketing", "seo", "social media"],
        }

        for role, signals in role_mappings.items():
            if role in query:
                for signal in signals:
                    if signal in " ".join(keywords + categories) or signal in name:
                        boost += 3.0
                        break

        # Skill-based matching
        skill_to_assessment = {
            "stakeholder": ["opq", "personality", "communication", "interpersonal"],
            "communication": ["verbal", "opq", "personality", "english", "communication"],
            "problem solving": ["reasoning", "inductive", "deductive", "critical thinking"],
            "analytical": ["numerical", "reasoning", "inductive", "deductive", "analytical"],
            "teamwork": ["opq", "personality", "interpersonal"],
            "leadership": ["opq", "mbq", "leadership", "management", "sjt"],
            "attention to detail": ["checking", "attention to detail", "accuracy"],
            "numerical": ["numerical", "calculation", "math"],
            "coding": ["programming", "developer", "software"],
            "programming": ["programming", "developer", "software"],
        }

        for skill, assessment_signals in skill_to_assessment.items():
            if skill in query:
                for signal in assessment_signals:
                    if signal in name or signal in " ".join(keywords):
                        boost += 4.0
                        break

        # Seniority-based matching
        if any(s in query for s in ["senior", "experienced", "lead", "principal"]):
            if any(s in name or s in " ".join(keywords) for s in ["senior", "management", "advanced", "reasoning"]):
                boost += 2.0
        if any(s in query for s in ["junior", "entry", "graduate", "intern", "fresher"]):
            if any(s in name or s in " ".join(keywords) for s in ["graduate", "entry level", "general", "basic"]):
                boost += 2.0

        # Type-based boosts
        if "personality" in query and test_type == "P":
            boost += 5.0
        if "cognitive" in query and test_type == "A":
            boost += 5.0
        if "technical" in query and test_type == "K":
            boost += 3.0
        if "behavioral" in query and test_type == "B":
            boost += 5.0
        if "situational" in query and test_type == "B":
            boost += 5.0

        return boost

    def get_item_by_name(self, name: str) -> Optional[Dict]:
        """Find a catalog item by exact or fuzzy name match."""
        name_lower = name.lower()
        # Exact match
        for item in self.items:
            if item["name"].lower() == name_lower:
                return item
        # Substring match
        for item in self.items:
            if name_lower in item["name"].lower() or item["name"].lower() in name_lower:
                return item
        return None

    def get_items_by_names(self, names: List[str]) -> List[Dict]:
        """Find multiple catalog items by name."""
        results = []
        for name in names:
            item = self.get_item_by_name(name)
            if item:
                results.append(item)
        return results

    def validate_recommendations(self, recommendations: List[Dict]) -> List[Dict]:
        """Validate that all recommendations exist in the catalog."""
        valid = []
        for rec in recommendations:
            # Find matching catalog item
            item = self.get_item_by_name(rec.get("name", ""))
            if item:
                valid.append({
                    "name": item["name"],
                    "url": item["url"],
                    "test_type": item["test_type"],
                })
            else:
                # Try URL matching
                for cat_item in self.items:
                    if rec.get("url") and cat_item["url"] == rec["url"]:
                        valid.append({
                            "name": cat_item["name"],
                            "url": cat_item["url"],
                            "test_type": cat_item["test_type"],
                        })
                        break
        return valid

    def to_recommendations(self, items: List[Dict]) -> List[Recommendation]:
        """Convert catalog items to Recommendation objects."""
        return [
            Recommendation(
                name=item["name"],
                url=item["url"],
                test_type=item["test_type"],
            )
            for item in items
        ]


# Singleton instance
catalog_manager = CatalogManager()