"""Create separate public-source and private-application archives with manifests."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent
EXCLUDED = {".git", ".venv", ".local", "instance", "private", "__pycache__", ".pytest_cache", ".vercel", "node_modules", "recording-raw"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state_path = ROOT / "private/hosting-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    report = json.loads((ROOT / "artifacts/browser-verification.json").read_text())
    assert report["checkCount"] == 20 and report["automatedAccessibilityViolations"] == 0
    test_path = ROOT / "artifacts/pytest-sqlite.xml"
    if not test_path.exists():
        test_path = ROOT / "artifacts/pytest.xml"
    suites = ET.parse(test_path).getroot().findall("testsuite")
    test_count = sum(int(s.attrib["tests"]) for s in suites)
    assert test_count >= 48
    assert all(int(s.attrib["errors"]) == int(s.attrib["failures"]) == 0 for s in suites)
    assert (ROOT / "artifacts/LoopDesk-Demo.webm").stat().st_size > 100_000
    files = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if set(rel.parts) & EXCLUDED or p.name.startswith(".env") and p.name != ".env.example":
            continue
        if p.name in {"source-manifest.json", "browser-failure.png"} or p.suffix in {".pyc", ".zip"}:
            continue
        if p.name not in {"LoopDesk-Demo.webm"} and p.suffix == ".webm":
            continue
        files.append(p)
    files.sort()
    # Block private contact details and mailbox URLs in textual public contents.
    cv = json.loads((ROOT / "private/cv-verification.json").read_text())
    forbidden = [value.split(":",1)[1] for value in cv["links"] if value.startswith(("mailto:","tel:"))]
    forbidden.append("mail.google.com/mail/u/")
    for p in files:
        if p.suffix.lower() in {".py", ".js", ".mjs", ".json", ".html", ".css", ".md", ".txt", ".toml", ".sql", ".xml"} and p.name != "package-release.py":
            text = p.read_text(encoding="utf-8")
            assert not any(value in text for value in forbidden), f"Private data in {p.relative_to(ROOT)}"
    manifest = {"kind":"publication-source-review", "published":state.get("published",False),
                "excludes":"Private CV/application files, database/session secret, local caches, .env values, Git metadata, raw duplicate recordings",
                "files":[{"path":p.relative_to(ROOT).as_posix(),"bytes":p.stat().st_size,"sha256":digest(p)} for p in files]}
    manifest_path = ROOT / "artifacts/source-manifest.json"
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    public_zip = OUT / "LoopDesk-Source.zip"
    with ZipFile(public_zip,"w",ZIP_DEFLATED) as archive:
        for p in files + [manifest_path]:
            archive.write(p, "loopdesk/" + p.relative_to(ROOT).as_posix())
    private_zip = OUT / "Madenat-Application-Private.zip"
    application_files = {"application-message.md", "project-summary.md", "research-opportunity.md", "requirement-to-evidence.md",
                         "submission-checklist.md", "cv-claim-evidence.md", "cv-extracted.txt", "cv-verification.json"}
    with ZipFile(private_zip,"w",ZIP_DEFLATED) as archive:
        for p in sorted((ROOT / "private").iterdir()):
            if p.is_file() and (p.name in application_files or p.name.startswith("Mohammad_Uzair_Khan_Madenat_Software_Intern.") and p.suffix in {".pdf",".tex"}):
                archive.write(p,p.name)
    with ZipFile(public_zip) as archive:
        assert archive.testzip() is None
        assert not any(set(Path(n).parts) & EXCLUDED for n in archive.namelist())
    with ZipFile(private_zip) as archive:
        assert archive.testzip() is None
    result = {"publicSource":{"path":str(public_zip),"bytes":public_zip.stat().st_size,"sha256":digest(public_zip),"fileCount":len(files)+1},
              "privateApplication":{"path":str(private_zip),"bytes":private_zip.stat().st_size,"sha256":digest(private_zip)},
              "localChecks":test_count,"browserChecks":report["checkCount"],"accessibilityScans":len(report["accessibilityScans"]),
              "publicationAuthorized":state.get("publicationAuthorized",False),"hostedVerified":state.get("hostedVerified",False),
              "postgresVerified":state.get("postgresVerified",False),"published":state.get("published",False),"submitted":False}
    (ROOT / "private/release-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
