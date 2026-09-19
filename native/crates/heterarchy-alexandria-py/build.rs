use std::env;

fn main() {
    pyo3_build_config::add_extension_module_link_args();
    println!("cargo:rerun-if-env-changed=PYO3_BUILD_EXTENSION_MODULE");
    println!("cargo:rustc-check-cfg=cfg(alexandria_extension_module)");
    if env::var_os("PYO3_BUILD_EXTENSION_MODULE").is_some() {
        println!("cargo:rustc-cfg=alexandria_extension_module");
    }
    println!("cargo:rerun-if-env-changed=ALEXANDRIA_BUILD_REVISION");
    let revision = env::var("ALEXANDRIA_BUILD_REVISION").unwrap_or_else(|_| "unknown".into());
    let profile = env::var("PROFILE").unwrap_or_else(|_| "unknown".into());
    println!("cargo:rustc-env=HETERARCHY_ALEXANDRIA_NATIVE_GIT_REVISION={revision}");
    println!("cargo:rustc-env=HETERARCHY_ALEXANDRIA_NATIVE_BUILD_PROFILE={profile}");
}
