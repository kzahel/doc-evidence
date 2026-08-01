use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    env,
    fmt::Write as _,
    fs,
    io::{BufRead, BufReader, Read, Write},
    net::{Ipv4Addr, SocketAddrV4, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex, RwLock,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};

const DESKTOP_PROTOCOL: &str = "doc-evidence.desktop.v1";
const DESKTOP_ORIGIN: &str = "tauri://localhost";
const APPLICATION_VERSION: &str = env!("CARGO_PKG_VERSION");
const MAX_READY_BYTES: usize = 64 * 1024;
const MAX_CONTROL_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_BUNDLE_MANIFEST_BYTES: u64 = 8 * 1024 * 1024;
const MAX_PACK_MANIFEST_BYTES: u64 = 1024 * 1024;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const CONTROL_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopRuntimeInfo {
    base_url: String,
    bearer_token: String,
    protocol_version: String,
    application_version: String,
    api_version: u8,
    platform: String,
    architecture: String,
    baseline_pack: Option<DesktopPackIdentity>,
    host_capabilities: HostCapabilities,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
struct DesktopPackIdentity {
    pack_id: String,
    version: String,
    manifest_sha256: String,
}

#[derive(Debug, Deserialize)]
struct BundleManifestIdentity {
    schema_version: String,
    product: String,
    version: String,
    identifier: String,
    platform: String,
    architecture: String,
    python_version: String,
    extractor_packs: Vec<DesktopPackIdentity>,
}

#[derive(Debug, Deserialize)]
struct PackManifestIdentity {
    schema_version: String,
    pack_id: String,
    version: String,
    platform: String,
    architecture: String,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct HostCapabilities {
    create_managed_library: bool,
    register_existing_library: bool,
    add_collection: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReadyRecord {
    schema_version: String,
    protocol_version: String,
    application_version: String,
    api_version: u8,
    host: String,
    port: u16,
    platform: String,
    architecture: String,
    application_home_source: String,
    baseline_pack: Option<DesktopPackIdentity>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlHandshake {
    schema_version: String,
    compatible: bool,
    protocol_version: String,
    capabilities: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlLibraryResult {
    schema_version: u8,
    outcome: String,
    library_id: String,
    name: String,
    store_mode: String,
    status: String,
    status_detail: Option<String>,
    collection_count: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ControlCollectionResult {
    schema_version: u8,
    preflight_kind: String,
    changed: bool,
    confirmation_required: bool,
    affected_collection_ids: Vec<String>,
    library: ControlLibraryResult,
}

#[derive(Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeLibraryOperation {
    outcome: String,
    library_id: Option<String>,
    status: Option<String>,
}

#[derive(Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeCollectionOperation {
    outcome: String,
    library_id: Option<String>,
    changed: bool,
    preflight_kind: Option<String>,
}

#[derive(Clone)]
enum RuntimeStatus {
    Initializing,
    Ready(Box<DesktopRuntimeInfo>),
    Failed(String),
}

#[derive(Clone)]
struct HostControl {
    port: u16,
    token: String,
}

struct DesktopProcess {
    child: Arc<Mutex<Child>>,
    expected_shutdown: Arc<AtomicBool>,
}

struct DesktopState {
    status: Arc<RwLock<RuntimeStatus>>,
    process: Mutex<Option<DesktopProcess>>,
    control: Option<HostControl>,
}

impl DesktopState {
    fn shutdown(&self) {
        if let Ok(mut process) = self.process.lock() {
            if let Some(process) = process.take() {
                process.shutdown();
            }
        }
    }

    fn host_control(&self) -> Result<HostControl, String> {
        self.control
            .clone()
            .ok_or_else(|| "The desktop engine is unavailable.".to_string())
    }
}

impl Drop for DesktopState {
    fn drop(&mut self) {
        self.shutdown();
    }
}

impl DesktopProcess {
    fn shutdown(self) {
        self.expected_shutdown.store(true, Ordering::SeqCst);
        let deadline = Instant::now() + Duration::from_secs(20);
        if let Ok(mut child) = self.child.lock() {
            drop(child.stdin.take());
        }
        while Instant::now() < deadline {
            if let Ok(mut child) = self.child.lock() {
                match child.try_wait() {
                    Ok(Some(_)) => return,
                    Ok(None) => {}
                    Err(_) => break,
                }
            }
            thread::sleep(Duration::from_millis(50));
        }
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes)
        .map_err(|error| format!("could not create desktop credentials: {error}"))?;
    let mut encoded = String::with_capacity(64);
    for byte in bytes {
        write!(&mut encoded, "{byte:02x}")
            .map_err(|_| "could not encode desktop credentials".to_string())?;
    }
    Ok(encoded)
}

fn resource_dir_for_executable(executable: &Path) -> Option<PathBuf> {
    let macos = executable.parent()?;
    if macos.file_name()?.to_string_lossy() != "MacOS" {
        return None;
    }
    let contents = macos.parent()?;
    if contents.file_name()?.to_string_lossy() != "Contents" {
        return None;
    }
    Some(contents.join("Resources"))
}

fn runtime_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    if let Some(override_path) = env::var_os("DOC_EVIDENCE_DESKTOP_RUNTIME_ROOT") {
        return Ok(PathBuf::from(override_path));
    }
    match app.path().resource_dir() {
        Ok(directory) => Ok(directory.join("desktop-runtime")),
        Err(error) => env::current_exe()
            .ok()
            .and_then(|path| resource_dir_for_executable(&path))
            .map(|path| path.join("desktop-runtime"))
            .ok_or_else(|| format!("could not locate desktop resources: {error}")),
    }
}

fn application_home(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .data_dir()
        .map(|path| path.join("doc-evidence"))
        .map_err(|error| format!("could not locate application data: {error}"))
}

fn read_bounded(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, String> {
    let metadata = fs::metadata(path).map_err(|_| format!("{label} is missing"))?;
    if !metadata.is_file() || metadata.len() > maximum {
        return Err(format!("{label} is invalid"));
    }
    fs::read(path).map_err(|_| format!("{label} is unreadable"))
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn packaged_baseline_identity(runtime_root: &Path) -> Result<DesktopPackIdentity, String> {
    let bundle_bytes = read_bounded(
        &runtime_root.join("bundle-manifest.json"),
        MAX_BUNDLE_MANIFEST_BYTES,
        "desktop bundle manifest",
    )?;
    let bundle: BundleManifestIdentity = serde_json::from_slice(&bundle_bytes)
        .map_err(|_| "desktop bundle manifest is invalid".to_string())?;
    if bundle.schema_version != "doc-evidence.desktop-bundle-manifest.v1"
        || bundle.product != "Doc Evidence"
        || bundle.version != APPLICATION_VERSION
        || bundle.identifier != "io.github.kzahel.doc-evidence"
        || bundle.platform != "macos"
        || bundle.architecture != "arm64"
        || bundle.python_version != "3.12.12"
        || bundle.extractor_packs.len() != 1
    {
        return Err("desktop bundle manifest is incompatible".to_string());
    }
    let expected = bundle.extractor_packs[0].clone();
    if expected.pack_id != "baseline-macos-arm64"
        || expected.version.is_empty()
        || !is_lower_hex_64(&expected.manifest_sha256)
    {
        return Err("desktop bundle extractor-pack identity is incompatible".to_string());
    }

    let pack_bytes = read_bounded(
        &runtime_root.join("baseline-pack/pack-manifest.json"),
        MAX_PACK_MANIFEST_BYTES,
        "baseline extractor-pack manifest",
    )?;
    if sha256_hex(&pack_bytes) != expected.manifest_sha256 {
        return Err("baseline extractor-pack manifest identity changed".to_string());
    }
    let pack: PackManifestIdentity = serde_json::from_slice(&pack_bytes)
        .map_err(|_| "baseline extractor-pack manifest is invalid".to_string())?;
    if pack.schema_version != "doc-evidence.extractor-pack-manifest.v1"
        || pack.pack_id != expected.pack_id
        || pack.version != expected.version
        || pack.platform != "macos"
        || pack.architecture != "arm64"
    {
        return Err("baseline extractor-pack manifest is incompatible".to_string());
    }
    Ok(expected)
}

fn read_ready(reader: impl Read) -> Result<ReadyRecord, String> {
    let mut bytes = Vec::new();
    BufReader::new(reader)
        .take((MAX_READY_BYTES + 1) as u64)
        .read_until(b'\n', &mut bytes)
        .map_err(|error| format!("could not read desktop startup record: {error}"))?;
    if bytes.len() > MAX_READY_BYTES || !bytes.ends_with(b"\n") {
        return Err("desktop startup record exceeded its bound".to_string());
    }
    serde_json::from_slice(&bytes).map_err(|_| "desktop startup record is invalid".to_string())
}

fn validate_ready(ready: &ReadyRecord, expected_pack: &DesktopPackIdentity) -> Result<(), String> {
    if ready.schema_version != "doc-evidence.desktop-ready.v1"
        || ready.protocol_version != DESKTOP_PROTOCOL
        || ready.application_version != APPLICATION_VERSION
        || ready.api_version != 1
        || ready.host != "127.0.0.1"
        || ready.port == 0
        || ready.platform != "macos"
        || ready.architecture != "arm64"
        || !matches!(
            ready.application_home_source.as_str(),
            "environment" | "desktop_host" | "platform_default"
        )
    {
        return Err("desktop startup record is incompatible".to_string());
    }
    if ready.baseline_pack.as_ref() != Some(expected_pack) {
        return Err("desktop extractor-pack record is incompatible".to_string());
    }
    Ok(())
}

fn is_lower_hex_64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn parse_http_response<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, String> {
    let separator = bytes
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "desktop control response is malformed".to_string())?;
    let headers = std::str::from_utf8(&bytes[..separator])
        .map_err(|_| "desktop control response headers are invalid".to_string())?;
    let status = headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u16>().ok())
        .ok_or_else(|| "desktop control response status is invalid".to_string())?;
    if status != 200 {
        return Err(format!(
            "desktop control operation was rejected with HTTP {status}"
        ));
    }
    serde_json::from_slice(&bytes[separator + 4..])
        .map_err(|_| "desktop control response body is invalid".to_string())
}

fn control_request<T: DeserializeOwned>(
    control: &HostControl,
    method: &str,
    path: &str,
    body: Option<&serde_json::Value>,
) -> Result<T, String> {
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, control.port);
    let mut stream = TcpStream::connect_timeout(&address.into(), CONTROL_TIMEOUT)
        .map_err(|_| "could not connect to desktop control".to_string())?;
    stream
        .set_read_timeout(Some(CONTROL_TIMEOUT))
        .map_err(|_| "could not bound desktop control reads".to_string())?;
    stream
        .set_write_timeout(Some(CONTROL_TIMEOUT))
        .map_err(|_| "could not bound desktop control writes".to_string())?;
    let encoded = body.map(serde_json::Value::to_string).unwrap_or_default();
    let mut request = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAuthorization: Bearer {}\r\nConnection: close\r\n",
        control.port, control.token
    );
    if body.is_some() {
        write!(
            request,
            "Content-Type: application/json\r\nContent-Length: {}\r\n",
            encoded.len()
        )
        .map_err(|_| "could not create desktop control request".to_string())?;
    }
    request.push_str("\r\n");
    request.push_str(&encoded);
    stream
        .write_all(request.as_bytes())
        .map_err(|_| "could not send desktop control request".to_string())?;
    let mut response = Vec::new();
    stream
        .take((MAX_CONTROL_RESPONSE_BYTES + 1) as u64)
        .read_to_end(&mut response)
        .map_err(|_| "could not read desktop control response".to_string())?;
    if response.len() > MAX_CONTROL_RESPONSE_BYTES {
        return Err("desktop control response exceeded its bound".to_string());
    }
    parse_http_response(&response)
}

fn validate_control(handshake: &ControlHandshake) -> Result<HostCapabilities, String> {
    if handshake.schema_version != "doc-evidence.desktop-control.v1"
        || !handshake.compatible
        || handshake.protocol_version != DESKTOP_PROTOCOL
    {
        return Err("desktop host-control handshake is incompatible".to_string());
    }
    let allowed = [
        "create_managed_library",
        "register_existing_library",
        "add_collection",
    ];
    if handshake.capabilities.len() != allowed.len()
        || handshake
            .capabilities
            .iter()
            .any(|value| !allowed.contains(&value.as_str()))
        || allowed.iter().any(|value| {
            handshake
                .capabilities
                .iter()
                .filter(|item| *item == value)
                .count()
                != 1
        })
    {
        return Err("desktop host-control capabilities are incompatible".to_string());
    }
    let capabilities = HostCapabilities {
        create_managed_library: handshake
            .capabilities
            .iter()
            .any(|value| value == "create_managed_library"),
        register_existing_library: handshake
            .capabilities
            .iter()
            .any(|value| value == "register_existing_library"),
        add_collection: handshake
            .capabilities
            .iter()
            .any(|value| value == "add_collection"),
    };
    if !capabilities.create_managed_library
        || !capabilities.register_existing_library
        || !capabilities.add_collection
    {
        return Err("desktop host-control capabilities are incomplete".to_string());
    }
    Ok(capabilities)
}

fn wait_for_control(control: &HostControl) -> Result<HostCapabilities, String> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Ok(handshake) = control_request::<ControlHandshake>(
            control,
            "GET",
            "/desktop-control/v1/handshake",
            None,
        ) {
            return validate_control(&handshake);
        }
        if Instant::now() >= deadline {
            return Err("desktop host-control handshake timed out".to_string());
        }
        thread::sleep(Duration::from_millis(50));
    }
}

