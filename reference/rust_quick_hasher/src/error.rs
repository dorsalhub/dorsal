use thiserror::Error;

#[derive(Error, Debug)]
pub enum QuickHasherError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("File size {0} bytes is outside the permitted range ({1} - {2} bytes)")]
    FileSizeOutOfRange(u64, u64, u64),

    #[error("File may have changed during hashing: {0}")]
    FileInstability(String),
    
    #[error("Data file integrity check failed for predictable.bin")]
    DataIntegrity,
}

pub type Result<T> = std::result::Result<T, QuickHasherError>;