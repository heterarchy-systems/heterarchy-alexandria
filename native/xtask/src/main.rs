use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::{self, Command};
use toml::Value;

const MODEL_BUFFER_MEMBER: &str = "crates/heterarchy-alexandria-model-buffer";
const MODEL_BUFFER_PACKAGE: &str = "heterarchy-alexandria-model-buffer";
const EXPECTED_MEMBERS: [&str; 4] = [
    "crates/heterarchy-alexandria-core",
    "crates/heterarchy-alexandria-py",
    MODEL_BUFFER_MEMBER,
    "xtask",
];
const EXPECTED_FEATURES: [&str; 10] = [
    "document_analysis",
    "chunking",
    "link_extraction",
    "fingerprint",
    "graph_compute",
    "embedding_compute",
    "retrieval_kernel",
    "reconciliation_candidates",
    "context_reindex_manifest",
    "compile_plan",
];
const FORBIDDEN_CORE_DEPENDENCIES: [&str; 8] = [
    "pyo3",
    "sqlx",
    "postgres",
    "tokio-postgres",
    "diesel",
    "redis",
    "reqwest",
    "ureq",
];
const FORBIDDEN_CORE_SOURCE_MARKERS: [&str; 7] = [
    "pyo3::",
    "std::fs",
    "std::net",
    "std::process::Command",
    "sqlx::",
    "redis::",
    "reqwest::",
];

type TaskResult<T> = Result<T, String>;

#[derive(Debug, Deserialize)]
struct CargoMetadata {
    target_directory: PathBuf,
}

#[derive(Debug, Clone, Eq, PartialEq)]
struct NativeArtifactPaths {
    target_directory: PathBuf,
    fastembed_cache_directory: PathBuf,
}

