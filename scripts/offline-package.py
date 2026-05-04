"""Bundle and verify this Windows/Python 3.14 build using cached wheels only."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from email.parser import Parser
import hashlib
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def build():
    expected = {}
    for file in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / file).read_text().splitlines():
            if "==" not in line or line.lstrip().startswith("#"):
                continue
            name,version = line.split(";",1)[0].strip().split("==")
            expected[name.lower().replace("-","_")] = version
    wheels = {}
    for path in (ROOT / ".local/wheels").glob("*.whl"):
        with ZipFile(path) as wheel:
            metadata = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
            parsed = Parser().parsestr(wheel.read(metadata).decode("utf-8"))
            name = parsed["Name"].lower().replace("-","_")
            if expected.get(name) == parsed["Version"]:
                wheels[name] = path
    missing = set(expected) - set(wheels)
    assert not missing, "Offline wheels unavailable for: " + ",".join(sorted(missing))
    out = ROOT.parent / "LoopDesk-Windows-Offline.zip"
    source = ROOT.parent / "LoopDesk-Source.zip"
    with ZipFile(source) as src, ZipFile(out,"w",ZIP_DEFLATED) as dest:
        for name in src.namelist():
            if name.endswith(("artifacts/offline-verification.json", "artifacts/source-manifest.json")):
                continue
            dest.writestr(name,src.read(name))
        for path in sorted(wheels.values()):
            dest.write(path,"loopdesk/.local/wheels/"+path.name)
        dest.writestr("START-HERE.txt", "LoopDesk offline Windows demo\n\nExtract the loopdesk folder to D: and open Start-LoopDesk.cmd.\nRequires the existing Windows x64 Python 3.14 installation.\nIncludes exact cached runtime/test wheels; no package download is required.\nData, environments, caches and temporary files stay under the extracted folder.\nUse fictional details. Hosting is separate and is not included in this local bundle.\n")
    assert ZipFile(out).testzip() is None
    return out,len(wheels)


def verify(archive):
    folder = ROOT / ".local" / ("offline-review-" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    with ZipFile(archive) as source:
        # This archive was generated above from the reviewed local source; still check paths.
        for member in source.namelist():
            resolved = (folder / member).resolve()
            assert resolved.is_relative_to(folder.resolve())
        source.extractall(folder)
    checkout = folder / "loopdesk"
    temp = checkout / ".local/temp"
    temp.mkdir(parents=True)
    env = os.environ.copy()
    env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp), PIP_CACHE_DIR=str(checkout / ".local/pip-cache"), PIP_DISABLE_PIP_VERSION_CHECK="1")
    for key in ("DATABASE_URL", "APP_ENV", "VERCEL", "SECRET_KEY"):
        env.pop(key,None)
    env["PYTHONPYCACHEPREFIX"] = str(checkout / ".local/pycache")
    commands = [
        [sys.executable,"-m","venv",str(checkout / ".venv")],
        [str(checkout / ".venv/Scripts/python.exe"),"-m","pip","install","--no-index","--find-links",str(checkout / ".local/wheels"),"-r","requirements.txt"],
        [str(checkout / ".venv/Scripts/python.exe"),"-m","flask","--app","app","migrate"],
    ]
    log = []
    for command in commands:
        result = subprocess.run(command,cwd=checkout,env=env,capture_output=True,text=True)
        log.append(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError("Offline setup failed: " + log[-1][-2000:])
    python = str(checkout / ".venv/Scripts/python.exe")
    output = (ROOT / ".local/offline-server.log").open("w",encoding="utf-8")
    process = subprocess.Popen([python,"-m","flask","--app","app","run","--host","127.0.0.1","--port","5057"],cwd=checkout,env=env,stdout=output,stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    base = "http://127.0.0.1:5057"
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("Extracted application exited before readiness")
            try:
                with urllib.request.urlopen(base+"/health",timeout=1) as response:
                    assert response.status == 200
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.25)
        else:
            raise RuntimeError("Extracted application did not become ready")
        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
        html = opener.open(base).read().decode()
        token = re.search(r'name="csrf_token" value="([^"]+)"',html)[1]
        request = urllib.request.Request(base+"/demo",data=urllib.parse.urlencode({"csrf_token":token}).encode())
        dashboard = opener.open(request).read().decode()
        assert "Open opportunities" in dashboard
        assert "Synthetic data only" in dashboard
        assert "Open by service" in opener.open(base+"/reports").read().decode()
        csv = opener.open(base+"/opportunities.csv").read().decode("utf-8-sig")
        import csv as csv_module, io
        assert len(list(csv_module.reader(io.StringIO(csv)))) == 37
        return {"verified":True,"python":sys.version.split()[0],"platform":sys.platform,"cleanVirtualEnvironment":True,
                "installedWithoutNetwork":True,"health":200,"isolatedDemoStarted":True,"seededOpportunityExportRows":36,
                "allGeneratedFilesUnder":str(folder),"newServerStoppedAfterCheck":True}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output.close()
        (ROOT / ".local/offline-install.log").write_text("\n".join(log),encoding="utf-8")


if __name__ == "__main__":
    archive,count = build()
    result = verify(archive)
    result.update(archive=str(archive),wheelCount=count,bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    (ROOT / "artifacts/offline-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
