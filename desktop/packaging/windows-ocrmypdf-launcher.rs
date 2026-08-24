// Relocatable Windows launcher for the Python-owned OCRmyPDF module.

use std::env;
use std::process::{self, Command};

fn main() {
    let result = (|| {
        let executable = env::current_exe().map_err(|_| "could not locate OCRmyPDF launcher")?;
        let pack_bin = executable
            .parent()
            .ok_or("OCRmyPDF launcher has no parent directory")?;
        let runtime = pack_bin
            .parent()
            .and_then(|pack| pack.parent())
            .ok_or("OCRmyPDF launcher is outside the desktop runtime")?;
        let python = runtime.join("python").join("python.exe");
        if !python.is_file() {
            return Err("packaged Python runtime is missing");
        }
        let status = Command::new(python)
            .arg("-I")
            .arg("-B")
            .arg("-m")
            .arg("ocrmypdf")
            .args(env::args_os().skip(1))
            .status()
            .map_err(|_| "could not launch packaged OCRmyPDF")?;
        Ok(status.code().unwrap_or(1))
    })();
    match result {
        Ok(code) => process::exit(code),
        Err(message) => {
            eprintln!("{message}");
            process::exit(1);
        }
    }
}
