"""A compact Tkinter interface for the offline MicroOps agents."""

from __future__ import annotations

import sys
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from .agents import AgentCoordinator, AutonomousAgentTeam, ITEM_STATES, SchedulingAgent, SupplyAgent, TrackingAgent, timestamp
from .micro_lm import STARTER_CORPUS, generate_text, train_model
from .store import Store


APP_NAME = "MicroOps — Offline Agent Desk"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


class MicroOpsApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("980x680")
        self.root.minsize(820, 560)
        self.store = Store(project_root() / "data" / "microops.json")
        self.tracking = TrackingAgent()
        self.supply = SupplyAgent()
        self.scheduling = SchedulingAgent()
        self.coordinator = AgentCoordinator(self.tracking, self.supply, self.scheduling)
        self.autonomous = AutonomousAgentTeam(self.tracking, self.supply, self.scheduling)
        self.training_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.training_active = False
        self.data = self.store.load()
        self._style()
        self._build()
        self.refresh()

    def _style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background="#f4f6fa")
        style.configure("Hero.TLabel", font=("Segoe UI", 20, "bold"), background="#f4f6fa", foreground="#17253b")
        style.configure("Sub.TLabel", font=("Segoe UI", 10), background="#f4f6fa", foreground="#516178")
        style.configure("Card.TLabelframe", background="#ffffff", padding=12)
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 11, "bold"), foreground="#263c59")
        style.configure("TButton", padding=(10, 6))

    def _build(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="MicroOps", style="Hero.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Three local agents for tracking, supplies, and a simple dependency-aware plan.", style="Sub.TLabel").pack(anchor="w", pady=(2, 14))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self.tracking_tab = ttk.Frame(self.notebook, padding=14)
        self.supply_tab = ttk.Frame(self.notebook, padding=14)
        self.schedule_tab = ttk.Frame(self.notebook, padding=14)
        self.activity_tab = ttk.Frame(self.notebook, padding=14)
        self.home_tab = ttk.Frame(self.notebook, padding=14)
        self.model_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.home_tab, text="Agent Desk")
        self.notebook.add(self.tracking_tab, text="Tracking Agent")
        self.notebook.add(self.supply_tab, text="Supply Agent")
        self.notebook.add(self.schedule_tab, text="Scheduling Agent")
        self.notebook.add(self.activity_tab, text="Agent Activity")
        self.notebook.add(self.model_tab, text="Train MicroLM")
        self._build_tracking()
        self._build_supply()
        self._build_schedule()
        self._build_activity()
        self._build_home()
        self._build_model()
        ttk.Label(outer, text="Offline by default  •  Data stays in this project’s data folder", style="Sub.TLabel").pack(anchor="w", pady=(10, 0))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(300, self._poll_training)
        self.root.after(2500, self._autonomous_cycle)

    def _build_home(self) -> None:
        ttk.Label(self.home_tab, text="Run all three agents", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(self.home_tab, text="Describe a goal or ask for a status review. The coordinator checks local tracking, inventory, and schedule data.", wraplength=820).pack(anchor="w", pady=(4, 12))
        prompt = ttk.LabelFrame(self.home_tab, text="Your request", style="Card.TLabelframe")
        prompt.pack(fill="x")
        self.request_text = tk.Text(prompt, height=4, wrap="word", font=("Segoe UI", 10), relief="solid", borderwidth=1)
        self.request_text.pack(fill="x", pady=(0, 10))
        ttk.Button(prompt, text="Run local agents", command=self.run_agents).pack(anchor="e")
        self.auto_status = tk.StringVar(value="Autonomous checks starting…")
        ttk.Label(self.home_tab, textvariable=self.auto_status, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 2))
        ttk.Label(self.home_tab, text="Checks run every 15 seconds while this window is open. Agents detect issues and suggest actions; they never order supplies automatically.", wraplength=820).pack(anchor="w")
        self.report = tk.Text(self.home_tab, height=12, wrap="word", font=("Segoe UI", 10), state="disabled", relief="flat", background="#ffffff", padx=14, pady=12)
        self.report.pack(fill="both", expand=True, pady=(14, 0))

    def run_agents(self) -> None:
        request = self.request_text.get("1.0", "end").strip()
        try:
            result = self.coordinator.run(self.data, request)
            self.store.save(self.data)
            self.refresh()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Could not run agents", str(exc), parent=self.root)
            return
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        lines = [
            f"Request: {result['request']}",
            "",
            f"TRACKING AGENT   {result['tracking']}",
            f"SUPPLY AGENT       {result['supply']}",
            f"SCHEDULING AGENT   {result['scheduling']}",
        ]
        if result["shortages"]:
            lines.extend(["", "Reorder: " + ", ".join(result["shortages"])])
        if result["plan"]:
            lines.extend(["", "Plan:"])
            lines.extend(f"  Day {row['start_day']}–{row['finish_day']}: {row['name']}" for row in result["plan"])
        self.report.insert("1.0", "\n".join(lines))
        self.report.configure(state="disabled")

    def _build_model(self) -> None:
        ttk.Label(self.model_tab, text="Train your local MicroLM", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(self.model_tab, text="Character-level PyTorch GRU. Training and generation run locally; your text is saved only in the model checkpoint.", wraplength=820).pack(anchor="w", pady=(4, 10))
        corpus_frame = ttk.LabelFrame(self.model_tab, text="Training text", style="Card.TLabelframe")
        corpus_frame.pack(fill="both", expand=True)
        self.corpus_text = tk.Text(corpus_frame, height=10, wrap="word", font=("Consolas", 10))
        self.corpus_text.pack(fill="both", expand=True, pady=(0, 8))
        self.corpus_text.insert("1.0", STARTER_CORPUS)
        controls = ttk.Frame(self.model_tab)
        controls.pack(fill="x", pady=8)
        ttk.Label(controls, text="Epochs:").pack(side="left")
        self.epochs_var = tk.StringVar(value="80")
        ttk.Entry(controls, textvariable=self.epochs_var, width=8).pack(side="left", padx=6)
        self.train_button = ttk.Button(controls, text="Train model", command=self.start_training)
        self.train_button.pack(side="left", padx=6)
        self.training_status = tk.StringVar(value="Not trained yet")
        ttk.Label(controls, textvariable=self.training_status).pack(side="left", padx=10)
        generation = ttk.LabelFrame(self.model_tab, text="Generate a sample", style="Card.TLabelframe")
        generation.pack(fill="x")
        self.generation_prompt = tk.StringVar(value="school")
        ttk.Entry(generation, textvariable=self.generation_prompt).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(generation, text="Generate", command=self.generate_sample).pack(side="left")
        self.generation_output = tk.StringVar(value="Train a model to generate text.")
        ttk.Label(generation, textvariable=self.generation_output, wraplength=760).pack(anchor="w", pady=(8, 0))

    def _autonomous_cycle(self) -> None:
        if not self.root.winfo_exists():
            return
        try:
            result = self.autonomous.cycle(self.data)
            if result["changed"]:
                self.store.save(self.data)
                self.refresh()
            if result["healthy"]:
                self.auto_status.set(f"● All checks clear · last checked {result['checked']}")
            else:
                self.auto_status.set(f"● {len(result['alerts'])} alert(s) · last checked {result['checked']}")
            if hasattr(self, "plan_tree"):
                rows = [((row["name"], row["start_day"], row["finish_day"], row["duration"]), row["name"]) for row in result["plan"]]
                self._fill(self.plan_tree, rows)
        except (OSError, ValueError) as exc:
            self.auto_status.set(f"Autonomous check failed: {exc}")
        self.root.after(15000, self._autonomous_cycle)

    def start_training(self) -> None:
        if self.training_active:
            return
        try:
            epochs = self._integer(self.epochs_var.get(), "Epochs", minimum=1)
            if epochs > 2000:
                raise ValueError("Epochs must be 2000 or fewer.")
            corpus = self.corpus_text.get("1.0", "end")
            output = project_root() / "data" / "microlm.pt"
        except ValueError as exc:
            messagebox.showerror("Training settings", str(exc), parent=self.root)
            return
        self.training_active = True
        self.train_button.configure(state="disabled")
        self.training_status.set("Training on CPU…")

        def report(epoch: int, total: int, loss: float) -> None:
            self.training_queue.put(("progress", (epoch, total, loss)))

        def worker() -> None:
            try:
                result = train_model(corpus, output, epochs, report)
                self.training_queue.put(("done", result))
            except Exception as exc:  # surfaced in the UI; thread must not crash silently
                self.training_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="MicroLM-training").start()

    def _poll_training(self) -> None:
        try:
            while True:
                kind, payload = self.training_queue.get_nowait()
                if kind == "progress":
                    epoch, total, loss = payload
                    self.training_status.set(f"Epoch {epoch}/{total} · loss {loss:.3f}")
                elif kind == "done":
                    self.training_active = False
                    self.train_button.configure(state="normal")
                    self.training_status.set(f"Trained · {payload['parameters']:,} parameters · loss {payload['final_loss']:.3f}")
                    self.data["events"].insert(0, {"time": timestamp(), "message": f"MicroLM: trained {payload['parameters']:,} parameters"})
                    self.store.save(self.data)
                    self.refresh()
                elif kind == "error":
                    self.training_active = False
                    self.train_button.configure(state="normal")
                    self.training_status.set("Training failed")
                    messagebox.showerror("Training failed", str(payload), parent=self.root)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(300, self._poll_training)

    def generate_sample(self) -> None:
        try:
            result = generate_text(project_root() / "data" / "microlm.pt", self.generation_prompt.get())
            self.generation_output.set(result)
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            messagebox.showerror("Could not generate", str(exc), parent=self.root)

    def close(self) -> None:
        self.root.destroy()

    def _build_tracking(self) -> None:
        form = ttk.LabelFrame(self.tracking_tab, text="Add tracked item", style="Card.TLabelframe")
        form.pack(fill="x")
        self.item_name = tk.StringVar()
        ttk.Entry(form, textvariable=self.item_name).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(form, text="Add item", command=self.add_item).pack(side="left")
        actions = ttk.Frame(self.tracking_tab)
        actions.pack(fill="x", pady=(12, 6))
        ttk.Label(actions, text="Set selected item state:").pack(side="left", padx=(0, 8))
        self.state_choice = tk.StringVar(value="In Progress")
        ttk.Combobox(actions, textvariable=self.state_choice, values=ITEM_STATES, state="readonly", width=16).pack(side="left")
        ttk.Button(actions, text="Update state", command=self.update_state).pack(side="left", padx=8)
        self.items_tree = self._tree(self.tracking_tab, ("name", "state", "updated"), ("Item", "State", "Last updated"))

    def _build_supply(self) -> None:
        form = ttk.LabelFrame(self.supply_tab, text="Add or update supply", style="Card.TLabelframe")
        form.pack(fill="x")
        self.supply_name = tk.StringVar()
        self.supply_qty = tk.StringVar(value="10")
        self.supply_reorder = tk.StringVar(value="3")
        self._field(form, "Supply", self.supply_name, 0, 22)
        self._field(form, "Quantity", self.supply_qty, 1, 8)
        self._field(form, "Reorder at", self.supply_reorder, 2, 8)
        ttk.Button(form, text="Save supply", command=self.add_supply).grid(row=0, column=6, padx=(12, 0))
        actions = ttk.Frame(self.supply_tab)
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text="−1 stock", command=lambda: self.adjust_supply(-1)).pack(side="left")
        ttk.Button(actions, text="+1 stock", command=lambda: self.adjust_supply(1)).pack(side="left", padx=6)
        self.shortage_label = ttk.Label(actions, text="")
        self.shortage_label.pack(side="left", padx=12)
        self.supplies_tree = self._tree(self.supply_tab, ("name", "quantity", "reorder", "status"), ("Supply", "In stock", "Reorder at", "Agent check"))

    def _build_schedule(self) -> None:
        form = ttk.LabelFrame(self.schedule_tab, text="Add task", style="Card.TLabelframe")
        form.pack(fill="x")
        self.task_name = tk.StringVar()
        self.task_duration = tk.StringVar(value="1")
        self.task_dependencies = tk.StringVar()
        self._field(form, "Task", self.task_name, 0, 20)
        self._field(form, "Days", self.task_duration, 1, 6)
        self._field(form, "Depends on (task names, comma-separated)", self.task_dependencies, 2, 30)
        ttk.Button(form, text="Add task", command=self.add_task).grid(row=0, column=6, padx=(12, 0))
        actions = ttk.Frame(self.schedule_tab)
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text="Build plan", command=self.build_plan).pack(side="left")
        ttk.Label(actions, text="Serial plan honors dependencies; days are relative to day 0.").pack(side="left", padx=10)
        self.plan_tree = self._tree(self.schedule_tab, ("name", "start", "finish", "duration"), ("Task", "Start day", "Finish day", "Duration"))

    def _build_activity(self) -> None:
        self.activity_tree = self._tree(self.activity_tab, ("time", "message"), ("Time", "Agent event"))
        self.activity_tree.column("message", width=650)

    @staticmethod
    def _field(parent: ttk.LabelFrame, label: str, variable: tk.StringVar, column: int, width: int) -> None:
        ttk.Label(parent, text=label).grid(row=0, column=column * 2, sticky="w", padx=(0, 4))
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=0, column=column * 2 + 1, sticky="w", padx=(0, 12))

    @staticmethod
    def _tree(parent: ttk.Frame, columns: tuple[str, ...], headings: tuple[str, ...]) -> ttk.Treeview:
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        tree = ttk.Treeview(holder, columns=columns, show="headings", selectmode="browse")
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=160, anchor="w")
        return tree

    def _change(self, operation: Callable[[], object]) -> bool:
        try:
            operation()
            self.store.save(self.data)
            self.refresh()
            return True
        except (ValueError, OSError) as exc:
            messagebox.showerror("Could not complete action", str(exc), parent=self.root)
            return False

    @staticmethod
    def _integer(value: str, field: str, minimum: int = 0) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a whole number.") from exc
        if parsed < minimum:
            raise ValueError(f"{field} must be at least {minimum}.")
        return parsed

    def add_item(self) -> None:
        if self._change(lambda: self.tracking.add_item(self.data, self.item_name.get())):
            self.item_name.set("")

    def update_state(self) -> None:
        selected = self.items_tree.selection()
        if not selected:
            messagebox.showinfo("Select an item", "Choose an item first.", parent=self.root)
            return
        self._change(lambda: self.tracking.set_state(self.data, int(selected[0]), self.state_choice.get()))

    def add_supply(self) -> None:
        def action() -> None:
            quantity = self._integer(self.supply_qty.get(), "Quantity")
            reorder = self._integer(self.supply_reorder.get(), "Reorder level")
            self.supply.add_supply(self.data, self.supply_name.get(), quantity, reorder)
        if self._change(action):
            self.supply_name.set("")

    def adjust_supply(self, delta: int) -> None:
        selected = self.supplies_tree.selection()
        if not selected:
            messagebox.showinfo("Select a supply", "Choose a supply first.", parent=self.root)
            return
        self._change(lambda: self.supply.adjust(self.data, int(selected[0]), delta))

    def add_task(self) -> None:
        def action() -> None:
            duration = self._integer(self.task_duration.get(), "Duration", minimum=1)
            self.scheduling.add_task(self.data, self.task_name.get(), duration, self.task_dependencies.get())
        if self._change(action):
            self.task_name.set("")
            self.task_dependencies.set("")

    def build_plan(self) -> None:
        try:
            plan = self.scheduling.plan(self.data["tasks"])
        except ValueError as exc:
            messagebox.showerror("Cannot build plan", str(exc), parent=self.root)
            return
        self._fill(self.plan_tree, [((row["name"], row["start_day"], row["finish_day"], row["duration"]), row["name"]) for row in plan])

    def refresh(self) -> None:
        self._fill(self.items_tree, [((item["name"], item["state"], item.get("updated", "")), item["id"]) for item in self.data["items"]])
        shortages = self.supply.shortages(self.data)
        short_ids = {item["id"] for item in shortages}
        self._fill(self.supplies_tree, [((item["name"], item["quantity"], item["reorder_at"], "LOW — reorder" if item["id"] in short_ids else "OK"), item["id"]) for item in self.data["supplies"]])
        self.shortage_label.configure(text=f"⚠ {len(shortages)} supply item(s) at or below reorder level" if shortages else "All supplies above reorder level")
        self._fill(self.activity_tree, [((event.get("time", ""), event.get("message", "")), "") for event in self.data["events"][:500]])

    @staticmethod
    def _fill(tree: ttk.Treeview, rows: list[tuple[tuple[object, ...], object]]) -> None:
        tree.delete(*tree.get_children())
        for values, iid in rows:
            tree.insert("", "end", iid=str(iid) if iid != "" else None, values=values)


def main() -> None:
    root = tk.Tk()
    try:
        MicroOpsApp(root)
    except (ValueError, OSError) as exc:
        messagebox.showerror("MicroOps could not start", str(exc), parent=root)
        root.destroy()
        return
    root.mainloop()
