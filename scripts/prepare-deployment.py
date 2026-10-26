"""Prepare an allowlisted Vercel source payload; performs no network request."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ("app.py", "pyproject.toml", "requirements.txt", "vercel.json")
DIRECTORIES = ("loopdesk", "migrations", "public")


def prepare(project="loopdesk", target="production"):
    paths = [ROOT / name for name in ROOT_FILES]
    for folder in DIRECTORIES:
        paths.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    paths.sort()
    files, manifest = [], []
    combined = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        content = path.read_bytes()
        combined.update(relative.encode() + b"\0" + content)
        files.append({"file":relative, "encoding":"base64", "data":base64.b64encode(content).decode("ascii")})
        manifest.append({"path":relative,"bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()})
    fingerprint = combined.hexdigest()
    body = {"name":"loopdesk", "project":project, "target":target, "files":files,
            "projectSettings":{"framework":"flask"}, "meta":{"loopdeskSourceSha256":fingerprint}}
    folder = ROOT / "private"
    folder.mkdir(exist_ok=True)
    (folder / "vercel-deployment.json").write_text(json.dumps(body),encoding="utf-8")
    (folder / "vercel-deployment-manifest.json").write_text(json.dumps({"sent":False,"project":project,"target":target,"sourceSha256":fingerprint,"files":manifest},indent=2),encoding="utf-8")
    return {"files":len(files),"bytes":sum(item["bytes"] for item in manifest),"sourceSha256":fingerprint,
            "payload":"private/vercel-deployment.json","sent":False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",default="loopdesk",help="Exact project ID or name after creation in the approved team")
    parser.add_argument("--target",choices=["preview","production"],default="production")
    args = parser.parse_args()
    print(json.dumps(prepare(args.project,args.target),indent=2))
