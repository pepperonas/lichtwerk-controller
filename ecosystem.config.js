module.exports = {
  apps: [{
    name: 'lichtwerk-controller',
    script: 'web_controller.py',
    interpreter: 'python3',
    cwd: '/home/pi/apps/lichtwerk-controller',
    env: {
      NODE_ENV: 'production',
      PYTHONUNBUFFERED: '1'
    },
    exec_mode: 'fork',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '200M',
    restart_delay: 5000,
    min_uptime: '10s',
    max_restarts: 10,
    error_file: './logs/pm2-error.log',
    out_file: './logs/pm2-out.log',
    log_file: './logs/pm2-combined.log',
    time: true,
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
  }]
};