fn start_sidecar(
    app: &tauri::AppHandle,
    status: Arc<RwLock<RuntimeStatus>>,
) -> Result<(DesktopProcess, HostControl, DesktopRuntimeInfo), String> {
    let runtime_root = runtime_root(app)?;
    let expected_pack = packaged_baseline_identity(&runtime_root)?;
    let python = runtime_root.join("python/bin/python3");
    if !python.is_file() {
        return Err("packaged Python runtime is missing".to_string());
    }
    let app_home = application_home(app)?;
    let pack = runtime_root.join("baseline-pack");
    let pack_bin = pack.join("bin");
    let python_bin = runtime_root.join("python/bin");
    let executable_path = env::join_paths([
        pack_bin,
        python_bin,
        PathBuf::from("/usr/bin"),
        PathBuf::from("/bin"),
    ])
    .map_err(|_| "could not construct the desktop executable path".to_string())?;
    let writable_cache = app_home.join("cache");
    fs::create_dir_all(&writable_cache)
        .map_err(|_| "could not create the desktop cache directory".to_string())?;
    let runtime_token = token()?;
    let control_token = token()?;
    if runtime_token == control_token {
        return Err("desktop credentials are not independent".to_string());
    }

    let mut command = Command::new(&python);
    command
        .env_clear()
        .current_dir(&runtime_root)
        .arg("-I")
        .arg("-B")
        .arg("-m")
        .arg("doc_evidence.desktop_sidecar")
        .arg("--expected-protocol")
        .arg(DESKTOP_PROTOCOL)
        .arg("--desktop-origin")
        .arg(DESKTOP_ORIGIN)
        .env("DOC_EVIDENCE_DESKTOP_RUNTIME_TOKEN", &runtime_token)
        .env("DOC_EVIDENCE_DESKTOP_HOST_CONTROL_TOKEN", &control_token)
        .env("DOC_EVIDENCE_DESKTOP_APP_HOME", &app_home)
        .env("DOC_EVIDENCE_BASELINE_PACK", &pack)
        .env("PATH", executable_path)
        .env("TESSDATA_PREFIX", pack.join("tessdata"))
        .env("FONTCONFIG_FILE", pack.join("etc/fonts/fonts.conf"))
        .env("FONTCONFIG_PATH", pack.join("etc/fonts"))
        .env("XDG_CACHE_HOME", writable_cache)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("PYTHONNOUSERSITE", "1")
        .env("PYTHONUTF8", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(value) = env::var_os("DOC_EVIDENCE_HOME") {
        command.env("DOC_EVIDENCE_HOME", value);
    }
    for name in ["LANG", "LC_ALL", "TMPDIR"] {
        if let Some(value) = env::var_os(name) {
            command.env(name, value);
        }
    }
    let mut child = command
        .spawn()
        .map_err(|_| "could not launch packaged Python runtime".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "desktop startup output is unavailable".to_string())?;
    if let Some(stderr) = child.stderr.take() {
        thread::spawn(move || {
            let mut sink = std::io::sink();
            let _ = std::io::copy(&mut BufReader::new(stderr), &mut sink);
        });
    }
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let _ = sender.send(read_ready(stdout));
    });
    let ready = match receiver.recv_timeout(STARTUP_TIMEOUT) {
        Ok(result) => result,
        Err(_) => Err("desktop startup record timed out".to_string()),
    };
    let ready = match ready {
        Ok(value) => value,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };
    if let Err(error) = validate_ready(&ready, &expected_pack) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    let control = HostControl {
        port: ready.port,
        token: control_token,
    };
    let capabilities = match wait_for_control(&control) {
        Ok(value) => value,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };
    let info = DesktopRuntimeInfo {
        base_url: format!("http://127.0.0.1:{}", ready.port),
        bearer_token: runtime_token,
        protocol_version: DESKTOP_PROTOCOL.to_string(),
        application_version: APPLICATION_VERSION.to_string(),
        api_version: 1,
        platform: "macos".to_string(),
        architecture: "arm64".to_string(),
        baseline_pack: ready.baseline_pack,
        host_capabilities: capabilities,
    };
    let child = Arc::new(Mutex::new(child));
    let expected_shutdown = Arc::new(AtomicBool::new(false));
    let monitor_child = Arc::clone(&child);
    let monitor_expected = Arc::clone(&expected_shutdown);
    let monitor_status = Arc::clone(&status);
    let monitor_app = app.clone();
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(200));
        let exited = monitor_child
            .lock()
            .ok()
            .and_then(|mut child| child.try_wait().ok().flatten());
        if exited.is_some() {
            if !monitor_expected.load(Ordering::SeqCst) {
                let message = "The local document engine stopped unexpectedly.".to_string();
                if let Ok(mut current) = monitor_status.write() {
                    *current = RuntimeStatus::Failed(message.clone());
                }
                let _ = monitor_app.emit("desktop-runtime-failed", message);
            }
            break;
        }
    });
    Ok((
        DesktopProcess {
            child,
            expected_shutdown,
        },
        control,
        info,
    ))
}

