/// Return Python-compatible cosine similarity for two vector slices.
///
/// Dimension mismatch, empty inputs, or either zero norm return zero. Finite caller inputs
/// otherwise produce the raw dot-product cosine without clamping.
#[must_use]
pub fn cosine_similarity(left: &[f64], right: &[f64]) -> f64 {
    if left.len() != right.len() || left.is_empty() {
        return 0.0;
    }
    let dot = left
        .iter()
        .zip(right)
        .map(|(left_value, right_value)| left_value * right_value)
        .sum::<f64>();
    let left_norm = left.iter().map(|value| value * value).sum::<f64>().sqrt();
    let right_norm = right.iter().map(|value| value * value).sum::<f64>().sqrt();
    let denominator = left_norm * right_norm;
    if denominator == 0.0 {
        0.0
    } else {
        dot / denominator
    }
}
