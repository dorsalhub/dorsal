use crate::config::{
    CHUNK_SIZE, FILE_SIZE_CHUNKS, MAX_CHUNKS, MAX_PERMITTED_FILESIZE, MIN_CHUNKS,
    MIN_PERMITTED_FILESIZE, PREDICTABLE_COUNT
};
use crate::error::{Result, QuickHasherError};
use crate::predictable::Predictable;
use sha2::{Digest, Sha256};
use std::cmp::max;
use std::cmp::min;
use std::fs::File;
use std::io::{BufReader, Read, Seek, SeekFrom};
use std::path::Path;

/// Generates a 'quick hash' for large files by sampling content chunks.
pub struct QuickHasher;

impl QuickHasher {
    pub fn new() -> Self {
        Self
    }
    
    /// The main hashing function.
    pub fn hash(&self, file_path: &Path) -> Result<String> {
        let file_size = file_path.metadata()?.len();

        if !(MIN_PERMITTED_FILESIZE..=MAX_PERMITTED_FILESIZE).contains(&file_size) {
            return Err(QuickHasherError::FileSizeOutOfRange(
                file_size,
                MIN_PERMITTED_FILESIZE,
                MAX_PERMITTED_FILESIZE,
            ));
        }

        let mut hasher = Sha256::new();
        let total_chunks_in_file = file_size / CHUNK_SIZE;
        let num_chunks_to_sample = self.get_chunk_count(file_size);

        let chunk_indices_to_read = self.random_sample_chunk_indices(
            file_size,
            num_chunks_to_sample,
            total_chunks_in_file,
        );

        if chunk_indices_to_read.is_empty() {
             // Handle case for files smaller than one chunk
            if file_size > 0 && file_size < CHUNK_SIZE {
                let mut file = File::open(file_path)?;
                let mut buffer = Vec::new();
                file.read_to_end(&mut buffer)?;
                hasher.update(&buffer);
                return Ok(hex::encode(hasher.finalize()));
            } else {
                // This case should ideally not be hit for permitted file sizes
                return Ok(hex::encode(hasher.finalize()));
            }
        }
        
        let file = File::open(file_path)?;
        let mut reader = BufReader::new(file);
        let mut buffer = vec![0; CHUNK_SIZE as usize];

        for chunk_index in chunk_indices_to_read {
            let byte_offset = chunk_index * CHUNK_SIZE;
            if byte_offset >= file_size {
                 return Err(QuickHasherError::FileInstability(format!(
                    "Calculated offset {} exceeds file size {}",
                    byte_offset, file_size
                )));
            }

            reader.seek(SeekFrom::Start(byte_offset))?;
            let bytes_read = reader.read(&mut buffer)?;
            
            if bytes_read == 0 {
                return Err(QuickHasherError::FileInstability(format!(
                    "Read empty chunk at offset {}",
                    byte_offset
                )));
            }
            hasher.update(&buffer[..bytes_read]);
        }

        Ok(hex::encode(hasher.finalize()))
    }

    /// Determines the number of chunks to sample based on file size.
    fn get_chunk_count(&self, file_size: u64) -> usize {
        if file_size >= *FILE_SIZE_CHUNKS.last().unwrap() { // Simplified upper bound check
            return MAX_CHUNKS;
        }
        if file_size <= *FILE_SIZE_CHUNKS.first().unwrap() { // Simplified lower bound check
            return MIN_CHUNKS;
        }
        
        // bisect_left equivalent using Rust's binary_search
        let idx = match FILE_SIZE_CHUNKS.binary_search(&file_size) {
            Ok(i) => i,
            Err(i) => i,
        };
        min(MAX_CHUNKS, max(MIN_CHUNKS, MIN_CHUNKS + idx))
    }
    
    /// Creates a deterministic seed from file size.
    fn make_seed(&self, file_size: u64) -> usize {
        (file_size % PREDICTABLE_COUNT as u64) as usize
    }

    /// Generates a deterministic, sorted list of chunk indices to sample.
    fn random_sample_chunk_indices(
        &self,
        file_size: u64,
        num_chunks_to_sample: usize,
        total_chunks_in_file: u64,
    ) -> Vec<u64> {
        if num_chunks_to_sample == 0 || total_chunks_in_file == 0 {
            return Vec::new();
        }
        
        let actual_num_to_sample = min(num_chunks_to_sample, total_chunks_in_file as usize);
        let seed = self.make_seed(file_size);
        
        // Reservoir Sampling (Algorithm R)
        let mut predictable = Predictable::new(seed);
        let mut reservoir: Vec<u64> = (0..actual_num_to_sample as u64).collect();

        for i in (actual_num_to_sample as u64)..total_chunks_in_file {
            let j = predictable.randint(0, i);
            if j < actual_num_to_sample as u64 {
                reservoir[j as usize] = i;
            }
        }
        
        reservoir.sort_unstable();
        reservoir
    }
}