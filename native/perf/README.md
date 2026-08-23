# Native Compute Performance Evidence

`cargo xtask perf` records machine-specific candidate evidence under `native/perf/evidence/`.

For bulk embedding, the current report deliberately separates:

- direct Rust preparation/finalization throughput,
- real `PyO3` JSON boundary latency,
- equivalent Python preparation/vector-validation latency,
- native model inference status.

A `PARTIAL_PASS` is not a Rust-authority approval. Until local FastEmbed/ONNX inference,
numerical parity, cold/warm model measurements, and downstream retrieval-quality checks are
recorded, `embedding_compute` remains Python-authoritative.

For the retrieval kernel, the report also separates:

- direct Rust candidate-fusion and best-per-context throughput,
- the real `PyO3` JSON request/response boundary,
- the current authoritative in-process Python ranking functions,
- versioned synthetic parity and benchmark-tool checks.

The measured boundary is part of the result, not incidental overhead. At large candidate sets,
direct Rust compute is fast and hybrid fusion can approach Python latency even after JSON
conversion. Best-per-context JSON FFI remains materially slower than Python at every measured
scale, and 50,000 candidates per lane require multi-megabyte payloads. Therefore the current
evidence rejects a naive JSON authority cutover. `retrieval_kernel` remains Python-authoritative
until a coarser boundary or lower-copy transport is implemented and the seeded exact-title and
semantic endpoint-quality metrics are rerun without regression.

For reconciliation candidate discovery, the benchmark uses bounded blocks of eight hard-negative
items at 1k, 10k, and 100k scale. This deliberately exercises comparison work without producing
large candidate outputs. The current machine evidence records 350,000 comparisons for 100,000
items instead of the theoretical 4,999,950,000 global pairs (0.007% of all-pairs work). The real
release PyO3 boundary remains faster than the equivalent Python baseline at all three measured
scales while preserving exact result parity. This evidence validates the bounded candidate engine,
not final reconciliation semantics; relation classification and lifecycle policy remain Python-owned.

The retrieval production-boundary candidate now uses compact `PyO3` tuple/index calls rather than
JSON for hybrid fusion. Heavyweight Python Context/Chunk DTOs stay in Python; only context IDs and
source indices/scores cross the native boundary. With `PyBackedStr`, hybrid fusion is faster than
the current Python implementation from 50 through 50,000 candidates (about 1.6x at 50 and >3x at
50,000 on the current machine). The single-lane best-per-context helper remains faster in Python at
all measured sizes, so it is a current `KEEP` candidate rather than a forced Rust migration. That
KEEP decision must remain explicit in the final cutover evidence; it is not a Python fallback for a
Rust-owned hybrid fusion path.
