"""
Learning summary generator for creating learning insights from user corrections.
"""

import logging
from typing import Any, Dict, Optional

from ..config import config
from ..llm import get_model_name, is_llm_available, llm_complete

logger = logging.getLogger(__name__)


class LearningGenerator:
    """Generates learning summaries from user folder corrections to improve future classifications."""

    def __init__(self):
        logger.debug(f"LearningGenerator using {get_model_name()}")

    def is_available(self) -> bool:
        """Check if the LLM provider is available."""
        return is_llm_available()

    def generate_learning_summary(
        self, email_data: Dict[str, Any], source_folder: str, target_classification: str
    ) -> Optional[str]:
        """
        Generate a learning summary from a user folder correction.

        Args:
            email_data: Dictionary containing email data
            source_folder: Folder the email came from ("INBOX", "Suspicious", "Newsletters")
            target_classification: What the email should be classified as ("regular", "spam", "newsletter")

        Returns:
            Learning summary string or None if generation fails
        """
        try:
            email_id = email_data.get("id", "unknown")
            logger.info(f"Generating learning summary for email {email_id}: {source_folder} → {target_classification}")

            # Prepare email content for analysis
            email_content = self._prepare_email_content(email_data)

            # Create learning prompt based on correction type
            prompt = self._create_learning_prompt(email_content, source_folder, target_classification)

            # Call LLM for plain text summary
            result = llm_complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
                system_prompt=self._get_system_prompt(source_folder, target_classification),
            )

            if result and result.strip():
                summary = result.strip()
                logger.info(f"Generated learning summary for email {email_id}: {summary[:100]}...")
                return summary
            else:
                logger.error(f"Failed to generate learning summary for email {email_id}")
                return None

        except Exception as e:
            logger.error(f"Learning summary generation failed for email {email_id}: {e}")
            return None

    def _prepare_email_content(self, email_data: Dict[str, Any]) -> Dict[str, str]:
        """Prepare email content for learning analysis."""
        return {
            "subject": email_data.get("subject", ""),
            "sender": email_data.get("sender", ""),
            "body": email_data.get("body", "")[:1500],  # Limit body for prompt efficiency
            "date": email_data.get("date", ""),
        }

    def _get_system_prompt(self, source_folder: str, target_classification: str) -> str:
        """Get system prompt based on the type of correction."""
        default_name = config.default_category.name

        if target_classification == default_name:
            # False positive correction (wrongly classified, should be default)
            return f"""You are analyzing an email that was incorrectly classified but should be {default_name.upper()}.

Generate a concise learning rule explaining why similar emails should be classified as {default_name.upper()} in the future, focusing on:

1. **Sender Legitimacy**: What makes this sender trustworthy?
2. **Content Patterns**: What content indicates legitimate communication?
3. **Context Clues**: What suggests personal/business relevance?
4. **Classification Rule**: What pattern should guide future similar emails?

Be specific but concise. Focus on actionable patterns that can help avoid similar misclassifications."""

        else:
            return f"""You are analyzing an email that was incorrectly classified but should be {target_classification.upper()}.

Generate a concise learning rule explaining why similar emails should be classified as {target_classification.upper()} in the future, focusing on:

1. **Sender Analysis**: What characteristics identify this type of email?
2. **Content Patterns**: What patterns indicate {target_classification} content?
3. **Key Indicators**: What should trigger {target_classification} classification?
4. **Classification Rule**: What pattern should guide future similar emails?

Be specific but concise. Focus on actionable patterns that can help identify similar {target_classification} emails."""

    def _create_learning_prompt(
        self, email_content: Dict[str, str], source_folder: str, target_classification: str
    ) -> str:
        """Create learning prompt for the email."""
        correction_type = f"{source_folder} → {target_classification}"

        return f"""Email that was corrected ({correction_type}):

SUBJECT: {email_content["subject"]}
SENDER: {email_content["sender"]}
DATE: {email_content["date"]}

BODY:
{email_content["body"]}

Generate a learning rule for future classifications:"""
