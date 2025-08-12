module.exports = {
  apps: [{
    name: 'lichtwerk-controller',
    script: 'server.py',
    interpreter: '/home/pi/apps/lichtwerk-controller/venv/bin/python',
    cwd: '/home/pi/apps/lichtwerk-controller',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '100M',
    env: {
      PORT: '5006',
      ARDUINO_PORT: '/dev/ttyACM0',
      PYTHONUNBUFFERED: '1'
    },
    log_file: './logs/combined.log',
    out_file: './logs/out.log',
    error_file: './logs/error.log',
    pid_file: './logs/pid',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    min_uptime: '5s',
    max_restarts: 5
  }]
};