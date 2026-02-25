"""
Daily email summary generator for Email-Buddy.
Composes a structured HTML statistics report with LLM-generated tips
and delivers it to INBOX via IMAP APPEND.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from .config import config
from .database import get_database_manager
from .email_client import EmailClient
from .llm import is_llm_available, llm_complete
from .models import DailySummary, ProcessedEmail

logger = logging.getLogger(__name__)

# Category accent colors for the HTML template
_CATEGORY_COLORS: Dict[str, str] = {
    "spam": "#EF4444",
    "newsletter": "#F59E0B",
    "regular": "#22C55E",
}
_DEFAULT_CATEGORY_COLOR = "#6366F1"


class DailySummaryGenerator:
    """Generates and delivers daily email processing summaries."""

    def __init__(self):
        self.db_manager = get_database_manager()

    def is_summary_due(self) -> bool:
        """Check if a daily summary should be generated now."""
        if not config.DAILY_SUMMARY_ENABLED:
            return False

        if datetime.now().hour < config.DAILY_SUMMARY_HOUR:
            return False

        return not self.db_manager.is_summary_sent_today()

    def generate_and_send(self) -> bool:
        """Generate the daily summary and deliver it to INBOX.

        Returns:
            True if the summary was successfully generated, False otherwise.
        """
        logger.info("Generating daily email summary...")

        try:
            # Determine the period start
            since = self._get_period_start()
            now = datetime.now()

            # Gather statistics
            stats = self.db_manager.get_summary_statistics_since(since)

            if stats["total_processed"] == 0:
                logger.info("No emails processed since last summary, recording empty summary")
                self._save_summary_record(since, now, stats, narrative=None, delivered=False)
                return True

            # Build structured stats context
            ctx = self._build_stats_context(stats, since)

            # Load previous summaries and recent email details for context
            previous_summaries = self.db_manager.get_recent_summaries(limit=7)
            recent_emails = self.db_manager.get_recent_email_details_since(since)

            # Generate LLM tips (optional, graceful fallback)
            narrative = self._generate_narrative(stats, previous_summaries, recent_emails)

            # Render HTML email body
            body = self._render_html(ctx, narrative)

            # Compose and deliver email
            today = now.strftime("%Y-%m-%d")
            subject = f"[Email-Buddy] Daily Summary - {today}"

            delivered = self._deliver_to_inbox(subject, body)

            # Save summary record (always, even if delivery failed)
            self._save_summary_record(since, now, stats, narrative, delivered)

            if delivered:
                logger.info("Daily summary delivered successfully")
            else:
                logger.error("Failed to deliver daily summary to INBOX")

            return delivered

        except Exception as e:
            logger.error(f"Error generating daily summary: {e}")
            return False

    def _get_period_start(self) -> datetime:
        """Get the start of the summary period."""
        recent = self.db_manager.get_recent_summaries(limit=1)
        if recent:
            return datetime.fromisoformat(recent[0].period_end)
        return datetime.now() - timedelta(hours=24)

    def _build_stats_context(self, stats: Dict[str, Any], since: datetime) -> Dict[str, Any]:
        """Build a structured context dict from raw statistics."""
        now = datetime.now()
        period_hours = (now - since).total_seconds() / 3600

        classifications = []
        for classification, count in stats.get("by_classification", {}).items():
            avg_conf = stats.get("average_confidence", {}).get(classification, 0)
            classifications.append({
                "name": classification,
                "count": count,
                "avg_confidence": avg_conf,
            })

        senders = []
        for sender, count in stats.get("top_senders", {}).items():
            display = sender[:60] + "..." if len(sender) > 60 else sender
            senders.append({"address": display, "count": count})

        return {
            "period_start": since.strftime("%Y-%m-%d %H:%M"),
            "period_end": now.strftime("%Y-%m-%d %H:%M"),
            "period_hours": period_hours,
            "total_processed": stats["total_processed"],
            "classifications": classifications,
            "senders": senders,
            "learning_entries": stats.get("learning_entries", 0),
        }

    def _generate_narrative(
        self,
        stats: Dict[str, Any],
        previous_summaries: List[DailySummary],
        recent_emails: Optional[List] = None,
    ) -> Optional[str]:
        """Generate personalized LLM tips from statistics and email details."""
        if not is_llm_available():
            logger.info("LLM not available, skipping tips generation")
            return None

        try:
            language = config.DAILY_SUMMARY_LANGUAGE

            system_prompt = (
                "You are a personal email assistant. "
                f"You MUST respond entirely in {language}. "
                "You are given today's email list and statistics from Email-Buddy, "
                "an automated email classifier.\n"
                "Write 3-5 concise bullet points as a helpful assistant would. Focus on:\n"
                "- Important emails classified as 'regular' that the user should read or reply to\n"
                "- Emails that might have been misclassified "
                "(low confidence, unusual sender for the category)\n"
                "- Notable patterns (new senders, recurring topics)\n"
                "Be specific: mention sender names and email subjects. "
                "Write naturally, as if briefing a colleague. "
                "Do NOT use labels like 'ATTENTION' or 'WARNING'.\n"
                "Use plain text bullet points starting with '- '."
            )

            # Build stats representation
            parts = [
                f"Today's statistics:\n"
                f"Total emails processed: {stats['total_processed']}\n"
                f"By classification: {stats.get('by_classification', {})}\n"
                f"Average confidence: {stats.get('average_confidence', {})}\n"
                f"Top senders: {stats.get('top_senders', {})}\n"
                f"Learning entries: {stats.get('learning_entries', 0)}"
            ]

            # Add individual email details for personalized tips
            if recent_emails:
                parts.append("\nRecent emails processed today:")
                for email in recent_emails:
                    parts.append(
                        f"  - [{email.classification}] (conf: {email.confidence:.2f}) "
                        f"From: {email.sender} | Subject: {email.subject}"
                    )

            # Add previous summaries for cross-referencing
            if previous_summaries:
                parts.append("\nPrevious days' data:")
                for summary in previous_summaries:
                    prev_stats = json.loads(summary.stats_json)
                    date = summary.generated_at[:10]
                    parts.append(
                        f"  {date}: {prev_stats.get('total_processed', 0)} emails, "
                        f"categories: {prev_stats.get('by_classification', {})}"
                    )

            narrative = llm_complete(
                messages=[{"role": "user", "content": "\n".join(parts)}],
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=500,
            )

            if narrative:
                logger.info("LLM tips generated successfully")
            return narrative

        except Exception as e:
            logger.warning(f"Failed to generate LLM tips: {e}")
            return None

    # ── Markdown Conversion ───────────────────────────────────────────

    @staticmethod
    def _markdown_to_html(text: str) -> str:
        """Convert simple LLM markdown (bullets and bold) to HTML."""
        if not text or not text.strip():
            return ""

        lines = text.split("\n")
        html_parts: list[str] = []
        in_list = False

        for line in lines:
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)

            stripped = line.strip()
            if not stripped:
                if in_list:
                    html_parts.append("</ul>")
                    in_list = False
                continue

            if stripped.startswith("- "):
                if not in_list:
                    html_parts.append(
                        '<ul style="margin:0;padding-left:20px;list-style-type:disc;">'
                    )
                    in_list = True
                item_text = stripped[2:].strip()
                html_parts.append(
                    f'<li style="margin-bottom:6px;">{item_text}</li>'
                )
            else:
                if in_list:
                    html_parts.append("</ul>")
                    in_list = False
                html_parts.append(f'<p style="margin:4px 0;">{stripped}</p>')

        if in_list:
            html_parts.append("</ul>")

        return "\n".join(html_parts)

    # ── HTML Rendering ─────────────────────────────────────────────────

    def _render_html(self, ctx: Dict[str, Any], narrative: Optional[str]) -> str:
        """Render the full HTML email from structured stats and optional narrative."""
        parts = [
            self._html_head(),
            self._html_header(ctx),
        ]
        if narrative:
            parts.append(self._html_tips_section(narrative))
        parts.append(self._html_stats_overview(ctx))
        parts.append(self._html_classification_cards(ctx))
        if ctx["senders"]:
            parts.append(self._html_senders_table(ctx))
        if ctx["learning_entries"] > 0:
            parts.append(self._html_learning_section(ctx))
        parts.append(self._html_footer())
        return "\n".join(parts)

    def _html_head(self) -> str:
        return (
            '<!DOCTYPE html>\n'
            '<html lang="en">\n'
            '<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            '</head>\n'
            '<body style="margin:0;padding:0;background-color:#f8f9fa;'
            "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;\">\n"
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="background-color:#f8f9fa;">\n'
            '<tr><td align="center" style="padding:20px 10px;">\n'
            '<table width="600" cellpadding="0" cellspacing="0" border="0" '
            'style="max-width:600px;width:100%;">'
        )

    def _html_header(self, ctx: Dict[str, Any]) -> str:
        return (
            '<tr><td style="background-color:#2c3e50;border-radius:8px 8px 0 0;'
            'padding:30px 30px 24px;">\n'
            '  <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;'
            'letter-spacing:0.3px;">Email-Buddy Daily Summary</h1>\n'
            f'  <p style="margin:8px 0 0;color:#bdc3c7;font-size:13px;">'
            f'{ctx["period_start"]} &mdash; {ctx["period_end"]} '
            f'({ctx["period_hours"]:.0f}h)</p>\n'
            '</td></tr>'
        )

    def _html_tips_section(self, narrative: str) -> str:
        content = self._markdown_to_html(narrative)
        return (
            '<tr><td style="padding:0;">\n'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0">\n'
            '<tr>\n'
            '  <td width="4" style="background-color:#2563EB;"></td>\n'
            '  <td style="background-color:#EFF6FF;padding:24px 26px;">\n'
            '    <p style="font-size:12px;font-weight:600;color:#2563EB;'
            'text-transform:uppercase;letter-spacing:1px;margin:0 0 12px;">'
            'Tips &amp; Alerts</p>\n'
            f'    <div style="font-size:14px;color:#1E40AF;line-height:1.6;">'
            f'{content}</div>\n'
            '  </td>\n'
            '</tr></table>\n'
            '</td></tr>'
        )

    def _html_stats_overview(self, ctx: Dict[str, Any]) -> str:
        return (
            '<tr><td style="background-color:#ffffff;padding:30px 30px;'
            'text-align:center;border-bottom:1px solid #e9ecef;">\n'
            '  <p style="color:#6c757d;font-size:12px;text-transform:uppercase;'
            'letter-spacing:1px;margin:0 0 8px;">Total Emails Processed</p>\n'
            f'  <p style="margin:0;font-size:48px;font-weight:700;color:#2c3e50;'
            f'line-height:1;">{ctx["total_processed"]}</p>\n'
            '</td></tr>'
        )

    def _html_classification_cards(self, ctx: Dict[str, Any]) -> str:
        if not ctx["classifications"]:
            return ""
        rows = []
        for c in ctx["classifications"]:
            color = _CATEGORY_COLORS.get(c["name"], _DEFAULT_CATEGORY_COLOR)
            conf_pct = f'{c["avg_confidence"]:.0%}'
            rows.append(
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="margin-bottom:8px;">\n'
                f'<tr>\n'
                f'  <td width="4" style="background-color:{color};"></td>\n'
                f'  <td style="padding:12px 16px;background-color:#f8f9fa;">\n'
                f'    <span style="font-weight:600;font-size:15px;color:#2c3e50;">'
                f'{c["name"].capitalize()}</span>\n'
                f'    <span style="float:right;font-weight:700;font-size:18px;'
                f'color:{color};">{c["count"]}</span>\n'
                f'    <br><span style="color:#6c757d;font-size:12px;">'
                f'avg confidence: {conf_pct}</span>\n'
                f'  </td>\n'
                f'</tr></table>'
            )
        return (
            '<tr><td style="background-color:#ffffff;padding:30px 30px;">\n'
            '  <p style="font-size:12px;font-weight:600;color:#6c757d;'
            'text-transform:uppercase;letter-spacing:1px;margin:0 0 16px;">'
            'Classification Breakdown</p>\n'
            + "\n".join(rows)
            + "\n</td></tr>"
        )

    def _html_senders_table(self, ctx: Dict[str, Any]) -> str:
        rows = []
        for i, s in enumerate(ctx["senders"]):
            bg = "#f8f9fa" if i % 2 == 0 else "#ffffff"
            rows.append(
                f'<tr style="background-color:{bg};">'
                f'<td style="padding:10px 14px;font-size:14px;color:#334155;'
                f'border-bottom:1px solid #e9ecef;">{s["address"]}</td>'
                f'<td style="padding:10px 14px;font-size:14px;color:#334155;'
                f'text-align:right;font-weight:600;border-bottom:1px solid #e9ecef;">'
                f'{s["count"]}</td>'
                f'</tr>'
            )
        return (
            '<tr><td style="background-color:#ffffff;padding:30px 30px;'
            'border-top:1px solid #e9ecef;">\n'
            '  <p style="font-size:12px;font-weight:600;color:#6c757d;'
            'text-transform:uppercase;letter-spacing:1px;margin:0 0 16px;">'
            'Top Senders</p>\n'
            '  <table width="100%" cellpadding="0" cellspacing="0" border="0">\n'
            + "\n".join(rows)
            + "\n  </table>\n</td></tr>"
        )

    def _html_learning_section(self, ctx: Dict[str, Any]) -> str:
        return (
            '<tr><td style="background-color:#ffffff;padding:24px 30px;'
            'border-top:1px solid #e9ecef;">\n'
            '  <p style="font-size:12px;font-weight:600;color:#6c757d;'
            'text-transform:uppercase;letter-spacing:1px;margin:0 0 12px;">'
            'Learning Activity</p>\n'
            f'  <p style="margin:0;font-size:14px;color:#334155;">'
            f'New learning entries: <strong>{ctx["learning_entries"]}</strong></p>\n'
            '</td></tr>'
        )

    def _html_footer(self) -> str:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            '<tr><td style="padding:20px 30px 10px;text-align:center;">\n'
            '  <p style="color:#94A3B8;font-size:12px;margin:0;">'
            'Generated by Email-Buddy</p>\n'
            f'  <p style="color:#94A3B8;font-size:12px;margin:4px 0 0;">'
            f'Report generated at {now_str}</p>\n'
            '</td></tr>\n'
            '</table>\n'
            '</td></tr></table>\n'
            '</body></html>'
        )

    # ── Delivery & Persistence ─────────────────────────────────────────

    def _deliver_to_inbox(self, subject: str, body: str) -> bool:
        """Compose an RFC 2822 message and APPEND it to INBOX."""
        try:
            summary_message_id = f"<summary-{datetime.now().strftime('%Y%m%d%H%M%S')}@email-buddy>"

            msg = MIMEText(body, "html", "utf-8")
            msg["From"] = "Email-Buddy <noreply@email-buddy>"
            msg["To"] = config.IMAP_USERNAME
            msg["Subject"] = subject
            msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
            msg["Message-ID"] = summary_message_id
            msg["X-Mailer"] = "Email-Buddy Daily Summary"

            message_bytes = msg.as_bytes()

            # Generate content_id matching the IMAP client's _generate_content_id pattern
            # (subject|sender|body|date) — use empty body since header-only check uses ""
            content_for_id = f"{subject}|Email-Buddy <noreply@email-buddy>||{msg['Date']}"
            content_id = hashlib.md5(content_for_id.encode("utf-8"), usedforsecurity=False).hexdigest()

            # Save ProcessedEmail record to prevent classifier from re-processing
            anti_classification_record = ProcessedEmail(
                email_id=content_id,
                message_id=summary_message_id,
                subject=subject,
                sender="Email-Buddy <noreply@email-buddy>",
                date_received=datetime.now().isoformat(),
                classification="summary",
                confidence=1.0,
                reason="Daily summary email — auto-excluded",
                folder_moved_to=None,
                processed_at=datetime.now().isoformat(),
                content_hash=content_id,
            )
            self.db_manager.save_processed_email(anti_classification_record)

            # IMAP APPEND to INBOX (no \Seen flag — appears as unread)
            client = EmailClient()
            if not client.connect():
                logger.error("Cannot connect to IMAP for summary delivery")
                return False

            try:
                result = client.imap_client.append(
                    config.INBOX_FOLDER,
                    "",
                    None,
                    message_bytes,
                )

                if result[0] == "OK":
                    logger.info(f"Summary email appended to {config.INBOX_FOLDER}")
                    return True
                else:
                    logger.error(f"IMAP APPEND failed: {result[1]}")
                    return False
            finally:
                client.disconnect()

        except Exception as e:
            logger.error(f"Error delivering summary email: {e}")
            return False

    def _save_summary_record(
        self,
        period_start: datetime,
        period_end: datetime,
        stats: Dict[str, Any],
        narrative: Optional[str],
        delivered: bool,
    ) -> None:
        """Save the summary record to the database."""
        summary = DailySummary(
            generated_at=datetime.now().isoformat(),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            total_processed=stats["total_processed"],
            stats_json=json.dumps(stats),
            narrative=narrative,
            delivered=delivered,
        )
        self.db_manager.save_daily_summary(summary)
