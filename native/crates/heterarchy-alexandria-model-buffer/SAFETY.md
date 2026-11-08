# Anonymous model input ownership

Approved boundary: `heterarchy-alexandria-model-buffer`, owned by the native
model-input implementation and independently reviewed by Astra. Core/adapter
remain safe Rust. The only external dependency is already-locked libc0.2.189.

`Mapping` privately owns one successful anonymous private mapping. Allocation
rejects zero and lengths beyond isize::MAX; MAP_FAILED owns no allocation.
An otherwise successful null address is unmapped before rejection. Anonymous
pages are initialized to zero, nonnull accepted addresses are aligned for u8,
and slices cover only the requested logical size. mmap/mprotect/munmap accept
the original nonzero size and perform OS page rounding; no unchecked manual
rounding or fabricated pointer arithmetic is needed.

MutableModelBuffer exposes only an exclusive borrow. Consuming freeze prevents
outstanding borrows and changes protection to read-only before transferring the
single Mapping into ModelBuffer. mprotect errors are captured before automatic
cleanup; failed freeze publishes no owner. Neither wrapper has Clone, Sync,
raw-pointer construction or pointer access. Mapping's sole unsafe Send guarantee
rests on unique ownership, borrow lifetimes and absence of thread-affine state.
There is no custom raw-pointer API; callers can derive raw pointers from ordinary
borrowed slices, whose safe lifetime remains bound to the owner. The SDK's owned
ORT commit completes before model input is dropped.

Mapping::drop calls munmap once using the original range. It cannot panic or
mask another failure. If the OS rejects unmapping, memory is retained; this is
not reported as proven release and is never retried through another allocator.
There are no file/descriptor inputs, file mappings, global allocators or Python
references. macOS and Linux are the supported project targets.

Verification: native initialization/content/length tests, repeated allocation
and owned cross-thread transfer, compile-fail checks for forbidden auto-traits,
strict compiler/Clippy checks, independent source review and available native
sanitizer/platform runs. Miri cannot establish OS mapping behavior; unsupported
or unexecuted tooling is recorded explicitly. Full performance/FFI acceptance
is separate and uses unchanged model/integrity/timing/RSS criteria.
