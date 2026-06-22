# Menu Quick Search

Adds an `F3` quick-search provider for Isaac Sim menu bar actions.

## Usage

1. Add the parent folder of this extension as an extension search path in Isaac Sim.
2. Enable **Menu Quick Search** in `Window > Extensions`.
3. Press `F3`.
4. Search for menu bar entries like `Extensions`, `Console`, `Cable Simulation`, or `Physics Stage Settings`.

The extension captures the visible Isaac Sim menu bar once at extension startup and exposes those entries through Kit Quick Search. Selecting a result executes the underlying menu callback directly where possible, without moving the mouse.

## Notes

- The menu snapshot is captured once per extension startup.
- Menu entries added after startup require reloading the extension to appear.
- `Tab` Quick Search remains unchanged; `F3` opens the menu-only provider.
