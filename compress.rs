#!/usr/bin/env rust-script
//!
//! ```cargo
//! [dependencies]
//! walkdir = "2.5"
//! ciborium = "0.2"
//! flate2 = "1.0"
//! serde = "1.0"
//! serde_json = "1.0"
//! ```

fn should_pack_profile(path: &std::path::Path) -> bool {
    path != std::path::Path::new("camera_database.json") &&
        !path.starts_with("catalog") &&
        matches!(path.extension().and_then(|ext| ext.to_str()), Some("json" | "gyroflow"))
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::io::Write;

    let version: u32 = std::env::var("GITHUB_RUN_NUMBER")?.parse()?;
    let mut profiles = vec![("__version".to_owned(), serde_json::json!(version))];
    for entry in walkdir::WalkDir::new(".").sort_by_file_name() {
        let entry = entry?;
        if !entry.file_type().is_file() { continue; }
        let path = entry.path().strip_prefix(".")?;
        if !should_pack_profile(path) { continue; }
        let profile = serde_json::from_slice(&std::fs::read(path)?)
            .map_err(|error| format!("{}: {error}", path.display()))?;
        profiles.push((path.to_string_lossy().replace('\\', "/"), profile));
    }
    if profiles.len() == 1 { return Err("No profiles found".into()); }
    let file = std::fs::File::create("profiles.cbor.gz")?;
    let mut gzip = flate2::write::GzEncoder::new(std::io::BufWriter::new(file), flate2::Compression::best());
    ciborium::into_writer(&profiles, &mut gzip)?;
    gzip.finish()?.flush()?;
    println!("Packed {} profiles for v{version}", profiles.len() - 1);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::should_pack_profile;
    use std::path::Path;

    #[test]
    fn excludes_catalog_registry_and_generated_camera_database() {
        assert!(!should_pack_profile(Path::new("catalog/curated_identities.json")));
        assert!(!should_pack_profile(Path::new("camera_database.json")));
        assert!(should_pack_profile(Path::new("Sony/profile.json")));
        assert!(should_pack_profile(Path::new("Sony/profile.gyroflow")));
        assert!(!should_pack_profile(Path::new("Sony/notes.md")));
    }
}
