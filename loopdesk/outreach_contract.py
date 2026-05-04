"""Bounded version-one integration contract. No user text is executable."""
import hashlib
import json
import re
from datetime import datetime, timezone


class ContractError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def strict_json(raw, maximum=32768):
    if len(raw) > maximum:
        raise ContractError("JSON exceeds the allowed size.")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("Duplicate JSON keys are not accepted.")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda x: (_ for _ in ()).throw(ContractError("Non-finite JSON number.")))
        canonical(value).encode("utf-8")
    except (UnicodeError, ValueError, RecursionError, OverflowError) as exc:
        raise ContractError("Invalid UTF-8 JSON.") from exc
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ContractError("Invalid record identifier.")
    return value


def text(value, label, maximum=1024, required=True):
    if not isinstance(value, str):
        raise ContractError(f"{label} must be text.")
    value = value.replace("\r\n","\n").strip()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise ContractError(f"{label} contains invalid text.") from exc
    if (required and not value) or size > maximum or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ContractError(f"{label} is required and must be at most {maximum} UTF-8 bytes, without control characters.")
    return value


EVENT_KINDS = {"demo_delivery", "manual_task", "synthetic_reply", "reviewer_reply", "meeting", "not_interested", "opt_out", "invalid_address", "out_of_office", "paused", "resumed", "stopped", "skipped"}


def event_payload(value):
    fields = {"schema_version", "source_system", "source_workspace_id", "event_id", "enrollment_id", "sequence", "opportunity_id", "kind", "recorded_at_utc", "summary", "digest"}
    if not isinstance(value, dict) or set(value) != fields or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["source_system"] != "followdesk":
        raise ContractError("Unsupported outreach event contract.")
    for key in ("source_workspace_id", "event_id", "enrollment_id", "opportunity_id"):
        identifier(value[key])
    if type(value["sequence"]) is not int or not 1 <= value["sequence"] <= 2147483647 or not isinstance(value["kind"],str) or value["kind"] not in EVENT_KINDS:
        raise ContractError("Invalid event sequence or kind.")
    if text(value["summary"], "Event summary", 1800) != value["summary"]:
        raise ContractError("Event summary is not canonical.")
    try:
        at = datetime.fromisoformat(value["recorded_at_utc"])
        if at.tzinfo is None or at.utcoffset().total_seconds() != 0:
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        raise ContractError("Event time must be UTC.") from None
    if not isinstance(value["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["digest"]) or digest({k: v for k, v in value.items() if k != "digest"}) != value["digest"]:
        raise ContractError("Event integrity check failed.")
    return value


def address_key(value):
    value = text(value, "Email", 254)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ContractError("The CRM contact needs a valid email address.")
    local, domain = value.rsplit("@", 1)
    return local + "@" + domain.lower()
