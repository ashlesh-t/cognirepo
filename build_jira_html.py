import os
import re
import json
import glob
import yaml

jira_dir = "/home/ashlesh/my_works/cognirepo/JIRA"
output_file = "/home/ashlesh/JIRAS/JIRA.html"

# Ensure output directory exists
os.makedirs(os.path.dirname(output_file), exist_ok=True)

# Load status.yml
status_data = {}
status_path = os.path.join(jira_dir, "status.yml")
if os.path.exists(status_path):
    with open(status_path, "r", encoding="utf-8") as f:
        status_data = yaml.safe_load(f)

# Load per-epic status.yml files (real story/defect status, branch, pr, test_status)
# so the board reflects actual repo state instead of guessing.
story_status = {}
epic_test_status = {}
STATUS_TO_COLUMN = {
    "not-started": "todo",
    "blocked": "todo",
    "in-progress": "in-progress",
    "done": "done",
}
for epic_status_path in sorted(glob.glob(os.path.join(jira_dir, "EPIC-*", "status.yml"))):
    with open(epic_status_path, "r", encoding="utf-8") as f:
        epic_status_data = yaml.safe_load(f) or {}
    for item in (epic_status_data.get("stories") or []) + (epic_status_data.get("defects") or []):
        story_status[item["id"]] = {
            "column": STATUS_TO_COLUMN.get(item.get("status"), "todo"),
            "raw_status": item.get("status", "not-started"),
            "branch": item.get("branch"),
            "pr": item.get("pr"),
            "test_status": item.get("test_status", "not-run"),
        }
    epic_id = epic_status_data.get("epic_id")
    if epic_id:
        epic_test_status[epic_id] = epic_status_data.get("epic_test_suite_status", "not-run")

# Helper function to parse sections from markdown
def parse_sections(md_text):
    sections = {
        "title": "",
        "backstory": "",
        "description": "",
        "acceptance_criteria": "",
        "notes": ""
    }
    
    # Extract title from first # heading
    title_match = re.search(r"^#\s+(?:COGNIREPO-[A-Z0-9]+)\s*[—:]\s*(.*)$", md_text, re.MULTILINE)
    if title_match:
        sections["title"] = title_match.group(1).strip()
    else:
        # Fallback for other header styles
        title_match_fallback = re.search(r"^#\s*(.*)$", md_text, re.MULTILINE)
        if title_match_fallback:
            sections["title"] = title_match_fallback.group(1).strip()
            
    # Extract sections by split
    lines = md_text.splitlines()
    current_section = None
    current_lines = []
    
    for line in lines:
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            
            header = line[3:].strip().lower()
            if "backstory" in header or "reproduction" in header:
                current_section = "backstory"
            elif "description" in header or "fix" in header:
                current_section = "description"
            elif "acceptance" in header:
                current_section = "acceptance_criteria"
            elif "notes" in header or "risks" in header:
                current_section = "notes"
            else:
                current_section = header.replace(" ", "_")
            current_lines = []
        elif line.startswith("# "):
            pass
        else:
            if current_section:
                current_lines.append(line)
                
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()
        
    return sections

# Walk and find files
raw_files = []
for root, dirs, files in os.walk(jira_dir):
    for file in files:
        if file.endswith(".md"):
            path = os.path.join(root, file)
            raw_files.append((path, file))

issues_db = {}
sub_docs = [] # (base_key, type, md_content)

for path, file in raw_files:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    rel_path = os.path.relpath(path, jira_dir)
    
    # Check if it is a Test Suite or Discovery document
    if "-TEST_SUITE.md" in file:
        base_key = file.replace("-TEST_SUITE.md", "")
        sub_docs.append((base_key, "test_suite", content))
        continue
    elif "-Discovery.md" in file:
        base_key = file.replace("-Discovery.md", "")
        sub_docs.append((base_key, "discovery", content))
        continue
        
    # Main issue parsing
    key_match = re.search(r"(COGNIREPO-[A-Z0-9]+)", file)
    if not key_match:
        continue
    key = key_match.group(1)
    
    # Parse title and sections
    secs = parse_sections(content)
    
    # Parse metadata line: Epic:, Branch:, Base:, Severity:
    epic = ""
    branch = ""
    base = ""
    severity = "Medium" # default
    
    meta_line = ""
    for line in content.splitlines():
        if line.startswith("Epic:"):
            meta_line = line
            break
            
    if meta_line:
        m_epic = re.search(r"Epic:\s*(COGNIREPO-\d+)", meta_line)
        if m_epic:
            epic = m_epic.group(1)
        m_branch = re.search(r"Branch:\s*([^\s·]+)", meta_line)
        if m_branch:
            branch = m_branch.group(1)
        m_base = re.search(r"Base:\s*([^\s·]+)", meta_line)
        if m_base:
            base = m_base.group(1)
        m_sev = re.search(r"Severity:\s*([^\s·]+)", meta_line)
        if m_sev:
            severity = m_sev.group(1)
            
    # Determine Issue Type
    issue_type = "Story"
    if "DEFECT" in path or "/defect/" in path.lower():
        issue_type = "Bug"
    elif key.endswith("00"):
        issue_type = "Epic"
        
    # Status: sourced from the real per-epic status.yml (falls back to "todo" for
    # epics, which are tracked separately via the root status.yml epics list).
    real_status = story_status.get(key, {})
    status = real_status.get("column", "todo")
    if real_status.get("branch"):
        branch = real_status["branch"]
    issue_test_status = real_status.get("test_status") if issue_type != "Epic" else epic_test_status.get(key, "not-run")

    issues_db[key] = {
        "key": key,
        "title": secs["title"],
        "type": issue_type,
        "epic": epic,
        "branch": branch,
        "base": base,
        "severity": severity,
        "status": status,
        "pr": real_status.get("pr"),
        "test_status": issue_test_status or "not-run",
        "backstory_md": secs["backstory"],
        "description_md": secs["description"],
        "acceptance_criteria_md": secs["acceptance_criteria"],
        "notes_md": secs["notes"],
        "raw_md": content,
        "test_suite_md": "",
        "discovery_md": "",
        "file_path": path,
        "rel_path": rel_path
    }

# Merge sub-documents into main issues
for base_key, doc_type, doc_content in sub_docs:
    if base_key in issues_db:
        if doc_type == "test_suite":
            issues_db[base_key]["test_suite_md"] = doc_content
        elif doc_type == "discovery":
            issues_db[base_key]["discovery_md"] = doc_content
    else:
        found = False
        for k in issues_db:
            if k == base_key:
                if doc_type == "test_suite":
                    issues_db[k]["test_suite_md"] = doc_content
                elif doc_type == "discovery":
                    issues_db[k]["discovery_md"] = doc_content
                found = True
                break
        if not found:
            pass

# Add epics from status.yml if any are missing, and sync statuses
epics_list = []
if status_data and "epics" in status_data:
    for ep in status_data["epics"]:
        ep_id = ep["id"]
        ep_name = ep["name"]
        epics_list.append({
            "id": ep_id,
            "name": ep_name,
            "blocked_by": ep.get("blocked_by", []),
            "status": ep.get("status", "not-started"),
            "test_suite_status": epic_test_status.get(ep_id, "not-run")
        })

        if ep_id not in issues_db:
            issues_db[ep_id] = {
                "key": ep_id,
                "title": f"EPIC: {ep_name}",
                "type": "Epic",
                "epic": "",
                "branch": "",
                "base": "",
                "severity": "Medium",
                "status": "todo",
                "pr": None,
                "test_status": epic_test_status.get(ep_id, "not-run"),
                "backstory_md": "",
                "description_md": f"Epic: {ep_name}. Status from registry: {ep.get('status')}",
                "acceptance_criteria_md": "",
                "notes_md": "",
                "raw_md": f"# {ep_id}\n\nEpic: {ep_name}",
                "test_suite_md": "",
                "discovery_md": "",
                "file_path": "",
                "rel_path": ""
            }

# Save DB as JSON in the HTML
db_json = json.dumps(list(issues_db.values()), indent=2)
epics_json = json.dumps(epics_list, indent=2)
active_epic = status_data.get("active_epic", "COGNIREPO-100")

