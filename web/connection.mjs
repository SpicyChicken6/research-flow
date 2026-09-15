// Connection credential is separate from workflow state, history and portable exports.
export function readAccessToken(portable, environment = globalThis) {
  if (portable) return '';
  const fragment = new URLSearchParams(environment.location.hash.slice(1));
  const incoming = fragment.get('token');
  if (incoming) {
    // Remove the fragment immediately; do not put it into links, logs or downloads.
    try { environment.history.replaceState(null, '', environment.location.pathname + environment.location.search); } catch { /* restricted embed */ }
    try { environment.sessionStorage.setItem('research-flow-token', incoming); } catch { /* private browsing */ }
    return incoming;
  }
  try { return environment.sessionStorage.getItem('research-flow-token') || ''; } catch { return ''; }
}