fn current_runtime_info(status: &Arc<RwLock<RuntimeStatus>>) -> Result<DesktopRuntimeInfo, String> {
    match status
        .read()
        .map_err(|_| "The desktop engine state is unavailable.".to_string())?
        .clone()
    {
        RuntimeStatus::Ready(info) => Ok(*info),
        RuntimeStatus::Failed(error) => Err(error),
        RuntimeStatus::Initializing => Err("The desktop engine is still starting.".to_string()),
    }
}

fn local_dialog_path(value: tauri_plugin_dialog::FilePath) -> Result<PathBuf, String> {
    value
        .into_path()
        .map_err(|_| "The selected item is not a local path.".to_string())
}

fn validate_library_result(result: &ControlLibraryResult) -> Result<(), String> {
    if result.schema_version != 1
        || result.library_id.is_empty()
        || result.name.is_empty()
        || !matches!(result.store_mode.as_str(), "managed" | "adopted")
        || !matches!(
            result.status.as_str(),
            "ready" | "unavailable" | "integrity_error"
        )
        || !matches!(
            result.outcome.as_str(),
            "created" | "registered" | "already_registered" | "updated"
        )
    {
        return Err("desktop library result is incompatible".to_string());
    }
    if result.collection_count > 100 {
        return Err("desktop library result exceeds its collection bound".to_string());
    }
    let _ = &result.status_detail;
    Ok(())
}

