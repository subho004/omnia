// Native UI handoff remains available for compatibility.
const handoff = document.querySelector('#handoff');
if (handoff) handoff.submit();

// Invalidate open workspace tabs after login, switch, or logout. Server checks
// remain authoritative; the channel contains no identity, token, or private data.
if (document.querySelector('.actions')) {
  try {
    const channel = new BroadcastChannel('claw-auth');
    channel.postMessage({ type: 'session-changed', marker: document.querySelector('meta[name="workspace-session"]').content });
    channel.close();
  } catch { /* Session fences and visibility checks remain active. */ }
}
