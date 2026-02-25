"""
Low-level IMAP operations and MIME parsing utilities.

Stateless functions that wrap raw imaplib calls and email parsing.
Each function takes an IMAP client as its first argument and performs
a single, focused operation.
"""

import email
import hashlib
import imaplib
import logging
import re
import ssl
from email.header import decode_header as _stdlib_decode_header
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def connect_ssl(
    host: str, port: int, username: str, password: str
) -> imaplib.IMAP4_SSL:
    """Create an authenticated IMAP4_SSL connection."""
    context = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(host, port, ssl_context=context)
    result = client.login(username, password)
    if result[0] != "OK":
        raise imaplib.IMAP4.error(f"Login failed: {result[1]}")
    return client


def connect_plain(
    host: str, port: int, username: str, password: str
) -> imaplib.IMAP4:
    """Create an authenticated plain IMAP4 connection."""
    client = imaplib.IMAP4(host, port)
    result = client.login(username, password)
    if result[0] != "OK":
        raise imaplib.IMAP4.error(f"Login failed: {result[1]}")
    return client


def disconnect(client) -> None:
    """Logout from the IMAP server."""
    client.logout()


def is_alive(client) -> bool:
    """Check connection health via NOOP."""
    if client is None:
        return False
    try:
        return client.noop()[0] == "OK"
    except Exception:
        return False


def detect_separator(client) -> str:
    """Detect the IMAP folder hierarchy separator via LIST (RFC 3501 section 6.3.8).

    Returns the separator character (e.g. '.' or '/'), falling back to '.'.
    """
    try:
        result = client.list('""', '""')
        if result[0] == "OK" and result[1]:
            raw = result[1][0]
            line = raw.decode() if isinstance(raw, bytes) else str(raw)
            match = re.search(r'\) "(.)" ', line)
            if match:
                sep = match.group(1)
                logger.info(f"Detected IMAP hierarchy separator: '{sep}'")
                return sep
            if ") NIL " in line:
                logger.warning(
                    "IMAP server reports NIL hierarchy separator, using '.' as fallback"
                )
    except Exception as e:
        logger.warning(f"Failed to detect IMAP hierarchy separator: {e}")

    logger.info("Using fallback IMAP hierarchy separator: '.'")
    return "."


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------


def select_folder(client, folder: str) -> bool:
    """Select an IMAP folder. Returns True on success."""
    result = client.select(folder)
    if result[0] != "OK":
        logger.error(f"Failed to select folder {folder}: {result[1]}")
        return False
    return True


def create_folder(client, folder: str) -> bool:
    """Create an IMAP folder. Returns True on success."""
    result = client.create(folder)
    if result[0] != "OK":
        logger.error(f"Failed to create folder {folder}: {result[1]}")
        return False
    logger.info(f"Created folder: {folder}")
    return True


def folder_exists(client, folder: str) -> bool:
    """Check if a folder exists using the LIST command."""
    result = client.list('""', folder)
    if result[0] != "OK":
        return False
    for entry in result[1] or []:
        if not entry:
            continue
        line = entry.decode() if isinstance(entry, bytes) else str(entry)
        if f'"{folder}"' in line or line.endswith(f" {folder}"):
            return True
    return False


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_since(client, since_date: str) -> List[bytes]:
    """UID SEARCH SINCE <date>. Returns list of UIDs."""
    result = client.uid("search", None, f"SINCE {since_date}")
    if result[0] != "OK":
        logger.error(f"SEARCH SINCE failed: {result[1]}")
        return []
    return result[1][0].split() if result[1][0] else []


def search_by_message_id(client, message_id: str) -> List[bytes]:
    """UID SEARCH by Message-ID header. Returns list of UIDs."""
    result = client.uid("search", None, f'HEADER Message-ID "{message_id}"')
    if result[0] != "OK" or not result[1][0]:
        return []
    return result[1][0].split()