fn completed_library(result: ControlLibraryResult) -> Result<NativeLibraryOperation, String> {
    validate_library_result(&result)?;
    Ok(NativeLibraryOperation {
        outcome: "completed".to_string(),
        library_id: Some(result.library_id),
        status: Some(result.status),
    })
}

#[tauri::command]
fn desktop_runtime(state: tauri::State<'_, DesktopState>) -> Result<DesktopRuntimeInfo, String> {
    current_runtime_info(&state.status)
}

#[tauri::command(async)]
fn desktop_create_managed_library(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopState>,
) -> Result<NativeLibraryOperation, String> {
    let selected = app
        .dialog()
        .file()
        .set_title("Choose the read-only source folder for a new library")
        .blocking_pick_folder();
    let Some(selected) = selected else {
        return Ok(NativeLibraryOperation {
            outcome: "cancelled".to_string(),
            library_id: None,
            status: None,
        });
    };
    let path = local_dialog_path(selected)?;
    let name = path
        .file_name()
        .map(|value| value.to_string_lossy().trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "Document Library".to_string());
    let control = state.host_control()?;
    let result: ControlLibraryResult = control_request(
        &control,
        "POST",
        "/desktop-control/v1/libraries/create-managed",
        Some(&json!({"source_path": path, "name": name})),
    )?;
    completed_library(result)
}

