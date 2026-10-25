#!/usr/bin/env python3
"""Reproducible external merge-sort benchmark. Binary records: <uint64 key,uint64 payload>."""
import argparse, heapq, json, os, resource, shutil, socket, struct, time
from pathlib import Path
import numpy as np

MIB = 1024**2
GIB = 1024**3
DTYPE = np.dtype([('key','<u8'), ('payload','<u8')])
RECORD_BYTES = DTYPE.itemsize

def memory_limit():
    for path in ('/sys/fs/cgroup/memory.max','/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        try:
            value = Path(path).read_text().strip()
            if value != 'max' and 0 < int(value) < (1 << 60): return int(value)
        except (OSError,ValueError): pass
    return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')

def percentile(values, q):
    return float(np.percentile(values,q)) if values else None

def latency_stats(seconds):
    return {'count':len(seconds), 'average_ms':round(1000*sum(seconds)/len(seconds),3) if seconds else None,
            'p50_ms':round(1000*percentile(seconds,50),3) if seconds else None,
            'p95_ms':round(1000*percentile(seconds,95),3) if seconds else None,
            'p99_ms':round(1000*percentile(seconds,99),3) if seconds else None,
            'maximum_ms':round(1000*max(seconds),3) if seconds else None}

def make_input(path, size_gib, seed):
    if path.exists():
        if path.stat().st_size % RECORD_BYTES: raise ValueError('Input must contain complete 16-byte records')
        print(f'Reusing input: {path} ({path.stat().st_size/GIB:.3f} GiB)',flush=True)
        return
    total_records = int(size_gib*GIB)//RECORD_BYTES
    rng = np.random.default_rng(seed)
    tmp = path.with_suffix(path.suffix+'.partial')
    print(f'Generating deterministic input: {total_records:,} records',flush=True)
    try:
        with tmp.open('wb', buffering=4*MIB) as f:
            for offset in range(0,total_records,500_000):
                n = min(500_000,total_records-offset)
                records = np.empty(n,dtype=DTYPE)
                records['key'] = rng.integers(0, np.iinfo(np.uint64).max, size=n, dtype=np.uint64)
                records['payload'] = np.arange(offset,offset+n,dtype=np.uint64)
                f.write(records.tobytes())
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)

def sort_runs(input_path, tmp_dir, chunk_records):
    runs, durations = [], []
    with input_path.open('rb',buffering=4*MIB) as f:
        while True:
            start = time.perf_counter()
            buf = f.read(chunk_records*RECORD_BYTES)
            if not buf: break
            arr = np.frombuffer(buf,dtype=DTYPE).copy()
            arr.sort(order=['key','payload'],kind='quicksort')
            target = tmp_dir/f'run_{len(runs):04d}.bin'
            with target.open('wb',buffering=4*MIB) as out: out.write(arr.tobytes())
            elapsed = time.perf_counter()-start
            durations.append(elapsed)
            runs.append(target)
            print(f'Created run {len(runs)} ({len(arr):,} records), latency={elapsed*1000:.1f} ms',flush=True)
    return runs,durations

def merge_runs(runs, output_path, buffer_records=8192):
    # Multiway merge; latency is recorded for each output batch, not each record.
    handles = [p.open('rb',buffering=1024*1024) for p in runs]
    buffers = [np.empty(0,dtype=DTYPE) for _ in runs]
    indexes = [0]*len(runs)
    heap = []
    def next_record(i):
        if indexes[i] >= len(buffers[i]):
            data = handles[i].read(buffer_records*RECORD_BYTES)
            if not data: return None
            buffers[i] = np.frombuffer(data,dtype=DTYPE)
            indexes[i] = 0
        rec = buffers[i][indexes[i]]
        indexes[i] += 1
        return (int(rec['key']),int(rec['payload']))
    try:
        for i in range(len(runs)):
            item = next_record(i)
            if item is not None: heapq.heappush(heap,(*item,i))
        batch = bytearray()
        durations = []
        batch_started = time.perf_counter()
        with output_path.open('wb',buffering=4*MIB) as out:
            while heap:
                key,payload,i = heapq.heappop(heap)
                batch.extend(struct.pack('<QQ',key,payload))
                nxt = next_record(i)
                if nxt is not None: heapq.heappush(heap,(*nxt,i))
                if len(batch) >= buffer_records*RECORD_BYTES:
                    out.write(batch)
                    durations.append(time.perf_counter()-batch_started)
                    batch.clear()
                    batch_started = time.perf_counter()
            if batch:
                out.write(batch)
                durations.append(time.perf_counter()-batch_started)
        return durations
    finally:
        for f in handles: f.close()

