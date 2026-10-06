"""Interactive Flet desktop interface for the offline MicroOps agents."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import flet as ft

from .agents import AgentCoordinator, AutonomousAgentTeam, ITEM_STATES, SchedulingAgent, SupplyAgent, TrackingAgent, timestamp
from .micro_lm import STARTER_CORPUS, generate_text, train_model
from .store import Store


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def main(page: ft.Page) -> None:
    page.title = "MicroOps — Offline Agent Desk"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
    page.bgcolor = "#f3f6fb"
    page.padding = 0
    page.window.width = 1180
    page.window.height = 820
    page.window.min_width = 880
    page.window.min_height = 620

    store = Store(project_root() / "data" / "microops.json")
    data = store.load()
    tracking, supply, scheduling = TrackingAgent(), SupplyAgent(), SchedulingAgent()
    coordinator = AgentCoordinator(tracking, supply, scheduling)
    autonomous = AutonomousAgentTeam(tracking, supply, scheduling)
    selected = {"screen": "Overview", "item_id": None, "supply_id": None}
    body = ft.Container(expand=True, padding=24)
    auto_label = ft.Text("Starting automatic checks…", color="#475569", size=12)

    destinations = [
        ("Overview", ft.Icons.DASHBOARD_OUTLINED),
        ("Tracking", ft.Icons.TASK_ALT),
        ("Supplies", ft.Icons.INVENTORY_2_OUTLINED),
        ("Schedule", ft.Icons.CALENDAR_MONTH_OUTLINED),
        ("MicroLM", ft.Icons.PSYCHOLOGY_OUTLINED),
        ("Activity", ft.Icons.HISTORY),
    ]

    def save() -> None:
        store.save(data)

    def card(content: ft.Control, *, padding: int = 16) -> ft.Control:
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#e2e8f0"),
            border_radius=14,
        )

    def title_block(title: str, subtitle: str) -> ft.Control:
        return ft.Column(
            [ft.Text(title, size=24, weight=ft.FontWeight.BOLD, color="#172554"), ft.Text(subtitle, size=13, color="#64748b")],
            spacing=4,
        )

    def metric(label: str, value: str, icon: str, color: str) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                [ft.Container(ft.Icon(icon, color=color, size=22), padding=11, bgcolor=f"{color}18", border_radius=10),
                 ft.Column([ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color="#172554"), ft.Text(label, size=12, color="#64748b")], spacing=2)],
                spacing=12,
            ),
            padding=16,
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#e2e8f0"),
            border_radius=14,
            expand=True,
        )

    def refresh(screen: str | None = None) -> None:
        if screen:
            selected["screen"] = screen
        body.content = build_screen(selected["screen"])
        page.update()

    def run_review(e: Any = None) -> None:
        prompt = review_field.value or "Review current operations"
        try:
            report = coordinator.run(data, prompt)
            save()
            result = ft.Column(
                [
                    ft.Text(f"Tracking · {report['tracking']}"),
                    ft.Text(f"Supply · {report['supply']}"),
                    ft.Text(f"Scheduling · {report['scheduling']}"),
                    *([ft.Text("Reorder: " + ", ".join(report["shortages"]), color="#b45309")] if report["shortages"] else []),
                ],
                spacing=8,
            )
            review_result.content = result
            refresh("Overview")
        except (ValueError, OSError) as exc:
            review_result.content = ft.Text(str(exc), color="#b91c1c")
            page.update()

    review_field = ft.TextField(label="Ask the agents to review", hint_text="Example: Check if anything is blocked or running low", multiline=True, min_lines=2, max_lines=3, expand=True)
    review_result = ft.Container(content=ft.Text("Run a review to see each agent's findings.", color="#64748b"), padding=12, bgcolor="#f8fafc", border_radius=10)

    def build_gantt() -> ft.Control:
        try:
            plan = scheduling.plan(data["tasks"])
        except ValueError as exc:
            return ft.Text(str(exc), color="#b91c1c")
        if not plan:
            return ft.Text("Add a few tasks to see the Gantt chart.", color="#64748b")
        total_days = max(row["finish_day"] for row in plan)
        cell = max(42, min(92, 720 / max(1, total_days)))
        axis = ft.Row(
            [ft.Container(width=220, content=ft.Text("Task", weight=ft.FontWeight.BOLD, color="#475569"))]
            + [ft.Container(width=cell, content=ft.Text(str(day), size=11, color="#64748b"), alignment=ft.Alignment.CENTER) for day in range(total_days + 1)],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
        )
        rows: list[ft.Control] = []
        palette = ["#4f46e5", "#0891b2", "#7c3aed", "#0f766e", "#2563eb"]
        for index, task in enumerate(plan):
            offset = task["start_day"] * cell
            bar_width = max(38, task["duration"] * cell - 8)
            bar = ft.Container(
                content=ft.Text(task["name"], color=ft.Colors.WHITE, size=11, weight=ft.FontWeight.BOLD, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                width=bar_width,
                height=28,
                padding=ft.Padding.symmetric(horizontal=8, vertical=5),
                bgcolor=palette[index % len(palette)],
                border_radius=7,
                tooltip=f"Day {task['start_day']} to day {task['finish_day']} · {task['duration']} day(s)",
            )
            rows.append(
                ft.Row(
                    [ft.Container(width=220, content=ft.Text(task["name"], size=12, color="#334155", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)),
                     ft.Container(width=offset), bar],
                    spacing=0,
                    height=38,
                )
            )
        chart = ft.Column([axis, ft.Divider(height=1, color="#e2e8f0"), *rows], spacing=5, scroll=ft.ScrollMode.AUTO)
        return chart

    def add_tracking(name: str) -> None:
        try:
            tracking.add_item(data, name)
            save()
            refresh("Tracking")
        except (ValueError, OSError) as exc:
            show_error(str(exc))

    def set_tracking_state(item_id: int, state: str) -> None:
        try:
            tracking.set_state(data, item_id, state)
            save()
            refresh("Tracking")
        except (ValueError, OSError) as exc:
            show_error(str(exc))

    def add_supply(name: str, qty: str, reorder: str) -> None:
        try:
            supply.add_supply(data, name, int(qty), int(reorder))
            save()
            refresh("Supplies")
        except (ValueError, OSError) as exc:
            show_error("Enter a supply name and whole-number stock levels." if isinstance(exc, ValueError) and "invalid literal" in str(exc) else str(exc))

    def adjust_supply(supply_id: int, delta: int) -> None:
        try:
            supply.adjust(data, supply_id, delta)
            save()
            refresh("Supplies")
        except (ValueError, OSError) as exc:
            show_error(str(exc))

    def add_task(name: str, duration: str, dependencies: str) -> None:
        try:
            scheduling.add_task(data, name, int(duration), dependencies)
            save()
            refresh("Schedule")
        except (ValueError, OSError) as exc:
            show_error("Enter a task name and duration as a whole number." if isinstance(exc, ValueError) and "invalid literal" in str(exc) else str(exc))

    def show_error(message: str) -> None:
        page.open(ft.SnackBar(ft.Text(message), bgcolor="#b91c1c"))

    def build_screen(name: str) -> ft.Control:
        if name == "Overview":
            active = sum(item["state"] != "Complete" for item in data["items"])
            blocked = sum(item["state"] == "Blocked" for item in data["items"])
            shortage_count = len(supply.shortages(data))
            return ft.Column(
                [
                    title_block("Operations overview", "Local status, actionable alerts, and quick agent review."),
                    ft.Row([metric("Active items", str(active), ft.Icons.TASK_ALT, "#4f46e5"), metric("Blocked", str(blocked), ft.Icons.BLOCK, "#dc2626"), metric("Low supplies", str(shortage_count), ft.Icons.INVENTORY_2_OUTLINED, "#d97706")], spacing=12),
                    ft.Row([review_field, ft.FilledButton("Run review", icon=ft.Icons.PLAY_ARROW, on_click=run_review)], vertical_alignment=ft.CrossAxisAlignment.END),
                    card(review_result),
                    auto_label,
                    ft.Text("Autonomous checks repeat every 15 seconds while this desktop app is open. Agents report issues; they do not order supplies or silently change task states.", size=12, color="#64748b"),
                ],
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
            )
        if name == "Tracking":
            name_field = ft.TextField(label="New tracked item", expand=True)
            controls: list[ft.Control] = [title_block("Tracking agent", "Track work and update its state.")]
            controls.append(ft.Row([name_field, ft.FilledButton("Add item", icon=ft.Icons.ADD, on_click=lambda e: add_tracking(name_field.value or ""))]))
            if not data["items"]:
                controls.append(card(ft.Text("No tracked items yet.")))
            for item in data["items"]:
                state_select = ft.Dropdown(label="State", value=item["state"], width=160, options=[ft.dropdown.Option(value) for value in ITEM_STATES])
                controls.append(card(ft.Row([ft.Column([ft.Text(item["name"], weight=ft.FontWeight.BOLD), ft.Text("Updated " + item.get("updated", ""), size=11, color="#64748b")], expand=True), state_select, ft.OutlinedButton("Save state", on_click=lambda e, iid=item["id"], sel=state_select: set_tracking_state(iid, sel.value or "Planned"))])))
            return ft.Column(controls, spacing=12, scroll=ft.ScrollMode.AUTO)
        if name == "Supplies":
            name_field, qty_field, reorder_field = ft.TextField(label="Supply name", expand=True), ft.TextField(label="Quantity", value="10", width=120), ft.TextField(label="Reorder at", value="3", width=120)
            controls = [title_block("Supply agent", "Maintain local stock and catch low inventory."), ft.Row([name_field, qty_field, reorder_field, ft.FilledButton("Save", icon=ft.Icons.SAVE, on_click=lambda e: add_supply(name_field.value or "", qty_field.value or "", reorder_field.value or ""))])]
            if not data["supplies"]:
                controls.append(card(ft.Text("No supply items yet.")))
            for item in data["supplies"]:
                is_low = item["quantity"] <= item["reorder_at"]
                controls.append(card(ft.Row([ft.Icon(ft.Icons.WARNING_AMBER if is_low else ft.Icons.CHECK_CIRCLE, color="#d97706" if is_low else "#059669"), ft.Column([ft.Text(item["name"], weight=ft.FontWeight.BOLD), ft.Text(f"{item['quantity']} in stock · reorder at {item['reorder_at']}", size=12, color="#64748b")], expand=True), ft.IconButton(ft.Icons.REMOVE, tooltip="Use one", on_click=lambda e, sid=item["id"]: adjust_supply(sid, -1)), ft.Text(str(item["quantity"]), width=30, text_align=ft.TextAlign.CENTER), ft.IconButton(ft.Icons.ADD, tooltip="Add one", on_click=lambda e, sid=item["id"]: adjust_supply(sid, 1))])))
            return ft.Column(controls, spacing=12, scroll=ft.ScrollMode.AUTO)
        if name == "Schedule":
            task_field, duration_field, dependency_field = ft.TextField(label="Task", expand=True), ft.TextField(label="Duration (days)", value="1", width=145), ft.TextField(label="Dependencies (comma-separated task names)", expand=True)
            controls = [title_block("Scheduling agent", "Dependency-aware Gantt chart. Independent tasks can run in parallel."), ft.Row([task_field, duration_field, dependency_field, ft.FilledButton("Add task", icon=ft.Icons.ADD, on_click=lambda e: add_task(task_field.value or "", duration_field.value or "", dependency_field.value or ""))]), card(build_gantt()), ft.Text("Bars use relative days. This baseline planner does not yet model people, rooms, or other shared resources.", size=12, color="#64748b")]
            if data["tasks"]:
                controls.append(ft.Text("Dependencies: " + " · ".join(f"{t['name']} ← {', '.join(t['depends_on']) or 'none'}" for t in data["tasks"]), size=11, color="#64748b"))
            return ft.Column(controls, spacing=14, scroll=ft.ScrollMode.AUTO)
        if name == "MicroLM":
            corpus = ft.TextField(label="Training corpus", value=STARTER_CORPUS, multiline=True, min_lines=8, max_lines=16)
            epochs = ft.TextField(label="Epochs", value="80", width=130)
            prompt = ft.TextField(label="Generation prompt", value="school", expand=True)
            status = ft.Text("Training is local and runs on CPU.", color="#64748b")
            generated = ft.Text("Train the model, then generate a sample.", selectable=True)

            async def train_clicked(e: Any) -> None:
                try:
                    count = int(epochs.value or "80")
                    status.value = "Training…"
                    page.update()
                    result = await asyncio.to_thread(train_model, corpus.value or "", project_root() / "data" / "microlm.pt", count)
                    status.value = f"Trained · {result['parameters']:,} parameters · loss {result['final_loss']:.3f}"
                    data["events"].insert(0, {"time": timestamp(), "message": f"MicroLM: trained {result['parameters']:,} parameters"})
                    save()
                except Exception as exc:
                    status.value = f"Training failed: {exc}"
                page.update()

            async def generate_clicked(e: Any) -> None:
                try:
                    generated.value = await asyncio.to_thread(generate_text, project_root() / "data" / "microlm.pt", prompt.value or "school")
                except Exception as exc:
                    generated.value = str(exc)
                page.update()

            return ft.Column([title_block("MicroLM training", "Train a local character-level PyTorch GRU (over 1,000 parameters)."), corpus, ft.Row([epochs, ft.FilledButton("Train model", icon=ft.Icons.MODEL_TRAINING, on_click=train_clicked), status]), card(ft.Column([ft.Row([prompt, ft.OutlinedButton("Generate", icon=ft.Icons.AUTO_AWESOME, on_click=generate_clicked)]), generated], spacing=12))], spacing=14, scroll=ft.ScrollMode.AUTO)
        events = data["events"][:300]
        event_rows = [card(ft.Row([ft.Text(event.get("time", ""), size=11, color="#64748b", width=190), ft.Text(event.get("message", ""), size=12, expand=True)])) for event in events]
        if not event_rows:
            event_rows = [card(ft.Text("No activity yet."))]
        return ft.Column([title_block("Agent activity", "Recent local actions and autonomous alerts."), *event_rows], spacing=8, scroll=ft.ScrollMode.AUTO)

    def nav_changed(e: Any) -> None:
        index = e.control.selected_index or 0
        refresh(destinations[index][0])

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=92,
        group_alignment=-0.9,
        bgcolor=ft.Colors.WHITE,
        indicator_color="#dbeafe",
        on_change=nav_changed,
        destinations=[ft.NavigationRailDestination(icon=icon, selected_icon=icon, label=label) for label, icon in destinations],
    )
    header = ft.Container(
        content=ft.Row([ft.Column([ft.Text("MicroOps", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE), ft.Text("Offline agent workspace", size=12, color="#bfdbfe")], spacing=1), ft.Container(expand=True), ft.Icon(ft.Icons.CLOUD_OFF, color="#bfdbfe"), ft.Text("LOCAL", size=11, weight=ft.FontWeight.BOLD, color="#bfdbfe")]),
        bgcolor="#172554",
        padding=ft.Padding.symmetric(horizontal=22, vertical=14),
    )
    page.add(header, ft.Row([rail, ft.VerticalDivider(width=1, color="#e2e8f0"), body], expand=True, spacing=0))
    refresh("Overview")

    async def autonomous_loop() -> None:
        while True:
            try:
                result = autonomous.cycle(data)
                auto_label.value = ("● All checks clear" if result["healthy"] else f"● {len(result['alerts'])} alert(s): " + " · ".join(result["alerts"])) + f" · {result['checked']}"
                if result["changed"]:
                    save()
                    if selected["screen"] == "Overview" or selected["screen"] == "Schedule":
                        refresh()
                    else:
                        page.update()
            except (OSError, ValueError) as exc:
                auto_label.value = f"Automatic check failed: {exc}"
                page.update()
            await asyncio.sleep(15)

    page.run_task(autonomous_loop)


def launch() -> None:
    ft.run(main)


if __name__ == "__main__":
    launch()
