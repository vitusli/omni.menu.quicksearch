import asyncio
import re
from functools import partial
from typing import Callable, Optional

import carb
import omni.ui as ui


ActionFn = Callable[[], None]
_MENU_SNAPSHOT = {}
_TRIGGER_MAP = {}


def set_menu_snapshot(menu_snapshot: dict, trigger_map: Optional[dict] = None):
    global _MENU_SNAPSHOT, _TRIGGER_MAP
    _MENU_SNAPSHOT = menu_snapshot or {}
    _TRIGGER_MAP = trigger_map or {}


class MenuQuickSearchItem(ui.AbstractItem):
    def __init__(
        self,
        name: str,
        path: str,
        action: Optional[ActionFn] = None,
        children: Optional[list["MenuQuickSearchItem"]] = None,
    ):
        super().__init__()
        self.name = name
        self.path = path
        self.action = action
        self.children = children or []
        self.name_model = ui.SimpleStringModel(self.name)
        self.description_model = ui.SimpleStringModel(self.path)
        self.icon_model = ui.SimpleStringModel("")
        self.tooltip_model = ui.SimpleStringModel(self.path)


class MenuQuickSearchModel(ui.AbstractItemModel):
    def __init__(self):
        super().__init__()
        self._action_map, self._actions_by_leaf = self._build_action_maps()
        self._items = self._build_items()

    def destroy(self):
        self._items = []
        self._action_map = {}
        self._actions_by_leaf = {}

    def get_item_children(self, item):
        if item is None:
            return self._items
        return item.children

    def get_item_value_model_count(self, item):
        return 4

    def get_item_value_model(self, item, column_id):
        if item is None:
            return None
        if column_id == 0:
            return item.name_model
        if column_id == 1:
            return item.description_model
        if column_id == 2:
            return item.icon_model
        if column_id == 3:
            return item.tooltip_model
        return None

    def execute(self, item):
        if item and item.action:
            item.action()

    def complete(self, current_value: str, item) -> str:
        return item.path if item else current_value

    def _build_items(self) -> list[MenuQuickSearchItem]:
        items = []
        seen = set()
        for menu_name, entries in _MENU_SNAPSHOT.items():
            if menu_name == "_":
                continue
            children = list(self._flatten_entries(entries, (menu_name,), seen))
            if children:
                items.append(MenuQuickSearchItem(menu_name, menu_name, children=children))
        if not items:
            for menu_name, entries in self._build_menu_dict_from_actions().items():
                children = list(self._flatten_entries(entries, (menu_name,), seen))
                if children:
                    items.append(MenuQuickSearchItem(menu_name, menu_name, children=children))
        return items

    def _build_menu_dict_from_actions(self) -> dict:
        menu_dict = {}
        for path in self._action_map:
            if len(path) < 2:
                continue
            output = menu_dict.setdefault(path[0], {})
            for name in path[1:-1]:
                output = output.setdefault(name, {})
            output.setdefault("_", []).append(path[-1])
        return menu_dict

    def _build_action_maps(self) -> tuple[dict[tuple[str, ...], ActionFn], dict[str, list[tuple[tuple[str, ...], ActionFn]]]]:
        try:
            import omni.kit.menu.utils

            menus = omni.kit.menu.utils.get_merged_menus() or {}
        except Exception as exc:
            carb.log_warn(f"[MenuQuickSearch] Could not read menu actions: {exc}")
            return {}, {}

        action_map = {}
        for menu_name, entries in menus.items():
            self._collect_actions(entries, (self._clean_name(menu_name),), action_map)

        actions_by_leaf = {}
        for path, action in action_map.items():
            if path:
                actions_by_leaf.setdefault(path[-1], []).append((path, action))
        return action_map, actions_by_leaf

    def _collect_actions(self, entries, prefix: tuple[str, ...], action_map: dict[tuple[str, ...], ActionFn]):
        for entry in entries or []:
            name = self._entry_name(entry)
            if not name:
                continue

            path = (*prefix, name)
            sub_menu = getattr(entry, "sub_menu", None)
            if sub_menu:
                self._collect_actions(sub_menu, path, action_map)
                continue

            action = self._entry_action(entry, path)
            if action:
                action_map[path] = action

    def _flatten_entries(
        self,
        entries: dict,
        prefix: tuple[str, ...],
        seen: set[str],
    ):
        if not isinstance(entries, dict):
            return

        for name, sub_menu in (entries or {}).items():
            if name == "_":
                continue
            path = (*prefix, name)
            path_text = " > ".join(path)
            children = list(self._flatten_entries(sub_menu, path, seen))
            if children:
                yield MenuQuickSearchItem(name, path_text, children=children)

        for name in (entries or {}).get("_", []):
            path = (*prefix, name)
            path_text = " > ".join(path)
            if path_text in seen:
                continue
            seen.add(path_text)
            action = partial(self._execute_menu_path, path)
            yield MenuQuickSearchItem(name, path_text, action)

    def _entry_name(self, entry) -> str:
        name_fn = getattr(entry, "name_fn", None)
        if name_fn:
            try:
                return self._clean_name(name_fn())
            except Exception as exc:
                carb.log_warn(f"[MenuQuickSearch] Could not resolve dynamic menu name: {exc}")
        return self._clean_name(getattr(entry, "name", ""))

    def _clean_name(self, name) -> str:
        return re.sub(r"[^\x00-\x7F]+", " ", str(name or "")).lstrip()

    def _entry_action(self, entry, path: tuple[str, ...]) -> Optional[ActionFn]:
        onclick_action = getattr(entry, "onclick_action", None)
        unclick_action = getattr(entry, "unclick_action", None)
        if onclick_action and unclick_action:
            return partial(self._execute_actions, (onclick_action, unclick_action), path)
        if onclick_action:
            return partial(self._execute_actions, (onclick_action,), path)

        onclick_fn = getattr(entry, "onclick_fn", None)
        unclick_fn = getattr(entry, "unclick_fn", None)
        if onclick_fn and unclick_fn:
            return partial(self._execute_fns, (onclick_fn, unclick_fn), path)
        if onclick_fn:
            return partial(self._execute_fns, (onclick_fn,), path)
        return None

    def _resolve_action(self, path: tuple[str, ...]) -> Optional[ActionFn]:
        trigger_fn = _TRIGGER_MAP.get(path)
        if trigger_fn:
            return partial(self._execute_trigger_fn, trigger_fn, path)

        action = self._action_map.get(path)
        if action:
            return action

        suffix_matches = [action for action_path, action in self._action_map.items() if self._endswith(action_path, path)]
        if len(suffix_matches) == 1:
            return suffix_matches[0]

        leaf_matches = self._actions_by_leaf.get(path[-1], [])
        if len(leaf_matches) == 1:
            return leaf_matches[0][1]

        return None

    def _endswith(self, candidate: tuple[str, ...], suffix: tuple[str, ...]) -> bool:
        return len(candidate) >= len(suffix) and candidate[-len(suffix) :] == suffix

    def _execute_menu_path(self, path: tuple[str, ...]):
        action = self._resolve_action(path)
        if not action:
            carb.log_warn(f"[MenuQuickSearch] No direct operator found for menubar path {' > '.join(path)}")
            return
        action()

    def _execute_trigger_fn(self, trigger_fn: ActionFn, path: tuple[str, ...]):
        try:
            trigger_fn()
        except Exception as exc:
            carb.log_warn(f"[MenuQuickSearch] Could not execute menubar trigger {' > '.join(path)}: {exc}")

    def _execute_actions(self, actions: tuple[tuple, ...], path: tuple[str, ...]):
        try:
            import omni.kit.app
            import omni.kit.actions.core
            from omni.kit.menu.utils import MenuActionControl

            async_delay = all(MenuActionControl.NODELAY not in action for action in actions)
            cleaned_actions = [
                tuple(item for item in action if item not in (MenuActionControl.NONE, MenuActionControl.NODELAY))
                for action in actions
            ]

            def execute_all():
                for action in cleaned_actions:
                    omni.kit.actions.core.execute_action(*action)

            if async_delay:

                async def execute_later():
                    await omni.kit.app.get_app().next_update_async()
                    execute_all()

                asyncio.ensure_future(execute_later())
            else:
                execute_all()
        except Exception as exc:
            carb.log_warn(f"[MenuQuickSearch] Could not execute menu action {' > '.join(path)}: {exc}")

    def _execute_fns(self, fns: tuple[ActionFn, ...], path: tuple[str, ...]):
        try:
            for fn in fns:
                fn()
        except Exception as exc:
            carb.log_warn(f"[MenuQuickSearch] Could not execute menu function {' > '.join(path)}: {exc}")
