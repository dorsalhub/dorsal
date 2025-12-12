use clap::Parser;
use rust_quick_hasher::quick_hasher::QuickHasher;
use std::path::PathBuf;

#[derive(Parser)]
#[command(version, about, long_about = None)]
struct Cli {
    /// The path to the file to hash
    #[arg(required = true)]
    file_path: PathBuf,
}

fn main() {
    let cli = Cli::parse();
    
    if !cli.file_path.exists() {
        eprintln!("Error: File not found at '{}'", cli.file_path.display());
        std::process::exit(1);
    }
    
    let hasher = QuickHasher::new();
    
    match hasher.hash(&cli.file_path) {
        Ok(quick_hash) => {
            println!("QUICK Hash: {}", quick_hash);
        }
        Err(e) => {
            eprintln!("Error generating quick hash: {}", e);
            std::process::exit(1);
        }
    }
}