impl NativeArtifactPaths {
    fn resolve(repository_root: &Path) -> TaskResult<Self> {
        let target_directory = cargo_target_directory(repository_root)?;
        let configured_cache = env::var_os("ALEXANDRIA_FASTEMBED_PARITY_CACHE");
        let fastembed_cache_directory = resolve_fastembed_cache_directory(
            repository_root,
            &target_directory,
            configured_cache.as_deref(),
        )?;
        Ok(Self {
            target_directory,
            fastembed_cache_directory,
        })
    }
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Authority {
    Python,
    Rust,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum RetirementState {
    Pending,
    Complete,
}

#[derive(Debug, Deserialize)]
struct LegacyPythonMarker {
    path: String,
    contains: String,
}

#[derive(Debug, Deserialize)]
struct FeatureAuthority {
    authority: Authority,
    python_retirement: RetirementState,
    legacy_inventory_complete: bool,
    golden_corpora: Vec<String>,
    legacy_python_markers: Vec<LegacyPythonMarker>,
    forbidden_python_imports_when_rust: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct CutoverPolicy {
    forbidden_production_markers: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct AuthorityRegistry {
    schema_version: u32,
    cutover: CutoverPolicy,
    features: BTreeMap<String, FeatureAuthority>,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("xtask: FAIL: {error}");
        process::exit(1);
    }
}

fn run() -> TaskResult<()> {
    let mut arguments = env::args().skip(1);
    let command = arguments.next().ok_or_else(|| {
        "missing command; expected rules|fmt|check|test|python-ci|ci|perf|extended|doctor|deps|gil-policy"
            .to_owned()
    })?;
    if arguments.next().is_some() {
        return Err("xtask commands do not accept positional arguments".to_owned());
    }

    let repository_root = repository_root()?;
    match command.as_str() {
        "rules" => verify_rules(&repository_root),
        "fmt" => run_fmt(&repository_root),
        "check" => run_check(&repository_root),
        "test" => run_tests(&repository_root),
        "python-ci" => run_python_ci(&repository_root),
        "ci" => run_ci(&repository_root),
        "perf" => run_perf(&repository_root),
        "extended" => run_extended(&repository_root),
        "doctor" => run_doctor(&repository_root),
        "deps" => run_deps(&repository_root),
        "gil-policy" => run_gil_policy_probe(&repository_root),
        _ => Err(format!("unknown xtask command: {command}")),
    }
}

fn repository_root() -> TaskResult<PathBuf> {
    let xtask_root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let native_root = xtask_root
        .parent()
        .ok_or_else(|| "xtask manifest has no native parent".to_owned())?;
    let repository_root = native_root
        .parent()
        .ok_or_else(|| "native workspace has no repository parent".to_owned())?;
    Ok(repository_root.to_path_buf())
}

fn verify_rules(repository_root: &Path) -> TaskResult<()> {
    let workspace_manifest = read_toml(&repository_root.join("native/Cargo.toml"))?;
    verify_workspace_manifest(&workspace_manifest)?;
    verify_member_manifests(repository_root)?;
    verify_dependency_direction(repository_root)?;
    verify_core_effect_boundary(repository_root)?;
    verify_authority_registry(repository_root)?;
    println!("rules: PASS");
    Ok(())
}

fn verify_workspace_manifest(manifest: &Value) -> TaskResult<()> {
    let workspace = manifest
        .get("workspace")
        .and_then(Value::as_table)
        .ok_or_else(|| "native/Cargo.toml is missing [workspace]".to_owned())?;

    let resolver = workspace
        .get("resolver")
        .and_then(Value::as_str)
        .ok_or_else(|| "workspace resolver is missing".to_owned())?;
    if resolver != "3" {
        return Err(format!("workspace resolver must be 3, found {resolver}"));
    }

    let package = workspace
        .get("package")
        .and_then(Value::as_table)
        .ok_or_else(|| "workspace is missing [workspace.package]".to_owned())?;
    let edition = package
        .get("edition")
        .and_then(Value::as_str)
        .ok_or_else(|| "workspace package edition is missing".to_owned())?;
    if edition != "2024" {
        return Err(format!("workspace edition must be 2024, found {edition}"));
    }

    verify_workspace_members(workspace)?;
    verify_workspace_lints(workspace)
}

fn verify_workspace_members(workspace: &toml::Table) -> TaskResult<()> {
    let members = workspace
        .get("members")
        .and_then(Value::as_array)
        .ok_or_else(|| "workspace members are missing".to_owned())?;
    let mut actual = BTreeSet::new();
    for member in members {
        let member = member
            .as_str()
            .ok_or_else(|| "workspace member must be a string".to_owned())?;
        actual.insert(member.to_owned());
    }
    let expected = EXPECTED_MEMBERS
        .into_iter()
        .map(str::to_owned)
        .collect::<BTreeSet<_>>();
    if actual != expected {
        return Err(format!(
            "workspace members differ: expected {expected:?}, found {actual:?}"
        ));
    }
    Ok(())
}

fn verify_workspace_lints(workspace: &toml::Table) -> TaskResult<()> {
    let lints = workspace
        .get("lints")
        .and_then(Value::as_table)
        .ok_or_else(|| "workspace is missing [workspace.lints]".to_owned())?;
    let rust_lints = lints
        .get("rust")
        .and_then(Value::as_table)
        .ok_or_else(|| "workspace is missing [workspace.lints.rust]".to_owned())?;
    require_lint_level(rust_lints, "unsafe_code", "forbid")?;
    require_lint_level(rust_lints, "unused_must_use", "deny")?;

    let clippy_lints = lints
        .get("clippy")
        .and_then(Value::as_table)
        .ok_or_else(|| "workspace is missing [workspace.lints.clippy]".to_owned())?;
    require_lint_level(clippy_lints, "all", "deny")?;
    require_lint_level(clippy_lints, "pedantic", "warn")?;
    for lint in [
        "unwrap_used",
        "expect_used",
        "panic",
        "todo",
        "unimplemented",
        "dbg_macro",
    ] {
        require_lint_level(clippy_lints, lint, "deny")?;
    }
    if clippy_lints.contains_key("restriction") {
        return Err("whole clippy restriction group must not be configured".to_owned());
    }
    Ok(())
}

fn require_lint_level(table: &toml::Table, lint: &str, expected: &str) -> TaskResult<()> {
    let value = table
        .get(lint)
        .ok_or_else(|| format!("required lint {lint} is missing"))?;
    let level = if let Some(level) = value.as_str() {
        level
    } else {
        value
            .as_table()
            .and_then(|lint_table| lint_table.get("level"))
            .and_then(Value::as_str)
            .ok_or_else(|| format!("lint {lint} has no string level"))?
    };
    if level != expected {
        return Err(format!("lint {lint} must be {expected}, found {level}"));
    }
    Ok(())
}

fn verify_member_manifests(repository_root: &Path) -> TaskResult<()> {
    for member in EXPECTED_MEMBERS {
        let manifest_path = repository_root
            .join("native")
            .join(member)
            .join("Cargo.toml");
        let manifest = read_toml(&manifest_path)?;
        verify_workspace_inheritance(&manifest, member)?;
    }
    Ok(())
}

fn verify_workspace_inheritance(manifest: &Value, member: &str) -> TaskResult<()> {
    let package = manifest
        .get("package")
        .and_then(Value::as_table)
        .ok_or_else(|| format!("{member} is missing [package]"))?;
    for key in ["version", "edition", "rust-version", "license"] {
        let inherited = package
            .get(key)
            .and_then(Value::as_table)
            .and_then(|value| value.get("workspace"))
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if !inherited {
            return Err(format!(
                "{member} must inherit package.{key} from the workspace"
            ));
        }
    }

    let inherits_lints = manifest
        .get("lints")
        .and_then(Value::as_table)
        .and_then(|lints| lints.get("workspace"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if member == MODEL_BUFFER_MEMBER {
        if inherits_lints {
            return Err(
                "approved model buffer must declare its exact local lint boundary".to_owned(),
            );
        }
        return verify_model_buffer_manifest(manifest);
    }
    if !inherits_lints {
        return Err(format!("{member} must declare [lints] workspace = true"));
    }
    Ok(())
}

fn verify_model_buffer_manifest(manifest: &Value) -> TaskResult<()> {
    if manifest
        .get("package")
        .and_then(|p| p.get("name"))
        .and_then(Value::as_str)
        != Some(MODEL_BUFFER_PACKAGE)
    {
        return Err("unsafe approval is limited to the exact model buffer package".to_owned());
    }
    let lints = manifest
        .get("lints")
        .and_then(Value::as_table)
        .ok_or_else(|| "model buffer must declare local lints".to_owned())?;
    let rust_lints = lints
        .get("rust")
        .and_then(Value::as_table)
        .ok_or_else(|| "model buffer must declare Rust lints".to_owned())?;
    for (name, level) in [
        ("unsafe_code", "allow"),
        ("unsafe_op_in_unsafe_fn", "deny"),
        ("unused_must_use", "deny"),
        ("warnings", "deny"),
    ] {
        require_lint_level(rust_lints, name, level)?;
    }
    let clippy = lints
        .get("clippy")
        .and_then(Value::as_table)
        .ok_or_else(|| "model buffer must declare Clippy lints".to_owned())?;
    for (name, level) in [
        ("all", "deny"),
        ("pedantic", "warn"),
        ("dbg_macro", "deny"),
        ("expect_used", "deny"),
        ("panic", "deny"),
        ("todo", "deny"),
        ("unimplemented", "deny"),
        ("unwrap_used", "deny"),
    ] {
        require_lint_level(clippy, name, level)?;
    }
    let dependencies = dependency_table(manifest);
    if dependencies.len() != 1
        || dependencies
            .get("libc")
            .and_then(|dependency| dependency.get("workspace"))
            .and_then(Value::as_bool)
            != Some(true)
    {
        return Err("model buffer may only reuse workspace libc".to_owned());
    }
    for section in ["dev-dependencies", "build-dependencies", "target"] {
        if manifest.get(section).is_some() {
            return Err(format!(
                "model buffer has unreviewed dependency section {section}"
            ));
        }
    }
    Ok(())
}

fn verify_dependency_direction(repository_root: &Path) -> TaskResult<()> {
    let workspace_manifest = read_toml(&repository_root.join("native/Cargo.toml"))?;
    verify_pyo3_workspace_configuration(&workspace_manifest)?;

    let core_manifest =
        read_toml(&repository_root.join("native/crates/heterarchy-alexandria-core/Cargo.toml"))?;
    let adapter_manifest =
        read_toml(&repository_root.join("native/crates/heterarchy-alexandria-py/Cargo.toml"))?;

    let core_dependencies = dependency_table(&core_manifest);
    if core_dependencies.contains_key(MODEL_BUFFER_PACKAGE) {
        return Err("core must not depend on the platform model-buffer boundary".to_owned());
    }
    if core_dependencies.contains_key("pyo3") {
        return Err("core crate must not depend on PyO3".to_owned());
    }
    if core_dependencies.contains_key("heterarchy-alexandria-py") {
        return Err("core crate must not depend on the Python adapter".to_owned());
    }

    let adapter_dependencies = dependency_table(&adapter_manifest);
    let buffer_path = adapter_dependencies
        .get(MODEL_BUFFER_PACKAGE)
        .and_then(|dependency| dependency.get("path"))
        .and_then(Value::as_str);
    if buffer_path != Some("../heterarchy-alexandria-model-buffer") {
        return Err("adapter must use the approved local model-buffer boundary".to_owned());
    }
    let core_dependency = adapter_dependencies
        .get("heterarchy-alexandria-core")
        .ok_or_else(|| "Python adapter must depend on heterarchy-alexandria-core".to_owned())?;
    let core_path = core_dependency
        .as_table()
        .and_then(|dependency| dependency.get("path"))
        .and_then(Value::as_str)
        .ok_or_else(|| "adapter core dependency must be a local path dependency".to_owned())?;
    if core_path != "../heterarchy-alexandria-core" {
        return Err(format!(
            "unexpected adapter->core dependency path: {core_path}"
        ));
    }
    if !adapter_dependencies.contains_key("pyo3") {
        return Err("Python adapter must own the PyO3 dependency".to_owned());
    }

    let adapter_build_dependencies = adapter_manifest
        .get("build-dependencies")
        .and_then(Value::as_table)
        .ok_or_else(|| "Python adapter must declare [build-dependencies]".to_owned())?;
    if !adapter_build_dependencies.contains_key("pyo3-build-config") {
        return Err("Python adapter must own pyo3-build-config as a build dependency".to_owned());
    }

    let build_script = "native/crates/heterarchy-alexandria-py/build.rs";
    require_non_empty_file(repository_root, build_script)?;
    let build_script_source = read_file(&repository_root.join(build_script))?;
    if !build_script_source.contains("pyo3_build_config::add_extension_module_link_args()") {
        return Err(
            "Python adapter build.rs must call pyo3_build_config::add_extension_module_link_args()"
                .to_owned(),
        );
    }
    Ok(())
}

fn verify_pyo3_workspace_configuration(manifest: &Value) -> TaskResult<()> {
    let workspace_dependencies = manifest
        .get("workspace")
        .and_then(Value::as_table)
        .and_then(|workspace| workspace.get("dependencies"))
        .and_then(Value::as_table)
        .ok_or_else(|| "workspace is missing [workspace.dependencies]".to_owned())?;
    let pyo3 = workspace_dependencies
        .get("pyo3")
        .and_then(Value::as_table)
        .ok_or_else(|| "workspace dependency pyo3 must use a dependency table".to_owned())?;
    let features = pyo3
        .get("features")
        .and_then(Value::as_array)
        .ok_or_else(|| "workspace pyo3 dependency must declare explicit features".to_owned())?;
    let feature_names = features
        .iter()
        .filter_map(Value::as_str)
        .collect::<BTreeSet<_>>();
    if feature_names.contains("extension-module") {
        return Err(
            "PyO3 extension-module feature is forbidden: it breaks Rust test/doc-test linking on current PyO3; use the adapter build.rs linker hook"
                .to_owned(),
        );
    }
    if !feature_names.contains("macros") {
        return Err("workspace PyO3 dependency must enable the macros feature".to_owned());
    }
    if !workspace_dependencies.contains_key("pyo3-build-config") {
        return Err("workspace must declare pyo3-build-config".to_owned());
    }
    Ok(())
}

fn dependency_table(manifest: &Value) -> toml::Table {
    manifest
        .get("dependencies")
        .and_then(Value::as_table)
        .cloned()
        .unwrap_or_default()
}

fn verify_core_effect_boundary(repository_root: &Path) -> TaskResult<()> {
    let core_root = repository_root.join("native/crates/heterarchy-alexandria-core");
    let manifest = read_toml(&core_root.join("Cargo.toml"))?;
    for section in ["dependencies", "dev-dependencies", "build-dependencies"] {
        if let Some(dependencies) = manifest.get(section).and_then(Value::as_table) {
            for dependency in dependencies.keys() {
                if is_forbidden_core_dependency(dependency) {
                    return Err(format!(
                        "core crate has forbidden effect/Python dependency {dependency} in [{section}]"
                    ));
                }
            }
        }
    }

    for source_file in files_with_extension(&core_root.join("src"), "rs")? {
        let source = read_file(&source_file)?;
        for marker in FORBIDDEN_CORE_SOURCE_MARKERS {
            if source.contains(marker) {
                return Err(format!(
                    "core source {} contains forbidden effect marker {marker}",
                    source_file.display()
                ));
            }
        }
    }
    Ok(())
}

fn is_forbidden_core_dependency(dependency: &str) -> bool {
    FORBIDDEN_CORE_DEPENDENCIES.contains(&dependency) || dependency.starts_with("aws-sdk-")
}

fn verify_authority_registry(repository_root: &Path) -> TaskResult<()> {
    let registry_path = repository_root.join("native/feature_authority.toml");
    let registry_source = read_file(&registry_path)?;
    let registry: AuthorityRegistry = toml::from_str(&registry_source)
        .map_err(|error| format!("failed to parse {}: {error}", registry_path.display()))?;
    if registry.schema_version != 1 {
        return Err(format!(
            "feature authority schema_version must be 1, found {}",
            registry.schema_version
        ));
    }
    verify_feature_set(&registry)?;

    let mut rust_authority_exists = false;
    for (feature_name, feature) in &registry.features {
        verify_feature_authority(repository_root, feature_name, feature)?;
        rust_authority_exists |= feature.authority == Authority::Rust;
    }
    if rust_authority_exists {
        verify_no_permanent_fallbacks(repository_root, &registry.cutover)?;
    }
    Ok(())
}

fn verify_feature_set(registry: &AuthorityRegistry) -> TaskResult<()> {
    let actual = registry.features.keys().cloned().collect::<BTreeSet<_>>();
    let expected = EXPECTED_FEATURES
        .into_iter()
        .map(str::to_owned)
        .collect::<BTreeSet<_>>();
    if actual != expected {
        return Err(format!(
            "feature authority registry differs: expected {expected:?}, found {actual:?}"
        ));
    }
    Ok(())
}

fn verify_feature_authority(
    repository_root: &Path,
    feature_name: &str,
    feature: &FeatureAuthority,
) -> TaskResult<()> {
    validate_registry_paths(feature_name, feature)?;
    for corpus in &feature.golden_corpora {
        require_non_empty_file(repository_root, corpus)?;
    }
    match feature.authority {
        Authority::Python => {
            if feature.python_retirement == RetirementState::Complete {
                return Err(format!(
                    "{feature_name}: Python authority cannot declare Python retirement complete"
                ));
            }
        }
        Authority::Rust => {
            if feature.python_retirement != RetirementState::Complete {
                return Err(format!(
                    "{feature_name}: Rust authority requires python_retirement = complete"
                ));
            }
            if !feature.legacy_inventory_complete {
                return Err(format!(
                    "{feature_name}: Rust authority requires a completed live Python owner inventory"
                ));
            }
            if feature.golden_corpora.is_empty() {
                return Err(format!(
                    "{feature_name}: Rust authority requires at least one golden corpus"
                ));
            }
            verify_legacy_markers_removed(repository_root, feature_name, feature)?;
            verify_forbidden_python_imports_removed(repository_root, feature_name, feature)?;
        }
    }
    Ok(())
}

fn validate_registry_paths(feature_name: &str, feature: &FeatureAuthority) -> TaskResult<()> {
    for corpus in &feature.golden_corpora {
        validate_repository_relative_path(feature_name, corpus)?;
    }
    for marker in &feature.legacy_python_markers {
        validate_repository_relative_path(feature_name, &marker.path)?;
        if marker.contains.trim().is_empty() {
            return Err(format!("{feature_name}: legacy marker cannot be empty"));
        }
    }
    for import in &feature.forbidden_python_imports_when_rust {
        if import.trim().is_empty() {
            return Err(format!(
                "{feature_name}: forbidden Python import cannot be empty"
            ));
        }
    }
    Ok(())
}

fn validate_repository_relative_path(feature_name: &str, value: &str) -> TaskResult<()> {
    let path = Path::new(value);
    let escapes_repository = path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        });
    if value.trim().is_empty() || escapes_repository {
        return Err(format!(
            "{feature_name}: registry path must be a non-empty repository-relative path: {value}"
        ));
    }
    Ok(())
}

fn verify_legacy_markers_removed(
    repository_root: &Path,
    feature_name: &str,
    feature: &FeatureAuthority,
) -> TaskResult<()> {
    for marker in &feature.legacy_python_markers {
        let path = repository_root.join(&marker.path);
        if path.is_file() && read_file(&path)?.contains(&marker.contains) {
            return Err(format!(
                "{feature_name}: legacy Python authority marker remains at {}: {}",
                marker.path, marker.contains
            ));
        }
    }
    Ok(())
}

fn verify_forbidden_python_imports_removed(
    repository_root: &Path,
    feature_name: &str,
    feature: &FeatureAuthority,
) -> TaskResult<()> {
    let python_roots = [
        repository_root.join("backend/app"),
        repository_root.join("backend/tests"),
        repository_root.join("native/tests"),
    ];
    for forbidden_import in &feature.forbidden_python_imports_when_rust {
        for python_root in &python_roots {
            if let Some(path) = find_python_import_marker(python_root, forbidden_import)? {
                return Err(format!(
                    "{feature_name}: forbidden Python import marker {forbidden_import} remains in {}",
                    path.display()
                ));
            }
        }
    }
    Ok(())
}

fn verify_no_permanent_fallbacks(
    repository_root: &Path,
    cutover: &CutoverPolicy,
) -> TaskResult<()> {
    let production_root = repository_root.join("backend/app");
    for marker in &cutover.forbidden_production_markers {
        if marker.trim().is_empty() {
            return Err("cutover forbidden production marker cannot be empty".to_owned());
        }
        if let Some(path) = find_marker(&production_root, "py", marker)? {
            return Err(format!(
                "permanent Python/Rust fallback marker {marker} remains in {}",
                path.display()
            ));
        }
    }
    Ok(())
}

fn find_marker(root: &Path, extension: &str, marker: &str) -> TaskResult<Option<PathBuf>> {
    for path in files_with_extension(root, extension)? {
        if read_file(&path)?.contains(marker) {
            return Ok(Some(path));
        }
    }
    Ok(None)
}

fn find_python_import_marker(root: &Path, marker: &str) -> TaskResult<Option<PathBuf>> {
    for path in files_with_extension(root, "py")? {
        if contains_python_module_marker(&read_file(&path)?, marker) {
            return Ok(Some(path));
        }
    }
    Ok(None)
}

fn contains_python_module_marker(source: &str, marker: &str) -> bool {
    source.match_indices(marker).any(|(offset, matched)| {
        // A retired package marker also forbids its submodules, but does not
        // name unrelated modules such as fastembed_runtime or fastembed_tools.
        source[offset + matched.len()..]
            .chars()
            .next()
            .is_none_or(|next| next != '_' && !next.is_alphanumeric())
    })
}

fn files_with_extension(root: &Path, extension: &str) -> TaskResult<Vec<PathBuf>> {
    let mut files = Vec::new();
    collect_files_with_extension(root, extension, &mut files)?;
    files.sort();
    Ok(files)
}

fn collect_files_with_extension(
    root: &Path,
    extension: &str,
    files: &mut Vec<PathBuf>,
) -> TaskResult<()> {
    let entries = fs::read_dir(root)
        .map_err(|error| format!("failed to read directory {}: {error}", root.display()))?;
    for entry in entries {
        let entry = entry
            .map_err(|error| format!("failed to read entry in {}: {error}", root.display()))?;
        let path = entry.path();
        if path.is_dir() {
            collect_files_with_extension(&path, extension, files)?;
        } else if path.extension().and_then(|value| value.to_str()) == Some(extension) {
            files.push(path);
        }
    }
    Ok(())
}

fn require_non_empty_file(repository_root: &Path, relative_path: &str) -> TaskResult<()> {
    validate_repository_relative_path("rules", relative_path)?;
    let path = repository_root.join(relative_path);
    let contents = read_file(&path)?;
    if contents.trim().is_empty() {
        return Err(format!("required file is empty: {relative_path}"));
    }
    Ok(())
}

fn read_toml(path: &Path) -> TaskResult<Value> {
    let source = read_file(path)?;
    toml::from_str::<Value>(&source)
        .map_err(|error| format!("failed to parse {}: {error}", path.display()))
}

fn read_file(path: &Path) -> TaskResult<String> {
    fs::read_to_string(path).map_err(|error| format!("failed to read {}: {error}", path.display()))
}

fn run_fmt(repository_root: &Path) -> TaskResult<()> {
    run_command(
        repository_root,
        "cargo",
        &[
            "fmt",
            "--manifest-path",
            "native/Cargo.toml",
            "--all",
            "--",
            "--check",
        ],
    )?;
    println!("fmt: PASS");
    Ok(())
}

fn run_check(repository_root: &Path) -> TaskResult<()> {
    let python = backend_python_executable(repository_root)?;
    let environment = [("PYO3_PYTHON", python.to_string_lossy().into_owned())];
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "check",
            "--manifest-path",
            "native/Cargo.toml",
            "--workspace",
            "--all-targets",
        ],
        &environment,
    )?;
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "clippy",
            "--manifest-path",
            "native/Cargo.toml",
            "--workspace",
            "--all-targets",
            "--",
            "-D",
            "warnings",
        ],
        &environment,
    )?;
    println!("check: PASS");
    Ok(())
}

