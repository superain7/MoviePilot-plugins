from typing import Any, Dict, List, Tuple
import asyncio
import urllib.parse

import httpx

from app.sdk.plugin import _PluginBase
from app.sdk.logging import logger


class EmbyPlaybackBark(_PluginBase):
    plugin_name = "Emby播放Bark通知"
    plugin_desc = "检测Emby中正在播放的用户，通过Bark推送用户名和影片名。"
    plugin_version = "1.0.0"
    plugin_author = "your_name"
    plugin_config_prefix = "embyplaybackbark_"

    _enabled: bool = False
    _task: asyncio.Task | None = None
    _stop_event: asyncio.Event | None = None

    _emby_url: str = ""
    _emby_api_key: str = ""
    _bark_url: str = ""
    _interval: int = 30

    def init_plugin(self, config: dict | None = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._emby_url = str(config.get("emby_url") or "").rstrip("/")
        self._emby_api_key = str(config.get("emby_api_key") or "")
        self._bark_url = str(config.get("bark_url") or "").rstrip("/")
        self._interval = int(config.get("interval") or 30)

        self._stop_monitor()

        if not self._enabled:
            return
        if not self._emby_url or not self._emby_api_key or not self._bark_url:
            logger.error("Emby播放Bark通知：配置不完整，监控未启动")
            return

        self._start_monitor()

    def get_state(self) -> bool:
        return self._enabled

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}},
                    {"component": "VTextField", "props": {"model": "emby_url", "label": "Emby服务器地址", "placeholder": "http://192.168.1.100:8096"}},
                    {"component": "VTextField", "props": {"model": "emby_api_key", "label": "Emby API Key", "type": "password"}},
                    {"component": "VTextField", "props": {"model": "bark_url", "label": "Bark推送地址", "placeholder": "https://api.day.app/你的设备Key"}},
                    {"component": "VTextField", "props": {"model": "interval", "label": "检查间隔（秒）", "type": "number"}},
                ],
            }
        ], {
            "enabled": False,
            "emby_url": "",
            "emby_api_key": "",
            "bark_url": "",
            "interval": 30,
        }

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self) -> None:
        self._stop_monitor()
        self._enabled = False

    def _start_monitor(self) -> None:
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._monitor_loop())

    def _stop_monitor(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._stop_event = None

    async def _monitor_loop(self) -> None:
        while self._stop_event and not self._stop_event.is_set():
            try:
                await self._check_and_notify()
            except Exception as e:
                logger.error(f"Emby播放检查失败：{e}")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue
            else:
                break

    async def _check_and_notify(self) -> None:
        sessions = await self._fetch_playing_sessions()
        for session in sessions:
            user = session.get("UserName", "未知用户")
            item = session.get("NowPlayingItem") or {}
            title = item.get("Name", "未知影片")
            await self._send_bark(user, title)

    async def _fetch_playing_sessions(self) -> List[dict]:
        url = f"{self._emby_url}/Sessions"
        headers = {"X-Emby-Token": self._emby_api_key}
        params = {"IsPlaying": "true"}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        active: List[dict] = []
        for s in data:
            if not s.get("NowPlayingItem"):
                continue
            if s.get("PlayState", {}).get("IsPaused", False):
                continue
            active.append(s)
        return active

    async def _send_bark(self, user: str, title: str) -> None:
        push_title = "Emby播放提醒"
        push_body = f"{user} 正在观看《{title}》"
        url = (
            f"{self._bark_url}/"
            f"{urllib.parse.quote(push_title)}/"
            f"{urllib.parse.quote(push_body)}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Bark推送失败：{resp.status_code}")