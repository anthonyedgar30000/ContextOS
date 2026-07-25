use std::path::PathBuf;
use std::process::Command;

fn repo_root() -> Result<PathBuf, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|gui_dir| gui_dir.parent())
        .map(PathBuf::from)
        .ok_or_else(|| "failed to resolve ContextOS repository root".to_string())
}

#[tauri::command]
fn classify_changes() -> Result<String, String> {
    let root = repo_root()?;
    let output = Command::new("python3")
        .arg("contextos.py")
        .arg("classify-changes")
        .arg("--contract")
        .arg(".contextos/contracts/CTX-0001-contextos-readme-update.yaml")
        .arg("--policy")
        .arg(".contextos/policies/normalized-policy.example.yaml")
        .arg("--format")
        .arg("json")
        .current_dir(&root)
        .output()
        .map_err(|error| format!("failed to execute contextos.py: {error}"))?;

    if !output.status.success() {
        return Err(format!(
            "contextos.py classify-changes failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }

    String::from_utf8(output.stdout)
        .map_err(|error| format!("classifier output was not valid UTF-8: {error}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![classify_changes])
        .run(tauri::generate_context!())
        .expect("error while running ContextOS desktop application");
}
