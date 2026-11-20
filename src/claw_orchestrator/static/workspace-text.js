// Presentation only. Keep original input, stored instructions and exact review
// proposals intact. For streaming, call this on the full accumulated text.
export function displayText(value) {
  return String(value ?? '')
    .replace(/open[\s_-]*claw/gi, 'Morrow')
    .replace(/(?:nemo[\s_-]*claw|open[\s_-]*shell)/gi, 'workspace runtime');
}