def search_by_subject_sender(
    client, subject: str, sender: str
) -> List[bytes]:
    """UID SEARCH by SUBJECT and FROM. Returns list of UIDs."""
    subject_escaped = subject.replace('"', '\\"')
    sender_escaped = sender.replace('"', '\\"')
    result = client.uid(
        "search", None, f'SUBJECT "{subject_escaped}" FROM "{sender_escaped}"'
    )
    if result[0] != "OK" or not result[1][0]:
        return []
    return result[1][0].split()


def fetch_message_id_header(client, uid: bytes) -> str:
    """Fetch only the Message-ID header for a single UID."""
    res = client.uid(
        "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
    )
    if res[0] != "OK" or not res[1]:
        return ""
    for part in res[1]:
        if (
            isinstance(part, tuple)
            and len(part) >= 2
            and isinstance(part[1], bytes)
        ):
            header_text = part[1].decode("utf-8", errors="ignore")
            msg = email.message_from_string(header_text)
            return msg.get("Message-ID", "").strip()
    return ""


def uid_exists(client, uid: str) -> bool:
    """Verify that a UID still exists in the currently selected folder."""
    try:
        result = client.uid("fetch", uid, "(FLAGS)")
        return result[0] == "OK" and result[1] and result[1][0] is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _parse_flags(response_str: str) -> list:
    """Extract FLAGS from a FETCH response line."""
    match = re.search(r"FLAGS \(([^)]*)\)", response_str)
    if match:
        return [f.strip() for f in match.group(1).split() if f.strip()]
    return []


def _parse_internaldate(response_str: str) -> Optional[str]:
    """Extract INTERNALDATE from a FETCH response line."""
    match = re.search(r'INTERNALDATE "([^"]*)"', response_str)
    return match.group(1) if match else None


def fetch_email_full(client, email_uid: bytes) -> Optional[Dict[str, Any]]:
    """Fetch full email data (headers, body, flags, INTERNALDATE) using BODY.PEEK."""
    try:
        result = client.uid(
            "fetch",
            email_uid,
            "(FLAGS INTERNALDATE BODY.PEEK[HEADER] BODY.PEEK[TEXT])",
        )
        if result[0] != "OK":
            logger.error(f"Failed to fetch email UID {email_uid}: {result[1]}")
            return None

        flags = []
        internaldate = None
        header_content = b""
        body_content = b""

        for part in result[1]:
            if isinstance(part, tuple) and len(part) >= 2:
                resp = (
                    part[0].decode()
                    if isinstance(part[0], bytes)
                    else str(part[0])
                )
                if "FLAGS" in resp:
                    flags = _parse_flags(resp)
                if "INTERNALDATE" in resp:
                    internaldate = _parse_internaldate(resp)
                if isinstance(part[1], bytes):
                    if (
                        b"HEADER" in part[0]
                        if isinstance(part[0], bytes)
                        else "HEADER" in str(part[0])
                    ):
                        header_content = part[1]
                    elif (
                        b"TEXT" in part[0]
                        if isinstance(part[0], bytes)
                        else "TEXT" in str(part[0])
                    ):
                        body_content = part[1]

        # Fallback: RFC822.PEEK
        if not header_content and not body_content:
            logger.debug(
                f"Structured fetch failed for UID {email_uid}, trying RFC822.PEEK"
            )
            result = client.uid(
                "fetch", email_uid, "(FLAGS INTERNALDATE RFC822.PEEK)"
            )
            if result[0] != "OK" or not result[1] or not result[1][0]:
                logger.error(
                    f"RFC822.PEEK fallback also failed for UID {email_uid}"
                )
                return None

            fetch_data = result[1][0]
            resp = (
                fetch_data[0].decode()
                if isinstance(fetch_data[0], bytes)
                else str(fetch_data[0])
            )
            if not internaldate and "INTERNALDATE" in resp:
                internaldate = _parse_internaldate(resp)
            flags = _parse_flags(resp)

            if len(fetch_data) > 1 and isinstance(fetch_data[1], bytes):
                email_message = email.message_from_bytes(fetch_data[1])
            else:
                logger.error(
                    f"No email content in RFC822.PEEK response for UID {email_uid}"
                )
                return None
        else:
            email_message = email.message_from_bytes(
                header_content + b"\r\n\r\n" + body_content
            )

        subject = decode_header(email_message.get("Subject", ""))
        sender = decode_header(email_message.get("From", ""))
        body = extract_body(email_message)
        date = email_message.get("Date", "")
        message_id = email_message.get("Message-ID", "")
        content_id = generate_content_id(subject, sender, body, date)
        is_unread = "\\Seen" not in flags

        email_data = {
            "content_id": content_id,
            "imap_uid": email_uid.decode(),
            "id": content_id,
            "message_id": message_id,
            "subject": subject,
            "sender": sender,
            "date": date,
            "body": body,
            "raw_message": email_message,
            "flags": flags,
            "internaldate": internaldate,
            "is_unread": is_unread,
        }

        logger.debug(
            f"Fetched email {content_id[:8]}... flags={flags}, "
            f"unread={is_unread}, internaldate={internaldate}"
        )
        return email_data

    except Exception as e:
        logger.error(f"Error fetching email data for UID {email_uid}: {e}")
        return None


