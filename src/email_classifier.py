"""
AI-powered email classifier using LLM for configurable email classification.
Classifies emails into user-defined categories.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from .config import config
from .database import get_database_manager
from .llm import get_model_name, is_llm_available, llm_complete_structured
from .schemas import EmailClassification

logger = logging.getLogger(__name__)


class EmailClassifier:
    """AI-powered email classifier using configurable LLM providers."""

    def __init__(self):
        self.db_manager = get_database_manager()
        logger.info(f"EmailClassifier using {get_model_name()}")

    def is_available(self) -> bool:
        """Check if the LLM provider is available."""
        return is_llm_available()

    def classify_email(self, email_data: Dict[str, Any]) -> Tuple[str, float, str]:
        """
        Classify an email into one of the configured categories.

        Args:
            email_data: Dictionary containing email data (subject, sender, body, etc.)

        Returns:
            Tuple of (category, confidence, reason)
        """
        import time

        email_id = email_data.get("id", "unknown")

        try:
            logger.info(f"Starting LLM classification for email {email_id} - Model: {get_model_name()}")

            email_content = self._prepare_email_content(email_data)
            prompt = self._create_enhanced_classification_prompt(email_content)

            start_time = time.time()

            result = llm_complete_structured(
                EmailClassification,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
                system_prompt=self._get_system_prompt(),
            )

            elapsed_time = time.time() - start_time
            logger.info(f"LLM API call completed in {elapsed_time:.2f}s for email {email_id}")

            if result:
                logger.info(
                    f"Email {email_id} classified as {result.category.upper()} "
                    f"(confidence: {result.confidence:.2f}) - AI: {result.reason}"
                )
                return result.category, result.confidence, result.reason
            else:
                default = config.default_category.name
                logger.error(f"Failed to get classification for email {email_id}")
                return default, 0.0, "Failed to get AI response"

        except Exception as e:
            elapsed_time = time.time() - start_time if "start_time" in locals() else 0
            default = config.default_category.name
            logger.error(f"LLM API call failed for email {email_id} after {elapsed_time:.2f}s: {e}")
            return default, 0.0, f"Classification error: {e!s}"

    def _prepare_email_content(self, email_data: Dict[str, Any]) -> Dict[str, str]:
        """Prepare email content for classification."""
        return {
            "subject": email_data.get("subject", ""),
            "sender": email_data.get("sender", ""),
            "body": email_data.get("body", "")[:2000],
            "date": email_data.get("date", ""),
        }

    def _get_system_prompt(self) -> str:
        """Get system prompt with learning context for classification."""
        # Build category descriptions dynamically from config
        category_sections = []
        for i, cat in enumerate(config.CATEGORIES, 1):
            category_sections.append(f"{i}. **{cat.name.upper()}**: {cat.description}")

        categories_text = "\n\n".join(category_sections)
        default_name = config.default_category.name

        base_prompt = f"""You are an expert email classifier. Your task is to analyze email content and classify it into one of these categories:

{categories_text}

Consider these factors when classifying:
- Sender reputation and domain trustworthiness
- Subject line patterns and promotional language
- Email body content and intent
- Presence of unsubscribe links (newsletters usually have them)
- Personal vs. mass communication indicators

Be conservative - when in doubt between categories, prefer "{default_name}" over more restrictive categories.

CONFIDENCE SCORING GUIDELINES:
Assign a confidence score that reflects how certain you are:
- 0.95-1.0: Unambiguous. Strong, clear signals for this category.
- 0.85-0.94: Confident. Most indicators point to this category.
- 0.70-0.84: Uncertain. Mixed signals between categories.
- 0.50-0.69: Low confidence. Weak or contradictory signals.
- Below 0.50: Very uncertain.
Use the FULL range. Do NOT default to a single value like 0.80 for uncertain cases.
If genuinely torn between categories, use 0.70-0.75.
If the email clearly belongs to one category, use 0.90+."""

        # Add learning context if available
        if config.LEARNING_ENABLED:
            learning_context = self._get_learning_context()
            if learning_context:
                base_prompt += f"\n\n**LEARNING FROM USER FEEDBACK:**\n{learning_context}"

        return base_prompt

    def _get_learning_context(self) -> str:
        """Get learning context from recent user corrections."""
        try:
            recent_learning = self.db_manager.get_recent_learning(
                limit=config.MAX_LEARNING_CONTEXT, days=config.LEARNING_RETENTION_DAYS
            )

            if not recent_learning:
                return ""

            context_lines = ["Based on recent user corrections:"]
            for learning in recent_learning:
                context_lines.append(f"\u2022 {learning}")

            return "\n".join(context_lines)

        except Exception as e:
            logger.error(f"Error getting learning context: {e}")
            return ""

    def _create_enhanced_classification_prompt(self, email_content: Dict[str, str]) -> str:
        """Create enhanced classification prompt with sender statistics."""
        sender = email_content["sender"]
        sender_email, sender_domain = self._extract_sender_info(sender)

        sender_stats = self.db_manager.get_sender_statistics(sender_email, sender_domain)

        historical_context = self._build_historical_context(sender_email, sender_domain, sender_stats)

        category_list = ", ".join(config.category_names)

        prompt = f"""Please analyze this email and classify it as {category_list}:

