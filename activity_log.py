from datetime import datetime
MAX_ACTIONS = 200
RECENT_ACTIONS = []

def log_action(message: str):
    RECENT_ACTIONS.append({
        "ts": datetime.utcnow().isoformat(),
        "message": str(message),
    })
    if len(RECENT_ACTIONS) > MAX_ACTIONS:
        RECENT_ACTIONS.pop(0)
