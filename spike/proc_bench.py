"""Throwaway: run each probe 20 times, report wall time and peak memory of the child process.
Build the Rust probe first: CARGO_TARGET_DIR=/tmp/kt-rust-target cargo build --release (in spike/rust-bench).
Run from the repository root: python3 spike/proc_bench.py"""
import statistics
import subprocess
import time

DB = "/tmp/kt-dict/en-es-indexed.sqlite3"
RUNS = 20
CMDS = {
    "python3 bare (control)": ["python3", "-c", "print([l for l in open('/proc/self/status') if l.startswith('VmHWM')][0].strip())"],
    "python: bus + sqlite + lookup": ["python3", "spike/proc_probe.py", DB, "house"],
    "rust: bus + sqlite + lookup": ["/tmp/kt-rust-target/release/rust-bench", DB, "house"],
}

for name, cmd in CMDS.items():
    times, peaks = [], []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        times.append((time.perf_counter() - t0) * 1000)
        # ru_maxrss from wait4 includes the parent's memory before exec, so each probe reports its own VmHWM
        peaks.append(int(out.strip().splitlines()[-1].split()[1]) / 1024)
    print(f"{name}: wall median {statistics.median(times):.1f} ms (max {max(times):.1f}), peak rss median {statistics.median(peaks):.1f} MB")
