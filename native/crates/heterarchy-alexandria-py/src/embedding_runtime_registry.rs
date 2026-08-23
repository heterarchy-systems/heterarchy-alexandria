//! Process-scoped, concurrency-safe lifetime control for native embedding sessions.
//!
//! The registry owns no inference implementation. A concrete FastEmbed/ONNX factory is
//! injected at initialization time, which keeps model/cache effects in the `PyO3` adapter
//! while the pure compute crate remains unaware of runtime sessions.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::{Arc, Mutex};

const MAX_EMBEDDING_DIMENSIONS: usize = 65_536;
const MAX_EMBEDDING_THREADS: usize = 4_096;

/// Stable process-session identity for one native embedding runtime configuration.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct EmbeddingRuntimeIdentity {
    runtime_name: String,
    model_name: String,
    dimensions: usize,
    cache_directory: Option<String>,
    threads: usize,
}

impl EmbeddingRuntimeIdentity {
    /// Construct one validated runtime identity.
    ///
    /// Cache paths remain opaque identity material. The registry does not inspect the
    /// filesystem, download models, or decide cache-repair policy.
    ///
    /// # Errors
    ///
    /// Returns a typed configuration error for blank/null-bearing text, zero or excessive
    /// dimensions, zero or excessive thread counts, or a blank optional cache directory.
    pub fn new(
        runtime_name: String,
        model_name: String,
        dimensions: usize,
        cache_directory: Option<String>,
        threads: usize,
    ) -> Result<Self, EmbeddingRuntimeError> {
        validate_identity_text("runtime_name", &runtime_name)?;
        validate_identity_text("model_name", &model_name)?;
        if dimensions == 0 || dimensions > MAX_EMBEDDING_DIMENSIONS {
            return Err(EmbeddingRuntimeError::invalid_configuration(format!(
                "dimensions must be between 1 and {MAX_EMBEDDING_DIMENSIONS}"
            )));
        }
        if threads == 0 || threads > MAX_EMBEDDING_THREADS {
            return Err(EmbeddingRuntimeError::invalid_configuration(format!(
                "threads must be between 1 and {MAX_EMBEDDING_THREADS}"
            )));
        }
        if let Some(cache_directory) = cache_directory.as_deref() {
            validate_identity_text("cache_directory", cache_directory)?;
        }
        Ok(Self {
            runtime_name,
            model_name,
            dimensions,
            cache_directory,
            threads,
        })
    }

    /// Return the runtime implementation identifier.
    #[must_use]
    pub fn runtime_name(&self) -> &str {
        &self.runtime_name
    }

    /// Return the configured model identifier.
    #[must_use]
    pub fn model_name(&self) -> &str {
        &self.model_name
    }

    /// Return the required output dimensions.
    #[must_use]
    pub const fn dimensions(&self) -> usize {
        self.dimensions
    }

    /// Return the opaque configured cache directory, when present.
    #[must_use]
    pub fn cache_directory(&self) -> Option<&str> {
        self.cache_directory.as_deref()
    }

    /// Return the configured native inference thread count.
    #[must_use]
    pub const fn threads(&self) -> usize {
        self.threads
    }
}

/// Stable error category for native embedding session lifecycle operations.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EmbeddingRuntimeErrorCode {
    /// Runtime identity or configuration is invalid.
    InvalidConfiguration,
    /// The process-level identity registry lock was poisoned.
    RegistryUnavailable,
    /// One identity-specific initialization lock was poisoned.
    SessionUnavailable,
    /// The concrete model/runtime factory failed to initialize a session.
    BackendInitialization,
}

/// Typed non-secret failure returned by the native embedding runtime boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbeddingRuntimeError {
    code: EmbeddingRuntimeErrorCode,
    message: String,
}

impl EmbeddingRuntimeError {
    fn invalid_configuration(message: impl Into<String>) -> Self {
        Self {
            code: EmbeddingRuntimeErrorCode::InvalidConfiguration,
            message: message.into(),
        }
    }