fn run_tests(repository_root: &Path) -> TaskResult<()> {
    let python = backend_python_executable(repository_root)?;
    let environment = [("PYO3_PYTHON", python.to_string_lossy().into_owned())];
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "test",
            "--manifest-path",
            "native/Cargo.toml",
            "--workspace",
            "--all-targets",
        ],
        &environment,
    )?;
    run_command(
        repository_root,
        "cargo",
        &[
            "test",
            "--manifest-path",
            "native/Cargo.toml",
            "--locked",
            "-p",
            MODEL_BUFFER_PACKAGE,
            "--doc",
        ],
    )?;
    run_command(
        repository_root,
        "cargo",
        &[
            "test",
            "--manifest-path",
            "native/Cargo.toml",
            "--locked",
            "-p",
            "fastembed",
            "--lib",
            "owned_initializer_",
        ],
    )?;
    run_document_analysis_ffi_parity(repository_root, &python)?;
    println!("test: PASS");
    Ok(())
}

fn run_python_ci(repository_root: &Path) -> TaskResult<()> {
    let python = backend_python_executable(repository_root)?;
    let artifact_paths = NativeArtifactPaths::resolve(repository_root)?;
    let library = build_debug_python_extension(repository_root, &python, &artifact_paths)?;
    let environment = [(
        "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
        library.to_string_lossy().into_owned(),
    )];
    run_command_with_environment(
        repository_root,
        "make",
        &["-C", "backend", "ci"],
        &environment,
    )?;
    println!("python-ci: PASS");
    Ok(())
}

