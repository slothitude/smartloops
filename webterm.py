"""Smart Loops — Web Terminal.

Single-file Flask server that bridges a browser xterm.js terminal to a
Claude Code PTY session.  Mobile-optimised for phone access via Tailscale.

Usage:
    python webterm.py --project-path /path/to/project --port 8737
"""

import argparse
import base64
import os
import socket
import sys
import threading
import time

from flask import Flask, Response
from flask_sock import Sock

# ---------------------------------------------------------------------------
# Inline HTML (xterm.js + fit addon, dark theme, mobile viewport)
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Smart Loops Terminal</title>
<style>
  html,body{margin:0;padding:0;height:100%;overflow:hidden;background:#1e1e1e;}
  #terminal{height:100vh;width:100vw;}
</style>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css">
</head>
<body>
<div id="terminal"></div>
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
<script>
const term = new Terminal({cursorBlink:true,fontSize:14,theme:{background:'#1e1e1e',foreground:'#d4d4d4'}});
const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.open(document.getElementById('terminal'));
fitAddon.fit();

let ws;
function connect(){
  const proto = location.protocol==='https:'?'wss:':'ws:';
  ws = new WebSocket(proto+'//'+location.host+'/ws');
  ws.binaryType='arraybuffer';
  ws.onmessage=function(ev){
    const msg=JSON.parse(ev.data);
    if(msg.type==='output'){
      term.write(atob(msg.payload));
    }else if(msg.type==='exit'){
      term.write('\r\n\x1b[31m[session ended]\x1b[0m\r\n');
      ws.close();
    }
  };
  ws.onclose=function(){term.write('\r\n\x1b[33m[disconnected — refreshing in 3s]\x1b[0m\r\n');setTimeout(connect,3000);};
  ws.onerror=function(){};
  // Send initial size
  ws.send(JSON.stringify({type:'resize',cols:term.cols,rows:term.rows}));
}
connect();

term.onData(function(data){
  if(ws&&ws.readyState===WebSocket.OPEN){
    ws.send(JSON.stringify({type:'input',payload:btoa(data)}));
  }
});
term.onResize(function({cols,rows}){
  if(ws&&ws.readyState===WebSocket.OPEN){
    ws.send(JSON.stringify({type:'resize',cols:cols,rows:rows}));
  }
});
window.addEventListener('resize',function(){fitAddon.fit();});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(project_path: str) -> Flask:
    app = Flask(__name__)
    sock = Sock(app)

    @app.route("/")
    def index():
        return Response(HTML_TEMPLATE, mimetype="text/html")

    @sock.route("/ws")
    def ws_bridge(ws):
        """Bridge a WebSocket connection to a Claude PTY."""
        import winpty

        # Find claude executable
        claude_exe = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
        if not os.path.isfile(claude_exe):
            claude_exe = "claude"

        pty = winpty.PTY(120, 40)
        pty.spawn(claude_exe, claude_exe, cwd=project_path)

        # Resize handler
        def on_message():
            try:
                while True:
                    data = ws.receive()
                    if data is None:
                        break
                    import json as _json
                    msg = _json.loads(data)
                    if msg.get("type") == "input":
                        raw = base64.b64decode(msg["payload"])
                        pty.write(raw.decode("utf-8", errors="replace"))
                    elif msg.get("type") == "resize":
                        try:
                            pty.set_size(msg.get("cols", 120), msg.get("rows", 40))
                        except Exception:
                            pass
            except Exception:
                pass

        reader_done = threading.Event()

        # PTY → WebSocket reader thread
        def reader():
            try:
                while pty.isalive():
                    try:
                        data = pty.read(blocking=False)
                        if data:
                            import json as _json
                            ws.send(_json.dumps({
                                "type": "output",
                                "payload": base64.b64encode(data.encode("utf-8", errors="replace")).decode("ascii"),
                            }))
                        else:
                            time.sleep(0.05)
                    except Exception:
                        break
            finally:
                reader_done.set()
                try:
                    import json as _json
                    ws.send(_json.dumps({"type": "exit"}))
                except Exception:
                    pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        # Block on incoming messages until PTY exits
        on_message()

        # Give reader a moment, then clean up
        reader_done.wait(timeout=3)

    return app


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def find_free_port(start: int = 8737) -> int:
    """Find the first available port starting from `start`."""
    for port in range(start, start + 100):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port))
            s.close()
            return port
        except OSError:
            continue
    raise RuntimeError(f"No free port found in range {start}-{start+100}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Smart Loops Web Terminal")
    parser.add_argument("--project-path", required=True, help="Path to the project directory")
    parser.add_argument("--port", type=int, default=8737, help="Port to listen on")
    args = parser.parse_args()

    project_path = os.path.abspath(args.project_path)
    if not os.path.isdir(project_path):
        print(f"Error: {project_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    app = create_app(project_path)
    print(f"Web terminal for {project_path} on port {args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
