"""Run the predeclared paired study once and preserve every sample with host context."""
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
CACHE=Path(os.environ.get('FEED_CACHE',Path.home()/'.cache/job-apps-runtime/feed-replay'))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_freeze():
    directory=ROOT/'evidence/workload';manifest=json.loads((directory/'manifest.json').read_text())
    for name,digest in manifest['files'].items():
        if sha(directory/name)!=digest:raise ValueError('frozen workload changed: '+name)
    if sha(ROOT/'review/freeze-v1.json')!=manifest['reference_freeze_sha256']:raise ValueError('reference freeze changed')
    if sha(ROOT/'scripts/workload.py')!=manifest['generator_sha256']:raise ValueError('frozen generator source changed')
    return manifest


def main():
    manifest=validate_freeze();destination=ROOT/'evidence/benchmark.json'
    # Reserve first, so an accidental rerun cannot erase the original study.
    with destination.open('x') as output:
        context={'utc_start':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'load_average_start':os.getloadavg(),'logical_cpus':os.cpu_count(),'platform':platform.platform(),'cpu':subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip(),'compiler':subprocess.check_output(['clang++','--version'],text=True).splitlines()[0],'flags':'-std=c++20 -O2 -Wall -Wextra -Werror','binary_sha256':sha(CACHE/'build/feed_benchmark'),'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted([*ROOT.glob('src/*.cpp'),*ROOT.glob('include/feed/*.hpp')])},'workload_manifest_sha256':sha(ROOT/'evidence/workload/manifest.json')}
        start=time.monotonic()
        process=subprocess.run([str(CACHE/'build/feed_benchmark'),'--measure',str(ROOT/'evidence/workload')],capture_output=True,text=True,timeout=90)
        context['wall_seconds']=time.monotonic()-start;context['load_average_end']=os.getloadavg();context['utc_end']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        if process.returncode:
            json.dump({'status':'failed','context':context,'returncode':process.returncode,'stdout':process.stdout,'stderr':process.stderr},output,indent=2)
            raise RuntimeError('benchmark failed; original failure retained')
        result=json.loads(process.stdout)
        expected=json.loads((ROOT/'evidence/workload/oracle-final.json').read_text())
        if result['final_book']!=expected:raise ValueError('full final state differs from independent oracle')
        rows=[]
        for frequency in manifest['query_frequencies']:
            by_engine={engine:[int(s['elapsed_ns'])/1e6 for s in result['samples'] if s['frequency']==frequency and s['engine']==engine and s['measured']] for engine in ('indexed','scan')}
            assert all(len(values)==8 for values in by_engine.values())
            rows.append({'frequency':frequency,'indexed_ms':{'median':statistics.median(by_engine['indexed']),'min':min(by_engine['indexed']),'max':max(by_engine['indexed'])},'scan_ms':{'median':statistics.median(by_engine['scan']),'min':min(by_engine['scan']),'max':max(by_engine['scan'])},'median_scan_over_indexed':statistics.median(by_engine['scan'])/statistics.median(by_engine['indexed'])})
        document={'status':'passed','context':context,'summary':rows,'result':result}
        json.dump(document,output,indent=2);output.write('\n')
    print(json.dumps({'path':str(destination),'summary':rows,'wall_seconds':context['wall_seconds']},indent=2))


if __name__=='__main__':main()