fn run_gil_policy_probe(repository_root: &Path) -> TaskResult<()> {
    let python = env::var("ALEXANDRIA_FREE_THREADED_PYTHON").map_err(|error| {
        format!(
            "gil-policy: set ALEXANDRIA_FREE_THREADED_PYTHON to an already-installed CPython 3.14t interpreter: {error}"
        )
    })?;
    let python_path = Path::new(&python);
    if !python_path.is_absolute() || !python_path.is_file() {
        return Err(format!(
            "gil-policy: interpreter path must be absolute and already installed: {}",
            python_path.display()
        ));
    }
    run_command(
        repository_root,
        &python,
        &["-I", "native/tests/pyo3_gil_policy_probe.py"],
    )?;
    println!("gil-policy: PASS");
    Ok(())
}

fn run_document_analysis_ffi_parity(repository_root: &Path, python: &Path) -> TaskResult<()> {
    require_ffi_parity_artifacts(repository_root)?;
    let artifact_paths = NativeArtifactPaths::resolve(repository_root)?;
    let expected_library = native_python_library_path(&artifact_paths.target_directory, "debug");
    run_native_import_mode_contract(repository_root, python, &expected_library, "linked")?;
    let library = build_debug_python_extension(repository_root, python, &artifact_paths)?;
    run_native_import_mode_contract(repository_root, python, &library, "extension")?;
    run_ffi_parity_scripts(repository_root, &library)
}

fn run_native_import_mode_contract(
    repository_root: &Path,
    python: &Path,
    library: &Path,
    mode: &str,
) -> TaskResult<()> {
    run_command(
        repository_root,
        &python.to_string_lossy(),
        &[
            "native/tests/native_import_mode_contract.py",
            &library.to_string_lossy(),
            "--mode",
            mode,
        ],
    )
}

fn cargo_target_directory(repository_root: &Path) -> TaskResult<PathBuf> {
    let output = Command::new("cargo")
        .args([
            "metadata",
            "--locked",
            "--no-deps",
            "--format-version",
            "1",
            "--manifest-path",
            "native/Cargo.toml",
        ])
        .current_dir(repository_root)
        .output()
        .map_err(|error| format!("failed to inspect native Cargo metadata: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "native Cargo metadata failed with status {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let metadata: CargoMetadata = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("failed to parse native Cargo metadata: {error}"))?;
    if !metadata.target_directory.is_absolute() {
        return Err(format!(
            "native Cargo metadata returned a non-absolute target directory: {}",
            metadata.target_directory.display()
        ));
    }
    Ok(metadata.target_directory)
}

fn resolve_fastembed_cache_directory(
    repository_root: &Path,
    target_directory: &Path,
    configured: Option<&std::ffi::OsStr>,
) -> TaskResult<PathBuf> {
    if !repository_root.is_absolute() {
        return Err(format!(
            "repository root must be absolute when resolving FastEmbed cache: {}",
            repository_root.display()
        ));
    }
    if !target_directory.is_absolute() {
        return Err(format!(
            "Cargo target directory must be absolute when resolving FastEmbed cache: {}",
            target_directory.display()
        ));
    }

    let cache_directory = match configured {
        Some(value) if value.is_empty() => {
            return Err("ALEXANDRIA_FASTEMBED_PARITY_CACHE must not be empty".to_owned());
        }
        Some(value) => {
            let path = PathBuf::from(value);
            if path.is_absolute() {
                path
            } else {
                repository_root.join("backend").join(path)
            }
        }
        None => target_directory.join("fastembed-parity-cache"),
    };
    if !cache_directory.is_absolute() {
        return Err(format!(
            "resolved FastEmbed cache directory must be absolute: {}",
            cache_directory.display()
        ));
    }
    normalize_absolute_path(&cache_directory).map_err(|error| {
        format!(
            "failed to normalize FastEmbed cache directory {}: {error}",
            cache_directory.display()
        )
    })
}

fn normalize_absolute_path(path: &Path) -> TaskResult<PathBuf> {
    if !path.is_absolute() {
        return Err(format!("path is not absolute: {}", path.display()));
    }
    let mut lexical_path = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::Prefix(prefix) => lexical_path.push(prefix.as_os_str()),
            std::path::Component::RootDir => lexical_path.push(component.as_os_str()),
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                let _ = lexical_path.pop();
            }
            std::path::Component::Normal(part) => lexical_path.push(part),
        }
    }

    let mut existing_prefix = lexical_path.as_path();
    loop {
        match fs::metadata(existing_prefix) {
            Ok(_) => break,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                existing_prefix = existing_prefix.parent().ok_or_else(|| {
                    format!("path has no existing ancestor: {}", lexical_path.display())
                })?;
            }
            Err(error) => {
                return Err(format!(
                    "failed to inspect existing path component {}: {error}",
                    existing_prefix.display()
                ));
            }
        }
    }
    let canonical_prefix = fs::canonicalize(existing_prefix).map_err(|error| {
        format!(
            "failed to resolve existing path component {}: {error}",
            existing_prefix.display()
        )
    })?;
    let suffix = lexical_path
        .strip_prefix(existing_prefix)
        .map_err(|error| {
            format!(
                "failed to resolve path suffix for {}: {error}",
                lexical_path.display()
            )
        })?;
    Ok(canonical_prefix.join(suffix))
}

fn native_python_library_path(target_directory: &Path, profile: &str) -> PathBuf {
    target_directory.join(profile).join(format!(
        "{}heterarchy_alexandria_native{}",
        env::consts::DLL_PREFIX,
        env::consts::DLL_SUFFIX,
    ))
}

