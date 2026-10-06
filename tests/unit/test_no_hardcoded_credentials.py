from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[2]
SCHEME="postgres"+"ql://"
PAT=re.compile(SCHEME+r"[^/\\s:@]+:[^@\\s/]+@")
def test_no_postgres_credentials_in_repository():
    bad=[]
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in ("__pycache__",".pytest_cache","artifacts")): continue
        # Unit tests may construct synthetic DSNs to verify password masking.
        if "tests" in p.parts and p.name != "test_no_hardcoded_credentials.py": continue
        try:s=p.read_text()
        except (UnicodeDecodeError,OSError):continue
        s=s.replace(SCHEME+"legal_user:CHANGE_ME@localhost:5432/legal","")
        if PAT.search(s):bad.append(str(p.relative_to(ROOT)))
    assert bad == []
def test_env_example_dsn_is_blank():
    assert "LEGAL_DSN=" in (ROOT/".env.example").read_text().splitlines()
