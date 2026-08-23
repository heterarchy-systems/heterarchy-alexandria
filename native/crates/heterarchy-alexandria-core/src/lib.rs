//! Pure Rust compute-domain scaffold for heterarchy-alexandria.
//!
//! Python remains authoritative for transport, persistence, lifecycle, and external effects.

pub mod bulk_embedding;
pub mod document_analysis;
pub mod graph_compute;
pub mod hash_fingerprint;
pub mod markdown_chunking;
pub mod reconciliation_candidates;
pub mod reference_extraction;
pub mod retrieval_kernel;
mod text_compat;

/// Version of the coarse-grained Python/Rust compute contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ComputeContractVersion(u16);

impl ComputeContractVersion {
    /// Current native compute contract version.
    pub const CURRENT: Self = Self(1);

    /// Return the numeric contract version for adapter diagnostics.
    #[must_use]
    pub const fn value(self) -> u16 {
        self.0
    }
}

#[cfg(test)]
mod tests {
    use super::ComputeContractVersion;

    #[test]
    fn current_contract_version_is_stable() {
        assert_eq!(ComputeContractVersion::CURRENT.value(), 1);
    }
}