fn require_ffi_parity_artifacts(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/tests/native_import_mode_contract.py",
        "native/corpora/document_analysis/v1/cases.json",
        "native/tests/document_analysis_ffi_parity.py",
        "native/corpora/chunking/v1/cases.json",
        "native/tests/markdown_chunking_ffi_parity.py",
        "native/corpora/link_extraction/v1/cases.json",
        "native/tests/reference_extraction_ffi_parity.py",
        "native/corpora/fingerprint/v1/cases.json",
        "native/tests/hash_fingerprint_ffi_parity.py",
        "native/corpora/graph_compute/v1/cases.json",
        "native/tests/graph_compute_ffi_parity.py",
        "native/tests/graph_candidate_selection_ffi_parity.py",
        "native/tests/graph_diagnostics_ffi_parity.py",
        "native/corpora/bulk_embedding/v1/cases.json",
        "native/corpora/bulk_embedding/v1/python_fastembed_numerical_baseline.json",
        "native/tests/bulk_embedding_ffi_parity.py",
        "native/corpora/retrieval_kernel/v1/cases.json",
        "native/tests/retrieval_kernel_ffi_parity.py",
        "native/corpora/reconciliation_candidates/v1/cases.json",
        "native/tests/reconciliation_candidates_ffi_parity.py",
        "native/golden/context_reindex_manifest.v1.json",
        "native/tests/context_reindex_manifest_ffi_parity.py",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn build_debug_python_extension(
    repository_root: &Path,
    python: &Path,
    artifact_paths: &NativeArtifactPaths,
) -> TaskResult<PathBuf> {
    let build_environment = [
        ("PYO3_PYTHON", python.to_string_lossy().into_owned()),
        ("PYO3_BUILD_EXTENSION_MODULE", "1".to_owned()),
    ];
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "build",
            "--manifest-path",
            "native/Cargo.toml",
            "-p",
            "heterarchy-alexandria-py",
        ],
        &build_environment,
    )?;
    let library = native_python_library_path(&artifact_paths.target_directory, "debug");
    if !library.is_file() {
        return Err(format!(
            "native Python extension artifact is missing: {}",
            library.display()
        ));
    }
    Ok(library)
}

fn run_ffi_parity_scripts(repository_root: &Path, library: &Path) -> TaskResult<()> {
    let parity_environment = [(
        "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
        library.to_string_lossy().into_owned(),
    )];
    for script in [
        "../native/tests/document_analysis_ffi_parity.py",
        "../native/tests/markdown_chunking_ffi_parity.py",
        "../native/tests/reference_extraction_ffi_parity.py",
        "../native/tests/hash_fingerprint_ffi_parity.py",
        "../native/tests/graph_compute_ffi_parity.py",
        "../native/tests/graph_candidate_selection_ffi_parity.py",
        "../native/tests/graph_diagnostics_ffi_parity.py",
        "../native/tests/bulk_embedding_ffi_parity.py",
        "../native/tests/retrieval_kernel_ffi_parity.py",
        "../native/tests/reconciliation_candidates_ffi_parity.py",
        "../native/tests/context_reindex_manifest_ffi_parity.py",
    ] {
        run_command_in_directory_with_environment(
            &repository_root.join("backend"),
            "uv",
            &["run", "--no-editable", "python", script],
            &parity_environment,
        )?;
    }
    Ok(())
}

fn backend_python_executable(repository_root: &Path) -> TaskResult<PathBuf> {
    for relative_path in [
        "backend/.venv/bin/python3",
        "backend/.venv/bin/python",
        "backend/.venv/Scripts/python.exe",
    ] {
        let candidate = repository_root.join(relative_path);
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err(
        "backend Python environment is missing; run `cd backend && uv sync` before Rust cross-language gates"
            .to_owned(),
    )
}

fn run_ci(repository_root: &Path) -> TaskResult<()> {
    verify_rules(repository_root)?;
    run_fmt(repository_root)?;
    run_check(repository_root)?;
    run_tests(repository_root)?;
    println!("ci: PASS");
    Ok(())
}

struct BulkEmbeddingPerfPaths {
    core_report: PathBuf,
    combined_report: PathBuf,
}

struct RetrievalKernelPerfPaths {
    core: PathBuf,
    combined: PathBuf,
    compact: PathBuf,
}

struct ReconciliationCandidatePerfPaths {
    core_report: PathBuf,
    combined_report: PathBuf,
}

fn run_perf(repository_root: &Path) -> TaskResult<()> {
    let artifact_paths = NativeArtifactPaths::resolve(repository_root)?;
    require_deterministic_compute_perf_artifacts(repository_root)?;
    require_bulk_embedding_perf_artifacts(repository_root)?;
    require_retrieval_kernel_perf_artifacts(repository_root)?;
    require_reconciliation_candidate_perf_artifacts(repository_root)?;
    let bulk_paths = bulk_embedding_perf_paths(repository_root)?;
    let retrieval_paths = retrieval_kernel_perf_paths(repository_root)?;
    let reconciliation_paths = reconciliation_candidate_perf_paths(repository_root)?;
    let deterministic_report = deterministic_compute_perf_report_path(repository_root)?;
    run_bulk_embedding_core_perf(repository_root, &bulk_paths.core_report)?;
    run_retrieval_kernel_core_perf(repository_root, &retrieval_paths.core)?;
    run_reconciliation_candidate_core_perf(repository_root, &reconciliation_paths.core_report)?;
    let library = build_release_python_extension(repository_root, &artifact_paths)?;
    run_deterministic_compute_ffi_perf(repository_root, &library, &deterministic_report)?;
    run_bulk_embedding_ffi_perf(
        repository_root,
        &library,
        &bulk_paths,
        &artifact_paths.fastembed_cache_directory,
    )?;
    run_retrieval_kernel_ffi_perf(repository_root, &library, &retrieval_paths)?;
    run_retrieval_kernel_compact_perf(repository_root, &library, &retrieval_paths)?;
    run_reconciliation_candidate_ffi_perf(repository_root, &library, &reconciliation_paths)?;
    require_non_empty_file(
        repository_root,
        "native/perf/evidence/deterministic_compute_v1.json",
    )?;
    require_bulk_embedding_perf_reports(repository_root)?;
    require_retrieval_kernel_perf_reports(repository_root)?;
    require_reconciliation_candidate_perf_reports(repository_root)?;
    run_retrieval_benchmark_tool_gate(repository_root)?;
    let live_retrieval_measured =
        run_live_retrieval_perf_if_requested(repository_root, &artifact_paths.target_directory)?;
    let fastembed_inference_measured =
        fastembed_perf_cache_is_populated(&artifact_paths.fastembed_cache_directory)?;

    let rust_features = rust_authoritative_features(repository_root)?;
    if rust_features.is_empty() {
        if fastembed_inference_measured && live_retrieval_measured {
            println!(
                "perf: PASS — cached native FastEmbed inference, retrieval-kernel JSON/compact real FFI, reconciliation-candidate core/real FFI, and live HYBRID exact-title/semantic endpoint recall measured"
            );
        } else if fastembed_inference_measured {
            println!(
                "perf: PARTIAL_PASS — bulk embedding including cached native FastEmbed inference, retrieval-kernel JSON/compact real FFI, and reconciliation-candidate core/real FFI measured; live endpoint recall NOT RUN"
            );
        } else {
            println!(
                "perf: PARTIAL_PASS — bulk embedding preparation/finalization, retrieval-kernel JSON/compact real FFI, and reconciliation-candidate core/real FFI measured; native FastEmbed inference and live endpoint recall NOT RUN"
            );
        }
        return Ok(());
    }
    validate_rust_authority_perf_evidence(
        &rust_features,
        fastembed_inference_measured,
        live_retrieval_measured,
    )?;
    println!(
        "perf: PASS — Rust-authoritative feature performance evidence is complete for {rust_features:?}"
    );
    Ok(())
}

fn validate_rust_authority_perf_evidence(
    rust_features: &[String],
    fastembed_inference_measured: bool,
    live_retrieval_measured: bool,
) -> TaskResult<()> {
    for feature in rust_features {
        match feature.as_str() {
            "document_analysis"
            | "chunking"
            | "link_extraction"
            | "fingerprint"
            | "graph_compute"
            | "reconciliation_candidates" => {}
            "embedding_compute" if fastembed_inference_measured => {}
            "embedding_compute" => {
                return Err(
                    "perf: BLOCKED — embedding_compute Rust authority requires cached real FastEmbed inference evidence"
                        .to_owned(),
                );
            }
            "retrieval_kernel" if live_retrieval_measured => {}
            "retrieval_kernel" => {
                return Err(
                    "perf: BLOCKED — retrieval_kernel Rust authority requires live HYBRID exact-title and semantic endpoint evidence; rerun with HETERARCHY_ALEXANDRIA_PERF_LIVE=1 while the backend is healthy"
                        .to_owned(),
                );
            }
            unsupported => {
                return Err(format!(
                    "perf: BLOCKED — no completed feature-specific authority performance gate exists yet for {unsupported}"
                ));
            }
        }
    }
    Ok(())
}

fn run_live_retrieval_perf_if_requested(
    repository_root: &Path,
    target_directory: &Path,
) -> TaskResult<bool> {
    if !live_perf_requested()? {
        return Ok(false);
    }
    let backend_root = repository_root.join("backend");
    let scenarios = [
        (
            "benchmarks/golden_cases.exact_title.v1.json",
            target_directory.join("live-retrieval-exact-title.json"),
        ),
        (
            "benchmarks/golden_cases.semantic.v1.json",
            target_directory.join("live-retrieval-semantic.json"),
        ),
    ];
    for (corpus, output) in scenarios {
        run_command_in_directory_with_environment(
            &backend_root,
            "uv",
            &[
                "run",
                "--no-editable",
                "python",
                "-m",
                "benchmarks.context_rag_api_benchmark",
                "--golden-cases",
                corpus,
                "--strategy",
                "HYBRID",
                "--limit",
                "3",
                "--warmups",
                "1",
                "--repetitions",
                "1",
                "--timeout-seconds",
                "10",
                "--output",
                &output.to_string_lossy(),
            ],
            &[],
        )?;
        validate_live_retrieval_report(&output)?;
    }
    Ok(true)
}

fn live_perf_requested() -> TaskResult<bool> {
    match env::var("HETERARCHY_ALEXANDRIA_PERF_LIVE") {
        Err(env::VarError::NotPresent) => Ok(false),
        Err(error) => Err(format!("failed to read live perf environment: {error}")),
        Ok(value) if value == "1" || value.eq_ignore_ascii_case("true") => Ok(true),
        Ok(value) if value == "0" || value.eq_ignore_ascii_case("false") => Ok(false),
        Ok(value) => Err(format!(
            "HETERARCHY_ALEXANDRIA_PERF_LIVE must be 0/1/false/true, found {value}"
        )),
    }
}

fn validate_live_retrieval_report(path: &Path) -> TaskResult<()> {
    let source = read_file(path)?;
    let report: serde_json::Value = serde_json::from_str(&source).map_err(|error| {
        format!(
            "failed to parse live retrieval report {}: {error}",
            path.display()
        )
    })?;
    let cases = report
        .get("cases")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| format!("live retrieval report {} has no cases", path.display()))?;
    let retrieval_kernel_authority = report
        .get("environment")
        .and_then(|environment| environment.get("retrieval_kernel_authority"))
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| {
            format!(
                "live retrieval report {} has no retrieval-kernel runtime provenance",
                path.display()
            )
        })?;
    if retrieval_kernel_authority != "rust" {
        return Err(format!(
            "live retrieval report {} was not served by the Rust retrieval kernel: authority={retrieval_kernel_authority}",
            path.display()
        ));
    }
    if cases.is_empty() {
        return Err(format!(
            "live retrieval report {} has no cases",
            path.display()
        ));
    }
    for case in cases {
        let failed_samples = case
            .get("failed_samples")
            .and_then(serde_json::Value::as_u64)
            .ok_or_else(|| {
                format!(
                    "live retrieval report {} has invalid failed_samples",
                    path.display()
                )
            })?;
        let ranking_stable = case
            .get("ranking_stable")
            .and_then(serde_json::Value::as_bool)
            .ok_or_else(|| {
                format!(
                    "live retrieval report {} has invalid ranking_stable",
                    path.display()
                )
            })?;
        if failed_samples != 0 || !ranking_stable {
            return Err(format!(
                "live retrieval report {} contains failed or unstable samples",
                path.display()
            ));
        }
    }
    println!(
        "live-retrieval-perf: PASS corpus={} cases={}",
        path.display(),
        cases.len()
    );
    Ok(())
}

