import asyncio

import carb
import carb.input
import omni.ext
import omni.kit.app

from omni.kit.window.quicksearch import QuickSearchRegistry
from omni.kit.window.quicksearch.quicksearch_window import QuickSearchWindow

from .model import MenuQuickSearchModel, set_menu_snapshot


ACTION_ID = "ShowMenuQuickSearch"
ACTION_DISPLAY_NAME = "Menu Quick Search"


class MenuQuickSearchExtension(omni.ext.IExt):
    def __init__(self):
        super().__init__()
        self._ext_id = None
        self._subscription = None
        self._window = None
        self._exclusive = False
        self._hotkey = None
        self._keyboard_sub_id = None
        self._keyboard = None
        self._input = None
        self._action_registry = None
        self._hotkey_registry = None
        self._snapshot_task = None

    def on_startup(self, ext_id: str):
        self._ext_id = omni.ext.get_extension_name(ext_id)
        self._exclusive = False
        self._subscription = QuickSearchRegistry().register_quick_search_model(
            "Menu Bar",
            MenuQuickSearchModel,
            None,
            exclusive_fn=self._is_exclusive,
            priority=5,
            flat_search=True,
        )
        self._snapshot_task = asyncio.ensure_future(self._capture_menu_snapshot())
        self._register_f3_hotkey()
        carb.log_info("[MenuQuickSearch] Registered menu quick-search provider")

    def on_shutdown(self):
        if self._snapshot_task and not self._snapshot_task.done():
            self._snapshot_task.cancel()
        self._snapshot_task = None
        self._deregister_f3_hotkey()
        self._subscription = None
        if self._window:
            self._window.destroy()
            self._window = None
        carb.log_info("[MenuQuickSearch] Unregistered menu quick-search provider")

    def show_window(self):
        self._exclusive = True
        self._capture_menu_snapshot_once()
        if not self._window:
            self._window = QuickSearchWindow()
        else:
            self._window.show()
        asyncio.ensure_future(self._clear_exclusive_next_frame())

    def _is_exclusive(self):
        return self._exclusive

    async def _clear_exclusive_next_frame(self):
        await omni.kit.app.get_app().next_update_async()
        self._exclusive = False

    async def _capture_menu_snapshot(self):
        for _ in range(120):
            if self._capture_menu_snapshot_once():
                return
            await omni.kit.app.get_app().next_update_async()

        carb.log_warn("[MenuQuickSearch] Could not capture menubar snapshot during startup")

    def _capture_menu_snapshot_once(self):
        try:
            from omni.kit.mainwindow import get_main_window

            main_window = get_main_window()
            if not main_window:
                return False

            menu_bar = main_window.get_main_menu_bar()
            menu_dict, trigger_map = self._capture_menu_bar(menu_bar)
            if not menu_dict:
                return False

            set_menu_snapshot(menu_dict, trigger_map)
            carb.log_info(f"[MenuQuickSearch] Captured {len(menu_dict)} menubar roots")
            return True
        except Exception as exc:
            carb.log_warn(f"[MenuQuickSearch] Menubar snapshot not ready yet: {exc}")
            return False

    def _capture_menu_bar(self, menu_bar):
        import re
        import omni.ui as ui

        menu_dict = {}
        trigger_map = {}

        def clean_name(name):
            return re.sub(r"[^\x00-\x7F]+", " ", str(name or "")).lstrip()

        def walk(menu_root, output, prefix):
            for menu_item in ui.Inspector.get_children(menu_root):
                if not getattr(menu_item, "enabled", True) or not getattr(menu_item, "visible", True):
                    continue
                if not isinstance(menu_item, (ui.Menu, ui.MenuItem)):
                    continue

                name = clean_name(getattr(menu_item, "text", ""))
                if not name:
                    continue

                path = (*prefix, name)
                if isinstance(menu_item, ui.Menu):
                    child_dict = {}
                    walk(menu_item, child_dict, path)
                    if child_dict:
                        output[name] = child_dict
                    elif menu_item.has_triggered_fn():
                        output.setdefault("_", []).append(name)
                        trigger_map[path] = menu_item.call_triggered_fn
                elif menu_item.has_triggered_fn():
                    output.setdefault("_", []).append(name)
                    trigger_map[path] = menu_item.call_triggered_fn

        walk(menu_bar, menu_dict, ())
        return menu_dict, trigger_map

    def _register_f3_hotkey(self):
        try:
            from omni.kit.actions.core import get_action_registry
            from omni.kit.hotkeys.core import KeyCombination, get_hotkey_registry

            key = KeyCombination(carb.input.KeyboardInput.F3)
            if not key.as_string:
                raise ImportError

            self._action_registry = get_action_registry()
            self._action_registry.register_action(
                self._ext_id,
                ACTION_ID,
                lambda: self.show_window(),
                display_name=ACTION_DISPLAY_NAME,
                description="Open Quick Search for menubar entries",
                tag="Menu Quick Search",
            )
            self._hotkey_registry = get_hotkey_registry()
            self._hotkey = self._hotkey_registry.register_hotkey(self._ext_id, key, self._ext_id, ACTION_ID)
        except ImportError:
            self._register_keyboard_fallback()
        except Exception as exc:
            carb.log_warn(f"[MenuQuickSearch] Could not register F3 hotkey: {exc}")
            self._register_keyboard_fallback()

    def _deregister_f3_hotkey(self):
        if self._hotkey_registry:
            try:
                self._hotkey_registry.deregister_all_hotkeys_for_extension(self._ext_id)
            except Exception as exc:
                carb.log_warn(f"[MenuQuickSearch] Could not deregister F3 hotkey: {exc}")
            self._hotkey_registry = None
            self._hotkey = None
        if self._action_registry:
            try:
                self._action_registry.deregister_all_actions_for_extension(self._ext_id)
            except Exception as exc:
                carb.log_warn(f"[MenuQuickSearch] Could not deregister action: {exc}")
            self._action_registry = None
        if self._keyboard_sub_id is not None and self._input and self._keyboard:
            try:
                self._input.unsubscribe_to_keyboard_events(self._keyboard, self._keyboard_sub_id)
            except Exception as exc:
                carb.log_warn(f"[MenuQuickSearch] Could not unsubscribe keyboard fallback: {exc}")
            self._keyboard_sub_id = None

    def _register_keyboard_fallback(self):
        if self._keyboard_sub_id is not None:
            return
        try:
            import omni.appwindow

            app_window = omni.appwindow.get_default_app_window()
            if not app_window:
                return
            self._keyboard = app_window.get_keyboard()
            self._input = carb.input.acquire_input_interface()
            self._keyboard_sub_id = self._input.subscribe_to_keyboard_events(self._keyboard, self._on_keyboard_event)
        except Exception as exc:
            carb.log_warn(f"[MenuQuickSearch] Could not register keyboard fallback: {exc}")

    def _on_keyboard_event(self, event):
        if event.type == carb.input.KeyboardEventType.KEY_PRESS:
            if event.modifiers == 0 and event.input == carb.input.KeyboardInput.F3:
                self.show_window()
        return True
