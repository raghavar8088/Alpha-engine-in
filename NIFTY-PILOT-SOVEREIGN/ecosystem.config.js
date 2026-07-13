// PM2 process supervisor config. CONFIGURE BOOT PERSISTENCE FROM DAY
// ONE — this is a direct lesson from the BTC engine's P0 incident
// where a server reboot silently killed the trading engine because
// `pm2 startup` + `pm2 save` were never run:
//
//   pm2 start ecosystem.config.js
//   pm2 startup        # prints a systemd/init command to run once, as root
//   pm2 save           # persists the current process list for boot resurrection
//
// Re-run `pm2 save` after any change to this file's process list.
module.exports = {
  apps: [
    {
      name: 'niftypilot-engine',
      cwd: './engine',
      script: 'go',
      args: 'run ./cmd/niftypilot/main.go',
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      env: {
        PORT: '8090',
      },
    },
    {
      name: 'niftypilot-dashboard',
      cwd: './client',
      script: 'npm',
      args: 'run start',
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      env: {
        PORT: '3000',
        INTERNAL_API_URL: 'http://127.0.0.1:8090',
      },
    },
  ],
};
