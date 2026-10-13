from asyncio import subprocess
import os, psycopg
import sys
from legal.obligations.storage import extract_and_store
from legal.llm.providers import chat
with psycopg.connect(os.environ['LEGAL_DSN']) as conn:
    provision_id = '37a51dd7eee2ed81301b697f'
    text = conn.execute('SELECT text FROM eu_provision WHERE provision_id=%s', (provision_id,)).fetchone()[0]
    result = extract_and_store(conn, jurisdiction='EU', source_id=provision_id,
                               source_text=text, 
                               mode='llm', 
                               #mode="deterministic",
                               chat_fn=chat,
                               provider=os.getenv('LEGAL_LLM_PROVIDER'),
                               model=os.getenv('LEGAL_LLM_MODEL'))
    print(result)

    conn.commit()

    subprocess.run(
        [
            sys.executable,
            "scripts/audit_obligation_evidence.py",
            "--run-id",
            str(result["run_id"]),
        ],
        check=True,
    )
