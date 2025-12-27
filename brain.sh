#!/bin/bash
# Local Memory Brain - Server Management Script
# Usage: brain start|stop|status|restart|logs

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"
SERVER_SCRIPT="$SCRIPT_DIR/server.py"
PID_FILE="$SCRIPT_DIR/.server.pid"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/server.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

start() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Server is already running (PID: $PID)"
            return 1
        fi
    fi

    echo "Starting Local Memory Server..."

    # Check if Ollama is running
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "Warning: Ollama doesn't seem to be running."
        echo "Starting Ollama..."
        brew services start ollama
        sleep 2
    fi

    # Start server in background
    cd "$SCRIPT_DIR"
    nohup "$VENV_PYTHON" "$SERVER_SCRIPT" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    sleep 2

    if [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
        echo "Server started successfully (PID: $(cat "$PID_FILE"))"
        echo "Logs: $LOG_FILE"
        echo "API: http://localhost:8000"
        echo "Docs: http://localhost:8000/docs"
    else
        echo "Failed to start server. Check logs: $LOG_FILE"
        return 1
    fi
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Server is not running (no PID file)"
        return 1
    fi

    PID=$(cat "$PID_FILE")

    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "Server is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 1
    fi

    echo "Stopping server (PID: $PID)..."
    kill "$PID"

    # Wait for graceful shutdown
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done

    # Force kill if still running
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Force killing..."
        kill -9 "$PID"
    fi

    rm -f "$PID_FILE"
    echo "Server stopped"
}

status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Server is not running"
        return 1
    fi

    PID=$(cat "$PID_FILE")

    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Server is running (PID: $PID)"

        # Check if API is responding
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "API: http://localhost:8000 (healthy)"
        else
            echo "API: http://localhost:8000 (not responding)"
        fi
    else
        echo "Server is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 1
    fi
}

restart() {
    stop
    sleep 1
    start
}

logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "No log file found at: $LOG_FILE"
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    restart)
        restart
        ;;
    logs)
        logs
        ;;
    *)
        echo "Local Memory Brain - Server Management"
        echo ""
        echo "Usage: brain {start|stop|status|restart|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the server in background"
        echo "  stop    - Stop the running server"
        echo "  status  - Check if server is running"
        echo "  restart - Restart the server"
        echo "  logs    - View server logs (tail -f)"
        ;;
esac