fn fastembed_perf_cache_is_populated(cache_directory: &Path) -> TaskResult<bool> {
    let metadata = match fs::metadata(cache_directory) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => {
            return Err(format!(
                "failed to inspect FastEmbed performance cache {}: {error}",
                cache_directory.display()
            ));
        }
    };
    if !metadata.is_dir() {
        return Ok(false);
    }
    directory_contains_file(cache_directory).map_err(|error| {
        format!(
            "failed to inspect FastEmbed performance cache {}: {error}",
            cache_directory.display()
        )
    })
}

fn directory_contains_file(directory: &Path) -> std::io::Result<bool> {
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        let entry_type = entry.file_type()?;
        if entry_type.is_file() {
            return Ok(true);
        }
        if entry_type.is_dir() && directory_contains_file(&path)? {
            return Ok(true);
        }
        if entry_type.is_symlink() {
            match fs::metadata(&path) {
                Ok(metadata) if metadata.is_file() => return Ok(true),
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
        }
    }
    Ok(false)
}

fn require_deterministic_compute_perf_artifacts(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/tests/deterministic_compute_perf.py",
        "native/feature_authority.toml",
        "native/perf/README.md",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn require_bulk_embedding_perf_artifacts(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/crates/heterarchy-alexandria-core/examples/bulk_embedding_perf.rs",
        "native/tests/bulk_embedding_perf.py",
        "native/corpora/bulk_embedding/v1/cases.json",
        "native/perf/README.md",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn require_reconciliation_candidate_perf_artifacts(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/crates/heterarchy-alexandria-core/examples/reconciliation_candidates_perf.rs",
        "native/tests/reconciliation_candidates_perf.py",
        "native/corpora/reconciliation_candidates/v1/cases.json",
        "native/perf/README.md",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn require_retrieval_kernel_perf_artifacts(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/crates/heterarchy-alexandria-core/examples/retrieval_kernel_perf.rs",
        "native/tests/retrieval_kernel_perf.py",
        "native/tests/retrieval_kernel_compact_perf.py",
        "native/corpora/retrieval_kernel/v1/cases.json",
        "backend/benchmarks/golden_cases.exact_title.v1.json",
        "backend/benchmarks/golden_cases.semantic.v1.json",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn deterministic_compute_perf_report_path(repository_root: &Path) -> TaskResult<PathBuf> {
    let evidence_directory = repository_root.join("native/perf/evidence");
    fs::create_dir_all(&evidence_directory).map_err(|error| {
        format!(
            "failed to create performance evidence directory {}: {error}",
            evidence_directory.display()
        )
    })?;
    Ok(evidence_directory.join("deterministic_compute_v1.json"))
}

fn bulk_embedding_perf_paths(repository_root: &Path) -> TaskResult<BulkEmbeddingPerfPaths> {
    let evidence_directory = repository_root.join("native/perf/evidence");
    fs::create_dir_all(&evidence_directory).map_err(|error| {
        format!(
            "failed to create performance evidence directory {}: {error}",
            evidence_directory.display()
        )
    })?;
    Ok(BulkEmbeddingPerfPaths {
        core_report: evidence_directory.join("bulk_embedding_core_candidate_2026-08-22.json"),
        combined_report: evidence_directory.join("bulk_embedding_candidate_2026-08-22.json"),
    })
}

fn retrieval_kernel_perf_paths(repository_root: &Path) -> TaskResult<RetrievalKernelPerfPaths> {
    let evidence_directory = repository_root.join("native/perf/evidence");
    fs::create_dir_all(&evidence_directory).map_err(|error| {
        format!(
            "failed to create performance evidence directory {}: {error}",
            evidence_directory.display()
        )
    })?;
    Ok(RetrievalKernelPerfPaths {
        core: evidence_directory.join("retrieval_kernel_core_candidate_2026-08-22.json"),
        combined: evidence_directory.join("retrieval_kernel_candidate_2026-08-22.json"),
        compact: evidence_directory.join("retrieval_kernel_compact_v1.json"),
    })
}

fn reconciliation_candidate_perf_paths(
    repository_root: &Path,
) -> TaskResult<ReconciliationCandidatePerfPaths> {
    let evidence_directory = repository_root.join("native/perf/evidence");
    fs::create_dir_all(&evidence_directory).map_err(|error| {
        format!(
            "failed to create performance evidence directory {}: {error}",
            evidence_directory.display()
        )
    })?;
    Ok(ReconciliationCandidatePerfPaths {
        core_report: evidence_directory.join("reconciliation_candidates_core_v1.json"),
        combined_report: evidence_directory.join("reconciliation_candidates_combined_v1.json"),
    })
}

fn run_bulk_embedding_core_perf(repository_root: &Path, report: &Path) -> TaskResult<()> {
    let environment = [(
        "HETERARCHY_ALEXANDRIA_CORE_PERF_REPORT",
        report.to_string_lossy().into_owned(),
    )];
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "run",
            "--release",
            "--manifest-path",
            "native/Cargo.toml",
            "-p",
            "heterarchy-alexandria-core",
            "--example",
            "bulk_embedding_perf",
        ],
        &environment,
    )
}

fn run_retrieval_kernel_core_perf(repository_root: &Path, report: &Path) -> TaskResult<()> {
    let environment = [(
        "HETERARCHY_ALEXANDRIA_RETRIEVAL_CORE_PERF_REPORT",
        report.to_string_lossy().into_owned(),
    )];
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "run",
            "--release",
            "--manifest-path",
            "native/Cargo.toml",
            "-p",
            "heterarchy-alexandria-core",
            "--example",
            "retrieval_kernel_perf",
        ],
        &environment,
    )
}