# Write JIRA.html
html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CogniRepo Tracker</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%230052CC'%3E%3Cpath d='M11.53 2C6.81 2 3 5.81 3 10.53V20c0 1.1.9 2 2 2h9.47c4.72 0 8.53-3.81 8.53-8.53V4c0-1.1-.9-2-2-2h-9.47z'/%3E%3C/svg%3E">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-app: #f4f5f7;
            --bg-sidebar: #f8f9fa;
            --bg-sidebar-hover: #ebecf0;
            --bg-card: #ffffff;
            --bg-column: #eef0f3;
            --text-main: #172b4d;
            --text-muted: #5e6c84;
            --border-color: #dfe1e6;
            --primary-color: #0052cc;
            --primary-hover: #0747a6;
            --primary-bg: #deebff;
            --epic-bg: #eae6ff;
            --epic-text: #403294;
            --story-bg: #e3fcef;
            --story-text: #006644;
            --bug-bg: #ffebe6;
            --bug-text: #bf2600;
            --test-bg: #fff0b3;
            --test-text: #172b4d;
            --disc-bg: #deebff;
            --disc-text: #0747a6;
            --shadow-card: 0 1px 2px 0 rgba(9, 30, 66, 0.15), 0 0 1px 0 rgba(9, 30, 66, 0.31);
            --header-bg: #ffffff;
            --header-text: #172b4d;
            --header-border: #dfe1e6;
            --transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            --font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-display: 'Outfit', sans-serif;
        }

        body.dark-mode {
            --bg-app: #0f1214;
            --bg-sidebar: #161a1d;
            --bg-sidebar-hover: #22272b;
            --bg-card: #22272b;
            --bg-column: #161a1d;
            --text-main: #c7d1db;
            --text-muted: #9fadbc;
            --border-color: #30363d;
            --primary-color: #579dff;
            --primary-hover: #85b8ff;
            --primary-bg: #1c2b41;
            --epic-bg: #2d1f4d;
            --epic-text: #c0b6f2;
            --story-bg: #143c2c;
            --story-text: #7ee2b8;
            --bug-bg: #441c14;
            --bug-text: #ff8f73;
            --test-bg: #4a3c10;
            --test-text: #ffe066;
            --disc-bg: #1c2b41;
            --disc-text: #85b8ff;
            --shadow-card: 0 1px 1px 0 rgba(0, 0, 0, 0.5), 0 0 1px 0 rgba(255, 255, 255, 0.1);
            --header-bg: #161a1d;
            --header-text: #c7d1db;
            --header-border: #30363d;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: var(--font-family);
            background-color: var(--bg-app);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: var(--transition);
        }

        header {
            height: 56px;
            background-color: var(--header-bg);
            color: var(--header-text);
            border-bottom: 1px solid var(--header-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            z-index: 100;
            transition: var(--transition);
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 20px;
        }

        .logo-container {
            display: flex;
            align-items: center;
            gap: 8px;
            font-family: var(--font-display);
            font-weight: 700;
            font-size: 19px;
            color: var(--primary-color);
            cursor: pointer;
        }

        .logo-container svg {
            width: 28px;
            height: 28px;
        }

        .nav-links {
            display: flex;
            gap: 16px;
        }

        .nav-link {
            color: var(--text-main);
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            padding: 6px 12px;
            border-radius: 4px;
            transition: var(--transition);
            cursor: pointer;
        }

        .nav-link:hover {
            background-color: var(--bg-sidebar-hover);
        }

        .btn-create {
            background-color: var(--primary-color);
            color: #ffffff;
            border: none;
            padding: 6px 14px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: var(--transition);
            font-family: var(--font-family);
        }

        .btn-create:hover {
            background-color: var(--primary-hover);
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .search-container {
            position: relative;
            width: 250px;
        }

        .search-container input {
            width: 100%;
            background-color: var(--bg-app);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 6px 10px 6px 32px;
            font-size: 14px;
            color: var(--text-main);
            transition: var(--transition);
            font-family: var(--font-family);
        }

        .search-container input:focus {
            outline: none;
            border-color: var(--primary-color);
            background-color: var(--bg-card);
            box-shadow: 0 0 0 2px var(--primary-bg);
        }

        .search-icon {
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            width: 16px;
            height: 16px;
            fill: var(--text-muted);
            pointer-events: none;
        }

        .theme-toggle {
            background: none;
            border: none;
            cursor: pointer;
            padding: 6px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: var(--transition);
        }

        .theme-toggle:hover {
            background-color: var(--bg-sidebar-hover);
        }

        .theme-toggle svg {
            width: 20px;
            height: 20px;
            fill: var(--text-main);
        }

        .user-avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background-color: #FF5630;
            color: white;
            font-weight: 700;
            font-size: 13px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 0 0 2px var(--bg-card);
        }

        .app-body {
            display: flex;
            flex: 1;
            overflow: hidden;
            position: relative;
        }

        aside {
            width: 240px;
            background-color: var(--bg-sidebar);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            padding: 16px 8px;
            transition: width 0.2s ease, var(--transition);
            overflow-y: auto;
            flex-shrink: 0;
        }

        aside.collapsed {
            width: 20px;
            padding: 16px 0;
            overflow: hidden;
        }

        .sidebar-header {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 0 12px 16px 12px;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 16px;
        }

        .project-icon {
            width: 36px;
            height: 36px;
            border-radius: 4px;
            background-color: var(--primary-color);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 18px;
        }

        .project-details {
            display: flex;
            flex-direction: column;
        }

        .project-name {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-main);
        }

        .project-type {
            font-size: 11px;
            color: var(--text-muted);
        }

        .sidebar-menu {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .menu-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 12px;
            border-radius: 4px;
            color: var(--text-main);
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: var(--transition);
        }

        .menu-item:hover {
            background-color: var(--bg-sidebar-hover);
        }

        .menu-item.active {
            background-color: var(--primary-bg);
            color: var(--primary-color);
            font-weight: 600;
        }

        .menu-item svg {
            width: 18px;
            height: 18px;
            fill: currentColor;
        }

        .sidebar-toggle-btn {
            position: absolute;
            left: 230px;
            top: 76px;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 10;
            box-shadow: var(--shadow-card);
            transition: var(--transition);
        }

        body.sidebar-collapsed .sidebar-toggle-btn {
            left: 10px;
        }

        .sidebar-toggle-btn svg {
            width: 14px;
            height: 14px;
            fill: var(--text-main);
            transition: transform 0.2s;
        }

        body.sidebar-collapsed .sidebar-toggle-btn svg {
            transform: rotate(180deg);
        }

        main {
            flex: 1;
            padding: 24px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            transition: var(--transition);
        }

        .view-header {
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }

        .breadcrumbs {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 6px;
        }

        .view-title {
            font-family: var(--font-display);
            font-size: 24px;
            font-weight: 700;
            color: var(--text-main);
        }

        .filter-bar {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .filter-select, .filter-btn {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-main);
            cursor: pointer;
            outline: none;
            font-family: var(--font-family);
            transition: var(--transition);
        }

        .filter-select:focus, .filter-btn:hover {
            background-color: var(--bg-sidebar-hover);
            border-color: var(--text-muted);
        }

        .filter-btn.active {
            background-color: var(--primary-bg);
            border-color: var(--primary-color);
            color: var(--primary-color);
        }

        .board-container {
            display: flex;
            gap: 16px;
            flex: 1;
            overflow-x: auto;
            align-items: flex-start;
            min-height: 400px;
        }

        .board-column {
            flex: 1;
            min-width: 280px;
            max-width: 400px;
            background-color: var(--bg-column);
            border-radius: 6px;
            padding: 12px 8px;
            display: flex;
            flex-direction: column;
            max-height: 100%;
            border: 1px solid transparent;
            transition: var(--transition);
        }

        .board-column.drag-over {
            background-color: var(--bg-sidebar-hover);
            border: 1px dashed var(--primary-color);
        }

        .column-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0 8px 12px 8px;
        }

        .column-title {
            font-size: 13px;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .column-count {
            background-color: var(--border-color);
            color: var(--text-main);
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 10px;
        }

        .cards-container {
            display: flex;
            flex-direction: column;
            gap: 8px;
            overflow-y: auto;
            flex: 1;
            padding: 4px;
            min-height: 250px;
        }

        .card {
            background-color: var(--bg-card);
            border-radius: 4px;
            padding: 12px;
            box-shadow: var(--shadow-card);
            cursor: pointer;
            border: 1px solid var(--border-color);
            transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
            user-select: none;
        }

        .card:hover {
            box-shadow: 0 4px 8px -2px rgba(9, 30, 66, 0.25);
            border-color: var(--text-muted);
        }

        .card.dragging {
            opacity: 0.4;
            transform: scale(0.98);
        }

        .card-title {
            font-size: 14px;
            font-weight: 500;
            line-height: 1.4;
            color: var(--text-main);
            margin-bottom: 12px;
            word-wrap: break-word;
        }

        .card-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 8px;
        }

        .card-meta-left {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .badge {
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            text-transform: uppercase;
        }

        .badge-epic {
            background-color: var(--epic-bg);
            color: var(--epic-text);
            font-size: 10px;
            max-width: 100px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .badge-type {
            background-color: var(--story-bg);
            color: var(--story-text);
        }

        .badge-type.story {
            background-color: var(--story-bg);
            color: var(--story-text);
        }

        .badge-type.bug {
            background-color: var(--bug-bg);
            color: var(--bug-text);
        }

        .badge-type.epic {
            background-color: var(--epic-bg);
            color: var(--epic-text);
        }

        .badge-type.test {
            background-color: var(--test-bg);
            color: var(--test-text);
        }

        .card-key {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
        }

        .priority-icon {
            width: 16px;
            height: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .backlog-view {
            display: flex;
            gap: 20px;
            flex: 1;
            overflow: hidden;
        }

        .epic-panel {
            width: 250px;
            border: 1px solid var(--border-color);
            background-color: var(--bg-card);
            border-radius: 6px;
            padding: 16px 12px;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            flex-shrink: 0;
        }

        .panel-title {
            font-size: 14px;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 12px;
            padding-bottom: 6px;
            border-bottom: 1px solid var(--border-color);
        }

        .epic-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .epic-item {
            padding: 8px 10px;
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
            transition: var(--transition);
            border: 1px solid transparent;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .epic-item:hover {
            background-color: var(--bg-sidebar-hover);
        }

        .epic-item.active {
            background-color: var(--epic-bg);
            color: var(--epic-text);
            border-color: var(--epic-text);
        }

        .epic-item-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 6px;
        }

        .epic-item-name {
            font-weight: 600;
        }

        .epic-item-open-btn {
            opacity: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 22px;
            height: 22px;
            border-radius: 4px;
            flex-shrink: 0;
            transition: var(--transition);
            cursor: pointer;
        }

        .epic-item:hover .epic-item-open-btn {
            opacity: 1;
        }

        .epic-item-open-btn:hover {
            background-color: var(--bg-card);
        }

        .epic-item-open-btn svg {
            width: 14px;
            height: 14px;
            fill: var(--text-muted);
        }

        .epic-item-progress {
            height: 4px;
            background-color: var(--border-color);
            border-radius: 2px;
            overflow: hidden;
            width: 100%;
            margin-top: 4px;
        }

        .epic-item-progress-bar {
            height: 100%;
            background-color: var(--primary-color);
            width: 0%;
            transition: width 0.3s;
        }

        .backlog-list-container {
            flex: 1;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            background-color: var(--bg-card);
            padding: 16px;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }

        .backlog-section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            font-weight: 600;
            font-size: 15px;
        }

        .backlog-items {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .backlog-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            border: 1px solid var(--border-color);
            border-left: 3px solid var(--border-color);
            border-radius: 4px;
            background-color: var(--bg-app);
            cursor: pointer;
            transition: var(--transition);
        }

        .backlog-item:hover {
            background-color: var(--bg-sidebar-hover);
            border-top-color: var(--text-muted);
            border-right-color: var(--text-muted);
            border-bottom-color: var(--text-muted);
            transform: translateX(2px);
        }

        .backlog-item.story { border-left-color: var(--story-text); }
        .backlog-item.bug { border-left-color: var(--bug-text); }
        .backlog-item.epic { border-left-color: var(--epic-text); }

        .backlog-item-left {
            display: flex;
            align-items: center;
            gap: 12px;
            flex: 1;
            min-width: 0;
        }

        .backlog-item-title {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-main);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .backlog-item-right {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .backlog-status {
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            text-transform: uppercase;
        }

        .backlog-status.todo {
            background-color: var(--bg-sidebar-hover);
            color: var(--text-muted);
        }

        .backlog-status.in-progress {
            background-color: var(--primary-bg);
            color: var(--primary-color);
        }

        .backlog-status.done {
            background-color: var(--story-bg);
            color: var(--story-text);
        }

        .roadmap-container {
            border: 1px solid var(--border-color);
            border-radius: 6px;
            background-color: var(--bg-card);
            padding: 20px;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            flex: 1;
        }

        .roadmap-gantt {
            display: flex;
            flex-direction: column;
            gap: 16px;
            margin-top: 20px;
            position: relative;
        }

        .roadmap-header-row {
            display: flex;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 8px;
            font-weight: 700;
            font-size: 14px;
            color: var(--text-muted);
        }

        .roadmap-label-col {
            width: 250px;
            flex-shrink: 0;
        }

        .roadmap-timeline-col {
            flex: 1;
            display: flex;
            justify-content: space-around;
        }

        .roadmap-row {
            display: flex;
            align-items: center;
            padding: 8px 0;
            position: relative;
        }

        .roadmap-epic-label {
            width: 250px;
            flex-shrink: 0;
            display: flex;
            flex-direction: column;
            padding-right: 16px;
            cursor: pointer;
        }

        .roadmap-epic-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-main);
        }

        .roadmap-epic-key {
            font-size: 11px;
            color: var(--text-muted);
            font-weight: 500;
        }

        .roadmap-bar-container {
            flex: 1;
            position: relative;
            height: 36px;
            background-color: var(--bg-app);
            border-radius: 4px;
            overflow: hidden;
        }

        .roadmap-bar {
            position: absolute;
            height: 24px;
            top: 6px;
            border-radius: 12px;
            background-color: var(--primary-color);
            color: white;
            font-size: 11px;
            font-weight: 600;
            display: flex;
            align-items: center;
            padding: 0 12px;
            box-shadow: var(--shadow-card);
            transition: var(--transition);
            cursor: pointer;
        }

        .roadmap-bar.epic-100 { left: 5%; width: 25%; background-color: #0052cc; }
        .roadmap-bar.epic-200 { left: 30%; width: 20%; background-color: #5243aa; }
        .roadmap-bar.epic-300 { left: 50%; width: 20%; background-color: #00875a; }
        .roadmap-bar.epic-400 { left: 50%; width: 25%; background-color: #de350b; }
        .roadmap-bar.epic-500 { left: 55%; width: 20%; background-color: #00b8d9; }
        .roadmap-bar.epic-600 { left: 75%; width: 20%; background-color: #ff9900; }

        .roadmap-bar-progress {
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            background-color: rgba(255, 255, 255, 0.2);
            border-radius: 12px 0 0 12px;
        }

        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            flex: 1;
        }

        .dashboard-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            box-shadow: var(--shadow-card);
        }

        .dashboard-card-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 16px;
            font-family: var(--font-display);
        }

        .chart-placeholder {
            display: flex;
            align-items: center;
            justify-content: center;
            flex: 1;
            min-height: 200px;
        }

        .detail-pane {
            position: fixed;
            top: 56px;
            right: -600px;
            width: 600px;
            min-width: 420px;
            max-width: 96vw;
            bottom: 0;
            background-color: var(--bg-card);
            border-left: 1px solid var(--border-color);
            z-index: 90;
            box-shadow: -4px 0 15px rgba(0, 0, 0, 0.15);
            display: flex;
            flex-direction: column;
            transition: right 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .detail-pane.open {
            right: 0;
        }

        .detail-pane.resizing {
            transition: none;
        }

        .detail-pane.fullscreen {
            width: 100vw !important;
            min-width: 0;
            max-width: 100vw;
            border-left: none;
        }

        .detail-resize-handle {
            position: absolute;
            left: -3px;
            top: 0;
            bottom: 0;
            width: 7px;
            cursor: ew-resize;
            z-index: 5;
            background-color: transparent;
            transition: background-color 0.15s;
        }

        .detail-resize-handle:hover,
        .detail-resize-handle.active {
            background-color: var(--primary-color);
        }

        .detail-pane.fullscreen .detail-resize-handle {
            display: none;
        }

        #btn-fullscreen-detail.active svg {
            fill: var(--primary-color);
        }

        .detail-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
        }

        .detail-header-left {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .btn-close-detail {
            background: none;
            border: none;
            cursor: pointer;
            padding: 6px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: var(--transition);
        }

        .btn-close-detail:hover {
            background-color: var(--bg-sidebar-hover);
        }

        .btn-close-detail svg {
            width: 18px;
            height: 18px;
            fill: var(--text-main);
        }

        .detail-body-container {
            flex: 1;
            display: flex;
            overflow: hidden;
        }

        .detail-main-content {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
            border-right: 1px solid var(--border-color);
        }

        .detail-sidebar {
            width: 220px;
            padding: 20px 16px;
            overflow-y: auto;
            background-color: var(--bg-sidebar);
            display: flex;
            flex-direction: column;
            gap: 16px;
            flex-shrink: 0;
        }

        .detail-title {
            font-size: 20px;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 16px;
            outline: none;
            padding: 4px;
            border-radius: 4px;
            border: 1px solid transparent;
            font-family: var(--font-display);
        }

        .detail-title:focus {
            border-color: var(--primary-color);
            background-color: var(--bg-app);
        }

        .detail-tabs {
            display: flex;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 16px;
        }

        .detail-tab {
            padding: 8px 16px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            font-size: 13px;
            font-weight: 600;
            color: var(--text-muted);
            transition: var(--transition);
        }

        .detail-tab:hover {
            color: var(--text-main);
        }

        .detail-tab.active {
            color: var(--primary-color);
            border-bottom-color: var(--primary-color);
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        .markdown-rendered {
            font-size: 14px;
            line-height: 1.6;
            color: var(--text-main);
        }

        .markdown-rendered h1, .markdown-rendered h2, .markdown-rendered h3 {
            margin-top: 18px;
            margin-bottom: 8px;
            color: var(--text-main);
            font-family: var(--font-display);
            font-weight: 600;
        }

        .markdown-rendered h1 { font-size: 18px; border-bottom: 1px solid var(--border-color); padding-bottom: 4px; }
        .markdown-rendered h2 { font-size: 15px; }
        .markdown-rendered h3 { font-size: 13px; }

        .markdown-rendered p {
            margin-bottom: 12px;
        }

        .markdown-rendered ul, .markdown-rendered ol {
            margin-bottom: 12px;
            padding-left: 20px;
        }

        .markdown-rendered li {
            margin-bottom: 4px;
        }

        .markdown-rendered code {
            background-color: var(--bg-app);
            padding: 2px 4px;
            border-radius: 3px;
            font-family: monospace;
            font-size: 12px;
        }

        .markdown-rendered pre {
            background-color: var(--bg-app);
            padding: 12px;
            border-radius: 4px;
            overflow-x: auto;
            margin-bottom: 12px;
            border: 1px solid var(--border-color);
        }

        .markdown-rendered pre code {
            padding: 0;
            background-color: transparent;
            font-size: 12px;
        }

        .markdown-rendered a {
            color: var(--primary-color);
            text-decoration: none;
        }

        .markdown-rendered a:hover {
            text-decoration: underline;
        }

        .markdown-section-title {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 20px;
            margin-bottom: 8px;
        }

        .markdown-section-title:first-child {
            margin-top: 0;
        }

        .markdown-section-title::before {
            content: '';
            width: 3px;
            height: 12px;
            border-radius: 2px;
            background-color: var(--primary-color);
            display: inline-block;
        }

        .markdown-section-block {
            background-color: var(--bg-app);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 14px 16px;
            margin-bottom: 20px;
            transition: var(--transition);
        }

        .markdown-section-block:hover {
            border-color: var(--primary-color);
        }

        .markdown-section-block .markdown-rendered:last-child {
            margin-bottom: 0;
        }

        .markdown-section-block.empty {
            color: var(--text-muted);
            font-style: italic;
            font-size: 13px;
        }

        .test-case-item {
            display: flex;
            align-items: flex-start;
            gap: 10px;
            padding: 12px 14px;
            border: 1px solid var(--border-color);
            border-left: 3px solid var(--border-color);
            border-radius: 6px;
            background-color: var(--bg-card);
            margin-bottom: 10px;
            transition: var(--transition);
        }

        .test-case-item:hover {
            box-shadow: var(--shadow-card);
        }

        .test-case-item.passed {
            border-left-color: var(--story-text);
        }

        .test-case-checkbox {
            margin-top: 3px;
            cursor: pointer;
            width: 16px;
            height: 16px;
            flex-shrink: 0;
        }

        .test-case-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 6px;
        }

        .test-case-status-badge {
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            padding: 2px 8px;
            border-radius: 10px;
            background-color: var(--bg-column);
            color: var(--text-muted);
            flex-shrink: 0;
        }

        .test-case-status-badge.passed {
            background-color: var(--story-bg);
            color: var(--story-text);
        }

        .test-case-meta {
            display: block;
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 4px;
            line-height: 1.5;
        }

        .test-case-meta code {
            background-color: var(--bg-app);
            border: 1px solid var(--border-color);
            padding: 1px 5px;
            border-radius: 3px;
            font-size: 11px;
        }

        .test-case-expected {
            display: block;
            font-size: 12px;
            color: var(--text-main);
            background-color: var(--bg-app);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 8px 10px;
            margin-top: 6px;
            line-height: 1.5;
        }

        .test-case-details {
            display: flex;
            flex-direction: column;
            font-size: 13px;
            flex: 1;
            min-width: 0;
        }

        .sidebar-field {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .sidebar-field-label {
            font-size: 11px;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .sidebar-field-value {
            font-size: 13px;
            font-weight: 600;
        }

        .detail-status-select {
            width: 100%;
            padding: 8px;
            border-radius: 4px;
            border: 1px solid var(--border-color);
            background-color: var(--bg-card);
            color: var(--text-main);
            font-family: var(--font-family);
            font-weight: 600;
            cursor: pointer;
            outline: none;
        }

        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(9, 30, 66, 0.55);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s ease;
        }

        .modal-overlay.open {
            opacity: 1;
            pointer-events: auto;
        }

        .modal-container {
            width: 500px;
            background-color: var(--bg-card);
            border-radius: 6px;
            box-shadow: 0 8px 16px -4px rgba(9, 30, 66, 0.25);
            display: flex;
            flex-direction: column;
            border: 1px solid var(--border-color);
            overflow: hidden;
            transform: scale(0.95);
            transition: transform 0.2s ease;
        }

        .modal-overlay.open .modal-container {
            transform: scale(1);
        }

        .modal-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-title {
            font-size: 18px;
            font-weight: 700;
            font-family: var(--font-display);
        }

        .modal-body {
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            max-height: 450px;
            overflow-y: auto;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        .form-group label {
            font-size: 12px;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 8px;
            border-radius: 4px;
            border: 1px solid var(--border-color);
            background-color: var(--bg-card);
            color: var(--text-main);
            font-family: var(--font-family);
            font-size: 14px;
            outline: none;
        }

        .form-group textarea {
            resize: vertical;
            height: 100px;
        }

        .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
            border-color: var(--primary-color);
            box-shadow: 0 0 0 2px var(--primary-bg);
        }

        .modal-footer {
            padding: 16px 20px;
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: flex-end;
            gap: 12px;
        }

        .btn-cancel {
            background: none;
            border: none;
            color: var(--text-muted);
            font-weight: 600;
            cursor: pointer;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 14px;
        }

        .btn-cancel:hover {
            background-color: var(--bg-sidebar-hover);
            color: var(--text-main);
        }

        .toast-container {
            position: fixed;
            bottom: 20px;
            left: 20px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            z-index: 10000;
        }

        .toast {
            background-color: var(--text-main);
            color: var(--bg-card);
            padding: 12px 20px;
            border-radius: 4px;
            font-size: 13px;
            font-weight: 600;
            box-shadow: var(--shadow-card);
            display: flex;
            align-items: center;
            gap: 10px;
            animation: slideIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        @keyframes slideIn {
            from { transform: translateY(100px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }

        .priority-high { fill: #FF5630; }
        .priority-med { fill: #FFAB00; }
        .priority-low { fill: #36B37E; }

        .gantt-svg {
            width: 100%;
            height: 250px;
            background-color: var(--bg-app);
            border-radius: 4px;
        }

        .dark-mode code, .dark-mode pre {
            background-color: #1e1e1e;
        }
    </style>
</head>
<body>

    <header>
        <div class="header-left">
            <div class="logo-container" onclick="switchView('board')">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M11.53 2C6.81 2 3 5.81 3 10.53V20c0 1.1.9 2 2 2h9.47c4.72 0 8.53-3.81 8.53-8.53V4c0-1.1-.9-2-2-2h-9.47zM9.47 18H7v-4h2.47v4zm4-3H11V9h2.47v6zm4-3h-2.47V6H17.5v6z"/>
                </svg>
                <span>CogniRepo Tracker</span>
            </div>
            <div class="nav-links">
                <a class="nav-link" onclick="switchView('board')">Projects</a>
                <a class="nav-link" onclick="switchView('dashboard')">Dashboards</a>
                <a class="nav-link" onclick="switchView('roadmap')">Roadmaps</a>
            </div>
            <button class="btn-create" onclick="openCreateModal()">Create</button>
        </div>
        <div class="header-right">
            <div class="search-container">
                <svg class="search-icon" viewBox="0 0 24 24">
                    <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
                </svg>
                <input type="text" id="global-search" placeholder="Search issues..." oninput="handleSearch(this.value)">
            </div>
            <button class="theme-toggle" onclick="toggleTheme()" title="Toggle Theme">
                <svg viewBox="0 0 24 24" id="theme-icon">
                    <path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1zM5.99 4.58c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37c-.39-.39-1.03-.39-1.41 0s-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0s.39-1.03 0-1.41l-1.06-1.06zm1.06-10.96c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06zM7.05 18.01c.39-.39.39-1.03 0-1.41s-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06z"/>
                </svg>
            </button>
            <div class="user-avatar" title="Ashlesh T">AT</div>
        </div>
    </header>

    <div class="app-body">
        <button class="sidebar-toggle-btn" onclick="toggleSidebar()">
            <svg viewBox="0 0 24 24">
                <path d="M15.41 16.59L10.83 12l4.58-4.59L14 6l-6 6 6 6 1.41-1.41z"/>
            </svg>
        </button>

        <aside id="sidebar">
            <div class="sidebar-header">
                <div class="project-icon">C</div>
                <div class="project-details">
                    <span class="project-name">cognirepo</span>
                    <span class="project-type">Software project</span>
                </div>
            </div>
            <ul class="sidebar-menu">
                <li>
                    <a class="menu-item" id="menu-board" onclick="switchView('board')">
                        <svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4-4h-2V7h2v6zm4 2h-2v-4h2v4z"/></svg>
                        <span>Tasks</span>
                    </a>
                </li>
                <li>
                    <a class="menu-item active" id="menu-backlog" onclick="switchView('backlog')">
                        <svg viewBox="0 0 24 24"><path d="M19 15v4H5v-4h14m1-2H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zM19 5v4H5v-4h14m1-2H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1z"/></svg>
                        <span>Backlog</span>
                    </a>
                </li>
                <li>
                    <a class="menu-item" id="menu-roadmap" onclick="switchView('roadmap')">
                        <svg viewBox="0 0 24 24"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z"/></svg>
                        <span>Roadmap</span>
                    </a>
                </li>
                <li>
                    <a class="menu-item" id="menu-dashboard" onclick="switchView('dashboard')">
                        <svg viewBox="0 0 24 24"><path d="M19 5v14H5V5h14m0-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-4.86 8.86l-3 3-2-2L6 16.14 7.14 17.3l2-2 2 2 4.14-4.14-1.14-1.3z"/></svg>
                        <span>Dashboard</span>
                    </a>
                </li>
            </ul>
        </aside>

        <main>
            <div class="view-header">
                <div>
                    <div class="breadcrumbs" id="breadcrumbs">Projects / cognirepo / Backlog</div>
                    <h1 class="view-title" id="view-title">Backlog</h1>
                </div>
            </div>

            <div class="filter-bar" id="filter-bar">
                <input type="text" id="board-search" placeholder="Search this board..." oninput="handleSearch(this.value)" class="filter-select" style="width: 180px;">
                <select id="epic-filter" class="filter-select" onchange="filterIssues()">
                    <option value="">All Epics</option>
                </select>
                <select id="type-filter" class="filter-select" onchange="filterIssues()">
                    <option value="">All Types</option>
                    <option value="Story">Stories</option>
                    <option value="Bug">Bugs</option>
                    <option value="Epic">Epics</option>
                </select>
                <select id="severity-filter" class="filter-select" onchange="filterIssues()">
                    <option value="">All Priorities</option>
                    <option value="P1">P1 (Critical)</option>
                    <option value="P2">P2 (High)</option>
                    <option value="P3">P3 (Medium/Low)</option>
                </select>
                <button class="filter-btn" onclick="clearFilters()">Clear Filters</button>
            </div>

            <div class="board-container view-panel" id="view-board" style="display: none;">
                <div class="board-column" id="col-todo" ondragover="allowDrop(event)" ondragenter="dragEnter(event)" ondragleave="dragLeave(event)" ondrop="handleDrop(event, 'todo')">
                    <div class="column-header">
                        <span class="column-title">To Do <span class="column-count" id="count-todo">0</span></span>
                    </div>
                    <div class="cards-container" id="cards-todo"></div>
                </div>

                <div class="board-column" id="col-in-progress" ondragover="allowDrop(event)" ondragenter="dragEnter(event)" ondragleave="dragLeave(event)" ondrop="handleDrop(event, 'in-progress')">
                    <div class="column-header">
                        <span class="column-title">In Progress <span class="column-count" id="count-in-progress">0</span></span>
                    </div>
                    <div class="cards-container" id="cards-in-progress"></div>
                </div>

                <div class="board-column" id="col-done" ondragover="allowDrop(event)" ondragenter="dragEnter(event)" ondragleave="dragLeave(event)" ondrop="handleDrop(event, 'done')">
                    <div class="column-header">
                        <span class="column-title">Done <span class="column-count" id="count-done">0</span></span>
                    </div>
                    <div class="cards-container" id="cards-done"></div>
                </div>
            </div>

            <div class="backlog-view view-panel" id="view-backlog">
                <div class="epic-panel">
                    <div class="panel-title">Epics</div>
                    <ul class="epic-list" id="backlog-epic-list">
                    </ul>
                </div>
                <div class="backlog-list-container">
                    <div class="backlog-section-header">
                        <span>Backlog Issues</span>
                        <span id="backlog-issue-count" style="font-size: 13px; color: var(--text-muted);">0 issues</span>
                    </div>
                    <div class="backlog-items" id="backlog-items-list">
                    </div>
                </div>
            </div>

            <div class="roadmap-container view-panel" id="view-roadmap" style="display: none;">
                <div style="margin-bottom: 20px; font-size: 14px; color: var(--text-muted);">
                    Timeline overview of Epics, their progress, and horizontal sequencing.
                </div>
                <div class="roadmap-gantt" id="roadmap-gantt-chart">
                </div>
            </div>

            <div class="dashboard-grid view-panel" id="view-dashboard" style="display: none;">
                <div class="dashboard-card">
                    <div class="dashboard-card-title">Overall Completion</div>
                    <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; flex:1; gap:16px;">
                        <svg width="150" height="150" viewBox="0 0 36 36" style="transform: rotate(-90deg);">
                            <circle cx="18" cy="18" r="15.915" fill="none" stroke="var(--border-color)" stroke-width="3"></circle>
                            <circle id="dash-progress-ring" cx="18" cy="18" r="15.915" fill="none" stroke="var(--primary-color)" stroke-width="3" stroke-dasharray="100 100" stroke-dashoffset="100" style="transition: stroke-dashoffset 0.5s ease-out;"></circle>
                        </svg>
                        <div style="text-align:center;">
                            <h2 id="dash-percentage" style="font-family: var(--font-display); font-size: 32px; font-weight:700;">0%</h2>
                            <p style="font-size: 13px; color:var(--text-muted);" id="dash-progress-counts">0 of 0 issues complete</p>
                        </div>
                    </div>
                </div>

                <div class="dashboard-card">
                    <div class="dashboard-card-title">Issues by Status</div>
                    <div class="chart-placeholder" id="chart-status-bar">
                    </div>
                </div>

                <div class="dashboard-card" style="grid-column: span 2;">
                    <div class="dashboard-card-title">Epic Progress & Completion Rates</div>
                    <div style="display:flex; flex-direction:column; gap:16px; flex:1;" id="dash-epic-breakdown">
                    </div>
                </div>
            </div>
        </main>

        <div class="detail-pane" id="detail-pane">
            <div class="detail-resize-handle" id="detail-resize-handle" title="Drag to resize"></div>
            <div class="detail-header">
                <div class="detail-header-left">
                    <span class="badge badge-type" id="detail-type-badge">Story</span>
                    <span class="card-key" id="detail-issue-key">COGNIREPO-000</span>
                </div>
                <div style="display:flex; align-items:center;">
                    <button class="btn-close-detail" id="btn-fullscreen-detail" onclick="toggleDetailFullscreen()" title="Toggle full screen">
                        <svg viewBox="0 0 24 24" id="detail-fullscreen-icon"><path id="detail-fullscreen-path" d="M7 14H5v5h5v-2H7v-3zM5 10h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>
                    </button>
                    <button class="btn-close-detail" onclick="closeDetailPane()">
                        <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                    </button>
                </div>
            </div>
            <div class="detail-body-container">
                <div class="detail-main-content">
                    <div class="detail-title" contenteditable="true" id="detail-title-input" onblur="handleTitleEdit(this.innerText)">Issue Title</div>
                    
                    <div class="detail-tabs">
                        <div class="detail-tab active" id="tab-details-btn" onclick="switchDetailTab('details')">Details</div>
                        <div class="detail-tab" id="tab-discovery-btn" onclick="switchDetailTab('discovery')">Discovery</div>
                        <div class="detail-tab" id="tab-test-suite-btn" onclick="switchDetailTab('test-suite')">Test Suite</div>
                        <div class="detail-tab" id="tab-raw-btn" onclick="switchDetailTab('raw')">Raw Markdown</div>
                    </div>

                    <div class="tab-content active" id="tab-content-details">
                        <div class="markdown-section-title">Backstory</div>
                        <div class="markdown-section-block"><div class="markdown-rendered" id="rendered-backstory">No backstory provided.</div></div>

                        <div class="markdown-section-title">Description</div>
                        <div class="markdown-section-block"><div class="markdown-rendered" id="rendered-description">No description provided.</div></div>

                        <div class="markdown-section-title">Acceptance Criteria</div>
                        <div class="markdown-section-block"><div class="markdown-rendered" id="rendered-criteria">No criteria provided.</div></div>

                        <div class="markdown-section-title">Notes / Risks</div>
                        <div class="markdown-section-block"><div class="markdown-rendered" id="rendered-notes">No notes provided.</div></div>
                    </div>

                    <div class="tab-content" id="tab-content-discovery">
                        <div class="markdown-section-block"><div class="markdown-rendered" id="rendered-discovery">No discovery document associated.</div></div>
                    </div>

                    <div class="tab-content" id="tab-content-test-suite">
                        <div class="markdown-rendered" id="rendered-test-suite">No test suite associated.</div>
                    </div>

                    <div class="tab-content" id="tab-content-raw">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                            <span style="font-size:12px; color:var(--text-muted);">Raw markdown file content</span>
                            <button class="filter-btn" style="padding:4px 8px; font-size:11px;" onclick="copyRawMarkdown()">Copy to Clipboard</button>
                        </div>
                        <pre style="white-space: pre-wrap; word-break: break-all; max-height:400px; overflow-y:auto; padding:12px; border-radius:4px; background-color:var(--bg-app); border:1px solid var(--border-color); font-family:monospace; font-size:12px;" id="raw-markdown-text"></pre>
                    </div>
                </div>

                <div class="detail-sidebar">
                    <div class="sidebar-field">
                        <span class="sidebar-field-label">Status</span>
                        <select class="detail-status-select" id="detail-status-select" onchange="handleStatusChange(this.value)">
                            <option value="todo">To Do</option>
                            <option value="in-progress">In Progress</option>
                            <option value="done">Done</option>
                        </select>
                    </div>

                    <div class="sidebar-field">
                        <span class="sidebar-field-label">Epic</span>
                        <select class="detail-status-select" id="detail-epic-select" onchange="handleEpicChange(this.value)">
                            <option value="">No Epic</option>
                        </select>
                    </div>

                    <div class="sidebar-field" id="detail-severity-field">
                        <span class="sidebar-field-label">Priority / Severity</span>
                        <select class="detail-status-select" id="detail-severity-select" onchange="handleSeverityChange(this.value)">
                            <option value="P1">P1 (Critical)</option>
                            <option value="P2">P2 (High)</option>
                            <option value="P3">P3 (Medium/Low)</option>
                        </select>
                    </div>

                    <div class="sidebar-field">
                        <span class="sidebar-field-label">Target Branch</span>
                        <span class="sidebar-field-value" id="detail-branch">-</span>
                    </div>

                    <div class="sidebar-field">
                        <span class="sidebar-field-label">Base Branch</span>
                        <span class="sidebar-field-value" id="detail-base">-</span>
                    </div>

                    <div class="sidebar-field">
                        <span class="sidebar-field-label">Pull Request</span>
                        <span class="sidebar-field-value" id="detail-pr">-</span>
                    </div>

                    <div class="sidebar-field">
                        <span class="sidebar-field-label">Test Status</span>
                        <span class="sidebar-field-value" id="detail-test-status">-</span>
                    </div>

                    <div class="sidebar-field" style="margin-top:auto;">
                        <span class="sidebar-field-label">File Path</span>
                        <span class="sidebar-field-value" style="font-size:11px; word-break:break-all; font-weight:normal;" id="detail-filepath">-</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="modal-overlay" id="create-modal">
        <div class="modal-container">
            <div class="modal-header">
                <span class="modal-title">Create Issue</span>
                <button class="btn-close-detail" onclick="closeCreateModal()">
                    <svg width="18" height="18" viewBox="0 0 24 24"><path fill="var(--text-main)" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label for="create-type">Issue Type</label>
                    <select id="create-type">
                        <option value="Story">Story</option>
                        <option value="Bug">Bug (Defect)</option>
                        <option value="Epic">Epic</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="create-title">Summary / Title</label>
                    <input type="text" id="create-title" placeholder="What needs to be done?">
                </div>
                <div class="form-group">
                    <label for="create-epic">Epic</label>
                    <select id="create-epic">
                    </select>
                </div>
                <div class="form-group">
                    <label for="create-severity">Severity / Priority</label>
                    <select id="create-severity">
                        <option value="P3">P3 (Medium/Low)</option>
                        <option value="P2">P2 (High)</option>
                        <option value="P1">P1 (Critical)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="create-description">Description</label>
                    <textarea id="create-description" placeholder="Provide a detailed description of the task..."></textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-cancel" onclick="closeCreateModal()">Cancel</button>
                <button class="btn-create" onclick="submitCreateIssue()">Create</button>
            </div>
        </div>
    </div>

    <div class="toast-container" id="toast-container"></div>

    <script>
        let issues = {db_json};
        let epics = {epics_json};
        let activeEpic = "{active_epic}";
        
        let currentView = 'board';
        let currentFilters = {
            search: '',
            epic: '',
            type: '',
            severity: ''
        };
        let selectedIssueKey = null;
        let activeDetailTab = 'details';

        if (localStorage.getItem('cognirepo_tracker_issues')) {
            try {
                issues = JSON.parse(localStorage.getItem('cognirepo_tracker_issues'));
            } catch(e) {
                console.error("Failed to parse saved issues from localStorage, using compiled default.");
            }
        }

        if (localStorage.getItem('theme') === 'dark') {
            document.body.classList.add('dark-mode');
        }

        window.addEventListener('DOMContentLoaded', () => {
            populateFilterOptions();
            switchView('backlog');
            renderView();
            updateDashboard();
            setupDetailPaneResize();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            const createModal = document.getElementById('create-modal');
            const detailPane = document.getElementById('detail-pane');
            if (createModal.classList.contains('open')) {
                closeCreateModal();
            } else if (detailPane.classList.contains('open')) {
                closeDetailPane();
            }
        });

        function toggleTheme() {
            document.body.classList.toggle('dark-mode');
            if (document.body.classList.contains('dark-mode')) {
                localStorage.setItem('theme', 'dark');
            } else {
                localStorage.setItem('theme', 'light');
            }
            updateDashboard();
        }

        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            sidebar.classList.toggle('collapsed');
            document.body.classList.toggle('sidebar-collapsed');
        }

        function switchView(view) {
            currentView = view;
            
            document.querySelectorAll('.menu-item').forEach(el => el.classList.remove('active'));
            const activeItem = document.getElementById(`menu-${view}`);
            if (activeItem) activeItem.classList.add('active');

            document.querySelectorAll('.view-panel').forEach(el => el.style.display = 'none');
            const targetPanel = document.getElementById(`view-${view}`);
            if (targetPanel) {
                if (view === 'board') targetPanel.style.display = 'flex';
                else targetPanel.style.display = 'block';
            }

            const filterBar = document.getElementById('filter-bar');
            if (view === 'board' || view === 'backlog') {
                filterBar.style.display = 'flex';
            } else {
                filterBar.style.display = 'none';
            }

            const titles = {
                board: 'Tasks',
                backlog: 'Backlog',
                roadmap: 'Epic Roadmap',
                dashboard: 'Project Dashboard'
            };
            document.getElementById('view-title').innerText = titles[view] || 'CogniRepo Tracker';
            document.getElementById('breadcrumbs').innerText = `Projects / cognirepo / ${titles[view] || ''}`;

            renderView();
        }

        function populateFilterOptions() {
            const epicSelects = [document.getElementById('epic-filter'), document.getElementById('create-epic'), document.getElementById('detail-epic-select')];
            
            epicSelects.forEach(sel => {
                if (sel) {
                    const firstOption = sel.options[0];
                    sel.innerHTML = '';
                    if (firstOption) sel.appendChild(firstOption);
                }
            });

            const epicIssues = epics;
            epicIssues.forEach(ep => {
                epicSelects.forEach(sel => {
                    if (sel) {
                        const opt = document.createElement('option');
                        opt.value = ep.id;
                        opt.textContent = `${ep.id} - ${ep.name}`;
                        sel.appendChild(opt);
                    }
                });
            });
        }

        function saveState() {
            localStorage.setItem('cognirepo_tracker_issues', JSON.stringify(issues));
            updateDashboard();
        }

        function renderView() {
            if (currentView === 'board') {
                renderBoard();
            } else if (currentView === 'backlog') {
                renderBacklog();
            } else if (currentView === 'roadmap') {
                renderRoadmap();
            } else if (currentView === 'dashboard') {
                updateDashboard();
            }
        }

        function getFilteredIssues() {
            return issues.filter(issue => {
                if (currentFilters.search) {
                    const s = currentFilters.search.toLowerCase();
                    const titleMatch = issue.title.toLowerCase().includes(s);
                    const keyMatch = issue.key.toLowerCase().includes(s);
                    const descMatch = (issue.description_md || '').toLowerCase().includes(s);
                    if (!titleMatch && !keyMatch && !descMatch) return false;
                }
                if (currentFilters.epic && issue.epic !== currentFilters.epic) {
                    return false;
                }
                if (currentFilters.type && issue.type !== currentFilters.type) {
                    return false;
                }
                if (currentFilters.severity && issue.severity !== currentFilters.severity) {
                    return false;
                }
                return true;
            });
        }

        function getTypeIconSVG(type) {
            if (type === 'Bug') {
                return `<svg viewBox="0 0 24 24" class="badge-type bug" style="width:16px;height:16px;padding:2px;border-radius:2px;"><path fill="white" d="M20 11.1c.3 0 .5-.2.5-.5V8.5c0-.3-.2-.5-.5-.5h-2.1C17.4 6.7 16.5 5.6 15.3 5l1.6-1.6c.2-.2.2-.5 0-.7s-.5-.2-.7 0L14 4.8C13.4 4.4 12.7 4.2 12 4.2s-1.4.2-2 .6L7.8 2.7c-.2-.2-.5-.2-.7 0s-.2.5 0 .7L8.7 5C7.5 5.6 6.6 6.7 6.1 8H4c-.3 0-.5.2-.5.5v2.1c0 .3.2.5.5.5h.1c0 1.2.4 2.3 1.1 3.2L3.6 16c-.2.2-.2.5 0 .7s.5.2.7 0l1.7-1.7c1 .8 2.4 1.3 3.9 1.3h4.2c1.5 0 2.9-.5 3.9-1.3l1.7 1.7c.2.2.5.2.7 0s.2-.5 0-.7l-1.6-1.6c.7-.9 1.1-2 1.1-3.2l.1-.1zM12 14c-1.7 0-3-1.3-3-3V9c0-1.7 1.3-3 3-3s3 1.3 3 3v2c0 1.7-1.3 3-3 3z"/></svg>`;
            } else if (type === 'Epic') {
                return `<svg viewBox="0 0 24 24" class="badge-type epic" style="width:16px;height:16px;padding:2px;border-radius:2px;fill:white;"><path d="M12 2L2 22h20L12 2z"/></svg>`;
            } else {
                return `<svg viewBox="0 0 24 24" class="badge-type story" style="width:16px;height:16px;padding:2px;border-radius:2px;fill:white;"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 10H7v-2h10v2z"/></svg>`;
            }
        }

        function getPriorityIconSVG(issue) {
            // Severity (P1/P2/P3) only means something for defects - stories/epics
            // have no meta-line severity, so we skip the badge for them entirely
            // rather than showing a default that matches no filter option.
            if (issue.type !== 'Bug') return '';
            const severity = issue.severity;
            let fill = 'var(--text-muted)';
            let title = 'Medium / Low';
            if (severity === 'P1') { fill = '#FF5630'; title = 'Critical'; }
            else if (severity === 'P2') { fill = '#FFAB00'; title = 'High'; }
            else if (severity === 'P3') { fill = '#36B37E'; title = 'Medium'; }
            return `<svg viewBox="0 0 24 24" class="priority-icon" title="${title}" style="fill:${fill}"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>`;
        }

        function renderBoard() {
            const columns = {
                'todo': document.getElementById('cards-todo'),
                'in-progress': document.getElementById('cards-in-progress'),
                'done': document.getElementById('cards-done')
            };

            for (let c in columns) {
                columns[c].innerHTML = '';
            }

            const filtered = getFilteredIssues().filter(i => i.type !== 'Epic');
            const counts = { 'todo': 0, 'in-progress': 0, 'done': 0 };

            filtered.forEach(issue => {
                const status = issue.status || 'todo';
                counts[status]++;

                const card = document.createElement('div');
                card.className = 'card';
                card.draggable = true;
                card.dataset.key = issue.key;
                card.onclick = () => openIssueDetail(issue.key);
                card.addEventListener('dragstart', handleDragStart);
                card.addEventListener('dragend', handleDragEnd);

                let epicTag = '';
                if (issue.epic) {
                    const ep = epics.find(e => e.id === issue.epic);
                    const epName = ep ? ep.name : issue.epic;
                    epicTag = `<span class="badge badge-epic" title="Epic: ${epName}">${epName}</span>`;
                }

                card.innerHTML = `
                    <div class="card-title">${issue.title}</div>
                    <div class="card-footer">
                        <div class="card-meta-left">
                            ${getTypeIconSVG(issue.type)}
                            <span class="card-key">${issue.key}</span>
                            ${epicTag}
                        </div>
                        <div style="display:flex; align-items:center; gap:4px;">
                            ${getPriorityIconSVG(issue)}
                        </div>
                    </div>
                `;

                if (columns[status]) {
                    columns[status].appendChild(card);
                }
            });

            for (let c in counts) {
                document.getElementById(`count-${c}`).innerText = counts[c];
            }
        }

        let draggedCard = null;

        function handleDragStart(e) {
            draggedCard = e.currentTarget;
            draggedCard.classList.add('dragging');
            e.dataTransfer.setData('text/plain', draggedCard.dataset.key);
            e.dataTransfer.effectAllowed = 'move';
        }

        function handleDragEnd(e) {
            if (draggedCard) {
                draggedCard.classList.remove('dragging');
            }
            draggedCard = null;
            document.querySelectorAll('.board-column').forEach(col => col.classList.remove('drag-over'));
        }

        function allowDrop(e) {
            e.preventDefault();
        }

        function dragEnter(e) {
            e.preventDefault();
            e.currentTarget.classList.add('drag-over');
        }

        function dragLeave(e) {
            e.currentTarget.classList.remove('drag-over');
        }

        function handleDrop(e, status) {
            e.preventDefault();
            const key = e.dataTransfer.getData('text/plain');
            const issueIndex = issues.findIndex(i => i.key === key);
            if (issueIndex > -1) {
                const oldStatus = issues[issueIndex].status;
                if (oldStatus !== status) {
                    issues[issueIndex].status = status;
                    saveState();
                    renderBoard();
                    showToast(`Updated ${key} status to ${status.replace('-', ' ')}`);
                }
            }
            e.currentTarget.classList.remove('drag-over');
        }

        let activeBacklogEpic = '';

        function renderBacklog() {
            const epicList = document.getElementById('backlog-epic-list');
            epicList.innerHTML = '';

            const allItem = document.createElement('li');
            allItem.className = `epic-item ${!activeBacklogEpic ? 'active' : ''}`;
            allItem.onclick = () => { activeBacklogEpic = ''; renderBacklog(); };
            allItem.innerHTML = `<span class="epic-item-name">All issues</span>`;
            epicList.appendChild(allItem);

            epics.forEach(ep => {
                const childIssues = issues.filter(i => i.epic === ep.id);
                const doneIssues = childIssues.filter(i => i.status === 'done');
                const pct = childIssues.length > 0 ? Math.round((doneIssues.length / childIssues.length) * 100) : 0;

                const epItem = document.createElement('li');
                epItem.className = `epic-item ${activeBacklogEpic === ep.id ? 'active' : ''}`;
                epItem.onclick = () => { activeBacklogEpic = ep.id; renderBacklog(); };
                epItem.innerHTML = `
                    <div class="epic-item-header">
                        <span class="epic-item-name">${ep.id} - ${ep.name}</span>
                        <span class="epic-item-open-btn" title="Open epic ${ep.id}" onclick="event.stopPropagation(); openIssueDetail('${ep.id}')">
                            <svg viewBox="0 0 24 24"><path d="M14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7zM5 5h5V3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-5h-2v5H5V5z"/></svg>
                        </span>
                    </div>
                    <span style="font-size:11px; color:var(--text-muted);">${doneIssues.length} of ${childIssues.length} done (${pct}%)</span>
                    <div class="epic-item-progress">
                        <div class="epic-item-progress-bar" style="width: ${pct}%;"></div>
                    </div>
                `;
                epicList.appendChild(epItem);
            });

            const itemsList = document.getElementById('backlog-items-list');
            itemsList.innerHTML = '';

            let filtered = getFilteredIssues().filter(i => i.type !== 'Epic');
            if (activeBacklogEpic) {
                filtered = filtered.filter(i => i.epic === activeBacklogEpic);
            }

            document.getElementById('backlog-issue-count').innerText = `${filtered.length} issue(s)`;

            if (filtered.length === 0) {
                itemsList.innerHTML = `<div style="text-align:center; padding:40px; color:var(--text-muted); font-size:14px;">No issues found.</div>`;
                return;
            }

            filtered.forEach(issue => {
                const item = document.createElement('div');
                item.className = `backlog-item ${issue.type.toLowerCase()}`;
                item.onclick = () => openIssueDetail(issue.key);

                let epicBadge = '';
                if (issue.epic) {
                    const ep = epics.find(e => e.id === issue.epic);
                    epicBadge = `<span class="badge badge-epic" style="margin-left:8px;">${ep ? ep.name : issue.epic}</span>`;
                }

                item.innerHTML = `
                    <div class="backlog-item-left">
                        ${getTypeIconSVG(issue.type)}
                        <span class="card-key" style="min-width: 120px;">${issue.key}</span>
                        <span class="backlog-item-title" title="${issue.title}">${issue.title}</span>
                        ${epicBadge}
                    </div>
                    <div class="backlog-item-right">
                        ${getPriorityIconSVG(issue)}
                        <span class="backlog-status ${issue.status}">${issue.status.replace('-', ' ')}</span>
                    </div>
                `;
                itemsList.appendChild(item);
            });
        }

        function renderRoadmap() {
            const chart = document.getElementById('roadmap-gantt-chart');
            chart.innerHTML = '';

            const headerRow = document.createElement('div');
            headerRow.className = 'roadmap-header-row';
            headerRow.innerHTML = `
                <div class="roadmap-label-col">Epic</div>
                <div class="roadmap-timeline-col">
                    <div>Q3 - JUL</div>
                    <div>Q3 - AUG</div>
                    <div>Q3 - SEP</div>
                    <div>Q4 - OCT</div>
                </div>
            `;
            chart.appendChild(headerRow);

            epics.forEach((ep, index) => {
                const childIssues = issues.filter(i => i.epic === ep.id);
                const doneIssues = childIssues.filter(i => i.status === 'done');
                const pct = childIssues.length > 0 ? Math.round((doneIssues.length / childIssues.length) * 100) : 0;

                const row = document.createElement('div');
                row.className = 'roadmap-row';
                
                let epicClass = `epic-${ep.id.split('-')[1]}`;

                row.innerHTML = `
                    <div class="roadmap-epic-label" onclick="openIssueDetail('${ep.id}')">
                        <span class="roadmap-epic-title">${ep.name}</span>
                        <span class="roadmap-epic-key">${ep.id} · ${pct}% done (${doneIssues.length} of ${childIssues.length})</span>
                    </div>
                    <div class="roadmap-bar-container">
                        <div class="roadmap-bar ${epicClass}" onclick="openIssueDetail('${ep.id}')">
                            <div class="roadmap-bar-progress" style="width: ${pct}%;"></div>
                            <span style="position:relative; z-index:2; text-shadow: 0 1px 2px rgba(0,0,0,0.5);">${ep.id}</span>
                        </div>
                    </div>
                `;
                chart.appendChild(row);
            });
        }

        function updateDashboard() {
            const totalIssues = issues.filter(i => i.type !== 'Epic').length;
            const doneIssuesCount = issues.filter(i => i.type !== 'Epic' && i.status === 'done').length;
            const progressPct = totalIssues > 0 ? Math.round((doneIssuesCount / totalIssues) * 100) : 0;

            const ring = document.getElementById('dash-progress-ring');
            if (ring) {
                const radius = 15.915;
                const circumference = 2 * Math.PI * radius;
                const offset = circumference - (progressPct / 100) * circumference;
                ring.style.strokeDashoffset = offset;
            }

            const pctText = document.getElementById('dash-percentage');
            if (pctText) pctText.innerText = `${progressPct}%`;

            const countsText = document.getElementById('dash-progress-counts');
            if (countsText) countsText.innerText = `${doneIssuesCount} of ${totalIssues} issues complete`;

            const todoCount = issues.filter(i => i.type !== 'Epic' && i.status === 'todo').length;
            const progressCount = issues.filter(i => i.type !== 'Epic' && i.status === 'in-progress').length;
            const doneCount = doneIssuesCount;

            const chartStatus = document.getElementById('chart-status-bar');
            if (chartStatus) {
                const max = Math.max(todoCount, progressCount, doneCount, 1);
                const todoHeight = (todoCount / max) * 100;
                const progressHeight = (progressCount / max) * 100;
                const doneHeight = (doneCount / max) * 100;

                chartStatus.innerHTML = `
                    <div style="display:flex; justify-content:space-around; width:100%; align-items:flex-end; height:180px; padding:10px;">
                        <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
                            <span style="font-weight:700; font-size:12px;">${todoCount}</span>
                            <div style="width:40px; height:${todoHeight}px; background-color:var(--text-muted); border-radius:4px 4px 0 0; transition: height 0.3s;"></div>
                            <span style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--text-muted)">To Do</span>
                        </div>
                        <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
                            <span style="font-weight:700; font-size:12px; color:var(--primary-color)">${progressCount}</span>
                            <div style="width:40px; height:${progressHeight}px; background-color:var(--primary-color); border-radius:4px 4px 0 0; transition: height 0.3s;"></div>
                            <span style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--primary-color)">In Progress</span>
                        </div>
                        <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
                            <span style="font-weight:700; font-size:12px; color:var(--story-text)">${doneCount}</span>
                            <div style="width:40px; height:${doneHeight}px; background-color:var(--story-text); border-radius:4px 4px 0 0; transition: height 0.3s;"></div>
                            <span style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--story-text)">Done</span>
                        </div>
                    </div>
                `;
            }

            const epicBreakdown = document.getElementById('dash-epic-breakdown');
            if (epicBreakdown) {
                epicBreakdown.innerHTML = '';
                epics.forEach(ep => {
                    const child = issues.filter(i => i.epic === ep.id);
                    const done = child.filter(i => i.status === 'done');
                    const progress = child.filter(i => i.status === 'in-progress');
                    const todo = child.filter(i => i.status === 'todo');
                    
                    const total = child.length || 1;
                    const donePct = (done.length / total) * 100;
                    const progressPct = (progress.length / total) * 100;
                    const todoPct = (todo.length / total) * 100;

                    const row = document.createElement('div');
                    row.style.marginBottom = '12px';
                    row.innerHTML = `
                        <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:4px;">
                            <span>${ep.id} - ${ep.name}</span>
                            <span>${done.length} / ${child.length} issues (${Math.round(donePct)}%)</span>
                        </div>
                        <div style="height:10px; display:flex; border-radius:5px; overflow:hidden; background-color:var(--border-color);">
                            <div style="width:${donePct}%; background-color:var(--story-text);" title="Done: ${done.length}"></div>
                            <div style="width:${progressPct}%; background-color:var(--primary-color);" title="In Progress: ${progress.length}"></div>
                            <div style="width:${todoPct}%; background-color:var(--text-muted);" title="To Do: ${todo.length}"></div>
                        </div>
                    `;
                    epicBreakdown.appendChild(row);
                });
            }
        }

        function openIssueDetail(key) {
            selectedIssueKey = key;
            const issue = issues.find(i => i.key === key);
            if (!issue) return;

            document.getElementById('detail-issue-key').innerText = issue.key;
            document.getElementById('detail-title-input').innerText = issue.title;
            document.getElementById('detail-status-select').value = issue.status || 'todo';
            document.getElementById('detail-filepath').innerText = issue.file_path || '-';
            
            document.getElementById('detail-branch').innerText = issue.branch || '-';
            document.getElementById('detail-base').innerText = issue.base || '-';
            document.getElementById('detail-pr').innerText = issue.pr || 'Not opened yet';
            document.getElementById('detail-test-status').innerText = (issue.test_status || 'not-run').replace('-', ' ');

            const severityField = document.getElementById('detail-severity-field');
            if (issue.type === 'Bug') {
                severityField.style.display = '';
                document.getElementById('detail-severity-select').value = issue.severity || 'P3';
            } else {
                severityField.style.display = 'none';
            }

            const epicSelect = document.getElementById('detail-epic-select');
            epicSelect.value = issue.epic || '';

            const typeBadge = document.getElementById('detail-type-badge');
            typeBadge.className = `badge badge-type ${issue.type.toLowerCase()}`;
            typeBadge.innerText = issue.type;

            document.getElementById('rendered-backstory').innerHTML = renderMarkdown(issue.backstory_md || '*No backstory provided.*');
            document.getElementById('rendered-description').innerHTML = renderMarkdown(issue.description_md || '*No description provided.*');
            document.getElementById('rendered-criteria').innerHTML = renderMarkdown(issue.acceptance_criteria_md || '*No criteria provided.*');
            document.getElementById('rendered-notes').innerHTML = renderMarkdown(issue.notes_md || '*No notes provided.*');

            const discTabBtn = document.getElementById('tab-discovery-btn');
            if (issue.discovery_md) {
                discTabBtn.style.display = 'block';
                document.getElementById('rendered-discovery').innerHTML = renderMarkdown(issue.discovery_md);
            } else {
                discTabBtn.style.display = 'none';
            }

            const testTabBtn = document.getElementById('tab-test-suite-btn');
            if (issue.test_suite_md) {
                testTabBtn.style.display = 'block';
                renderTestSuiteTab(issue.test_suite_md);
            } else {
                testTabBtn.style.display = 'none';
            }

            document.getElementById('raw-markdown-text').innerText = issue.raw_md || '';
            switchDetailTab('details');
            document.getElementById('detail-pane').classList.add('open');
        }

        function closeDetailPane() {
            const pane = document.getElementById('detail-pane');
            pane.classList.remove('open');
            pane.classList.remove('fullscreen');
            document.getElementById('btn-fullscreen-detail').classList.remove('active');
            selectedIssueKey = null;
        }

        function toggleDetailFullscreen() {
            const pane = document.getElementById('detail-pane');
            const btn = document.getElementById('btn-fullscreen-detail');
            const path = document.getElementById('detail-fullscreen-path');
            const isFullscreen = pane.classList.toggle('fullscreen');
            btn.classList.toggle('active', isFullscreen);
            btn.title = isFullscreen ? 'Exit full screen' : 'Toggle full screen';
            path.setAttribute('d', isFullscreen
                ? 'M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z'
                : 'M7 14H5v5h5v-2H7v-3zM5 10h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z');
        }

        function setupDetailPaneResize() {
            const pane = document.getElementById('detail-pane');
            const handle = document.getElementById('detail-resize-handle');
            const savedWidth = parseInt(localStorage.getItem('cognirepo_tracker_detail_width'), 10);
            if (savedWidth) pane.style.width = savedWidth + 'px';

            let dragging = false;

            handle.addEventListener('mousedown', (e) => {
                if (pane.classList.contains('fullscreen')) return;
                dragging = true;
                pane.classList.add('resizing');
                handle.classList.add('active');
                document.body.style.userSelect = 'none';
                e.preventDefault();
            });

            window.addEventListener('mousemove', (e) => {
                if (!dragging) return;
                const newWidth = Math.min(Math.max(window.innerWidth - e.clientX, 420), window.innerWidth * 0.96);
                pane.style.width = newWidth + 'px';
            });

            window.addEventListener('mouseup', () => {
                if (!dragging) return;
                dragging = false;
                pane.classList.remove('resizing');
                handle.classList.remove('active');
                document.body.style.userSelect = '';
                localStorage.setItem('cognirepo_tracker_detail_width', parseInt(pane.style.width, 10));
            });
        }

        function switchDetailTab(tab) {
            activeDetailTab = tab;
            document.querySelectorAll('.detail-tab').forEach(el => el.classList.remove('active'));
            document.getElementById(`tab-${tab}-btn`).classList.add('active');

            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.getElementById(`tab-content-${tab}`).classList.add('active');
        }

        function parseMarkdown(md) {
            if (!md) return "No content.";
            let html = md;
            
            html = html.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            
            html = html.replace(/```([\\s\\S]*?)```/g, (match, code) => {
                return `<pre><code>${code.trim()}</code></pre>`;
            });
            
            html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
            html = html.replace(/^### (.*$)/gim, "<h3>$1</h3>");
            html = html.replace(/^## (.*$)/gim, "<h2>$1</h2>");
            html = html.replace(/^# (.*$)/gim, "<h1>$1</h1>");
            html = html.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
            
            let lines = html.split("\\n");
            let inList = false;
            for (let i = 0; i < lines.length; i++) {
                let line = lines[i].trim();
                if (line.startsWith("- ") || line.startsWith("* ")) {
                    let content = line.substring(2);
                    
                    if (content.startsWith("[ ] ")) {
                        content = `<input type="checkbox" disabled> ` + content.substring(4);
                    } else if (content.startsWith("[x] ") || content.startsWith("[X] ")) {
                        content = `<input type="checkbox" checked disabled> ` + content.substring(4);
                    }
                    
                    if (!inList) {
                        lines[i] = "<ul><li>" + content + "</li>";
                        inList = true;
                    } else {
                        lines[i] = "<li>" + content + "</li>";
                    }
                } else {
                    if (inList) {
                        lines[i] = "</ul>" + lines[i];
                        inList = false;
                    }
                }
            }
            if (inList) lines.push("</ul>");
            html = lines.join("\\n");
            
            html = html.replace(/\\n/g, "<br>");
            html = html.replace(/<\\/ul><br>/g, "</ul>");
            html = html.replace(/<\\/h1><br>/g, "</h1>");
            html = html.replace(/<\\/h2><br>/g, "</h2>");
            html = html.replace(/<\\/h3><br>/g, "</h3>");
            html = html.replace(/<\\/pre><br>/g, "</pre>");
            
            return html;
        }

        function renderMarkdown(md) {
            if (window.marked) {
                return marked.parse(md);
            }
            return parseMarkdown(md);
        }

        function isTestCaseHeading(s) {
            return s.startsWith('## TC-') || s.startsWith('- TC-') || s.startsWith('TC-') ||
                   s.startsWith('## E2E-') || s.startsWith('- E2E-') || s.startsWith('E2E-');
        }

        function renderTestSuiteTab(testSuiteMd) {
            const container = document.getElementById('rendered-test-suite');
            container.innerHTML = '';

            const lines = testSuiteMd.split('\\n');
            let heading = '';

            lines.forEach((line, index) => {
                const trimmed = line.trim();

                if (isTestCaseHeading(trimmed)) {
                    heading = trimmed.replace(/^[#\\-\\s]*/, '');

                    let testRepo = '';
                    let whatToDo = '';
                    let expectedText = '';
                    let ver = '';
                    let checkedState = '';

                    for (let j = index + 1; j < lines.length; j++) {
                        const subLine = lines[j].trim();
                        if (isTestCaseHeading(subLine) && j > index) {
                            break;
                        }
                        if (subLine.startsWith('- Test repo:') || subLine.startsWith('Test repo:')) {
                            testRepo = subLine.replace(/^[-\\s]*Test repo:\\s*/, '');
                        }
                        if (subLine.startsWith('- What to do:') || subLine.startsWith('What to do:')) {
                            whatToDo = subLine.replace(/^[-\\s]*What to do:\\s*/, '');
                        }
                        if (subLine.startsWith('- Expected results:') || subLine.startsWith('Expected results:')) {
                            expectedText = subLine.replace(/^[-\\s]*Expected results:\\s*/, '');
                        }
                        if (subLine.startsWith('- Verdict:') || subLine.startsWith('Verdict:')) {
                            ver = subLine.replace(/^[-\\s]*Verdict:\\s*/, '').toLowerCase();
                            if (ver.includes('pass') || ver.includes('green') || ver.includes('x') || ver.includes('yes')) {
                                checkedState = 'checked';
                            }
                        }
                    }

                    const testRepoHtml = testRepo ? `<span class="test-case-meta"><strong>Test repo:</strong> <code>${testRepo}</code></span>` : '';
                    const whatToDoHtml = whatToDo ? `<span class="test-case-meta"><strong>What to do:</strong> ${whatToDo}</span>` : '';
                    const expectedHtml = expectedText ? `<span class="test-case-expected"><strong>Expected:</strong> ${expectedText}</span>` : '';
                    const statusClass = checkedState ? 'passed' : '';

                    const card = document.createElement('div');
                    card.className = `test-case-item ${statusClass}`;
                    card.innerHTML = `
                        <input type="checkbox" class="test-case-checkbox" ${checkedState} onchange="toggleTestCase(this, '${selectedIssueKey}', ${index})">
                        <div class="test-case-details">
                            <div class="test-case-head">
                                <strong>${heading}</strong>
                                <span class="test-case-status-badge ${statusClass}">${checkedState ? 'Passed' : 'Pending'}</span>
                            </div>
                            ${testRepoHtml}
                            ${whatToDoHtml}
                            ${expectedHtml}
                        </div>
                    `;
                    container.appendChild(card);
                }
            });

            if (container.children.length === 0) {
                container.innerHTML = renderMarkdown(testSuiteMd);
            }
        }

        function toggleTestCase(checkbox, issueKey, lineIndex) {
            const issue = issues.find(i => i.key === issueKey);
            if (!issue || !issue.test_suite_md) return;

            let lines = issue.test_suite_md.split('\\n');
            let foundVerdict = false;
            for (let i = lineIndex + 1; i < lines.length; i++) {
                if (isTestCaseHeading(lines[i].trim())) {
                    break;
                }
                if (lines[i].includes('Verdict:')) {
                    if (checkbox.checked) {
                        lines[i] = lines[i].split('Verdict:')[0] + 'Verdict: PASS';
                    } else {
                        lines[i] = lines[i].split('Verdict:')[0] + 'Verdict: ';
                    }
                    foundVerdict = true;
                    break;
                }
            }

            if (!foundVerdict) {
                let appendIdx = lines.length;
                for (let i = lineIndex + 1; i < lines.length; i++) {
                    if (lines[i].trim().startsWith('## TC-') || lines[i].trim().startsWith('- TC-')) {
                        appendIdx = i;
                        break;
                    }
                }
                const verdictStr = checkbox.checked ? '- Verdict: PASS' : '- Verdict: ';
                lines.splice(appendIdx, 0, verdictStr);
            }

            issue.test_suite_md = lines.join('\\n');
            saveState();
            showToast(`Updated test case verdict in test suite for ${issueKey}`);
            renderTestSuiteTab(issue.test_suite_md);
        }

        function handleStatusChange(status) {
            if (!selectedIssueKey) return;
            const issueIndex = issues.findIndex(i => i.key === selectedIssueKey);
            if (issueIndex > -1) {
                issues[issueIndex].status = status;
                saveState();
                renderView();
                showToast(`Updated status of ${selectedIssueKey} to ${status.replace('-', ' ')}`);
            }
        }

        function handleEpicChange(epic) {
            if (!selectedIssueKey) return;
            const issueIndex = issues.findIndex(i => i.key === selectedIssueKey);
            if (issueIndex > -1) {
                issues[issueIndex].epic = epic;
                saveState();
                renderView();
                showToast(`Associated ${selectedIssueKey} with epic ${epic || 'none'}`);
            }
        }

        function handleSeverityChange(sev) {
            if (!selectedIssueKey) return;
            const issueIndex = issues.findIndex(i => i.key === selectedIssueKey);
            if (issueIndex > -1) {
                issues[issueIndex].severity = sev;
                saveState();
                renderView();
                showToast(`Set priority of ${selectedIssueKey} to ${sev}`);
            }
        }

        function handleTitleEdit(newTitle) {
            if (!selectedIssueKey) return;
            const issueIndex = issues.findIndex(i => i.key === selectedIssueKey);
            if (issueIndex > -1) {
                const cleanTitle = newTitle.replace(/\\n/g, '').trim();
                if (cleanTitle && issues[issueIndex].title !== cleanTitle) {
                    issues[issueIndex].title = cleanTitle;
                    saveState();
                    renderView();
                    showToast(`Updated title of ${selectedIssueKey}`);
                }
            }
        }

        function copyRawMarkdown() {
            const text = document.getElementById('raw-markdown-text').innerText;
            navigator.clipboard.writeText(text).then(() => {
                showToast("Markdown copied to clipboard!");
            }).catch(err => {
                console.error("Failed to copy text: ", err);
            });
        }

        let searchDebounceTimer = null;
        function handleSearch(val) {
            currentFilters.search = val;
            const globSearch = document.getElementById('global-search');
            const boardSearch = document.getElementById('board-search');
            if (globSearch && globSearch.value !== val) globSearch.value = val;
            if (boardSearch && boardSearch.value !== val) boardSearch.value = val;
            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => renderView(), 180);
        }

        function filterIssues() {
            currentFilters.epic = document.getElementById('epic-filter').value;
            currentFilters.type = document.getElementById('type-filter').value;
            currentFilters.severity = document.getElementById('severity-filter').value;
            renderView();
        }

        function clearFilters() {
            currentFilters.search = '';
            currentFilters.epic = '';
            currentFilters.type = '';
            currentFilters.severity = '';

            document.getElementById('global-search').value = '';
            document.getElementById('board-search').value = '';
            document.getElementById('epic-filter').value = '';
            document.getElementById('type-filter').value = '';
            document.getElementById('severity-filter').value = '';

            renderView();
            showToast("Cleared all active filters");
        }

        function openCreateModal() {
            const epicSelect = document.getElementById('create-epic');
            epicSelect.innerHTML = '<option value="">No Epic</option>';
            epics.forEach(ep => {
                epicSelect.innerHTML += `<option value="${ep.id}">${ep.id} - ${ep.name}</option>`;
            });

            document.getElementById('create-modal').classList.add('open');
        }

        function closeCreateModal() {
            document.getElementById('create-modal').classList.remove('open');
            document.getElementById('create-title').value = '';
            document.getElementById('create-description').value = '';
        }

        function submitCreateIssue() {
            const type = document.getElementById('create-type').value;
            const title = document.getElementById('create-title').value.trim();
            const epic = document.getElementById('create-epic').value;
            const severity = document.getElementById('create-severity').value;
            const description = document.getElementById('create-description').value.trim();

            if (!title) {
                alert("Summary / Title is required");
                return;
            }

            let keyNum = 100;
            issues.forEach(i => {
                const m = i.key.match(/COGNIREPO-(\d+)/);
                if (m) {
                    const val = parseInt(m[1]);
                    if (val > keyNum && val < 1000) keyNum = val;
                }
            });
            
            const newKeyNum = keyNum + 1;
            let key = `COGNIREPO-${newKeyNum}`;
            if (type === 'Bug') {
                let defectNum = 0;
                issues.forEach(i => {
                    const m = i.key.match(/COGNIREPO-D(\d+)/);
                    if (m) {
                        const val = parseInt(m[1]);
                        if (val > defectNum) defectNum = val;
                    }
                });
                key = `COGNIREPO-D${String(defectNum + 1).padStart(2, '0')}`;
            } else if (type === 'Epic') {
                let epicNum = 600;
                epics.forEach(e => {
                    const m = e.id.match(/COGNIREPO-(\d+)/);
                    if (m) {
                        const val = parseInt(m[1]);
                        if (val > epicNum) epicNum = val;
                    }
                });
                key = `COGNIREPO-${epicNum + 100}`;
                
                epics.push({
                    id: key,
                    name: title,
                    status: 'not-started',
                    blocked_by: []
                });
                populateFilterOptions();
            }

            const newIssue = {
                key: key,
                title: title,
                type: type,
                epic: epic,
                branch: type === 'Epic' ? '' : `story/${key}`,
                base: type === 'Epic' ? '' : 'development',
                severity: severity,
                status: 'todo',
                backstory_md: '',
                description_md: description,
                acceptance_criteria_md: '',
                notes_md: '',
                raw_md: `# ${key} — ${title}\\n\\n## Description\\n${description}`,
                test_suite_md: '',
                discovery_md: '',
                file_path: '',
                rel_path: ''
            };

            issues.push(newIssue);
            saveState();
            closeCreateModal();
            renderView();
            showToast(`Created new ${type.toLowerCase()} ${key}`);
            openIssueDetail(key);
        }

        function showToast(message) {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            toast.className = 'toast';
            toast.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
                <span>${message}</span>
            `;
            container.appendChild(toast);

            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.5s';
                setTimeout(() => toast.remove(), 500);
            }, 3000);
        }
    </script>
</body>
</html>
"""

# Replace fields instead of f-string formatting
html_template = html_template.replace("{db_json}", db_json)
html_template = html_template.replace("{epics_json}", epics_json)
html_template = html_template.replace("{active_epic}", active_epic)

with open(output_file, "w", encoding="utf-8") as f:
    f.write(html_template)

print(f"Successfully generated JIRA.html at {output_file}")
