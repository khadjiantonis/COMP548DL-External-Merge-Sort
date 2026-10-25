# External Merge Sort Benchmark — COMP-548DL

Homework 1, Exercise 2 — University of Nicosia.

This project evaluates external merge sort on Docker containers with 1, 2, 4, and 8 GiB RAM, keeping the input at 2 GiB and CPU quota at 2 CPUs.

## Run on Windows PowerShell

Build the image:

```powershell
docker build -f Dockerfile.benchmark -t external-sort-bench .
```

Run one configuration at a time:

```powershell
docker run --rm --memory=1g --memory-swap=1g --cpus=2 -v "${PWD}:/app" external-sort-bench --label laptop_1gib_v2
docker run --rm --memory=2g --memory-swap=2g --cpus=2 -v "${PWD}:/app" external-sort-bench --label laptop_2gib_v2
docker run --rm --memory=4g --memory-swap=4g --cpus=2 -v "${PWD}:/app" external-sort-bench --label laptop_4gib_v2
docker run --rm --memory=8g --memory-swap=8g --cpus=2 -v "${PWD}:/app" external-sort-bench --label laptop_8gib_v2
```

The script generates a deterministic 2 GiB input file once, and reuses it for subsequent runs. The output reports are saved in `results/`. The sorting algorithm reads chunks into memory, sorts them, writes temporary sorted runs and merges them into a final output. Each run validates sorted order and record count.

## Definitions

- **Response time:** Full runtime for sorting, merging, and validation; excludes initial data generation.
- **Throughput:** Input MiB divided by response time (MiB/s), and input records per second.
- **Sorting batch latency:** Wall-clock time to read, sort and write one initial run (ms).
- **Merging output batch latency:** Wall-clock time to emit 8,192 merged output records (ms).
- **Batch counts:** Number of initial sorted runs and merge output batches.

Batch latency is not storage-device latency. Sorting chunks vary in size with RAM configuration, so their latency is not directly comparable as a measure of per-record performance.

## Recorded results

| Container RAM | Response time (s) | Throughput (MiB/s) | Sorted runs | Avg sorting batch latency (ms) | Avg merging batch latency (ms) |
|---|---:|---:|---:|---:|---:|
| 1 GiB | 310.619 | 6.593 | 34 | 2813.557 | 12.767 |
| 2 GiB | 309.525 | 6.617 | 17 | 5818.660 | 12.502 |
| 4 GiB | 313.550 | 6.532 | 9 | 11429.286 | 12.519 |
| 8 GiB | 310.288 | 6.600 | 5 | 21174.763 | 12.127 |

These are single-run measurements and should not be read as statistically conclusive performance differences.

## Generated files

`data/`, `work/`, and `results/` are excluded from Git via `.gitignore`; the 2 GiB input is not committed.

## Requirements

- Docker Desktop with sufficient memory allocation for 8 GiB runs
- Enough disk space for input, temporary runs and output

