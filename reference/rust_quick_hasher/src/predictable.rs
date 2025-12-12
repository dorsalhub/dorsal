use crate::config::{PREDICTABLE_COUNT, PREDICTABLE_NUMBERS, PREDICTABLE_SCALE};

/// A predictable number generator that cycles through a pre-loaded sequence.
pub struct Predictable {
    index: usize,
}

impl Predictable {
    /// Initializes the generator with a seed (offset).
    pub fn new(seed: usize) -> Self {
        Self { index: seed }
    }

    /// Returns the integer at the current index and moves the index along.
    fn next_predictable_int(&mut self) -> u64 {
        let val = PREDICTABLE_NUMBERS[self.index];
        self.index = (self.index + 1) % PREDICTABLE_COUNT;
        val
    }

    /// Returns a predictable integer N where a <= N <= b.
    /// Uses u128 for intermediate multiplication to prevent overflow.
    pub fn randint(&mut self, a: u64, b: u64) -> u64 {
        if b < a {
            panic!("'a' must be less than or equal to 'b'");
        }
        let range_size = b - a + 1;
        let predictable_int = self.next_predictable_int();

        // Perform calculation using u128 to match Python's arbitrary-precision integers
        a + ((predictable_int as u128 * range_size as u128) / PREDICTABLE_SCALE) as u64
    }
}