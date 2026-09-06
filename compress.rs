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

fn main() {
    let pwd = std::env::current_dir().unwrap().to_string_lossy().to_string().replace('\\', "/");
    println!("Current dir: {pwd}");
    let binary_path = format!("{pwd}/profiles.cbor.gz");
    let mut all_profiles = Vec::new();
    all_profiles.push(("__version".to_owned(), serde_json::Value::Number(env!("GITHUB_RUN_NUMBER").parse::<u64>().unwrap().into())));
    let catalogue: serde_json::Value = serde_json::from_slice(&std::fs::read("camera_database.json").expect("Generate the camera catalogue first")).unwrap();
    all_profiles.push(("__camera_database".to_owned(), catalogue));
    walkdir::WalkDir::new(&pwd).sort_by_file_name().into_iter()
        .filter_entry(|e| e.depth() == 0 || !e.file_type().is_dir() ||
            (!e.file_name().to_string_lossy().starts_with('.') && !["lensfun", "tools", "tests"].contains(&e.file_name().to_string_lossy().as_ref())))
        .for_each(|e| {
        if let Ok(entry) = e {
            let f_name = entry.path().to_string_lossy().replace('\\', "/");
            if entry.file_name() != "camera_database.json" && (f_name.ends_with(".json") || f_name.ends_with(".gyroflow")) {
                if let Ok(data) = std::fs::read_to_string(&f_name) {
                    let parsed = serde_json::from_str::<serde_json::Value>(&data).unwrap();
                    let pos = f_name.find(&pwd).unwrap();
                    println!("Adding: {}", &f_name[pos + pwd.len() + 1..]);
                    all_profiles.push((f_name[pos + pwd.len() + 1..].to_owned(), parsed));
                }
            }
        }
    });
    if !all_profiles.is_empty() {
        use std::io::Write;
        let mut file = std::fs::File::create(&binary_path).unwrap();
        let mut data = Vec::<u8>::new();
        ciborium::into_writer(&all_profiles, &mut data).unwrap();
        let mut e = flate2::write::GzEncoder::new(&mut file, flate2::Compression::best());
        e.write_all(&data).unwrap();
    }
}
