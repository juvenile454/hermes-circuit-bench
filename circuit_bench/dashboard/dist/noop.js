// Circuit Bench ships no web dashboard tab: the bench is the Desktop half (desktop/plugin.js).
// The manifest still needs a loadable entry for its hidden tab, and an entry that never calls register()
// shows "NO_REGISTER" on that route. So this registers an empty component.
window.__HERMES_PLUGINS__?.register?.('circuit-bench', function CircuitBenchHidden() { return null })
