"""Bind current source, retained evidence and local binaries; verify existing study hashes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from benchmark_report import validate_freeze

ROOT=Path(__file__).resolve().parents[1]
CACHE=Path(os.environ.get('FEED_CACHE',Path.home()/'.cache/job-apps-runtime/feed-replay'))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    validate_freeze()
    benchmark=json.loads((ROOT/'evidence/benchmark.json').read_text())
    for path,digest in benchmark['context']['source_sha256'].items():
        if sha(ROOT/path)!=digest:raise ValueError('timed source changed: '+path)
    freeze=json.loads((ROOT/'review/freeze-v1.json').read_text())
    for entry in freeze['files']:
        if sha(ROOT/'review'/entry['path'])!=entry['sha256']:raise ValueError('independent frozen file changed: '+entry['path'])
    files=sorted(p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='.DS_Store' and p!=ROOT/'evidence/index.json')
    binaries=sorted(p for p in (CACHE/'build').iterdir() if p.is_file())
    used=sum(p.stat().st_blocks*512 for p in CACHE.rglob('*') if p.is_file() and not p.is_symlink())
    document={'schema_version':1,'independent_final_review':'pending','source_matches_retained_timing':True,'frozen_reference_files_verified':len(freeze['files']),'runtime_allocated_bytes':used,'host_free_bytes_at_index':shutil.disk_usage(CACHE).free,'files':{str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in files},'local_binaries':{p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in binaries},'scope':'Current source and finite executed artifact evidence; not employer endorsement or personal mastery.'}
    (ROOT/'evidence/index.json').write_text(json.dumps(document,indent=2)+'\n')
    print(json.dumps({'indexed_files':len(files),'project_bytes':sum(p.stat().st_size for p in files),'runtime_allocated_bytes':used,'host_free_bytes':document['host_free_bytes_at_index']}))

if __name__=='__main__':main()