def fetch_headers_only(
    client, email_uid: bytes
) -> Optional[Dict[str, Any]]:
    """Fetch only headers for quick content_id generation."""
    try:
        result = client.uid(
            "fetch", email_uid, "(FLAGS BODY.PEEK[HEADER])"
        )
        if result[0] != "OK":
            logger.error(
                f"Failed to fetch headers for UID {email_uid}: {result[1]}"
            )
            return None

        if not result[1] or not result[1][0]:
            logger.error(f"No data returned for UID {email_uid}")
            return None

        flags = []
        header_content = b""

        for part in result[1]:
            if isinstance(part, tuple) and len(part) >= 2:
                resp = (
                    part[0].decode()
                    if isinstance(part[0], bytes)
                    else str(part[0])
                )
                if "FLAGS" in resp:
                    flags = _parse_flags(resp)
                if isinstance(part[1], bytes):
                    header_content = part[1]

        if not header_content:
            logger.error(f"No header content for UID {email_uid}")
            return None

        email_message = email.message_from_bytes(header_content)
        subject = decode_header(email_message.get("Subject", ""))
        sender = decode_header(email_message.get("From", ""))
        date = email_message.get("Date", "")
        message_id = email_message.get("Message-ID", "")
        content_id = generate_content_id(subject, sender, "", date)

        return {
            "content_id": content_id,
            "imap_uid": email_uid.decode(),
            "subject": subject,
            "sender": sender,
            "date": date,
            "message_id": message_id,
            "flags": flags,
            "headers_only": True,
        }

    except Exception as e:
        logger.error(f"Error fetching headers for UID {email_uid}: {e}")
        return None


# ---------------------------------------------------------------------------
# Move / Flags
# ---------------------------------------------------------------------------


def move_using_append(
    client,
    imap_uid: str,
    destination: str,
    flags: list,
    raw_message,
    internaldate: Optional[str] = None,
) -> bool:
    """Move email via APPEND + DELETE with flag and date preservation."""
    try:
        flags_str = " ".join(flags) if flags else ""

        if hasattr(raw_message, "as_bytes"):
            message_bytes = raw_message.as_bytes()
        elif hasattr(raw_message, "as_string"):
            message_bytes = raw_message.as_string().encode("utf-8")
        else:
            message_bytes = str(raw_message).encode("utf-8")

        formatted_date = (
            format_internaldate(internaldate) if internaldate else None
        )

        if formatted_date:
            logger.info(
                f"APPEND move UID {imap_uid} with INTERNALDATE: {formatted_date}"
            )
        else:
            logger.warning(
                f"APPEND move UID {imap_uid} without INTERNALDATE (will use server time)"
            )

        append_result = client.append(
            destination, flags_str, formatted_date, message_bytes
        )
        if append_result[0] != "OK":
            logger.error(f"APPEND failed: {append_result[1]}")
            return False

        return _mark_deleted_and_expunge(client, imap_uid)

    except Exception as e:
        logger.error(f"Error in APPEND move for UID {imap_uid}: {e}")
        return False


