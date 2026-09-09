"""Regression checks against real ESPHome code generation (tested with 2026.8.2).

Run with: python -m unittest discover -s tests -v
"""

from collections import Counter
from pathlib import Path
import re
import tempfile
import unittest

import yaml

from esphome.__main__ import generate_cpp_contents
from esphome.config import read_config
from esphome.core import CORE


COMPONENTS = Path(__file__).resolve().parents[1] / "components"


class RegistrationTest(unittest.TestCase):
    def generate(self, controller_count):
        # Reusing one process also checks that singleton state does not leak
        # between independently generated firmware configurations.
        CORE.reset()
        config = {
            "esphome": {"name": "ble-registration-test"},
            "esp32": {"board": "esp32dev", "framework": {"type": "arduino"}},
            "external_components": [{
                "source": {"type": "local", "path": str(COMPONENTS)},
                "components": ["ble_adv_controller"],
            }],
            "ble_adv_controller": [],
            "light": [],
            "button": [],
        }
        for i in range(controller_count):
            controller_id = f"controller_{i}"
            config["ble_adv_controller"].append({
                "id": controller_id,
                "encoding": "lampsmart_pro",
            })
            config["light"].append({
                "platform": "ble_adv_controller",
                "ble_adv_controller_id": controller_id,
                "name": f"Light {i}",
            })
            config["button"].append({
                "platform": "ble_adv_controller",
                "id": f"pair_{i}",
                "ble_adv_controller_id": controller_id,
                "name": f"Pair {i}",
                "cmd": "pair",
            })
        for suffix in ("simulator", "tv"):
            config["button"].append({
                "platform": "template",
                "id": f"hdmi_{suffix}",
                "name": f"HDMI {suffix}",
            })

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.yaml"
            path.write_text(yaml.safe_dump(config, sort_keys=False))
            CORE.config_path = path
            validated = read_config({})
            self.assertIsNotNone(validated)
            CORE.config = validated
            generate_cpp_contents(validated)

        return CORE.cpp_main_section, CORE.cpp_global_section

    def assert_registry_fits(self, source, method, define):
        registrations = re.findall(rf"App\.register_{method}\((\w+)", source)
        capacity = next(int(str(item.value)) for item in CORE.defines if item.name == define)
        self.assertEqual(len(registrations), capacity)
        self.assertTrue(all(count == 1 for count in Counter(registrations).values()))
        return registrations

    def test_shared_handler_and_buttons(self):
        for controller_count in (1, 3, 1):
            with self.subTest(controller_count=controller_count):
                source, globals_ = self.generate(controller_count)
                components = self.assert_registry_fits(
                    source, "component_", "ESPHOME_COMPONENT_COUNT"
                )
                self.assertIn("ble_adv_static_handler", components)
                self.assertTrue(any(name.startswith("esp32_ble_") for name in components))
                self.assertEqual(source.count("new(ble_adv_static_handler)"), 1)
                self.assertIn(
                    "1 * HasLoopOverride<bleadvcontroller::BleAdvHandler>::value",
                    globals_,
                )
                self.assertEqual(source.count("->set_handler(ble_adv_static_handler)"), controller_count)

                buttons = self.assert_registry_fits(
                    source, "button", "ESPHOME_ENTITY_BUTTON_COUNT"
                )
                self.assertEqual(
                    set(buttons),
                    {f"pair_{i}" for i in range(controller_count)} | {"hdmi_simulator", "hdmi_tv"},
                )


if __name__ == "__main__":
    unittest.main()