fn run_reconciliation_candidate_core_perf(repository_root: &Path, report: &Path) -> TaskResult<()> {
    let environment = [(
        "HETERARCHY_ALEXANDRIA_RECONCILIATION_CORE_PERF_REPORT",
        report.to_string_lossy().into_owned(),
    )];
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "run",
            "--release",
            "--manifest-path",
            "native/Cargo.toml",
            "-p",
            "heterarchy-alexandria-core",
            "--example",
            "reconciliation_candidates_perf",
        ],
        &environment,
    )
}

fn build_release_python_extension(
    repository_root: &Path,
    artifact_paths: &NativeArtifactPaths,
) -> TaskResult<PathBuf> {
    let python = backend_python_executable(repository_root)?;
    let environment = [
        ("PYO3_PYTHON", python.to_string_lossy().into_owned()),
        ("PYO3_BUILD_EXTENSION_MODULE", "1".to_owned()),
    ];
    run_command_with_environment(
        repository_root,
        "cargo",
        &[
            "build",
            "--release",
            "--manifest-path",
            "native/Cargo.toml",
            "-p",
            "heterarchy-alexandria-py",
        ],
        &environment,
    )?;
    let library = native_python_library_path(&artifact_paths.target_directory, "release");
    if !library.is_file() {
        return Err(format!(
            "release native Python extension artifact is missing: {}",
            library.display()
        ));
    }
    Ok(library)
}

fn run_bulk_embedding_ffi_perf(
    repository_root: &Path,
    library: &Path,
    paths: &BulkEmbeddingPerfPaths,
    fastembed_cache_directory: &Path,
) -> TaskResult<()> {
    let environment = [
        (
            "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
            library.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_CORE_PERF_REPORT",
            paths.core_report.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_BULK_EMBEDDING_PERF_REPORT",
            paths.combined_report.to_string_lossy().into_owned(),
        ),
        (
            "ALEXANDRIA_FASTEMBED_PARITY_CACHE",
            fastembed_cache_directory.to_string_lossy().into_owned(),
        ),
    ];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "uv",
        &[
            "run",
            "--no-editable",
            "python",
            "../native/tests/bulk_embedding_perf.py",
        ],
        &environment,
    )
}

fn run_deterministic_compute_ffi_perf(
    repository_root: &Path,
    library: &Path,
    report: &Path,
) -> TaskResult<()> {
    let environment = [
        (
            "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
            library.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_DETERMINISTIC_PERF_REPORT",
            report.to_string_lossy().into_owned(),
        ),
    ];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "uv",
        &[
            "run",
            "--no-editable",
            "python",
            "../native/tests/deterministic_compute_perf.py",
        ],
        &environment,
    )
}

fn run_retrieval_kernel_ffi_perf(
    repository_root: &Path,
    library: &Path,
    paths: &RetrievalKernelPerfPaths,
) -> TaskResult<()> {
    let environment = [
        (
            "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
            library.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_RETRIEVAL_CORE_PERF_REPORT",
            paths.core.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_RETRIEVAL_PERF_REPORT",
            paths.combined.to_string_lossy().into_owned(),
        ),
    ];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "uv",
        &[
            "run",
            "--no-editable",
            "python",
            "../native/tests/retrieval_kernel_perf.py",
        ],
        &environment,
    )
}

fn run_retrieval_kernel_compact_perf(
    repository_root: &Path,
    library: &Path,
    paths: &RetrievalKernelPerfPaths,
) -> TaskResult<()> {
    let environment = [
        (
            "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
            library.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_RETRIEVAL_COMPACT_PERF_REPORT",
            paths.compact.to_string_lossy().into_owned(),
        ),
    ];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "uv",
        &[
            "run",
            "--no-editable",
            "python",
            "../native/tests/retrieval_kernel_compact_perf.py",
        ],
        &environment,
    )
}

fn run_reconciliation_candidate_ffi_perf(
    repository_root: &Path,
    library: &Path,
    paths: &ReconciliationCandidatePerfPaths,
) -> TaskResult<()> {
    let environment = [
        (
            "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
            library.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_RECONCILIATION_CORE_PERF_REPORT",
            paths.core_report.to_string_lossy().into_owned(),
        ),
        (
            "HETERARCHY_ALEXANDRIA_RECONCILIATION_PERF_REPORT",
            paths.combined_report.to_string_lossy().into_owned(),
        ),
    ];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "uv",
        &[
            "run",
            "--no-editable",
            "python",
            "../native/tests/reconciliation_candidates_perf.py",
        ],
        &environment,
    )
}

fn require_reconciliation_candidate_perf_reports(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/perf/evidence/reconciliation_candidates_core_v1.json",
        "native/perf/evidence/reconciliation_candidates_combined_v1.json",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn require_bulk_embedding_perf_reports(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/perf/evidence/bulk_embedding_core_candidate_2026-08-22.json",
        "native/perf/evidence/bulk_embedding_candidate_2026-08-22.json",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn require_retrieval_kernel_perf_reports(repository_root: &Path) -> TaskResult<()> {
    for relative_path in [
        "native/perf/evidence/retrieval_kernel_core_candidate_2026-08-22.json",
        "native/perf/evidence/retrieval_kernel_candidate_2026-08-22.json",
    ] {
        require_non_empty_file(repository_root, relative_path)?;
    }
    Ok(())
}

fn run_retrieval_benchmark_tool_gate(repository_root: &Path) -> TaskResult<()> {
    run_command(
        repository_root,
        "make",
        &["-C", "backend", "benchmark_check"],
    )
}

fn rust_authoritative_features(repository_root: &Path) -> TaskResult<Vec<String>> {
    let registry_path = repository_root.join("native/feature_authority.toml");
    let registry_source = read_file(&registry_path)?;
    let registry: AuthorityRegistry = toml::from_str(&registry_source)
        .map_err(|error| format!("failed to parse {}: {error}", registry_path.display()))?;
    Ok(registry
        .features
        .into_iter()
        .filter(|(_, feature)| feature.authority == Authority::Rust)
        .map(|(name, _)| name)
        .collect())
}

fn run_extended(repository_root: &Path) -> TaskResult<()> {
    let artifact_paths = NativeArtifactPaths::resolve(repository_root)?;
    run_command(
        repository_root,
        "cargo",
        &[
            "test",
            "--manifest-path",
            "native/Cargo.toml",
            "--workspace",
            "--doc",
        ],
    )?;
    let library = build_release_python_extension(repository_root, &artifact_paths)?;
    run_python_native_adapter_parity(repository_root, &library)?;
    run_fastembed_numerical_parity_if_cached(
        repository_root,
        &library,
        &artifact_paths.fastembed_cache_directory,
    )?;
    run_native_retrieval_quality(repository_root, &library)?;
    println!(
        "extended: doc tests, Python/native adapter parity, cached FastEmbed parity against frozen pre-cutover numerical evidence when available, and real PostgreSQL native-retrieval quality PASS; optional Miri/fuzz/Loom stages are not configured"
    );
    Ok(())
}

fn run_python_native_adapter_parity(repository_root: &Path, library: &Path) -> TaskResult<()> {
    let environment = [(
        "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
        library.to_string_lossy().into_owned(),
    )];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "uv",
        &[
            "run",
            "--no-editable",
            "python",
            "../native/tests/python_native_adapter_parity.py",
        ],
        &environment,
    )
}

fn run_fastembed_numerical_parity_if_cached(
    repository_root: &Path,
    library: &Path,
    cache_directory: &Path,
) -> TaskResult<()> {
    let cache_is_populated = fastembed_perf_cache_is_populated(cache_directory)?;
    if !cache_is_populated {
        println!(
            "fastembed-frozen-numerical-parity: NOT_RUN — local model cache is absent; extended remains offline-safe"
        );
        return Ok(());
    }
    let environment = [
        (
            "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
            library.to_string_lossy().into_owned(),
        ),
        (
            "ALEXANDRIA_FASTEMBED_PARITY_CACHE",
            cache_directory.to_string_lossy().into_owned(),
        ),
    ];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "uv",
        &[
            "run",
            "--no-editable",
            "python",
            "../native/tests/fastembed_numerical_parity.py",
        ],
        &environment,
    )
}

