"""
MailRepo API - Filesystem Routes

Provides endpoints for browsing the local filesystem
to select files and folders for import.
"""

import os
import mailbox
from email import message_from_bytes, message_from_binary_file
from email.utils import parsedate_to_datetime
from pathlib import Path
from flask import request, jsonify
from utils.log import get_logger
from .email_parser import decode_email_header
from . import api_bp

log = get_logger()


def get_home_dir():
    """Get user's home directory."""
    return str(Path.home())


# Folders that aren't dotfile-hidden but should still be hidden from
# the destination picker on macOS \u2014 they're Windows artifacts that
# show up on shared external drives or USB sticks formatted on Windows.
_SYSTEM_DIRS_TO_HIDE = {
    "$RECYCLE.BIN",
    "System Volume Information",
    "RECYCLER",
    "$Recycle.Bin",
    ".Spotlight-V100",
    ".Trashes",
    ".fseventsd",
    ".DocumentRevisions-V100",
    ".TemporaryItems",
}


def is_hidden(name):
    """Check if file/folder is hidden.

    Hides dotfiles (Unix convention) and a small allowlist of cross-platform
    system directories that aren\'t dotfile-hidden but are still useless
    in a destination picker (Windows-style $RECYCLE.BIN, etc.).
    """
    return name.startswith('.') or name in _SYSTEM_DIRS_TO_HIDE


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
                item = {
                    "name": entry.name,
                    "path": entry.path,
                    "type": "dir" if is_dir else "file",
                    "size": stat.st_size if not is_dir else None,
                }
                
                # Mark mbox files for the file picker
                if not is_dir and file_filter == 'mbox':
                    item["is_mbox"] = True
                elif not is_dir and is_mbox_file(entry.path, entry.name):
                    item["is_mbox"] = True
                
                items.append(item)
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
                    folder = decode_email_header(folder)
                
                emails.append({
                    "uid": f"mbox-{i}",
                    "subject": decode_email_header(message.get("Subject", "(no subject)")),
                    "from": decode_email_header(message.get("From", "")),
                    "to": decode_email_header(message.get("To", "")),
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
                "subject": decode_email_header(message.get("Subject", "(no subject)")),
                "from": decode_email_header(message.get("From", "")),
                "to": decode_email_header(message.get("To", "")),
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
                        "subject": decode_email_header(message.get("Subject", "(no subject)")),
                        "from": decode_email_header(message.get("From", "")),
                        "to": decode_email_header(message.get("To", "")),
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
                                "subject": decode_email_header(message.get("Subject", "(no subject)")),
                                "from": decode_email_header(message.get("From", "")),
                                "to": decode_email_header(message.get("To", "")),
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
                    if entry.is_dir():
                        child = scan_folder(entry.path)
                        if child["emails"] or child["children"]:
                            result["children"].append(child)
        else:
            # Scan for .mbox packages and container folders inside this folder
            for entry in sorted(os.scandir(folder_path), key=lambda e: e.name.lower()):
                if entry.is_dir():
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


@api_bp.route("/filesystem/check-pst-support", methods=["GET"])
def check_pst_support():
    """
    Check if PST import is supported (readpst is installed).
    
    Returns:
        supported: Boolean indicating if PST import is available
        message: Status message
    """
    import shutil
    
    readpst_path = shutil.which("readpst")
    
    if readpst_path:
        return jsonify({
            "supported": True,
            "message": "PST import is available",
            "readpst_path": readpst_path,
        })
    else:
        return jsonify({
            "supported": False,
            "message": "PST import requires libpst. Install with: brew install libpst (macOS) or apt install pst-utils (Linux)",
        })


@api_bp.route("/filesystem/convert-pst", methods=["POST"])
def convert_pst_to_mbox():
    """
    Convert a PST file to mbox format using readpst.
    
    Request body:
        path: Path to .pst file
    
    Returns:
        mbox_path: Path to the converted mbox file
        folder_count: Number of folders extracted
    """
    import shutil
    import subprocess
    import tempfile
    
    data = request.get_json() or {}
    pst_path = data.get("path", "").strip()
    
    if not pst_path:
        return jsonify({"error": "Path is required"}), 400
    
    pst_path = os.path.expanduser(pst_path)
    pst_path = os.path.realpath(pst_path)
    
    if not os.path.exists(pst_path):
        return jsonify({"error": "File not found"}), 404
    
    if not os.path.isfile(pst_path):
        return jsonify({"error": "Not a file"}), 400
    
    if not pst_path.lower().endswith('.pst'):
        return jsonify({"error": "Not a PST file"}), 400
    
    # Check if readpst is available
    readpst_path = shutil.which("readpst")
    if not readpst_path:
        return jsonify({
            "error": "PST import requires libpst. Install with: brew install libpst (macOS) or apt install pst-utils (Linux)"
        }), 400
    
    try:
        # Create temp directory for conversion
        temp_dir = tempfile.mkdtemp(prefix="mailrepo_pst_")
        
        # Run readpst to convert PST to mbox
        # -r: recursive (outputs folders as subdirectories with mbox files)
        # -o: output directory
        # -w: overwrite existing files
        result = subprocess.run(
            [readpst_path, "-r", "-w", "-o", temp_dir, pst_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        
        if result.returncode != 0:
            # Clean up on error
            shutil.rmtree(temp_dir, ignore_errors=True)
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return jsonify({"error": f"PST conversion failed: {error_msg}"}), 500
        
        # Debug: log conversion output
        log.debug(f"PST readpst stdout: {result.stdout}")
        log.debug(f"PST readpst stderr: {result.stderr}")
        log.debug(f"PST temp_dir: {temp_dir}")
        
        # Find all generated mbox files
        # readpst with -r creates directory structure with mbox files (no extension)
        mbox_files = []
        for root, dirs, files in os.walk(temp_dir):
            log.debug(f"PST scanning dir: {root}, files: {files}")
            for f in files:
                filepath = os.path.join(root, f)
                if os.path.isfile(filepath):
                    # Check if it's an mbox file (starts with "From ")
                    try:
                        with open(filepath, 'rb') as mf:
                            header = mf.read(5)
                            log.debug(f"PST file {filepath} header: {header}")
                            if header == b'From ':
                                rel_path = os.path.relpath(filepath, temp_dir)
                                mbox_files.append({
                                    "path": filepath,
                                    "name": rel_path,
                                })
                    except Exception as e:
                        log.debug(f"PST error reading {filepath}: {e}")
        
        log.debug(f"PST found mbox_files: {mbox_files}")
        
        if not mbox_files:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({"error": "No emails found in PST file"}), 400
        
        return jsonify({
            "success": True,
            "temp_dir": temp_dir,
            "mbox_files": mbox_files,
            "folder_count": len(mbox_files),
        })
        
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"error": "PST conversion timed out (file may be too large)"}), 500
    except Exception as e:
        if 'temp_dir' in locals():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"error": f"PST conversion failed: {e}"}), 500


@api_bp.route("/filesystem/cleanup-pst-temp", methods=["POST"])
def cleanup_pst_temp():
    """
    Clean up temporary files from PST conversion.
    
    Request body:
        temp_dir: Path to temporary directory to remove
    """
    import shutil
    
    data = request.get_json() or {}
    temp_dir = data.get("temp_dir", "").strip()
    
    if not temp_dir:
        return jsonify({"error": "temp_dir is required"}), 400
    
    # Security: only allow cleanup of paths in system temp directory
    import tempfile
    system_temp = tempfile.gettempdir()
    
    temp_dir = os.path.realpath(temp_dir)
    if not temp_dir.startswith(system_temp):
        return jsonify({"error": "Invalid temp directory"}), 400
    
    if not temp_dir.startswith(os.path.join(system_temp, "mailrepo_pst_")):
        return jsonify({"error": "Invalid temp directory"}), 400
    
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
