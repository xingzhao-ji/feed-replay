import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest
from test_codec import ROOT
from test_cli import BINARY
BENCH=Path(os.environ.get('FEED_BENCHMARK',BINARY.with_name('feed_benchmark')))
WORKLOAD=ROOT/'evidence/workload'


def run(path):return subprocess.run([str(BENCH),'--check',str(path)],capture_output=True,text=True,timeout=20)


def test_exact_engine_queries_and_final_state_equal_independent_reference():
    p=run(WORKLOAD);assert p.returncode==0,p.stderr
    result=json.loads(p.stdout)
    assert result['final_book']==json.loads((WORKLOAD/'oracle-final.json').read_text())
    assert result['checks']==[{'frequency':1,'queries':50000},{'frequency':32,'queries':1563},{'frequency':256,'queries':196}]
    assert result['samples']==[] and result['parser_samples']==[]


@pytest.mark.parametrize('mutation',['quantity','flag','schedule','missing','extra'])
def test_benchmark_rejects_changed_oracle_contract(tmp_path,mutation):
    shutil.copyfile(WORKLOAD/'workload.frcp',tmp_path/'workload.frcp')
    lines=(WORKLOAD/'oracle-quotes.tsv').read_text().splitlines()
    fields=lines[0].split()
    if mutation=='quantity':fields[3]=str(int(fields[3])+1);lines[0]=' '.join(fields)
    elif mutation=='flag':fields[-1]='1';lines[0]=' '.join(fields)
    elif mutation=='schedule':fields[0]='1';lines[0]=' '.join(fields)
    elif mutation=='missing':lines.pop()
    else:lines.append(lines[-1])
    (tmp_path/'oracle-quotes.tsv').write_text('\n'.join(lines)+'\n')
    p=run(tmp_path);assert p.returncode!=0 and not p.stdout.strip(),(p.stdout,p.stderr)
