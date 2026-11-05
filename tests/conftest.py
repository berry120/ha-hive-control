"""Load the protocol package without importing HA's OS-specific runtime."""

import sys
from pathlib import Path
from types import ModuleType

package = ModuleType("custom_components.hive_local")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "hive_local")]
sys.modules["custom_components.hive_local"] = package