fn run_native_retrieval_quality(repository_root: &Path, library: &Path) -> TaskResult<()> {
    let environment = [(
        "HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY",
        library.to_string_lossy().into_owned(),
    )];
    run_command_in_directory_with_environment(
        &repository_root.join("backend"),
        "./scripts/run-postgres-tests.sh",
        &[
            "-q",
            "tests/memory/test_context_repository.py::test_native_hybrid_fusion_matches_python_authority_on_real_postgresql_retrieval",
        ],
        &environment,
    )
}

fn run_doctor(repository_root: &Path) -> TaskResult<()> {
    for (program, arguments) in [
        ("rustc", &["--version"][..]),
        ("cargo", &["--version"][..]),
        ("rustfmt", &["--version"][..]),
        ("cargo", &["clippy", "-V"][..]),
    ] {
        run_command(repository_root, program, arguments)?;
    }
    println!("doctor: PASS — mandatory Rust toolchain commands are available");
    Ok(())
}

fn run_deps(repository_root: &Path) -> TaskResult<()> {
    let deny_config = repository_root.join("native/deny.toml");
    if !deny_config.is_file() {
        return Err(
            "deps: BLOCKED — native/deny.toml is not configured; dependency audit is NOT RUN"
                .to_owned(),
        );
    }
    run_command(
        repository_root,
        "cargo",
        &["deny", "check", "--manifest-path", "native/Cargo.toml"],
    )?;
    println!("deps: PASS");
    Ok(())
}

fn run_command(repository_root: &Path, program: &str, arguments: &[&str]) -> TaskResult<()> {
    run_command_in_directory_with_environment(repository_root, program, arguments, &[])
}

fn run_command_with_environment(
    repository_root: &Path,
    program: &str,
    arguments: &[&str],
    environment: &[(&str, String)],
) -> TaskResult<()> {
    run_command_in_directory_with_environment(repository_root, program, arguments, environment)
}

fn run_command_in_directory_with_environment(
    current_directory: &Path,
    program: &str,
    arguments: &[&str],
    environment: &[(&str, String)],
) -> TaskResult<()> {
    let mut command = Command::new(program);
    command.args(arguments).current_dir(current_directory);
    for (key, value) in environment {
        command.env(key, value);
    }
    let status = command
        .status()
        .map_err(|error| format!("failed to execute {program}: {error}"))?;
    if !status.success() {
        return Err(format!(
            "command failed with status {status}: {program} {}",
            arguments.join(" ")
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unsafe_exception_rejects_other_packages_and_weakened_lints() -> TaskResult<()> {
        let root = repository_root()?;
        let manifest = read_toml(
            &root
                .join("native")
                .join(MODEL_BUFFER_MEMBER)
                .join("Cargo.toml"),
        )?;
        verify_workspace_inheritance(&manifest, MODEL_BUFFER_MEMBER)?;
        assert!(
            verify_workspace_inheritance(&manifest, "crates/heterarchy-alexandria-core").is_err()
        );
        for (key, value) in [
            ("unsafe_code", "warn"),
            ("unsafe_op_in_unsafe_fn", "allow"),
            ("warnings", "warn"),
            ("unused_must_use", "allow"),
        ] {
            let mut changed = manifest.clone();
            changed["lints"]["rust"][key] = Value::String(value.to_owned());
            assert!(verify_model_buffer_manifest(&changed).is_err(), "{key}");
        }
        let mut changed = manifest.clone();
        changed["package"]["name"] = Value::String("unapproved-boundary".to_owned());
        assert!(verify_model_buffer_manifest(&changed).is_err());
        let mut changed = manifest;
        changed["dependencies"]["libc"]["workspace"] = Value::Boolean(false);
        assert!(verify_model_buffer_manifest(&changed).is_err());
        Ok(())
    }

    #[test]
    fn retired_import_markers_respect_module_identifier_boundaries() {
        for source in [
            "from fastembed import TextEmbedding",
            "from fastembed.text.embedding import TextEmbedding",
            "from fastembed",
        ] {
            assert!(contains_python_module_marker(source, "from fastembed"));
        }
        for source in [
            "from fastembed_runtime import bootstrap_cached_fastembed_runtime",
            "from fastembed2 import helper",
            "from fastembed도구 import helper",
        ] {
            assert!(!contains_python_module_marker(source, "from fastembed"));
        }
        assert!(contains_python_module_marker(
            "from app.retired_module.child import value",
            "app.retired_module"
        ));
        assert!(!contains_python_module_marker(
            "from app.retired_module_native import value",
            "app.retired_module"
        ));
    }

    #[test]
    fn native_python_library_paths_follow_cargo_metadata_target_directory() -> TaskResult<()> {
        let repository_root = repository_root()?;
        let target_directory = cargo_target_directory(&repository_root)?;
        let filename = format!(
            "{}heterarchy_alexandria_native{}",
            env::consts::DLL_PREFIX,
            env::consts::DLL_SUFFIX,
        );

        for profile in ["debug", "release"] {
            let expected = target_directory.join(profile).join(&filename);
            assert_eq!(
                native_python_library_path(&target_directory, profile),
                expected,
                "{profile} native extension path must follow Cargo metadata"
            );
        }
        Ok(())
    }

    #[test]
    fn cache_resolution_uses_backend_child_directory_and_explicit_override() -> TaskResult<()> {
        let fixture = TestDirectory::new()?;
        let repository_root = fixture.path().join("repository");
        let backend_directory = repository_root.join("backend");
        let target_directory = fixture.path().join("cargo-target");
        let override_directory = backend_directory.join("cache");
        fs::create_dir_all(&override_directory)
            .map_err(|error| format!("failed to create cache fixture: {error}"))?;
        fs::create_dir_all(&repository_root)
            .map_err(|error| format!("failed to create repository fixture: {error}"))?;

        let default = resolve_fastembed_cache_directory(&repository_root, &target_directory, None)?;
        assert_eq!(default, target_directory.join("fastembed-parity-cache"));

        let relative_override = std::ffi::OsStr::new("models/../cache");
        let resolved_override = resolve_fastembed_cache_directory(
            &repository_root,
            &target_directory,
            Some(relative_override),
        )?;
        assert_eq!(
            resolved_override,
            fs::canonicalize(&override_directory)
                .map_err(|error| format!("failed to canonicalize cache fixture: {error}"))?
        );
        assert!(
            resolve_fastembed_cache_directory(
                &repository_root,
                &target_directory,
                Some(std::ffi::OsStr::new("")),
            )
            .is_err()
        );
        Ok(())
    }

    #[test]
    fn cache_population_requires_a_file_even_in_nested_directories() -> TaskResult<()> {
        let fixture = TestDirectory::new()?;
        let cache_directory = fixture.path().join("cache");
        let empty_subdirectory = cache_directory.join("empty-subdirectory");
        fs::create_dir_all(&empty_subdirectory)
            .map_err(|error| format!("failed to create empty cache fixture: {error}"))?;
        assert!(!fastembed_perf_cache_is_populated(&cache_directory)?);

        fs::write(empty_subdirectory.join("model.bin"), b"model")
            .map_err(|error| format!("failed to create cached model fixture: {error}"))?;
        assert!(fastembed_perf_cache_is_populated(&cache_directory)?);
        Ok(())
    }

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn new() -> TaskResult<Self> {
            let nonce = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|error| format!("system clock is before the Unix epoch: {error}"))?
                .as_nanos();
            let path = env::temp_dir().join(format!(
                "alexandria-xtask-fixture-{}-{nonce}",
                process::id()
            ));
            fs::create_dir_all(&path)
                .map_err(|error| format!("failed to create test directory: {error}"))?;
            Ok(Self(path))
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
}
