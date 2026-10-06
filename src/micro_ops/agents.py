"""Deterministic, local agents for tracking, inventory, and task planning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ITEM_STATES = ("Planned", "In Progress", "Blocked", "Complete")


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class TrackingAgent:
    def add_item(self, data: dict[str, Any], name: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Enter an item name.")
        item = {"id": _next_id(data["items"]), "name": name, "state": "Planned", "updated": timestamp()}
        data["items"].append(item)
        self._event(data, f"Tracking: added {name} (Planned)")
        return item

    def set_state(self, data: dict[str, Any], item_id: int, state: str) -> dict[str, Any]:
        if state not in ITEM_STATES:
            raise ValueError("Choose a valid state.")
        item = next((entry for entry in data["items"] if entry["id"] == item_id), None)
        if item is None:
            raise ValueError("That item no longer exists.")
        item["state"] = state
        item["updated"] = timestamp()
        self._event(data, f"Tracking: {item['name']} → {state}")
        return item

    @staticmethod
    def _event(data: dict[str, Any], message: str) -> None:
        data["events"].insert(0, {"time": timestamp(), "message": message})


class SupplyAgent:
    def add_supply(self, data: dict[str, Any], name: str, quantity: int, reorder_at: int) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Enter a supply name.")
        if quantity < 0 or reorder_at < 0:
            raise ValueError("Quantity and reorder level must be zero or greater.")
        existing = next((entry for entry in data["supplies"] if entry["name"].casefold() == name.casefold()), None)
        if existing:
            existing["quantity"] = quantity
            existing["reorder_at"] = reorder_at
            supply = existing
            event = f"Supply: updated {name} to {quantity}"
        else:
            supply = {"id": _next_id(data["supplies"]), "name": name, "quantity": quantity, "reorder_at": reorder_at}
            data["supplies"].append(supply)
            event = f"Supply: added {name} ({quantity})"
        data["events"].insert(0, {"time": timestamp(), "message": event})
        return supply

    def adjust(self, data: dict[str, Any], supply_id: int, delta: int) -> dict[str, Any]:
        supply = next((entry for entry in data["supplies"] if entry["id"] == supply_id), None)
        if supply is None:
            raise ValueError("That supply no longer exists.")
        quantity = supply["quantity"] + delta
        if quantity < 0:
            raise ValueError("Stock cannot go below zero.")
        supply["quantity"] = quantity
        data["events"].insert(0, {"time": timestamp(), "message": f"Supply: {supply['name']} stock is now {quantity}"})
        return supply

    @staticmethod
    def shortages(data: dict[str, Any]) -> list[dict[str, Any]]:
        return [s for s in data["supplies"] if s["quantity"] <= s["reorder_at"]]


class SchedulingAgent:
    """Create a deterministic serial task plan after checking dependencies."""

    def add_task(self, data: dict[str, Any], name: str, duration: int, depends_on: str = "") -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Enter a task name.")
        if duration < 1:
            raise ValueError("Duration must be at least one day.")
        dependency_names = [part.strip() for part in depends_on.split(",") if part.strip()]
        names = {task["name"].casefold() for task in data["tasks"]}
        for dependency in dependency_names:
            if dependency.casefold() not in names:
                raise ValueError(f"Dependency not found: {dependency}")
        task = {"id": _next_id(data["tasks"]), "name": name, "duration": duration, "depends_on": dependency_names}
        data["tasks"].append(task)
        data["events"].insert(0, {"time": timestamp(), "message": f"Scheduling: added {name} ({duration} days)"})
        return task

    @staticmethod
    def plan(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pending = list(tasks)
        known = {task["name"].casefold() for task in pending}
        for task in pending:
            missing = [dep for dep in task.get("depends_on", []) if dep.casefold() not in known]
            if missing:
                raise ValueError(f"{task['name']} has missing dependencies: {', '.join(missing)}")
        done: set[str] = set()
        result: list[dict[str, Any]] = []
        finish_by_name: dict[str, int] = {}
        while pending:
            ready = next((task for task in pending if all(dep.casefold() in done for dep in task.get("depends_on", []))), None)
            if ready is None:
                raise ValueError("Dependencies contain a cycle; remove a dependency to continue.")
            start = max((finish_by_name[dep.casefold()] for dep in ready.get("depends_on", [])), default=0)
            finish = start + int(ready["duration"])
            result.append({"name": ready["name"], "start_day": start, "finish_day": finish, "duration": int(ready["duration"])})
            done.add(ready["name"].casefold())
            finish_by_name[ready["name"].casefold()] = finish
            pending.remove(ready)
        return result


class AgentCoordinator:
    """Run deterministic agent checks for a user request and return a report."""

    def __init__(self, tracking: TrackingAgent, supply: SupplyAgent, scheduling: SchedulingAgent) -> None:
        self.tracking = tracking
        self.supply = supply
        self.scheduling = scheduling

    def run(self, data: dict[str, Any], request: str) -> dict[str, Any]:
        """Summarize local project state; no LLM or external service is used."""
        if not request.strip():
            raise ValueError("Describe what you want the agents to review.")
        shortages = self.supply.shortages(data)
        active = [item for item in data["items"] if item["state"] != "Complete"]
        try:
            plan = self.scheduling.plan(data["tasks"])
            plan_note = f"Schedule contains {len(plan)} task(s)."
        except ValueError as exc:
            plan = []
            plan_note = f"Schedule needs attention: {exc}"
        report = {
            "request": request.strip(),
            "tracking": f"{len(active)} active tracked item(s), {sum(item['state'] == 'Blocked' for item in active)} blocked.",
            "supply": f"{len(shortages)} shortage alert(s)." if shortages else "No supplies are at or below their reorder level.",
            "scheduling": plan_note,
            "shortages": [item["name"] for item in shortages],
            "plan": plan,
            "created": timestamp(),
        }
        data["events"].insert(0, {"time": report["created"], "message": "Coordinator: reviewed tracking, supplies, and schedule"})
        return report


class AutonomousAgentTeam:
    """Polling rule-based supervisor; it observes state and emits changed alerts."""

    def __init__(self, tracking: TrackingAgent, supply: SupplyAgent, scheduling: SchedulingAgent) -> None:
        self.tracking = tracking
        self.supply = supply
        self.scheduling = scheduling
        self.last_signature: tuple[str, ...] | None = None

    def cycle(self, data: dict[str, Any]) -> dict[str, Any]:
        alerts: list[str] = []
        blocked = [item["name"] for item in data["items"] if item["state"] == "Blocked"]
        if blocked:
            alerts.append("Blocked work: " + ", ".join(blocked))
        shortages = self.supply.shortages(data)
        for item in shortages:
            alerts.append(f"Low stock: {item['name']} ({item['quantity']} left; reorder at {item['reorder_at']})")
        try:
            plan = self.scheduling.plan(data["tasks"])
            plan_issue = None
        except ValueError as exc:
            plan = []
            plan_issue = str(exc)
            alerts.append("Schedule issue: " + plan_issue)
        signature = tuple(alerts)
        changed = signature != self.last_signature
        if changed:
            message = "Agents: " + ("; ".join(alerts) if alerts else "all checks clear")
            data["events"].insert(0, {"time": timestamp(), "message": message})
            self.last_signature = signature
        return {"alerts": alerts, "plan": plan, "changed": changed, "healthy": not alerts, "checked": timestamp()}


def _next_id(entries: list[dict[str, Any]]) -> int:
    return max((int(entry.get("id", 0)) for entry in entries), default=0) + 1