    fn registry_unavailable() -> Self {
        Self {
            code: EmbeddingRuntimeErrorCode::RegistryUnavailable,
            message: "native embedding runtime registry is unavailable".to_owned(),
        }
    }

    fn session_unavailable() -> Self {
        Self {
            code: EmbeddingRuntimeErrorCode::SessionUnavailable,
            message: "native embedding runtime session slot is unavailable".to_owned(),
        }
    }

    /// Construct a sanitized concrete-backend initialization failure.
    ///
    /// The caller must avoid including credentials, absolute cache paths, or model artifact
    /// URLs in the supplied message.
    #[must_use]
    pub fn backend_initialization(message: impl Into<String>) -> Self {
        Self {
            code: EmbeddingRuntimeErrorCode::BackendInitialization,
            message: message.into(),
        }
    }

    /// Return the stable machine-readable error category.
    #[must_use]
    pub const fn code(&self) -> EmbeddingRuntimeErrorCode {
        self.code
    }

    /// Return the sanitized diagnostic message.
    #[must_use]
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl Display for EmbeddingRuntimeError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for EmbeddingRuntimeError {}

/// Process-lifetime registry for lazily initialized embedding sessions.
///
/// The intended production owner is one `static` registry in the `PyO3` adapter. Sessions
/// with the same identity initialize serially and reuse one `Arc`; distinct identities may
/// initialize concurrently. Failed initialization is not cached, matching the current
/// Python provider's retry-on-next-call behavior.
pub struct EmbeddingRuntimeRegistry<Session> {
    slots: Mutex<BTreeMap<EmbeddingRuntimeIdentity, Arc<EmbeddingSessionSlot<Session>>>>,
}

impl<Session> EmbeddingRuntimeRegistry<Session> {
    /// Construct an empty process-level registry.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            slots: Mutex::new(BTreeMap::new()),
        }
    }

    /// Return a cached session or initialize it exactly once for concurrent callers.
    ///
    /// The factory executes while holding only the identity-specific lock. Different model
    /// identities therefore do not serialize model loading. A failed factory call leaves the
    /// slot empty so a later request can retry initialization.
    ///
    /// # Errors
    ///
    /// Returns a typed error when registry/session synchronization is unavailable or when the
    /// concrete backend factory reports an initialization failure.
    pub fn session_or_initialize<Factory>(
        &self,
        identity: &EmbeddingRuntimeIdentity,
        initialize: Factory,
    ) -> Result<Arc<Session>, EmbeddingRuntimeError>
    where
        Factory: FnOnce(&EmbeddingRuntimeIdentity) -> Result<Session, EmbeddingRuntimeError>,
    {
        let slot = self.slot(identity)?;
        let mut session = slot
            .session
            .lock()
            .map_err(|_| EmbeddingRuntimeError::session_unavailable())?;
        if let Some(existing) = session.as_ref() {
            return Ok(Arc::clone(existing));
        }
        let initialized = Arc::new(initialize(identity)?);
        *session = Some(Arc::clone(&initialized));
        Ok(initialized)
    }

    /// Return the number of runtime identities observed by this process registry.
    ///
    /// Failed initialization attempts still reserve an identity slot so simultaneous retries
    /// continue to serialize correctly.
    ///
    /// # Errors
    ///
    /// Returns a typed error when the process-level registry lock is unavailable.
    pub fn identity_count(&self) -> Result<usize, EmbeddingRuntimeError> {
        let slots = self
            .slots
            .lock()
            .map_err(|_| EmbeddingRuntimeError::registry_unavailable())?;
        Ok(slots.len())
    }

    fn slot(
        &self,
        identity: &EmbeddingRuntimeIdentity,
    ) -> Result<Arc<EmbeddingSessionSlot<Session>>, EmbeddingRuntimeError> {
        let mut slots = self
            .slots
            .lock()
            .map_err(|_| EmbeddingRuntimeError::registry_unavailable())?;
        Ok(Arc::clone(
            slots
                .entry(identity.clone())
                .or_insert_with(|| Arc::new(EmbeddingSessionSlot::new())),
        ))
    }
}

