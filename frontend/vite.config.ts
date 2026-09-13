import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Phase 46 mobile fix: getUserMedia requires a secure context (HTTPS or
    // literally "localhost") — real, verified browser behavior, not a
    // guess (see PHASE_STATUS.md). Testing the real check-in scanner on a
    // real phone therefore needs an HTTPS tunnel (ngrok), whose hostname
    // Vite's own dev-server Host-header protection would otherwise reject
    // as an unrecognized host (a real 403 hit live, not assumed) —
    // allowlisting the ngrok domain suffixes here is what lets that tunnel
    // actually reach this dev server. Dev-only; never shipped to production.
    allowedHosts: ['.ngrok-free.app', '.ngrok-free.dev', '.ngrok.app', '.ngrok.io'],
  },
})
