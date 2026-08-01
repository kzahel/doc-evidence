// Prevent an additional console window on Windows in a later platform build.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    doc_evidence_desktop_lib::run();
}