SUBJECT: {email_content["subject"]}
SENDER: {email_content["sender"]}
DATE: {email_content["date"]}

{historical_context}

BODY:
{email_content["body"]}

Classify this email."""

        return prompt

    def _extract_sender_info(self, sender: str) -> tuple:
        """Extract email address and domain from sender field."""
        try:
            if "<" in sender and ">" in sender:
                email_part = sender.split("<")[1].split(">")[0].strip()
            else:
                email_part = sender.strip()

            if "@" in email_part:
                domain = email_part.split("@")[1].strip()
                return email_part, domain
            else:
                return sender, ""

        except Exception as e:
            logger.debug(f"Error extracting sender info from '{sender}': {e}")
            return sender, ""

    def _build_historical_context(self, sender_email: str, sender_domain: str, stats: Dict[str, int]) -> str:
        """Build historical context string for the prompt."""
        context_parts = []

        # Sender-specific history
        if stats["sender_total"] > 0:
            sender_history = []
            for cat_name in config.category_names:
                count = stats.get(f"sender_{cat_name}", 0)
                if count > 0:
                    sender_history.append(f"{count} {cat_name}")

            if sender_history:
                context_parts.append(
                    f"SENDER HISTORY: We received {', '.join(sender_history)} "
                    f"emails from this exact sender ({sender_email})"
                )

        # Domain-specific history
        if stats["domain_total"] > 0 and sender_domain:
            domain_history = []
            for cat_name in config.category_names:
                count = stats.get(f"domain_{cat_name}", 0)
                if count > 0:
                    domain_history.append(f"{count} {cat_name}")

            if domain_history:
                context_parts.append(
                    f"DOMAIN HISTORY: We received {', '.join(domain_history)} "
                    f"emails from this domain ({sender_domain})"
                )

        # Add guidance based on predominant category
        if context_parts and stats["sender_total"] > 0:
            max_cat = max(config.category_names, key=lambda c: stats.get(f"sender_{c}", 0))
            max_count = stats.get(f"sender_{max_cat}", 0)
            others_count = stats["sender_total"] - max_count
            if max_count > others_count:
                context_parts.append(f"NOTE: This sender has primarily sent {max_cat} emails in the past.")

        if context_parts:
            return "\n".join(context_parts) + "\n"
        else:
            return "SENDER HISTORY: No previous emails from this sender or domain.\n"

    def classify_with_fallback(self, email_data: Dict[str, Any]) -> Optional[Tuple[str, float, str]]:
        """
        Classify email using AI only. If AI fails, return None to skip the email.

        Args:
            email_data: Dictionary containing email data

        Returns:
            Tuple of (category, confidence, reason) or None if classification fails
        """
        default_name = config.default_category.name

        if self.is_available():
            category, confidence, reason = self.classify_email(email_data)

            # Get threshold for this category from config
            cat_config = config.category_map.get(category)
            if cat_config and confidence >= cat_config.threshold:
                return category, confidence, f"AI: {reason}"
            else:
                # Low confidence - classify as default (safe fallback)
                logger.warning(
                    f"Low confidence AI classification: {category} ({confidence:.2f}), "
                    f"defaulting to {default_name}"
                )
                return default_name, confidence, f"AI: {reason} (Low confidence fallback)"

        # AI not available - skip email so it can be retried next cycle
        logger.warning("LLM not available, skipping email classification (will retry next cycle)")
        return None