impl<Session> Default for EmbeddingRuntimeRegistry<Session> {
    fn default() -> Self {
        Self::new()
    }
}

struct EmbeddingSessionSlot<Session> {
    session: Mutex<Option<Arc<Session>>>,
}

impl<Session> EmbeddingSessionSlot<Session> {
    const fn new() -> Self {
        Self {
            session: Mutex::new(None),
        }
    }
}

fn validate_identity_text(field_name: &str, value: &str) -> Result<(), EmbeddingRuntimeError> {
    if value.trim().is_empty() {
        return Err(EmbeddingRuntimeError::invalid_configuration(format!(
            "{field_name} must not be blank"
        )));
    }
    if value.contains('\0') {
        return Err(EmbeddingRuntimeError::invalid_configuration(format!(
            "{field_name} must not contain a null byte"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::mpsc;
    use std::sync::{Arc, Barrier};
    use std::thread;
    use std::time::Duration;

    use super::{
        EmbeddingRuntimeError, EmbeddingRuntimeErrorCode, EmbeddingRuntimeIdentity,
        EmbeddingRuntimeRegistry,
    };

    #[derive(Debug, PartialEq, Eq)]
    struct FakeSession {
        marker: usize,
    }

    fn identity(model_name: &str, threads: usize) -> EmbeddingRuntimeIdentity {
        match EmbeddingRuntimeIdentity::new(
            "fastembed".to_owned(),
            model_name.to_owned(),
            384,
            Some("cache-key".to_owned()),
            threads,
        ) {
            Ok(value) => value,
            Err(error) => unreachable!("test identity must be valid: {error}"),
        }
    }

    #[test]
    fn rejects_invalid_runtime_identity_configuration() {
        let blank = EmbeddingRuntimeIdentity::new(" ".to_owned(), "model".to_owned(), 384, None, 4);
        let Err(blank_error) = blank else {
            unreachable!("blank runtime name must fail");
        };
        assert_eq!(
            blank_error.code(),
            EmbeddingRuntimeErrorCode::InvalidConfiguration
        );

        let dimensions =
            EmbeddingRuntimeIdentity::new("fastembed".to_owned(), "model".to_owned(), 0, None, 4);
        assert!(dimensions.is_err());

        let threads =
            EmbeddingRuntimeIdentity::new("fastembed".to_owned(), "model".to_owned(), 384, None, 0);
        assert!(threads.is_err());
    }

    #[test]
    fn concurrent_same_identity_initializes_one_shared_session() {
        let registry = Arc::new(EmbeddingRuntimeRegistry::<FakeSession>::new());
        let identity = identity("intfloat/multilingual-e5-small", 4);
        let initialization_count = Arc::new(AtomicUsize::new(0));
        let start = Arc::new(Barrier::new(16));
        let mut handles = Vec::new();
        for _ in 0..16 {
            let registry = Arc::clone(&registry);
            let identity = identity.clone();
            let initialization_count = Arc::clone(&initialization_count);
            let start = Arc::clone(&start);
            handles.push(thread::spawn(move || {
                start.wait();
                registry.session_or_initialize(&identity, |_| {
                    initialization_count.fetch_add(1, Ordering::SeqCst);
                    thread::sleep(Duration::from_millis(15));
                    Ok(FakeSession { marker: 7 })
                })
            }));
        }

        let mut addresses = BTreeSet::new();
        for handle in handles {
            let Ok(joined) = handle.join() else {
                unreachable!("session worker must not panic");
            };
            let session = match joined {
                Ok(value) => value,
                Err(error) => unreachable!("session initialization failed: {error}"),
            };
            addresses.insert(Arc::as_ptr(&session) as usize);
            assert_eq!(session.marker, 7);
        }
        assert_eq!(addresses.len(), 1);
        assert_eq!(initialization_count.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn distinct_identities_may_initialize_concurrently() {
        let registry = Arc::new(EmbeddingRuntimeRegistry::<FakeSession>::new());
        let first_identity = identity("model-a", 4);
        let second_identity = identity("model-b", 4);
        let (entered_sender, entered_receiver) = mpsc::channel::<String>();
        let (first_release_sender, first_release_receiver) = mpsc::channel::<()>();
        let (second_release_sender, second_release_receiver) = mpsc::channel::<()>();

        let first_registry = Arc::clone(&registry);
        let first_sender = entered_sender.clone();
        let first = thread::spawn(move || {
            first_registry.session_or_initialize(&first_identity, |runtime_identity| {
                first_sender
                    .send(runtime_identity.model_name().to_owned())
                    .map_err(|_| {
                        EmbeddingRuntimeError::backend_initialization("entry signal failed")
                    })?;
                first_release_receiver
                    .recv_timeout(Duration::from_secs(1))
                    .map_err(|_| {
                        EmbeddingRuntimeError::backend_initialization("release signal failed")
                    })?;
                Ok(FakeSession { marker: 1 })
            })
        });

        let second_registry = Arc::clone(&registry);
        let second_sender = entered_sender;
        let second = thread::spawn(move || {
            second_registry.session_or_initialize(&second_identity, |runtime_identity| {
                second_sender
                    .send(runtime_identity.model_name().to_owned())
                    .map_err(|_| {
                        EmbeddingRuntimeError::backend_initialization("entry signal failed")
                    })?;
                second_release_receiver
                    .recv_timeout(Duration::from_secs(1))
                    .map_err(|_| {
                        EmbeddingRuntimeError::backend_initialization("release signal failed")
                    })?;
                Ok(FakeSession { marker: 2 })
            })
        });

        let first_entry = entered_receiver.recv_timeout(Duration::from_secs(1));
        let second_entry = entered_receiver.recv_timeout(Duration::from_secs(1));
        let _ = first_release_sender.send(());
        let _ = second_release_sender.send(());
        let first_entry = match first_entry {
            Ok(value) => value,
            Err(error) => unreachable!("first runtime did not enter initialization: {error}"),
        };
        let second_entry = match second_entry {
            Ok(value) => value,
            Err(error) => unreachable!("distinct runtime initialization serialized: {error}"),
        };
        assert_ne!(first_entry, second_entry);

        for handle in [first, second] {
            let Ok(joined) = handle.join() else {
                unreachable!("distinct identity worker must not panic");
            };
            if let Err(error) = joined {
                unreachable!("distinct identity initialization failed: {error}");
            }
        }
    }

    #[test]
    fn failed_initialization_is_retried_on_the_next_call() {
        let registry = EmbeddingRuntimeRegistry::<FakeSession>::new();
        let identity = identity("retry-model", 4);
        let attempts = AtomicUsize::new(0);

        let first = registry.session_or_initialize(&identity, |_| {
            attempts.fetch_add(1, Ordering::SeqCst);
            Err(EmbeddingRuntimeError::backend_initialization(
                "temporary model initialization failure",
            ))
        });
        let Err(first_error) = first else {
            unreachable!("first initialization must fail");
        };
        assert_eq!(
            first_error.code(),
            EmbeddingRuntimeErrorCode::BackendInitialization
        );

        let second = registry.session_or_initialize(&identity, |_| {
            attempts.fetch_add(1, Ordering::SeqCst);
            Ok(FakeSession { marker: 9 })
        });
        let second = match second {
            Ok(value) => value,
            Err(error) => unreachable!("second initialization must retry: {error}"),
        };
        assert_eq!(second.marker, 9);
        assert_eq!(attempts.load(Ordering::SeqCst), 2);
        let identity_count = match registry.identity_count() {
            Ok(value) => value,
            Err(error) => unreachable!("identity count failed: {error}"),
        };
        assert_eq!(identity_count, 1);
    }
}
