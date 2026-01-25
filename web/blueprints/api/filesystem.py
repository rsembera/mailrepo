"""
MailRepo API - Filesystem Routes

Provides endpoints for browsing the local filesystem
to select files and folders for import.
"""

import os
from pathlib import Path
from flask import request, jsonify
from . import api_bp


def get_home_dir():
    """Get user's home directory."""
    return str(Path.home())


def is_hidden(name):
    """Check if file/folder is hidden."""
    return name.startswith('.')


def is_mbox_file(filepath, name):
    """
    Check if a file is an mbox file.
    Checks by extension first, then by content signature.
    """
    # Check extension
    if name.lower().endswith('.mbox'):
        return True
    
    # Check content signature - mbox files start with "From "
    try:
        with open(filepath, 'rb') as f:
            # Read first 5 bytes
            header = f.read(5)
            if header == b'From ':
                return True
    except (PermissionError, OSError, IOError):
        pass
    
    return False


@api_bp.route("/filesystem/browse", methods=["POST"])
def browse_filesystem():
    """
    Browse a directory and return its contents.
    
    Request body:
        path: Directory path to browse (default: home)
        show_hidden: Whether to show hidden files (default: false)
        filter: Optional filter - 'dirs_only', 'mbox', 'eml'
    
    Returns:
        path: Current path
        parent: Parent path (null if at root)
        items: List of {name, path, type, size}
    """
    data = request.get_json() or {}
    path = data.get("path", "").strip() or get_home_dir()
    show_hidden = data.get("show_hidden", False)
    file_filter = data.get("filter", None)
    
    # Expand ~ to home directory
    path = os.path.expanduser(path)
    
    # Security: resolve to absolute path
    try:
        path = os.path.realpath(path)
    except Exception:
        return jsonify({"error": "Invalid path"}), 400
    
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
    
    if not os.path.isdir(path):
        return jsonify({"error": "Not a directory"}), 400
    
    try:
        items = []
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        
        for entry in entries:
            # Skip hidden files unless requested
            if not show_hidden and is_hidden(entry.name):
                continue
            
            try:
                is_dir = entry.is_dir()
                
                # Apply filter
                if file_filter == 'dirs_only' and not is_dir:
                    continue
                elif file_filter == 'mbox' and not is_dir:
                    if not is_mbox_file(entry.path, entry.name):
                        continue
                elif file_filter == 'eml' and not is_dir:
                    if not entry.name.lower().endswith('.eml'):
                        continue
                
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "type": "dir" if is_dir else "file",
                    "size": stat.st_size if not is_dir else None,
                })
            except (PermissionError, OSError):
                # Skip files we can't access
                continue
        
        # Get parent path
        parent = os.path.dirname(path)
        if parent == path:  # At root
            parent = None
        
        return jsonify({
            "path": path,
            "parent": parent,
            "items": items,
        })
        
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/filesystem/scan-eml", methods=["POST"])
def scan_eml_folder():
    """
    Scan a folder for .eml files.
    
    Request body:
        path: Directory path to scan
    
    Returns:
        path: Scanned path
        folder_name: Name of the folder
        files: List of {name, path, size}
    """
    data = request.get_json() or {}
    path = data.get("path", "").strip()
    
    if not path:
        return jsonify({"error": "Path is required"}), 400
    
    path = os.path.expanduser(path)
    path = os.path.realpath(path)
    
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
    
    if not os.path.isdir(path):
        return jsonify({"error": "Not a directory"}), 400
    
    try:
        files = []
        for entry in os.scandir(path):
            if entry.is_file() and entry.name.lower().endswith('.eml'):
                try:
                    stat = entry.stat()
                    files.append({
                        "name": entry.name,
                        "path": entry.path,
                        "size": stat.st_size,
                    })
                except (PermissionError, OSError):
                    continue
        
        # Sort by name
        files.sort(key=lambda f: f["name"].lower())
        
        return jsonify({
            "path": path,
            "folder_name": os.path.basename(path),
            "files": files,
            "count": len(files),
        })
        
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/filesystem/read-file", methods=["POST"])
def read_file_content():
    """
    Read a file's content (for parsing emails client-side).
    
    Request body:
        path: File path to read
    
    Returns:
        content: File content as text
    """
    data = request.get_json() or {}
    path = data.get("path", "").strip()
    
    if not path:
        return jsonify({"error": "Path is required"}), 400
    
    path = os.path.expanduser(path)
    path = os.path.realpath(path)
    
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    
    if not os.path.isfile(path):
        return jsonify({"error": "Not a file"}), 400
    
    # Limit file size to prevent memory issues (50MB)
    try:
        size = os.path.getsize(path)
        if size > 50 * 1024 * 1024:
            return jsonify({"error": "File too large (max 50MB)"}), 400
    except OSError:
        return jsonify({"error": "Cannot read file"}), 400
    
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        return jsonify({
            "path": path,
            "name": os.path.basename(path),
            "content": content,
            "size": size,
        })
        
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/filesystem/parse-mbox", methods=["POST"])
def parse_mbox_file():
    """
    Parse an mbox file and return email metadata with proper encoding.
    
    Request body:
        path: Path to mbox file
    
    Returns:
        emails: List of {uid, subject, from, to, date, message_id}
        count: Number of emails
    """
    import mailbox
    from email.header import decode_header
    from email.utils import parsedate_to_datetime
    
    data = request.get_json() or {}
    path = data.get("path", "").strip()
    
    if not path:
        return jsonify({"error": "Path is required"}), 400
    
    path = os.path.expanduser(path)
    path = os.path.realpath(path)
    
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    
    if not os.path.isfile(path):
        return jsonify({"error": "Not a file"}), 400
    
    def decode_header_value(header):
        """Decode RFC 2047 encoded header."""
        if not header:
            return ""
        try:
            parts = decode_header(header)
            decoded = []
            for content, charset in parts:
                if isinstance(content, bytes):
                    decoded.append(content.decode(charset or "utf-8", errors="replace"))
                else:
                    decoded.append(content)
            return " ".join(decoded)
        except:
            return str(header)
    
    try:
        mbox = mailbox.mbox(path)
        emails = []
        
        for i, message in enumerate(mbox):
            try:
                # Parse date
                date_str = message.get("Date", "")
                date_ts = None
                if date_str:
                    try:
                        dt = parsedate_to_datetime(date_str)
                        date_ts = dt.isoformat()
                    except:
                        date_ts = date_str
                
                # Check for folder indicator (X-Folder, X-Gmail-Labels, etc.)
                folder = message.get("X-Folder") or message.get("X-Gmail-Labels") or ""
                if folder:
                    folder = decode_header_value(folder)
                
                emails.append({
                    "uid": f"mbox-{i}",
                    "subject": decode_header_value(message.get("Subject", "(no subject)")),
                    "from": decode_header_value(message.get("From", "")),
                    "to": decode_header_value(message.get("To", "")),
                    "date": date_ts or date_str,
                    "message_id": message.get("Message-ID", ""),
                    "folder": folder,
                })
            except Exception as e:
                # Skip malformed messages
                emails.append({
                    "uid": f"mbox-{i}",
                    "subject": f"(error reading message: {e})",
                    "from": "",
                    "to": "",
                    "date": "",
                    "message_id": "",
                    "folder": "",
                })
        
        # Detect folder structure
        folders = {}
        for email in emails:
            if email.get("folder"):
                folder_name = email["folder"]
                if folder_name not in folders:
                    folders[folder_name] = []
                folders[folder_name].append(email["uid"])
        
        # Build folder list if any detected
        folder_list = None
        if folders:
            folder_list = [
                {"name": name, "fullPath": name, "emailUids": uids}
                for name, uids in sorted(folders.items())
            ]
        
        return jsonify({
            "path": path,
            "emails": emails,
            "count": len(emails),
            "folders": folder_list,
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to parse mbox: {e}"}), 500


@api_bp.route("/filesystem/parse-eml", methods=["POST"])
def parse_eml_file():
    """
    Parse an eml file and return email metadata with proper encoding.
    
    Request body:
        path: Path to eml file
    
    Returns:
        email: {uid, subject, from, to, date, message_id}
    """
    from email import message_from_binary_file
    from email.header import decode_header
    from email.utils import parsedate_to_datetime
    
    data = request.get_json() or {}
    path = data.get("path", "").strip()
    
    if not path:
        return jsonify({"error": "Path is required"}), 400
    
    path = os.path.expanduser(path)
    path = os.path.realpath(path)
    
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    
    if not os.path.isfile(path):
        return jsonify({"error": "Not a file"}), 400
    
    def decode_header_value(header):
        """Decode RFC 2047 encoded header."""
        if not header:
            return ""
        try:
            parts = decode_header(header)
            decoded = []
            for content, charset in parts:
                if isinstance(content, bytes):
                    decoded.append(content.decode(charset or "utf-8", errors="replace"))
                else:
                    decoded.append(content)
            return " ".join(decoded)
        except:
            return str(header)
    
    try:
        with open(path, 'rb') as f:
            message = message_from_binary_file(f)
        
        # Parse date
        date_str = message.get("Date", "")
        date_ts = None
        if date_str:
            try:
                dt = parsedate_to_datetime(date_str)
                date_ts = dt.isoformat()
            except:
                date_ts = date_str
        
        return jsonify({
            "path": path,
            "email": {
                "uid": f"eml-{os.path.basename(path)}",
                "subject": decode_header_value(message.get("Subject", "(no subject)")),
                "from": decode_header_value(message.get("From", "")),
                "to": decode_header_value(message.get("To", "")),
                "date": date_ts or date_str,
                "message_id": message.get("Message-ID", ""),
                "filename": os.path.basename(path),
                "sourcePath": path,  # Used by commit to retrieve raw email
            },
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to parse eml: {e}"}), 500


@api_bp.route("/filesystem/scan-apple-mbox", methods=["POST"])
def scan_apple_mbox_folder():
    """
    Scan a folder for Apple Mail mbox export structure.
    
    Apple Mail exports create:
    - FolderName.mbox/ (contains mbox file + table_of_contents)
    - FolderName/ (contains SubFolder.mbox/ for each subfolder)
    
    Request body:
        path: Path to the export folder
    
    Returns:
        tree: Nested structure of folders with email counts
    """
    import mailbox
    from email.header import decode_header
    from email.utils import parsedate_to_datetime
    
    data = request.get_json() or {}
    path = data.get("path", "").strip()
    
    if not path:
        return jsonify({"error": "Path is required"}), 400
    
    path = os.path.expanduser(path)
    path = os.path.realpath(path)
    
    if not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 404
    
    if not os.path.isdir(path):
        return jsonify({"error": "Not a directory"}), 400
    
    def decode_header_value(header):
        if not header:
            return ""
        try:
            parts = decode_header(header)
            decoded = []
            for content, charset in parts:
                if isinstance(content, bytes):
                    decoded.append(content.decode(charset or "utf-8", errors="replace"))
                else:
                    decoded.append(content)
            return " ".join(decoded)
        except:
            return str(header)
    
    def parse_mbox_file(mbox_path):
        """Parse a traditional mbox file and return emails."""
        emails = []
        try:
            mbox = mailbox.mbox(mbox_path)
            for i, message in enumerate(mbox):
                try:
                    date_str = message.get("Date", "")
                    date_ts = None
                    if date_str:
                        try:
                            dt = parsedate_to_datetime(date_str)
                            date_ts = dt.isoformat()
                        except:
                            date_ts = date_str
                    
                    emails.append({
                        "uid": f"apple-{os.path.basename(mbox_path)}-{i}",
                        "subject": decode_header_value(message.get("Subject", "(no subject)")),
                        "from": decode_header_value(message.get("From", "")),
                        "to": decode_header_value(message.get("To", "")),
                        "date": date_ts or date_str,
                        "message_id": message.get("Message-ID", ""),
                        "sourcePath": mbox_path,
                    })
                except:
                    pass
        except:
            pass
        return emails
    
    def scan_mbox_package(pkg_path):
        """Scan an Apple Mail .mbox package directory."""
        emails = []
        
        # Check for mbox file inside
        mbox_file = os.path.join(pkg_path, "mbox")
        if os.path.isfile(mbox_file):
            emails = parse_mbox_file(mbox_file)
        
        # Check for Messages directory with .emlx files
        messages_dir = os.path.join(pkg_path, "Messages")
        if os.path.isdir(messages_dir):
            for entry in os.scandir(messages_dir):
                if entry.name.endswith('.emlx') and entry.is_file():
                    # Parse .emlx file (similar to .eml but with Apple metadata prefix)
                    try:
                        with open(entry.path, 'rb') as f:
                            content = f.read()
                        
                        # .emlx files start with a line containing the byte count, skip it
                        first_newline = content.find(b'\n')
                        if first_newline > 0:
                            email_content = content[first_newline + 1:]
                            # Find where the email ends (before Apple's plist metadata)
                            plist_marker = email_content.rfind(b'<?xml version=')
                            if plist_marker > 0:
                                email_content = email_content[:plist_marker]
                            
                            from email import message_from_bytes
                            message = message_from_bytes(email_content)
                            
                            date_str = message.get("Date", "")
                            date_ts = None
                            if date_str:
                                try:
                                    dt = parsedate_to_datetime(date_str)
                                    date_ts = dt.isoformat()
                                except:
                                    date_ts = date_str
                            
                            emails.append({
                                "uid": f"emlx-{entry.name}",
                                "subject": decode_header_value(message.get("Subject", "(no subject)")),
                                "from": decode_header_value(message.get("From", "")),
                                "to": decode_header_value(message.get("To", "")),
                                "date": date_ts or date_str,
                                "message_id": message.get("Message-ID", ""),
                                "sourcePath": entry.path,
                            })
                    except Exception as e:
                        pass
        
        return emails
    
    def scan_folder(folder_path, name=None):
        """Recursively scan a folder for .mbox packages."""
        result = {
            "name": name or os.path.basename(folder_path),
            "path": folder_path,
            "emails": [],
            "children": [],
        }
        
        # Check if this folder itself is a .mbox package
        if folder_path.endswith('.mbox'):
            result["emails"] = scan_mbox_package(folder_path)
            
            # Check for sibling folder with subfolders
            sibling_folder = folder_path[:-5]  # Remove .mbox
            if os.path.isdir(sibling_folder):
                for entry in sorted(os.scandir(sibling_folder), key=lambda e: e.name.lower()):
                    if entry.is_dir() and entry.name.endswith('.mbox'):
                        child = scan_folder(entry.path)
                        if child["emails"] or child["children"]:
                            result["children"].append(child)
        else:
            # Scan for .mbox packages inside this folder
            for entry in sorted(os.scandir(folder_path), key=lambda e: e.name.lower()):
                if entry.is_dir() and entry.name.endswith('.mbox'):
                    child = scan_folder(entry.path)
                    if child["emails"] or child["children"]:
                        result["children"].append(child)
        
        return result
    
    try:
        tree = scan_folder(path)
        
        # Count total emails
        def count_emails(node):
            total = len(node.get("emails", []))
            for child in node.get("children", []):
                total += count_emails(child)
            return total
        
        total_count = count_emails(tree)
        
        return jsonify({
            "path": path,
            "tree": tree,
            "totalEmails": total_count,
        })
        
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500
