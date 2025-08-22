#!/bin/bash

echo "Starting Lichtwerk Controller with PM2..."

# Stop if already running
pm2 stop lichtwerk-controller 2>/dev/null || true
pm2 delete lichtwerk-controller 2>/dev/null || true

# Start with PM2
cd /home/pi/apps/lichtwerk-controller
pm2 start ecosystem.config.js

# Save PM2 configuration
pm2 save

# Generate startup script (only if not exists)
if ! pm2 startup | grep -q "sudo"; then
    echo "Setting up PM2 auto-start on boot..."
    pm2 startup systemd
else
    echo "PM2 auto-start already configured"
fi

echo "Lichtwerk Controller started!"
echo "Web interface: http://$(hostname -I | awk '{print $1}'):5006"
echo ""
echo "PM2 commands:"
echo "  pm2 status           - Show status"
echo "  pm2 logs             - Show logs"
echo "  pm2 restart lichtwerk-controller - Restart"
echo "  pm2 stop lichtwerk-controller    - Stop"