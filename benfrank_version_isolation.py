"""Sport-specific version lock: fail closed on missing, mismatched or unreleased artifacts."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "architecture" / "benfrank_version_lock.json"
CATALOG = ROOT / "architecture" / "benfrank_multisport_catalog.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")

class VersionIsolationError(ValueError):
    pass

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def artifact_sha256(content):
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()

def verify_release(sport, receipt, *, lock_path=LOCK, catalog_path=CATALOG):
    """Validate exact sport and all pinned versions before an operational prediction."""
    catalog = _load(catalog_path)
    lock = _load(lock_path)
    sport = str(sport).strip().upper()
    known = {s["id"] for s in catalog["sports"]}
    if sport not in known or sport not in lock["sports"]:
        raise VersionIsolationError("UNKNOWN_SPORT")
    spec = lock["sports"][sport]
    if spec["release_status"] != "OPERATIONAL":
        raise VersionIsolationError("SPORT_RELEASE_NOT_APPROVED")
    if spec["automatic_upgrades"]:
        raise VersionIsolationError("AUTOMATIC_UPGRADE_FORBIDDEN")
    if receipt.get("sport") != sport:
        raise VersionIsolationError("CROSS_SPORT_RECEIPT")
    expected = {
        "core_version": spec["core_version"],
        "model_version": spec["model_version"],
        "data_schema_version": spec["data_schema_version"],
        "scoring_rules_version": spec["scoring_rules_version"],
        "calibration_version": spec["calibration_version"],
        "core_sha256": spec["approved_core_sha256"],
        "model_sha256": spec["approved_model_sha256"],
    }
    for key, value in expected.items():
        if value is None or receipt.get(key) != value:
            raise VersionIsolationError("VERSION_LOCK_MISMATCH:" + key)
    for key in ("approved_core_sha256", "approved_model_sha256"):
        if not isinstance(spec[key], str) or not SHA256.fullmatch(spec[key]):
            raise VersionIsolationError("INVALID_RELEASE_DIGEST:" + key)
    if not receipt.get("cutoff_utc") or not receipt.get("approval_receipt"):
        raise VersionIsolationError("MISSING_CUTOFF_OR_APPROVAL")
    return True

def check_lock_change(old, new, *, approved_sports=()):
    """A lock update cannot change any sport without its explicit approval."""
    old, new = _load(old), _load(new)
    if old["schema_version"] != new["schema_version"]:
        raise VersionIsolationError("LOCK_SCHEMA_CHANGE_REQUIRES_REVIEW")
    approved = set(approved_sports)
    for sport, previous in old["sports"].items():
        if sport not in new["sports"]:
            raise VersionIsolationError("SPORT_REMOVAL_FORBIDDEN:" + sport)
        if previous != new["sports"][sport] and sport not in approved:
            raise VersionIsolationError("UNAPPROVED_SPORT_VERSION_CHANGE:" + sport)
    return True
