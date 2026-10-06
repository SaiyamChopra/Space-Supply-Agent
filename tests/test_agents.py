import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from micro_ops.agents import AgentCoordinator, SchedulingAgent, SupplyAgent, TrackingAgent
from micro_ops.store import Store


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.data = {"items": [], "supplies": [], "tasks": [], "events": []}

    def test_tracking_updates_state_and_records_event(self):
        agent = TrackingAgent()
        item = agent.add_item(self.data, "Prototype")
        agent.set_state(self.data, item["id"], "In Progress")
        self.assertEqual("In Progress", item["state"])
        self.assertIn("In Progress", self.data["events"][0]["message"])

    def test_supply_shortage_threshold_inclusive(self):
        agent = SupplyAgent()
        agent.add_supply(self.data, "Bolts", 3, 3)
        self.assertEqual(["Bolts"], [row["name"] for row in agent.shortages(self.data)])
        with self.assertRaises(ValueError):
            agent.adjust(self.data, 1, -4)

    def test_plan_respects_dependencies_and_detects_cycles(self):
        agent = SchedulingAgent()
        agent.add_task(self.data, "Prepare", 2)
        agent.add_task(self.data, "Build", 3, "Prepare")
        plan = agent.plan(self.data["tasks"])
        self.assertEqual(["Prepare", "Build"], [task["name"] for task in plan])
        self.assertEqual(2, plan[1]["start_day"])
        self.data["tasks"][0]["depends_on"] = ["Build"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            agent.plan(self.data["tasks"])

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.json")
            data = store.load()
            data["items"].append({"id": 1, "name": "A"})
            store.save(data)
            self.assertEqual("A", store.load()["items"][0]["name"])

    def test_coordinator_runs_all_three_agents_offline(self):
        tracking = TrackingAgent()
        supply = SupplyAgent()
        scheduling = SchedulingAgent()
        tracking.add_item(self.data, "Delivery")
        supply.add_supply(self.data, "Boxes", 1, 2)
        scheduling.add_task(self.data, "Pack", 1)
        coordinator = AgentCoordinator(tracking, supply, scheduling)
        result = coordinator.run(self.data, "Review today's operations")
        self.assertIn("1 active", result["tracking"])
        self.assertIn("1 shortage", result["supply"])
        self.assertIn("1 task", result["scheduling"])
        self.assertEqual(["Boxes"], result["shortages"])
        self.assertIn("Coordinator:", self.data["events"][0]["message"])

    def test_coordinator_rejects_empty_request(self):
        coordinator = AgentCoordinator(TrackingAgent(), SupplyAgent(), SchedulingAgent())
        with self.assertRaisesRegex(ValueError, "Describe"):
            coordinator.run(self.data, "  ")


if __name__ == "__main__":
    unittest.main()