#[tauri::command(async)]
fn desktop_register_existing_library(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopState>,
) -> Result<NativeLibraryOperation, String> {
    let selected = app
        .dialog()
        .file()
        .set_title("Choose an existing Doc Evidence configuration")
        .add_filter("Doc Evidence YAML", &["yaml", "yml"])
        .blocking_pick_file();
    let Some(selected) = selected else {
        return Ok(NativeLibraryOperation {
            outcome: "cancelled".to_string(),
            library_id: None,
            status: None,
        });
    };
    let path = local_dialog_path(selected)?;
    let control = state.host_control()?;
    let result: ControlLibraryResult = control_request(
        &control,
        "POST",
        "/desktop-control/v1/libraries/register-existing",
        Some(&json!({"config_path": path, "name": null})),
    )?;
    completed_library(result)
}

fn add_collection_request(
    control: &HostControl,
    library_id: &str,
    path: &Path,
    confirm_parent_replacement: bool,
) -> Result<ControlCollectionResult, String> {
    control_request(
        control,
        "POST",
        "/desktop-control/v1/libraries/add-collection",
        Some(&json!({
            "library_id": library_id,
            "source_path": path,
            "confirm_parent_replacement": confirm_parent_replacement,
        })),
    )
}

#[tauri::command(async)]
fn desktop_add_collection(
    app: tauri::AppHandle,
    state: tauri::State<'_, DesktopState>,
    library_id: String,
) -> Result<NativeCollectionOperation, String> {
    if library_id.is_empty() || library_id.len() > 200 {
        return Err("desktop library identity is invalid".to_string());
    }
    let selected = app
        .dialog()
        .file()
        .set_title("Choose a read-only collection folder")
        .blocking_pick_folder();
    let Some(selected) = selected else {
        return Ok(NativeCollectionOperation {
            outcome: "cancelled".to_string(),
            library_id: None,
            changed: false,
            preflight_kind: None,
        });
    };
    let path = local_dialog_path(selected)?;
    let control = state.host_control()?;
    let mut result = add_collection_request(&control, &library_id, &path, false)?;
    if result.confirmation_required {
        let replace = app
            .dialog()
            .message(
                "This folder contains existing collection roots. Replace those child roots with the selected parent while preserving cached evidence?",
            )
            .title("Expand collection scope")
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Replace child roots".to_string(),
                "Cancel".to_string(),
            ))
            .blocking_show();
        if !replace {
            return Ok(NativeCollectionOperation {
                outcome: "cancelled".to_string(),
                library_id: None,
                changed: false,
                preflight_kind: Some(result.preflight_kind),
            });
        }
        result = add_collection_request(&control, &library_id, &path, true)?;
    }
    if result.schema_version != 1
        || result.library.library_id != library_id
        || result.confirmation_required
    {
        return Err("desktop collection result is incompatible".to_string());
    }
    validate_library_result(&result.library)?;
    let _ = &result.affected_collection_ids;
    Ok(NativeCollectionOperation {
        outcome: "completed".to_string(),
        library_id: Some(result.library.library_id),
        changed: result.changed,
        preflight_kind: Some(result.preflight_kind),
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let application = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let status = Arc::new(RwLock::new(RuntimeStatus::Initializing));
            let result = start_sidecar(app.handle(), Arc::clone(&status));
            let (process, control) = match result {
                Ok((process, control, info)) => {
                    if let Ok(mut current) = status.write() {
                        *current = RuntimeStatus::Ready(Box::new(info));
                    }
                    (Some(process), Some(control))
                }
                Err(error) => {
                    if let Ok(mut current) = status.write() {
                        *current = RuntimeStatus::Failed(error);
                    }
                    (None, None)
                }
            };
            app.manage(DesktopState {
                status,
                process: Mutex::new(process),
                control,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_runtime,
            desktop_create_managed_library,
            desktop_register_existing_library,
            desktop_add_collection,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Doc Evidence");

    application.run(|handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            handle.state::<DesktopState>().shutdown();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn pack() -> DesktopPackIdentity {
        DesktopPackIdentity {
            pack_id: "baseline-macos-arm64".to_string(),
            version: "2026.08.1".to_string(),
            manifest_sha256: "a".repeat(64),
        }
    }

    fn ready() -> String {
        let pack = serde_json::to_string(&pack()).unwrap();
        format!(
            "{{\"schema_version\":\"doc-evidence.desktop-ready.v1\",\"protocol_version\":\"{DESKTOP_PROTOCOL}\",\"application_version\":\"{APPLICATION_VERSION}\",\"api_version\":1,\"host\":\"127.0.0.1\",\"port\":43111,\"platform\":\"macos\",\"architecture\":\"arm64\",\"application_home_source\":\"desktop_host\",\"baseline_pack\":{pack}}}\n"
        )
    }

    #[test]
    fn tokens_are_256_bit_lower_hex() {
        let first = token().unwrap();
        let second = token().unwrap();
        assert!(is_lower_hex_64(&first));
        assert!(is_lower_hex_64(&second));
        assert_ne!(first, second);
    }

    #[test]
    fn ready_record_is_strict_bounded_and_compatible() {
        let parsed = read_ready(Cursor::new(ready())).unwrap();
        validate_ready(&parsed, &pack()).unwrap();
        assert!(read_ready(Cursor::new("x".repeat(MAX_READY_BYTES + 1))).is_err());
        let extra = ready().replace("}}\n", "},\"token\":\"secret\"}\n");
        assert!(read_ready(Cursor::new(extra)).is_err());
        let other = DesktopPackIdentity {
            version: "other".to_string(),
            ..pack()
        };
        assert!(validate_ready(&parsed, &other).is_err());
    }

    #[test]
    fn packaged_pack_identity_binds_bundle_and_pack_manifests() {
        let root = env::temp_dir().join(format!("doc-evidence-rust-pack-{}", token().unwrap()));
        fs::create_dir_all(root.join("baseline-pack")).unwrap();
        let pack_manifest = json!({
            "schema_version": "doc-evidence.extractor-pack-manifest.v1",
            "pack_id": "baseline-macos-arm64",
            "version": "2026.08.1",
            "platform": "macos",
            "architecture": "arm64"
        });
        let pack_bytes = serde_json::to_vec(&pack_manifest).unwrap();
        fs::write(root.join("baseline-pack/pack-manifest.json"), &pack_bytes).unwrap();
        let identity = DesktopPackIdentity {
            manifest_sha256: sha256_hex(&pack_bytes),
            ..pack()
        };
        let bundle_manifest = json!({
            "schema_version": "doc-evidence.desktop-bundle-manifest.v1",
            "product": "Doc Evidence",
            "version": APPLICATION_VERSION,
            "identifier": "io.github.kzahel.doc-evidence",
            "platform": "macos",
            "architecture": "arm64",
            "python_version": "3.12.12",
            "extractor_packs": [identity]
        });
        fs::write(
            root.join("bundle-manifest.json"),
            serde_json::to_vec(&bundle_manifest).unwrap(),
        )
        .unwrap();
        let loaded = packaged_baseline_identity(&root).unwrap();
        assert_eq!(loaded.pack_id, "baseline-macos-arm64");
        fs::write(root.join("baseline-pack/pack-manifest.json"), b"{}").unwrap();
        assert!(packaged_baseline_identity(&root).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn http_response_parser_rejects_errors_and_extra_control_fields() {
        let body = br#"{"schema_version":"doc-evidence.desktop-control.v1","compatible":true,"protocol_version":"doc-evidence.desktop.v1","capabilities":["create_managed_library","register_existing_library","add_collection"]}"#;
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            std::str::from_utf8(body).unwrap()
        );
        let handshake: ControlHandshake = parse_http_response(response.as_bytes()).unwrap();
        assert!(validate_control(&handshake).is_ok());
        assert!(
            parse_http_response::<ControlHandshake>(b"HTTP/1.1 403 Forbidden\r\n\r\n{}").is_err()
        );
    }

    #[test]
    fn native_results_never_serialize_paths_or_control_credentials() {
        let value = NativeLibraryOperation {
            outcome: "completed".to_string(),
            library_id: Some("library-id".to_string()),
            status: Some("ready".to_string()),
        };
        let encoded = serde_json::to_string(&value).unwrap();
        assert_eq!(
            encoded,
            r#"{"outcome":"completed","libraryId":"library-id","status":"ready"}"#
        );
    }

    #[test]
    fn packaged_resource_fallback_is_bundle_relative() {
        let executable =
            Path::new("/Applications/Doc Evidence.app/Contents/MacOS/doc-evidence-desktop");
        assert_eq!(
            resource_dir_for_executable(executable).unwrap(),
            Path::new("/Applications/Doc Evidence.app/Contents/Resources")
        );
        assert!(resource_dir_for_executable(Path::new("/tmp/tool")).is_none());
    }
}