def move_using_copy(client, imap_uid: str, destination: str) -> bool:
    """Move email via COPY + DELETE (flags may not be perfectly preserved)."""
    try:
        copy_result = client.uid("copy", imap_uid, destination)
        if copy_result[0] != "OK":
            error_msg = str(copy_result[1])
            logger.error(f"COPY failed for UID {imap_uid}: {error_msg}")
            if any(
                err in error_msg.lower()
                for err in [
                    "invalid messageset",
                    "no such message",
                    "expunged",
                ]
            ):
                raise Exception(f"UID-related COPY error: {error_msg}")
            return False

        return _mark_deleted_and_expunge(client, imap_uid)

    except Exception as e:
        logger.error(f"Error in COPY move for UID {imap_uid}: {e}")
        return False


def _mark_deleted_and_expunge(client, imap_uid: str) -> bool:
    """Mark a UID as \\Deleted and expunge."""
    store_result = client.uid("store", imap_uid, "+FLAGS", "\\Deleted")
    if store_result[0] != "OK":
        error_msg = str(store_result[1])
        if any(
            err in error_msg.lower()
            for err in ["invalid messageset", "no such message", "expunged"]
        ):
            logger.warning(f"Original UID {imap_uid} may already be gone")
            return True
        logger.error(
            f"Failed to mark UID {imap_uid} as deleted: {store_result[1]}"
        )
        return False
    client.expunge()
    return True


def mark_as_read(
    client, uid: str, folder: Optional[str] = None
) -> bool:
    """Set the \\Seen flag on an email."""
    try:
        if folder and not select_folder(client, folder):
            return False
        result = client.uid("store", uid, "+FLAGS", "\\Seen")
        return result[0] == "OK"
    except Exception as e:
        logger.error(f"Error marking UID {uid} as read: {e}")
        return False


# ---------------------------------------------------------------------------
# MIME Parsing (stateless utilities)
# ---------------------------------------------------------------------------


def decode_header(header: str) -> str:
    """Decode an RFC 2047 encoded email header."""
    if not header:
        return ""
    try:
        parts = _stdlib_decode_header(header)
        decoded = ""
        for part, encoding in parts:
            if isinstance(part, bytes):
                decoded += part.decode(encoding or "utf-8")
            else:
                decoded += part
        return decoded
    except Exception as e:
        logger.error(f"Error decoding header: {e}")
        return header


def extract_body(email_message) -> str:
    """Extract plain-text body from an email.message.Message."""
    try:
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", errors="ignore")
        else:
            payload = email_message.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="ignore")
        return ""
    except Exception as e:
        logger.error(f"Error extracting email body: {e}")
        return ""


def format_internaldate(internaldate: str) -> Optional[str]:
    """Normalize an INTERNALDATE string for IMAP APPEND."""
    if not internaldate:
        return None
    try:
        from datetime import datetime as _dt

        imap_pattern = (
            r"^\d{1,2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}$"
        )
        if re.match(imap_pattern, internaldate):
            return internaldate

        try:
            dt = _dt.strptime(internaldate, "%d-%b-%Y %H:%M:%S %z")
            return dt.strftime("%d-%b-%Y %H:%M:%S %z")
        except ValueError:
            try:
                dt = _dt.strptime(internaldate, "%d-%b-%Y %H:%M:%S")
                return dt.strftime("%d-%b-%Y %H:%M:%S +0000")
            except ValueError:
                logger.warning(
                    f"Could not parse INTERNALDATE: {internaldate}, using as-is"
                )
                return internaldate

    except Exception as e:
        logger.warning(
            f"Error formatting INTERNALDATE {internaldate}: {e}"
        )
        return internaldate


def generate_content_id(
    subject: str, sender: str, body: str, date: str
) -> str:
    """Generate a content-based MD5 ID from email fields."""
    content = f"{subject}|{sender}|{body}|{date}"
    return hashlib.md5(
        content.encode("utf-8"), usedforsecurity=False
    ).hexdigest()
