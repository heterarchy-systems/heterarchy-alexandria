//! Uniquely owned anonymous storage for serialized model input. See `SAFETY.md`.
//!
//! These owners deliberately cannot be shared by reference or cloned.
//! ```compile_fail
//! fn requires_sync<T: Sync>() {}
//! requires_sync::<heterarchy_alexandria_model_buffer::MutableModelBuffer>();
//! ```
//! ```compile_fail
//! fn requires_sync<T: Sync>() {}
//! requires_sync::<heterarchy_alexandria_model_buffer::ModelBuffer>();
//! ```
//! ```compile_fail
//! fn requires_clone<T: Clone>() {}
//! requires_clone::<heterarchy_alexandria_model_buffer::MutableModelBuffer>();
//! ```
//! ```compile_fail
//! fn requires_clone<T: Clone>() {}
//! requires_clone::<heterarchy_alexandria_model_buffer::ModelBuffer>();
//! ```

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
compile_error!("anonymous model buffers support only the project's macOS/Linux targets");

use std::io;
use std::ptr::{self, NonNull};
use std::slice;

struct Mapping {
    pointer: NonNull<u8>,
    size: usize,
}

// SAFETY: Mapping has unique ownership, no public pointer/alias constructor and no
// thread-affine OS resource. Moving its owner preserves every live borrow's Rust
// lifetime. Access remains exclusive before freeze; neither owner implements Sync.
unsafe impl Send for Mapping {}

impl Mapping {
    fn new(size: usize) -> io::Result<Self> {
        if size == 0 || size > isize::MAX as usize {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "model buffer size must be nonzero and fit a Rust slice",
            ));
        }
        // SAFETY: No requested address or file backing. A successful private
        // anonymous map owns size initialized, readable/writable bytes. The OS
        // rounds mapping pages; we retain the original valid nonzero range.
        let pointer = unsafe {
            libc::mmap(
                ptr::null_mut(),
                size,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_PRIVATE | libc::MAP_ANON,
                -1,
                0,
            )
        };
        if pointer == libc::MAP_FAILED {
            return Err(io::Error::last_os_error());
        }
        let Some(pointer) = NonNull::new(pointer.cast::<u8>()) else {
            // SAFETY: A successful zero-address mapping still owns this range,
            // but Rust cannot represent its slices. Release it before rejecting.
            let _ = unsafe { libc::munmap(pointer, size) };
            return Err(io::Error::other(
                "model buffer mapping returned a null address",
            ));
        };
        Ok(Self { pointer, size })
    }
}

impl Drop for Mapping {
    fn drop(&mut self) {
        // SAFETY: This is the sole destructor owner of the original mmap range;
        // no Rust borrow can outlive it. Never retry through a second allocator.
        // An OS unmap failure retains storage; Drop must not mask another error.
        let _ = unsafe { libc::munmap(self.pointer.as_ptr().cast(), self.size) };
    }
}

/// Exclusive, initialized storage that receives model bytes before validation.
pub struct MutableModelBuffer(Mapping);

impl MutableModelBuffer {
    /// Allocate zero-initialized anonymous model storage.
    ///
    /// # Errors
    /// Rejects empty/oversized ranges or returns the OS allocation error.
    pub fn new(size: usize) -> io::Result<Self> {
        Mapping::new(size).map(Self)
    }

    /// Consume mutable ownership and seal the mapping read-only.
    ///
    /// # Errors
    /// Returns the protection error after dropping the sole mapping owner.
    pub fn freeze(self) -> io::Result<ModelBuffer> {
        // SAFETY: This exclusively owned, page-aligned mmap base and its original
        // nonzero size describe the entire mapping. No mutable borrow survives
        // this consuming call. No new owner is constructed before success.
        let status =
            unsafe { libc::mprotect(self.0.pointer.as_ptr().cast(), self.0.size, libc::PROT_READ) };
        if status != 0 {
            let error = io::Error::last_os_error();
            return Err(error);
        }
        Ok(ModelBuffer(self.0))
    }
}

impl AsMut<[u8]> for MutableModelBuffer {
    fn as_mut(&mut self) -> &mut [u8] {
        // SAFETY: Anonymous bytes are initialized; size fits isize, pointer is
        // nonnull and aligned for u8. Exclusive borrow prevents aliasing/moves.
        unsafe { slice::from_raw_parts_mut(self.0.pointer.as_ptr(), self.0.size) }
    }
}

/// Read-only model storage, released independently of the process malloc cache.
pub struct ModelBuffer(Mapping);

impl AsRef<[u8]> for ModelBuffer {
    fn as_ref(&self) -> &[u8] {
        // SAFETY: Freeze retained one initialized readable mapping and removed
        // mutable access. The returned slice cannot outlive its owner borrow.
        unsafe { slice::from_raw_parts(self.0.pointer.as_ptr(), self.0.size) }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_lengths_that_cannot_form_owned_slices() {
        for size in [0, isize::MAX as usize + 1, usize::MAX] {
            assert!(
                matches!(MutableModelBuffer::new(size), Err(error) if error.kind() == io::ErrorKind::InvalidInput)
            );
        }
    }

    #[test]
    fn zeroed_storage_preserves_exact_unaligned_length_after_freeze() -> io::Result<()> {
        for size in [1, 4097, 16385] {
            let mut buffer = MutableModelBuffer::new(size)?;
            assert_eq!(buffer.as_mut().len(), size);
            assert!(buffer.as_mut().iter().all(|byte| *byte == 0));
            buffer.as_mut()[0] = 7;
            buffer.as_mut()[size - 1] = 13;
            let frozen = buffer.freeze()?;
            assert_eq!(frozen.as_ref().len(), size);
            assert_eq!(frozen.as_ref()[size - 1], 13);
            if size > 1 {
                assert_eq!(frozen.as_ref()[0], 7);
            }
        }
        Ok(())
    }

    #[test]
    fn independently_owned_buffers_survive_thread_transfer_and_repeated_drop() -> io::Result<()> {
        let mut pending = Vec::new();
        for tag in 0_u8..8 {
            let mut buffer = MutableModelBuffer::new(65537)?;
            buffer.as_mut().fill(tag);
            pending.push(std::thread::spawn(move || -> io::Result<()> {
                let buffer = buffer.freeze()?;
                assert!(buffer.as_ref().iter().all(|byte| *byte == tag));
                for _ in 0..128 {
                    let mut next = MutableModelBuffer::new(4097)?;
                    next.as_mut()[4096] = tag;
                    assert_eq!(next.freeze()?.as_ref()[4096], tag);
                }
                Ok(())
            }));
        }
        for worker in pending {
            worker
                .join()
                .map_err(|_| io::Error::other("model buffer worker panicked"))??;
        }
        Ok(())
    }
}
