// Prevent an additional console window on Windows in a later platform build.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Some(exit_code) = doc_evidence_desktop_lib::run_sidecar_launcher_if_requested() {
        std::process::exit(exit_code);
    }
    doc_evidence_desktop_lib::run();
}
