#!/bin/bash
# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC
# SPDX-License-Identifier: Apache-2.0

# Control script for cadinstall listener daemon

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LISTENER_SCRIPT="${SCRIPT_DIR}/cadinstall_listener.py"
CONFIG_FILE="${SCRIPT_DIR}/../config/cadinstall.json"
PID_FILE="/var/run/cadinstall_listener.pid"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root to manage the listener daemon"
    echo "Please use: sudo $0 $@"
    exit 1
fi

# Function to get configured user from config file
get_configured_user() {
    if [ -f "$CONFIG_FILE" ]; then
        # Try to extract user from JSON config using python
        python3 -c "import json; f=open('$CONFIG_FILE'); c=json.load(f); print(c.get('listener', {}).get('user', 'cadtools'))" 2>/dev/null || echo "cadtools"
    else
        echo "cadtools"
    fi
}

# Function to start the listener
start_listener() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Listener is already running (PID: $PID)"
            return 0
        else
            echo "Removing stale PID file"
            rm -f "$PID_FILE"
        fi
    fi
    
    if [ ! -f "$LISTENER_SCRIPT" ]; then
        echo "ERROR: Listener script not found: $LISTENER_SCRIPT"
        exit 1
    fi
    
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "ERROR: Configuration file not found: $CONFIG_FILE"
        echo "Please create the configuration file first"
        exit 1
    fi
    
    CONFIGURED_USER=$(get_configured_user)
    
    echo "Starting cadinstall listener daemon as user: $CONFIGURED_USER"
    
    # Start the listener as the configured user in the background
    su - "$CONFIGURED_USER" -c "nohup $LISTENER_SCRIPT --config $CONFIG_FILE > /dev/null 2>&1 &"
    
    sleep 2
    
    # Find the PID of the listener process
    LISTENER_PID=$(pgrep -f "cadinstall_listener.py")
    
    if [ -n "$LISTENER_PID" ]; then
        echo "$LISTENER_PID" > "$PID_FILE"
        echo "Listener started successfully (PID: $LISTENER_PID)"
        
        # Show listener info
        python3 -c "
import json
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)
    listener = config.get('listener', {})
    print('Host: %s' % listener.get('host', 'localhost'))
    print('Port: %s' % listener.get('port', 9876))
    print('Log file: %s' % listener.get('logfile', '/tmp/cadinstall_listener.log'))
" 2>/dev/null
    else
        echo "ERROR: Failed to start listener"
        exit 1
    fi
}

# Function to stop the listener
stop_listener() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Listener is not running (no PID file found)"
        
        # Check if there's a process running anyway
        LISTENER_PID=$(pgrep -f "cadinstall_listener.py")
        if [ -n "$LISTENER_PID" ]; then
            echo "Found listener process without PID file (PID: $LISTENER_PID)"
            echo "Stopping listener..."
            kill "$LISTENER_PID"
            sleep 2
            if ps -p "$LISTENER_PID" > /dev/null 2>&1; then
                echo "Process still running, forcing kill..."
                kill -9 "$LISTENER_PID"
            fi
            echo "Listener stopped"
        fi
        return 0
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "Listener is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 0
    fi
    
    echo "Stopping listener (PID: $PID)..."
    kill "$PID"
    
    # Wait for the process to stop
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "Listener stopped successfully"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done
    
    # Force kill if still running
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Process still running, forcing kill..."
        kill -9 "$PID"
        sleep 1
        rm -f "$PID_FILE"
        echo "Listener stopped (forced)"
    fi
}

# Function to check listener status
status_listener() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Listener is not running (no PID file)"
        
        # Check if there's a process running anyway
        LISTENER_PID=$(pgrep -f "cadinstall_listener.py")
        if [ -n "$LISTENER_PID" ]; then
            echo "WARNING: Found listener process without PID file (PID: $LISTENER_PID)"
        fi
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Listener is running (PID: $PID)"
        
        # Show listener info
        if [ -f "$CONFIG_FILE" ]; then
            python3 -c "
import json
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)
    listener = config.get('listener', {})
    print('Host: %s' % listener.get('host', 'localhost'))
    print('Port: %s' % listener.get('port', 9876))
    print('User: %s' % listener.get('user', 'cadtools'))
    print('Log file: %s' % listener.get('logfile', '/tmp/cadinstall_listener.log'))
" 2>/dev/null
        fi
        return 0
    else
        echo "Listener is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 1
    fi
}

# Function to restart the listener
restart_listener() {
    stop_listener
    sleep 2
    start_listener
}

# Parse command line arguments
case "$1" in
    start)
        start_listener
        ;;
    stop)
        stop_listener
        ;;
    restart)
        restart_listener
        ;;
    status)
        status_listener
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        echo ""
        echo "Control script for cadinstall listener daemon"
        echo ""
        echo "Commands:"
        echo "  start   - Start the listener daemon"
        echo "  stop    - Stop the listener daemon"
        echo "  restart - Restart the listener daemon"
        echo "  status  - Check if the listener is running"
        echo ""
        echo "Example:"
        echo "  sudo $0 start"
        exit 1
        ;;
esac

