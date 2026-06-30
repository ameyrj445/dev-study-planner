import os
import json
import datetime
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("study-planner-mcp")

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "study_db.json")

def _read_db():
    if not os.path.exists(DB_FILE):
        return {"todos": [], "active_pomodoro": None}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"todos": [], "active_pomodoro": None}

def _write_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

@mcp.tool()
def get_study_todos() -> str:
    """Retrieve the list of all active and completed study tasks/todos."""
    db = _read_db()
    todos = db.get("todos", [])
    if not todos:
        return "No study tasks found. Create one!"
    
    result = "### 📋 Current Study Tasks:\n"
    for t in todos:
        status = "✅ Done" if t.get("completed") else "⏳ Pending"
        result += f"- **[{t['id']}] [{t['category']}]** {t['task']} (~{t['estimation_pomodoros']} Pomodoros) - {status}\n"
    return result

@mcp.tool()
def add_study_todo(task: str, category: str, estimation_pomodoros: int) -> str:
    """Add a new study task or Striver DSA problem to the todo list.
    
    Args:
        task: Name of the study topic or problem.
        category: Category of study (e.g. 'DSA', 'Tech').
        estimation_pomodoros: Estimated 25-minute Pomodoro sessions.
    """
    db = _read_db()
    todos = db.get("todos", [])
    new_id = max([t["id"] for t in todos], default=0) + 1
    new_todo = {
        "id": new_id,
        "task": task,
        "category": category,
        "estimation_pomodoros": estimation_pomodoros,
        "completed": False
    }
    todos.append(new_todo)
    db["todos"] = todos
    _write_db(db)
    return f"Successfully added study task: [{new_id}] {task} ({category})"

@mcp.tool()
def complete_study_todo(task_id: int) -> str:
    """Mark a study task or DSA problem as completed by its ID.
    
    Args:
        task_id: The ID of the task to mark completed.
    """
    db = _read_db()
    todos = db.get("todos", [])
    found = False
    for t in todos:
        if t["id"] == task_id:
            t["completed"] = True
            found = True
            break
    if found:
        _write_db(db)
        return f"Successfully completed study task with ID {task_id}."
    return f"Task ID {task_id} not found."

@mcp.tool()
def start_pomodoro_session(minutes: int = 25) -> str:
    """Start a Pomodoro session for study focus.
    
    Args:
        minutes: The duration of the Pomodoro session in minutes.
    """
    db = _read_db()
    end_time = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    db["active_pomodoro"] = {
        "duration_minutes": minutes,
        "started_at": datetime.datetime.now().isoformat(),
        "ends_at": end_time.isoformat()
    }
    _write_db(db)
    return f"⏱️ Pomodoro session started for {minutes} minutes! Focus time until {end_time.strftime('%H:%M:%S')}."

if __name__ == "__main__":
    mcp.run()
