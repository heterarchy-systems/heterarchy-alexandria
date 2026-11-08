# Native Compute Performance Evidence

`cargo xtask perf` records machine-specific candidate runs under
`native/perf/evidence/`.

Current production ownership comes from the [feature authority registry](../feature_authority.toml),
not from benchmark prose. It records Rust authority with Python retirement
complete for `document_analysis`, `chunking`, `link_extraction`, `fingerprint`,
`graph_compute`, `compile_plan`, `embedding_compute`, `retrieval_kernel`,
`reconciliation_candidates`, and `context_reindex_manifest`. The observations
below are historical, machine-specific evidence. They do not establish current
performance or change the registry's authority declarations.

## Historical recorded observations

The recorded bulk-embedding report separated:

- direct Rust preparation/finalization throughput;
- real PyO3 JSON boundary latency;
- equivalent Python preparation/vector-validation latency;
- native model inference status.

Its `PARTIAL_PASS` describes that report's evidence scope and does not change
the current authority recorded for `embedding_compute`.

The recorded retrieval-kernel report separated:

- direct Rust candidate-fusion and best-per-context throughput;
- the PyO3 JSON request/response boundary;
- Python ranking functions used as the report's comparison baseline;
- versioned synthetic parity and benchmark-tool checks.

In that run, direct Rust compute was fast at large candidate sets, and hybrid
fusion approached the Python baseline after JSON conversion. The report measured
best-per-context JSON FFI slower than the Python baseline at its measured scales,
with multi-megabyte payloads at 50,000 candidates per lane. These measurements
describe that JSON boundary and run; the report's rejection of that candidate
does not describe current production authority. The current registry assigns
`retrieval_kernel` to Rust.

The reconciliation-candidate report used blocks of eight hard-negative items at
1k, 10k, and 100k scale. That run recorded 350,000 comparisons for 100,000
items, compared with 4,999,950,000 theoretical global pairs (0.007% of all-pairs
work). Its release PyO3 boundary was faster than the equivalent Python baseline
at those measured scales and preserved exact result parity for the report's
cases. The evidence covered bounded candidate discovery; it did not establish
final reconciliation semantics or current performance. The current registry
assigns `reconciliation_candidates` to Rust.

A separate retrieval-boundary candidate used compact PyO3 tuple/index calls for
hybrid fusion instead of JSON. That report kept Python Context/Chunk DTOs in
Python and sent context IDs and source indices/scores across the native
boundary. It measured hybrid fusion faster than its Python baseline from 50
through 50,000 candidates (about 1.6x at 50 and over 3x at 50,000 on that
machine). The same report measured its single-lane best-per-context helper
faster in Python at all tested sizes. Its `KEEP` label was a candidate decision
from that report and does not override the current feature authority registry.
