# agent.py
import json
import os
import re
import logging
from typing import List, Dict, Optional, Tuple
from models import Message, ChatResponse, Recommendation
from catalog import catalog_manager
from prompts import build_system_prompt

logger = logging.getLogger(__name__)

# LLM provider selection
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")  # groq, gemini, openrouter, openai


def get_llm_response(messages: List[Dict[str, str]], temperature: float = 0.3) -> str:
    """Get response from LLM provider."""

    if LLM_PROVIDER == "groq":
        return _call_groq(messages, temperature)
    elif LLM_PROVIDER == "gemini":
        return _call_gemini(messages, temperature)
    elif LLM_PROVIDER == "openrouter":
        return _call_openrouter(messages, temperature)
    elif LLM_PROVIDER == "openai":
        return _call_openai(messages, temperature)
    else:
        raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}")


def _call_groq(messages: List[Dict], temperature: float) -> str:
    """Call Groq API."""
    from groq import Groq

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
        messages=messages,
        temperature=temperature,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def _call_gemini(messages: List[Dict], temperature: float) -> str:
    """Call Google Gemini API."""
    import google.generativeai as genai

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))

    # Convert messages format for Gemini
    # Gemini uses a different format - combine system + conversation
    system_msg = ""
    conversation = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg = msg["content"]
        else:
            role = "user" if msg["role"] == "user" else "model"
            conversation.append({"role": role, "parts": [msg["content"]]})

    if system_msg and conversation:
        # Prepend system message to first user message
        conversation[0]["parts"][0] = f"[System Instructions]\n{system_msg}\n\n[User Message]\n{conversation[0]['parts'][0]}"

    chat = model.start_chat(history=conversation[:-1] if len(conversation) > 1 else [])
    response = chat.send_message(
        conversation[-1]["parts"][0],
        generation_config=genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=2000,
        ),
    )
    return response.text


def _call_openrouter(messages: List[Dict], temperature: float) -> str:
    """Call OpenRouter API."""
    import requests

    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2000,
        },
        timeout=25,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _call_openai(messages: List[Dict], temperature: float) -> str:
    """Call OpenAI API."""
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        temperature=temperature,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


class AssessmentAgent:
    """Conversational agent for SHL assessment recommendations."""

    def __init__(self):
        self.catalog = catalog_manager
        catalog_text = self.catalog.get_all_items_for_context()
        self.system_prompt = build_system_prompt(catalog_text)
        logger.info("Assessment agent initialized")

    def process_chat(self, messages: List[Message]) -> ChatResponse:
        """Process a chat request and return a response."""
        try:
            # Build LLM messages
            llm_messages = self._build_llm_messages(messages)

            # Get LLM response
            raw_response = get_llm_response(llm_messages)

            # Parse and validate response
            response = self._parse_response(raw_response)

            # Validate recommendations against catalog
            if response.recommendations:
                response.recommendations = self._validate_recommendations(response.recommendations)

            return response

        except Exception as e:
            logger.error(f"Error processing chat: {e}", exc_info=True)
            return ChatResponse(
                reply="I apologize, but I encountered an error processing your request. Could you please rephrase your question about SHL assessments?",
                recommendations=[],
                end_of_conversation=False,
            )

    def _build_llm_messages(self, messages: List[Message]) -> List[Dict]:
        """Build the message list for the LLM."""
        llm_messages = [{"role": "system", "content": self.system_prompt}]

        # Add conversation history
        for msg in messages:
            llm_messages.append({
                "role": msg.role.value,
                "content": msg.content,
            })

        return llm_messages

    def _parse_response(self, raw_response: str) -> ChatResponse:
        """Parse the LLM response into a ChatResponse."""
        # Try to extract JSON from the response
        try:
            # Clean up the response - remove markdown code blocks if present
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                # Remove markdown code block
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)

            data = json.loads(cleaned)

            reply = data.get("reply", "I'm here to help with SHL assessments. Could you tell me more about the role you're hiring for?")
            recommendations = data.get("recommendations", [])
            end_of_conversation = data.get("end_of_conversation", False)

            # Parse recommendations
            rec_objects = []
            if recommendations and isinstance(recommendations, list):
                for rec in recommendations:
                    if isinstance(rec, dict) and "name" in rec:
                        rec_objects.append(Recommendation(
                            name=rec.get("name", ""),
                            url=rec.get("url", ""),
                            test_type=rec.get("test_type", "K"),
                        ))

            return ChatResponse(
                reply=reply,
                recommendations=rec_objects,
                end_of_conversation=end_of_conversation,
            )

        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON response: {raw_response[:200]}")
            # Try to extract useful text anyway
            reply = raw_response.strip()
            if len(reply) > 500:
                reply = reply[:500] + "..."
            return ChatResponse(
                reply=reply,
                recommendations=[],
                end_of_conversation=False,
            )

    def _validate_recommendations(self, recommendations: List[Recommendation]) -> List[Recommendation]:
        """Validate and fix recommendations against the catalog."""
        validated = []
        for rec in recommendations:
            # Try to find the item in catalog
            item = self.catalog.get_item_by_name(rec.name)
            if item:
                validated.append(Recommendation(
                    name=item["name"],
                    url=item["url"],
                    test_type=item["test_type"],
                ))
            else:
                # Try fuzzy matching
                best_match = self._fuzzy_match(rec.name)
                if best_match:
                    validated.append(Recommendation(
                        name=best_match["name"],
                        url=best_match["url"],
                        test_type=best_match["test_type"],
                    ))
                else:
                    logger.warning(f"Could not find catalog item for: {rec.name}")

        # Deduplicate by name
        seen = set()
        deduped = []
        for rec in validated:
            if rec.name not in seen:
                seen.add(rec.name)
                deduped.append(rec)

        # Limit to 10
        return deduped[:10]

    def _fuzzy_match(self, name: str) -> Optional[Dict]:
        """Find best fuzzy match for an assessment name."""
        name_lower = name.lower().strip()
        best_score = 0
        best_item = None

        for item in self.catalog.items:
            item_name_lower = item["name"].lower()

            # Check for key term overlap
            name_terms = set(re.findall(r'\b\w+\b', name_lower))
            item_terms = set(re.findall(r'\b\w+\b', item_name_lower))

            # Remove common stopwords
            stopwords = {"the", "a", "an", "and", "or", "for", "in", "of", "to", "new", "test", "assessment"}
            name_terms -= stopwords
            item_terms -= stopwords

            if not name_terms or not item_terms:
                continue

            overlap = len(name_terms & item_terms)
            score = overlap / max(len(name_terms), len(item_terms))

            if score > best_score:
                best_score = score
                best_item = item

        if best_score >= 0.4:  # Threshold for fuzzy match
            return best_item
        return None


# Singleton
agent = AssessmentAgent()