def validate(path, expected_count):
    previous = None
    count = 0
    with path.open('rb',buffering=4*MIB) as f:
        while True:
            raw = f.read(4*MIB)
            if not raw: break
            data = np.frombuffer(raw,dtype=DTYPE)
            if len(data):
                keys = data['key']
                if previous is not None and int(keys[0]) < previous: return False,count
                if np.any(keys[1:] < keys[:-1]): return False,count
                previous = int(keys[-1]); count += len(data)
    return count == expected_count,count

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input',default='data/input_2gib.bin')
    ap.add_argument('--size-gib',type=float,default=2)
    ap.add_argument('--seed',type=int,default=548)
    ap.add_argument('--label',default=os.environ.get('BENCHMARK_LABEL','benchmark'))
    ap.add_argument('--results-dir',default='results')
    ap.add_argument('--work-dir',default='work')
    ap.add_argument('--keep-output',action='store_true')
    args = ap.parse_args()
    input_path = Path(args.input).resolve()
    result_dir = Path(args.results_dir).resolve()
    work_dir = Path(args.work_dir).resolve()/args.label
    result_path = result_dir/f'{args.label}.json'
    if result_path.exists() or work_dir.exists():
        raise RuntimeError(f'Existing output for {args.label}; choose a new label or remove {result_path} and {work_dir}')
    input_path.parent.mkdir(parents=True,exist_ok=True)
    make_input(input_path,args.size_gib,args.seed)
    limit = memory_limit()
    # 6% of memory, bounded below by 8 MiB; 16-byte records.
    chunk_bytes = max(8*MIB,int(limit*0.06))
    chunk_records = max(1,chunk_bytes//RECORD_BYTES)
    input_size = input_path.stat().st_size
    # Create parent before checking disk space (fresh Docker volume).
    work_dir.parent.mkdir(parents=True, exist_ok=True)
    # Temporary runs + final output need ~2x input size, excluding input itself.
    if shutil.disk_usage(work_dir.parent).free < 2*input_size+300*MIB:
        raise RuntimeError('Insufficient free disk: need ~2x input size + 300 MiB in addition to input')
    work_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True,exist_ok=True)
    output = work_dir/'sorted.bin'
    print(f'Host: {socket.gethostname()} | RAM limit: {limit/GIB:.2f} GiB | Input: {input_size/GIB:.2f} GiB | Chunk: {chunk_records*16/MIB:.2f} MiB',flush=True)
    cpu_start = time.process_time()
    start = time.perf_counter()
    try:
        phase1_start = time.perf_counter()
        runs,sort_latencies = sort_runs(input_path,work_dir,chunk_records)
        sort_time = time.perf_counter()-phase1_start
        print('PHASE 2: MERGING RUNS',flush=True)
        phase2_start = time.perf_counter()
        merge_latencies = merge_runs(runs,output)
        merge_time = time.perf_counter()-phase2_start
        print('PHASE 3: VALIDATION',flush=True)
        valid,records = validate(output,input_size//RECORD_BYTES)
        total = time.perf_counter()-start
        cpu = time.process_time()-cpu_start
        # ru_maxrss is KiB on Linux.
        peak_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
        result = {
            'label':args.label,'host':socket.gethostname(),'ram_limit_gib':round(limit/GIB,3),
            'input_gib':round(input_size/GIB,3),'input_records':input_size//RECORD_BYTES,
            'output_records':records,'sorting_valid':valid,'sorted_runs':len(runs),
            'chunk_target_mib':round(chunk_records*16/MIB,3),
            'sorting_seconds':round(sort_time,3),'merging_seconds':round(merge_time,3),
            'execution_seconds':round(total,3),'response_time_seconds':round(total,3),
            'throughput_mib_per_sec':round(input_size/MIB/total,3),
            'throughput_records_per_sec':round(records/total,1),
            'cpu_seconds':round(cpu,3),'average_cpu_percent_one_core':round(100*cpu/total,2),
            'peak_process_ram_mib':round(peak_mib,2),
            'sorting_batch_latency':latency_stats(sort_latencies),
            'merging_output_batch_latency':latency_stats(merge_latencies),
            'merging_output_batch_records':8192,
            'latency_definition':'Wall time per sorting run / per merge output batch; not device I/O latency',
            'validation_included_in_response_time':True
        }
        result_path.write_text(json.dumps(result,indent=2)+'\n')
        print('BENCHMARK RESULTS\n'+json.dumps(result,indent=2),flush=True)
        if not valid: raise RuntimeError('Sorting validation failed')
    finally:
        if not args.keep_output: shutil.rmtree(work_dir,ignore_errors=True)

if __name__ == '__main__': main()
