"""Execute bounded checks, retain real UDP artifacts and bind evidence to source hashes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from benchmark_report import validate_freeze

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    validate_freeze()
    destination=ROOT/'evidence'/('verification-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
    destination.mkdir(exist_ok=False)
    commands=[[sys.executable,'review/test_reference.py'],[sys.executable,'-m','pytest','-q','-p','no:cacheprovider','tests']]
    env=dict(os.environ,FEED_EVIDENCE_DIR=str(destination/'udp'),PYTHONDONTWRITEBYTECODE='1')
    checks=[]
    for index,command in enumerate(commands):
        log=destination/f'check-{index+1}.log';start=time.monotonic()
        with log.open('x') as output:result=subprocess.run(command,cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=90)
        checks.append({'command':command,'returncode':result.returncode,'wall_seconds':time.monotonic()-start,'log':log.name})
        print(log.read_text(),end='')
        if result.returncode:raise RuntimeError(f'verification failed; evidence retained at {destination}')
    inputs=sorted([*ROOT.glob('src/*.cpp'),*ROOT.glob('include/feed/*.hpp'),*ROOT.glob('scripts/*.py'),*ROOT.glob('tests/*.py'),ROOT/'tests/probe.cpp',ROOT/'Makefile',ROOT/'evidence/workload/manifest.json',ROOT/'review/freeze-v1.json'])
    evidence=sorted(p for p in destination.rglob('*') if p.is_file())
    manifest={'checks':checks,'source_hashes':{str(p.relative_to(ROOT)):sha(p) for p in inputs},'evidence_hashes':{str(p.relative_to(destination)):sha(p) for p in evidence}}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'verification':str(destination),'source_files':len(inputs),'retained_evidence_files':len(evidence)}))


if __name__=='__main__':main()
