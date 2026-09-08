"""Report integrity: tamper-evident hash chain for audit reports.

N1 (2026-09-08): audit reports carry a SHA-256 content hash so a report
cannot be silently altered — enterprises treat reports as evidence.
"""

import hashlib
import json
import re


ALGORITHM = "sha256"


def _canonical(data: dict) -> str:
    """Canonical JSON string for hashing (stable key order)."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def hash_content(content: str) -> str:
    """SHA-256 hex digest of content bytes."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def hash_audit_result(result: dict) -> str:
    """Hash an audit result dict (canonical JSON)."""
    return hash_content(_canonical(result))


def chain_hash(prev_hash: str, content_hash: str) -> str:
    """Chain two hashes: h(prev_hash + content_hash)."""
    return hash_content(prev_hash + content_hash)


def build_integrity_block(result: dict, prev_hash: str | None = None, document_hash: str | None = None) -> dict:
    """Build the integrity block embedded in a report.

    Args:
        result: the audit result dict (all layers).
        prev_hash: optional previous report hash to build a chain.
        document_hash: SHA-256 of the report HTML *without* the integrity meta
            tag (computed by the caller before embedding). If None, falls back
            to the result hash only.
    Returns:
        dict with algorithm, result_hash, document_hash (if any),
        prev_hash (if any), report_hash.
    """
    result_hash = hash_audit_result(result)
    seed = _canonical({
        "result_hash": result_hash,
        "document_hash": document_hash or "",
        "prev_hash": prev_hash or "",
    })
    report_hash = hash_content(seed)
    block = {
        "algorithm": ALGORITHM,
        "result_hash": result_hash,
        "report_hash": report_hash,
    }
    if document_hash:
        block["document_hash"] = document_hash
    if prev_hash:
        block["prev_hash"] = prev_hash
    return block


INTEGRITY_META_RE = re.compile(
    r"<meta name=\"agentlens-integrity\" content='[^']*'[^>]*>"
)
INTEGRITY_VALUE_RE = re.compile(
    r"<meta name=\"agentlens-integrity\" content='([^']*)'"
)


def embed_integrity_meta(html: str, integrity: dict) -> str:
    """Inject the integrity meta tag into the generated HTML (before </head>).

    Uses single quotes for the content attribute because the payload is JSON
    (contains double quotes).
    """
    tag = (
        f'<meta name="agentlens-integrity" content=\''
        f'{json.dumps(integrity, sort_keys=True, separators=(",", ":"))}\'/>'
    )
    if "</head>" in html:
        return html.replace("</head>", f"{tag}</head>", 1)
    return f"{tag}\n{html}"


def extract_integrity_meta(html: str) -> dict | None:
    """Extract the integrity block from an HTML report."""
    m = INTEGRITY_VALUE_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def verify_report(html: str) -> dict:
    """Verify a report's integrity.

    Returns:
        dict with verified(bool), reason(str), expected(str), actual(str).
    """
    block = extract_integrity_meta(html)
    if block is None:
        return {
            "verified": False,
            "reason": "NO_INTEGRITY_META",
            "expected": None,
            "actual": None,
        }

    stripped = INTEGRITY_META_RE.sub("", html, count=1)

    # 1) Document integrity: hash of the HTML without the meta tag must match
    #    the embedded document_hash.
    doc_ok = True
    if block.get("document_hash"):
        doc_actual = hash_content(stripped)
        doc_ok = block["document_hash"] == doc_actual

    # 2) Report hash: re-derive the seed from embedded fields.
    expected = block.get("report_hash")
    seed = _canonical({
        "result_hash": block.get("result_hash"),
        "document_hash": block.get("document_hash", ""),
        "prev_hash": block.get("prev_hash", ""),
    })
    recomputed = hash_content(seed)
    seed_ok = expected == recomputed

    ok = doc_ok and seed_ok
    reason = "VERIFIED" if ok else ("DOC_HASH_MISMATCH" if not doc_ok else "REPORT_HASH_MISMATCH")
    return {
        "verified": ok,
        "reason": reason,
        "expected": expected,
        "actual": recomputed,
        "document_hash": block.get("document_hash"),
        "content_hash": hash_content(stripped),
    }
