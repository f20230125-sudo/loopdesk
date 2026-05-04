"""Version 1 offline handoff contract. Independently vendored in LoopDesk."""
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone


class HandoffError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(payload):
    return hashlib.sha256(canonical({k:v for k,v in payload.items() if k != "digest"}).encode("utf-8")).hexdigest()


def read_handoff(raw):
    if len(raw) > 48 * 1024:
        raise HandoffError("Handoff exceeds 48 KiB.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise HandoffError("Duplicate JSON keys are not accepted.")
            result[key] = value
        return result
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(HandoffError("Non-finite JSON number.")))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise HandoffError("Upload a valid UTF-8 JSON handoff.") from None
    required = {"schema_version", "source_system", "case_id", "revision", "review_status", "reviewed_at", "client_display_name", "scope", "assumptions", "followups", "source_references", "digest"}
    if not isinstance(obj, dict) or set(obj) != required:
        raise HandoffError("Unsupported handoff fields.")
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1 or obj["source_system"] != "ScopeDesk":
        raise HandoffError("Only ScopeDesk schema version 1 is supported.")
    def text(v, limit=160):
        return isinstance(v, str) and bool(v.strip()) and len(v) <= limit and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in v)
    if not text(obj["case_id"], 64) or not re.fullmatch(r"[a-zA-Z0-9_-]+", obj["case_id"]):
        raise HandoffError("Invalid case identity.")
    if type(obj["revision"]) is not int or not 1 <= obj["revision"] <= 1000000:
        raise HandoffError("Invalid revision number.")
    if obj["review_status"] not in ("Reviewed", "Reviewed with assumptions") or not text(obj["client_display_name"]):
        raise HandoffError("A reviewed status and client display name are required.")
    try:
        date = datetime.fromisoformat(obj["reviewed_at"])
        if date.utcoffset() != timezone.utc.utcoffset(date):
            raise ValueError
    except (ValueError, TypeError):
        raise HandoffError("Review timestamp must be UTC ISO 8601.") from None
    references = obj["source_references"]
    if not isinstance(references, list) or len(references) > 1000:
        raise HandoffError("Invalid source references.")
    ids = set()
    for ref in references:
        if not isinstance(ref, dict) or set(ref) != {"ref", "origin"} or not text(ref["ref"], 240) or ref["origin"] not in ("enquiry", "csv", "customer clarification", "reviewer statement", "assumption") or ref["ref"] in ids:
            raise HandoffError("Malformed or repeated source reference.")
        ids.add(ref["ref"])
    def refs(value):
        return isinstance(value, list) and bool(value) and all(isinstance(r,str) and r in ids for r in value)
    if not isinstance(obj["scope"], list) or not 1 <= len(obj["scope"]) <= 500:
        raise HandoffError("Handoff needs grouped scope.")
    for row in obj["scope"]:
        if not isinstance(row, dict) or set(row) != {"kind", "item", "site", "outcome", "quantity", "location", "collection", "source_refs"}:
            raise HandoffError("Malformed scope group.")
        if row["kind"] not in ("equipment", "loose_media", "embedded_media") or not text(row["item"]) or not text(row["site"]) or type(row["quantity"]) is not int or not 0 <= row["quantity"] <= 9999999 or not refs(row["source_refs"]):
            raise HandoffError("Invalid scope quantity, location or references.")
        if row["kind"] == "equipment":
            valid = row["outcome"] in ("reuse", "recycle", "destroy") and row["location"] == row["collection"] == ""
        else:
            valid = row["outcome"] in ("wipe", "destroy", "retain") and row["location"] in ("onsite", "offsite") and row["collection"] in ("before", "after", "none")
        if not valid:
            raise HandoffError("Unsupported scope action.")
    for key in ("assumptions", "followups"):
        if not isinstance(obj[key], list) or len(obj[key]) > 100:
            raise HandoffError("Invalid assumptions or follow-ups.")
        for row in obj[key]:
            if not isinstance(row, dict) or set(row) != {"text", "refs"} or not text(row["text"], 500) or not refs(row["refs"]):
                raise HandoffError("Malformed assumption or follow-up.")
    if obj["assumptions"] and obj["review_status"] != "Reviewed with assumptions":
        raise HandoffError("Assumptions require the reviewed-with-assumptions status.")
    if not isinstance(obj["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", obj["digest"]) or not hmac.compare_digest(obj["digest"], digest(obj)):
        raise HandoffError("SHA-256 digest does not match the canonical payload.")
    return obj
