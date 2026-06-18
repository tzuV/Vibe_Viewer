#!/usr/bin/env python3
"""
Vibe Web Viewer - Display Mistral Vibe CLI conversations in a web browser
====================================================================

This script provides a web interface that mirrors your Vibe CLI conversations
in a browser window with better readability. Features include:

- Manual refresh (no auto-refreshing)
- Session browser to navigate between conversations
- Beautiful markdown rendering
- Dark/light theme toggle
- Responsive design

Usage:
    python scripts/vibe_viewer.py           # Start viewer for current session
    python scripts/vibe_viewer.py --list    # List all sessions
    python scripts/vibe_viewer.py --port 8080  # Use custom port
"""

import os
import sys
import json
import argparse
import webbrowser
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Default configuration
DEFAULT_PORT = 5000
DEFAULT_HOST = "127.0.0.1"

# Paths
VIBE_DIR = os.path.expanduser("~/.vibe")
SESSIONS_DIR = os.path.join(VIBE_DIR, "logs", "session")


class VibeSession:
    """Represents a Vibe CLI conversation session"""
    
    def __init__(self, session_id, session_path):
        self.id = session_id
        self.path = session_path
        self.meta = self._load_meta()
        self.messages = self._load_messages()
    
    def _load_meta(self):
        """Load session metadata"""
        meta_path = os.path.join(self.path, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def _load_messages(self):
        """Load all messages from messages.jsonl"""
        messages_path = os.path.join(self.path, "messages.jsonl")
        messages = []
        
        if os.path.exists(messages_path):
            try:
                with open(messages_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                msg = json.loads(line)
                                messages.append(msg)
                            except json.JSONDecodeError:
                                pass
            except Exception:
                pass
        
        return messages
    
    def get_formatted_messages(self):
        """Get messages formatted for display"""
        formatted = []
        for msg in self.messages:
            formatted_msg = {
                'role': msg.get('role', 'unknown'),
                'content': msg.get('content', ''),
                'message_id': msg.get('message_id', ''),
                'timestamp': msg.get('timestamp', ''),
                'injected': msg.get('injected', False)
            }
            formatted.append(formatted_msg)
        return formatted

    def count_tokens(self):
        """Count estimated tokens in all messages. ponytail: word split estimate, use tiktoken if accuracy matters."""
        total = 0
        for msg in self.messages:
            content = msg.get('content', '')
            reasoning = msg.get('reasoning_content', '')
            # Simple word-based estimate: split on whitespace, filter empty
            total += len(content.split())
            total += len(reasoning.split())
        return total


class SessionManager:
    """Manages Vibe CLI sessions"""
    
    def __init__(self):
        self.sessions = {}
        self.current_session_id = self._get_current_session()
    
    def _get_current_session(self):
        """Get the current active session ID"""
        last_session_path = os.path.join(SESSIONS_DIR, ".last_session")
        if os.path.exists(last_session_path):
            try:
                # Read the session ID from the last_session file
                for root, dirs, files in os.walk(last_session_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                session_id = f.read().strip()
                                if session_id:
                                    return session_id
                        except Exception:
                            pass
            except Exception:
                pass
        
        # Fallback: get the most recent session
        return self._get_most_recent_session()
    
    def _get_most_recent_session(self):
        """Get the most recently modified session"""
        if not os.path.exists(SESSIONS_DIR):
            return None
        
        sessions = []
        for item in os.listdir(SESSIONS_DIR):
            item_path = os.path.join(SESSIONS_DIR, item)
            if os.path.isdir(item_path) and not item.startswith('.'):
                sessions.append(item)
        
        if sessions:
            # Sort by modification time, newest first
            sessions.sort(key=lambda s: os.path.getmtime(os.path.join(SESSIONS_DIR, s)), reverse=True)
            return sessions[0]
        return None
    
    def list_sessions(self, force_refresh=False):
        """List all available sessions"""
        if force_refresh:
            # Clear cached sessions to force refresh
            self.sessions = {}
            
        sessions = []
        if os.path.exists(SESSIONS_DIR):
            for item in os.listdir(SESSIONS_DIR):
                item_path = os.path.join(SESSIONS_DIR, item)
                if os.path.isdir(item_path) and not item.startswith('.'):
                    # Use cached session if available, otherwise create new
                    if item in self.sessions:
                        session = self.sessions[item]
                    else:
                        session = VibeSession(item, item_path)
                        self.sessions[item] = session
                    sessions.append({
                        'id': item,
                        'meta': session.meta,
                        'message_count': len(session.messages),
                        'modified': os.path.getmtime(item_path)
                    })
        # Sort by modification time, newest first
        sessions.sort(key=lambda s: s['modified'], reverse=True)
        return sessions
    
    def get_session(self, session_id=None):
        """Get a specific session"""
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        session_path = os.path.join(SESSIONS_DIR, session_id)
        if os.path.exists(session_path):
            session = VibeSession(session_id, session_path)
            self.sessions[session_id] = session
            return session
        
        return None
    
    def reload_session(self, session_id=None):
        """Reload a session's messages from disk"""
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session.messages = session._load_messages()
            return session
        
        return self.get_session(session_id)

    def rename_session(self, session_id, new_title):
        """Rename a session by updating its title in meta.json"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        session.meta['title'] = new_title
        meta_path = os.path.join(session.path, 'meta.json')
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(session.meta, f, indent=2, ensure_ascii=False)
            # Clear cache to force reload
            if session_id in self.sessions:
                del self.sessions[session_id]
            return True
        except Exception:
            return False


class VibeHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for the web viewer"""
    
    # Class-level storage for session manager
    session_manager = None
    
    def log_message(self, format, *args):
        """Suppress default logging to keep terminal clean"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/' or self.path == '/index.html':
            self._serve_index()
        elif self.path.startswith('/api/'):
            self._handle_api()
        else:
            self.send_error(404)
    
    def _serve_index(self):
        """Serve the main HTML page"""
        # Get the absolute path to the template
        script_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(script_dir, 'templates', 'index.html')
        
        if os.path.exists(html_path):
            with open(html_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content.encode('utf-8')))
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        else:
            # Fallback: serve a minimal HTML if template not found
            fallback_html = """
            <!DOCTYPE html>
            <html>
            <head><title>Vibe Web Viewer</title></head>
            <body>
                <h1>Vibe Web Viewer</h1>
                <p>Template not found. Please check the installation.</p>
            </body>
            </html>
            """
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(fallback_html.encode('utf-8')))
            self.end_headers()
            self.wfile.write(fallback_html.encode('utf-8'))
    
    def _handle_api(self):
        """Handle API requests"""
        if self.path == '/api/sessions':
            self._api_sessions()
        elif self.path == '/api/messages':
            self._api_messages()
        elif self.path.startswith('/api/session/'):
            self._api_session_messages()
        elif self.path == '/api/refresh':
            self._api_refresh()
        elif self.path == '/api/refresh_sessions':
            self._api_refresh_sessions()
        elif self.path == '/api/refresh_all':
            self._api_refresh_all()
        elif self.path == '/api/token_stats':
            self._api_token_stats()
        elif self.path.startswith('/api/session/rename'):
            self._api_rename_session()
        else:
            self.send_error(404)
    
    def _api_sessions(self):
        """Return list of all sessions"""
        sessions = self.session_manager.list_sessions()
        response = json.dumps({
            'sessions': sessions,
            'current_session': self.session_manager.current_session_id
        })
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(response.encode('utf-8')))
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def _api_messages(self):
        """Return messages from current session"""
        session = self.session_manager.get_session()
        if session:
            messages = session.get_formatted_messages()
            response = json.dumps({
                'session_id': session.id,
                'messages': messages
            })
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response.encode('utf-8')))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        else:
            self.send_error(404, "Session not found")
    
    def _api_session_messages(self):
        """Return messages from a specific session"""
        # Extract session ID from path: /api/session/{session_id}
        parts = self.path.split('/')
        if len(parts) >= 4:
            session_id = parts[3]
            session = self.session_manager.get_session(session_id)
            if session:
                messages = session.get_formatted_messages()
                response = json.dumps({
                    'session_id': session.id,
                    'messages': messages
                })
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(response.encode('utf-8')))
                self.end_headers()
                self.wfile.write(response.encode('utf-8'))
            else:
                self.send_error(404, "Session not found")
        else:
            self.send_error(400, "Invalid request")
    
    def _api_refresh(self):
        """Refresh the current session's messages"""
        # Get session ID from query parameters or use current
        session_id = self.session_manager.current_session_id
        
        # Reload the session
        session = self.session_manager.reload_session(session_id)
        
        if session:
            messages = session.get_formatted_messages()
            response = json.dumps({
                'session_id': session.id,
                'messages': messages,
                'refreshed_at': session.meta.get('modified', '')
            })
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response.encode('utf-8')))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        else:
            self.send_error(404, "Session not found")
    
    def _api_refresh_all(self):
        """Refresh both sessions list and current session messages"""
        try:
            # Update current session ID by re-reading from disk
            self.session_manager.current_session_id = self.session_manager._get_current_session()
            
            # Force refresh of sessions list
            sessions = self.session_manager.list_sessions(force_refresh=True)
            current_session = self.session_manager.current_session_id
            
            # Reload the current session's messages
            session = self.session_manager.reload_session(current_session)
            messages = []
            if session:
                messages = session.get_formatted_messages()
            
            response = json.dumps({
                'sessions': sessions,
                'current_session': current_session,
                'messages': messages,
                'session_id': session.id if session else None,
                'refreshed_at': session.meta.get('modified', '') if session else ''
            })
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response.encode('utf-8')))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error refreshing: {str(e)}")
    
    def _api_refresh_sessions(self):
        """Refresh the sessions list to discover new sessions"""
        try:
            # Update current session ID by re-reading from disk
            self.session_manager.current_session_id = self.session_manager._get_current_session()
            
            # Force refresh of sessions list
            sessions = self.session_manager.list_sessions(force_refresh=True)
            current_session = self.session_manager.current_session_id
            
            response = json.dumps({
                'sessions': sessions,
                'current_session': current_session
            })
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response.encode('utf-8')))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error refreshing sessions: {str(e)}")

    def _api_token_stats(self):
        """Return token statistics for all sessions"""
        try:
            sessions_list = self.session_manager.list_sessions(force_refresh=True)
            stats = []
            total_tokens = 0
            
            for session_info in sessions_list:
                session = self.session_manager.get_session(session_info['id'])
                if session:
                    token_count = session.count_tokens()
                    total_tokens += token_count
                    stats.append({
                        'session_id': session.id,
                        'title': session.meta.get('title', session.id),
                        'token_count': token_count,
                        'message_count': len(session.messages)
                    })
            
            response = json.dumps({
                'sessions': stats,
                'total_tokens': total_tokens,
                'total_sessions': len(stats)
            })
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response.encode('utf-8')))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error getting token stats: {str(e)}")

    def _api_rename_session(self):
        """Rename a session"""
        try:
            # Parse session_id and new_title from path: /api/session/rename/{session_id}?title=new_title
            parts = self.path.split('/')
            if len(parts) < 5:
                self.send_error(400, "Invalid request")
                return
            
            session_id = parts[4]
            
            # Get new title from query params
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            new_title = params.get('title', [''])[0]
            
            if not new_title:
                # Try to get from request body for POST
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    body = self.rfile.read(content_length).decode('utf-8')
                    body_params = parse_qs(body)
                    new_title = body_params.get('title', [''])[0]
            
            if not new_title:
                self.send_error(400, "Missing title parameter")
                return
            
            success = self.session_manager.rename_session(session_id, new_title)
            
            if success:
                # Force refresh sessions list
                sessions = self.session_manager.list_sessions(force_refresh=True)
                response = json.dumps({
                    'success': True,
                    'session_id': session_id,
                    'new_title': new_title,
                    'sessions': sessions
                })
                self.send_response(200)
            else:
                response = json.dumps({
                    'success': False,
                    'error': 'Session not found or could not rename'
                })
                self.send_response(404)
            
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(response.encode('utf-8')))
            self.end_headers()
            self.wfile.write(response.encode('utf-8'))
        except Exception as e:
            self.send_error(500, f"Error renaming session: {str(e)}")


