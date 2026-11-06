"""Render a small self-contained, noninteractive evidence report from retained results."""
import html
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]


def main():
    benchmark=json.loads((ROOT/'evidence/benchmark.json').read_text())
    verification=ROOT/'evidence/verification-20261023T212630Z'
    rows=[]
    for row in benchmark['summary']:
        i,s=row['indexed_ms'],row['scan_ms']
        rows.append([str(row['frequency']),f"{i['median']:.3f} ({i['min']:.3f}–{i['max']:.3f})",f"{s['median']:.3f} ({s['min']:.3f}–{s['max']:.3f})",f"{row['median_scan_over_indexed']:.3f}"])
    samples=[]
    for frequency in (1,32,256):
        for pair in range(1,9):
            entries=sorted((r for r in benchmark['result']['samples'] if r['frequency']==frequency and r['pair']==pair),key=lambda r:r['position'])
            samples.append([str(frequency),str(pair),' → '.join(r['engine'] for r in entries),*[f"{int(next(r for r in entries if r['engine']==engine)['elapsed_ns'])/1e6:.3f}" for engine in ('indexed','scan')]])
    drills=[]
    for summary_path in sorted((verification/'udp').glob('*/summary.json')):
        summary=json.loads(summary_path.read_text())
        events=[json.loads(line) for line in (summary_path.parent/'timeline.jsonl').read_text().splitlines()]
        elapsed=max((int(e['time_ns']) for e in events),default=0)/1e6
        drills.append([summary_path.parent.name,summary['status'],summary['expected'],summary['counters']['requests_sent'],f'{elapsed:.3f}'])
    parser=[int(s['elapsed_ns'])/1e6 for s in benchmark['result']['parser_samples'] if s['measured']]
    def md_table(headers,data):
        return '| '+' | '.join(headers)+' |\n| '+' | '.join('---' for _ in headers)+' |\n'+''.join('| '+' | '.join(row)+' |\n' for row in data)
    benchmark_headers=['Query interval','Indexed median (range), ms','Scan median (range), ms','Median scan/indexed ratio']
    sample_headers=['Interval','Pair','Order','Indexed ms','Scan ms']
    drill_headers=['Actual process drill','Status','Next sequence','Sent requests','Last recorded event, ms']
    context=benchmark['context']
    text=f'''# Feed Replay measured results

One fixed synthetic study; no success threshold, retuning or discarded timing samples. The primary finding is a crossover: maintaining price levels helps frequent quotes, while scanning is faster at the sparsest query interval.

{md_table(benchmark_headers,rows)}

Eight measured pairs per interval after one warmup pair. Table ranges retain the slowest samples, including the 321.836 ms scan observation. Both engines perform identical validated updates, queries and result writes; every query and full final state match the independent oracle. Shared lifecycle code is intentional; the separate Python reference supplies semantic independence.

The 50,000 updates start with 2,048 live orders over eight instruments. Query interval 1 cycles all instruments; frozen intervals 32/256 query instrument1. Thus cross-interval differences combine query frequency with instrument selection; do not treat this as a pure causal estimate of query frequency. Output is synthetic displayed depth only. No exchange traffic, cold-start, network or production latency is measured by this table.

Environment: {context['cpu']}, {context['platform']}, {context['compiler']}; flags `{context['flags']}`. {context['logical_cpus']} logical CPUs; start/end 1/5/15-minute load averages {context['load_average_start']} / {context['load_average_end']}. No CPU pinning or exclusive-host guarantee. The parent coordinated other portfolio benchmark work outside this short window. All paired observations, warmups, source hashes and timestamps are in [benchmark.json](../evidence/benchmark.json).

Separate parser-only phase: decode 52,056 messages from already resident raw packets, including frame/type/field checks and decoded-result construction; exclude file I/O. Eight measured passes after one warmup: median {statistics.median(parser):.3f} ms, range {min(parser):.3f}–{max(parser):.3f} ms. These values cannot be added to the book table to predict end-to-end service latency.

## Every measured pair

{md_table(sample_headers,samples)}

## Actual UDP drills

These rows come from separate receiver/publisher/recovery processes and retained `recvmsg` captures. Times are elapsed receiver steady-clock timestamps of the last recorded event, not packet latency distributions or throughput. Zero/no-input failures and retry deadlines remain in the report. Source-port pinning is unauthenticated. Captures omit foreign bytes and wall-clock timings; replay is a separate protocol-order check.

{md_table(drill_headers,drills)}

The complete 28 UDP test cases also include option rejection and competing capture creation. [Verification manifest](../evidence/verification-20261023T212630Z/manifest.json) hashes the actual artifacts and observed request bytes. Product suite 140 tests plus independent reference suite 10 tests passed. Full ASan/UBSan core/CLI/UDP/benchmark suite 140 tests passed; [sanitizer log](../evidence/logs/final-sanitized.log).

## Evidence boundaries

Whole packet structural admission and message-by-message semantic acceptance are different boundaries. The fixtures challenge both. Every offline report and completed historical snapshot sets freshness/usability false; observed high water cannot prove that unseen traffic was never lost. Hard caps intentionally fail a session/report rather than evict history, clip quantities or publish a successful partial result.

No full ITCH compatibility, authenticated feed, live exchange deployment, trading execution, operational reliability, personal mastery or employer endorsement is established. Final independent source/execution review remains pending.
'''
    (ROOT/'docs/results.md').write_text(text)
    def table(headers,data):
        return '<table><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(cell)+'</td>' for cell in row)+'</tr>' for row in data)+'</tbody></table>'
    document='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Feed Replay — measured evidence</title><style>body{max-width:1120px;margin:40px auto;padding:0 24px;color:#18232d;background:#fcfcfa;font:16px/1.6 system-ui,sans-serif}h1{font-size:2.2rem;line-height:1.2}h2{margin-top:2.4em}p{max-width:85ch}table{border-collapse:collapse;font-variant-numeric:tabular-nums;width:100%;font-size:14px;margin:20px 0}th,td{text-align:left;border-bottom:1px solid #ccd2d6;padding:9px 10px;vertical-align:top}th{background:#eaf0f2}td:first-child{overflow-wrap:anywhere}a{color:#164f79}small{color:#52606b}.scroll{overflow-x:auto}code{background:#edf0f1;padding:2px 5px}</style><main><p><small>C++20 · ITCH displayed-book subset · Actual loopback MoldUDP64</small></p><h1>Feed Replay</h1><p>Frequent quote queries benefit from maintained price levels. At the sparsest query interval, scanning wins. Every observation below comes from one frozen synthetic workload, with exact independent output checks.</p>'''
    document+='<h2>Book workload: 50,000 updates</h2><p>Eight measured pairs per interval; one warmup pair; alternating execution order. Values are milliseconds for the entire update/query workload, not per-packet latency.</p><div class="scroll">'+table(benchmark_headers,rows)+'</div>'
    document+='<p>The frozen sparse schedules query instrument 1; the every-update schedule cycles eight instruments. Cross-interval comparisons therefore mix query frequency and instrument selection. Both engines share admission/lifecycle code; the independent Python map supplies the separate semantic oracle.</p>'
    document+='<h2>All measured pairs</h2><div class="scroll">'+table(sample_headers,samples)+'</div>'
    document+=f'<p>Separate resident-packet parser phase: median {statistics.median(parser):.3f} ms for 52,056 decoded messages, range {min(parser):.3f}–{max(parser):.3f} ms. File I/O excluded.</p>'
    document+='<h2>Actual UDP drills</h2><p>Last-event times are receiver steady-clock observations. These are finite local correctness drills, not throughput or reliability estimates. All 28 UDP tests and all 140 product tests passed; the independently authored reference has 10 separate passing tests.</p><div class="scroll">'+table(drill_headers,drills)+'</div>'
    document+='<h2>Scope and reproducibility</h2><p>Apple M4 Pro, macOS 27.0.1, Apple Clang 21, -O2. No CPU pinning or exclusive-host guarantee. Unknown ITCH types stop processing. Prices and quantities stay integer exact; historical IDs are never evicted. Completed and replayed books are historical snapshots with freshness/usability false. Port pinning is not authentication.</p><p>No full-feed compatibility, trading execution, production latency, personal mastery or employer endorsement is claimed. Final independent execution review remains pending.</p><p><a href="benchmark.json">All samples and source hashes</a> · <a href="workload/manifest.json">Frozen workload</a> · <a href="verification-20261023T212630Z/manifest.json">Verification artifacts</a> · <a href="../README.md">Build and contract</a> · <a href="../docs/results.md">Detailed report</a></p></main></html>'
    (ROOT/'evidence/report.html').write_text(document)
    print(json.dumps({'measured_pairs':len(samples),'retained_live_drills':len(drills),'parser_measured_passes':len(parser)}))

if __name__=='__main__':main()