def open_browser(port):
    """Open browser automatically"""
    url = f"http://localhost:{port}"
    try:
        # Try to open in default browser
        webbrowser.open(url)
        print(f"Vibe Web Viewer running at: {url}")
        print("Press Ctrl+C to stop the server")
    except Exception as e:
        print(f"Could not open browser: {e}")
        print(f"Please manually open: {url}")


def main():
    parser = argparse.ArgumentParser(
        description='Vibe Web Viewer - View CLI conversations in browser'
    )
    
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=DEFAULT_PORT,
        help='Port to serve on (default: 5000)'
    )
    
    parser.add_argument(
        '--host', '-H',
        type=str,
        default=DEFAULT_HOST,
        help='Host to bind to (default: 127.0.0.1)'
    )
    
    parser.add_argument(
        '--session', '-s',
        type=str,
        default=None,
        help='Specific session ID to view'
    )
    
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all sessions and exit'
    )
    
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not open browser automatically'
    )
    
    args = parser.parse_args()
    
    # Initialize session manager
    session_manager = SessionManager()
    
    if args.list:
        # Just list sessions and exit
        sessions = session_manager.list_sessions()
        print(f"\nAvailable Sessions ({len(sessions)}):")
        print("=" * 60)
        for session in sessions:
            print(f"  {session['id']} ({session['message_count']} messages)")
        print("=" * 60)
        print(f"\nCurrent: {session_manager.current_session_id}\n")
        return
    
    # Override current session if specified
    if args.session:
        session_manager.current_session_id = args.session
    
    # Set up the handler
    VibeHandler.session_manager = session_manager
    
    # Get current session info
    current_session = session_manager.get_session()
    message_count = len(current_session.messages) if current_session else 0
    
    print(f"Starting Vibe Web Viewer on http://{args.host}:{args.port}")
    if current_session:
        print(f"Current session: {current_session.id} ({message_count} messages)")
    
    # Open browser if not disabled
    if not args.no_browser:
        # Small delay to ensure server is ready
        import time
        time.sleep(0.5)
        open_browser(args.port)
    
    try:
        # Start the server
        with HTTPServer((args.host, args.port), VibeHandler) as httpd:
            print(f"Server started. Use the refresh button in the browser to update conversations and discover new sessions.")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()