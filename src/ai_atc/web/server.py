import asyncio
import json
import logging
import time
import queue
import os
from quart import Quart, websocket, send_from_directory
from ai_atc.atc.controller import ATCController
from ai_atc.flightplan.flight_plan import FlightPlan
from ai_atc.voice.stt import ATCVoiceEngine
from ai_atc.voice.audio import AudioCapture
from ai_atc.voice.tts import ATCVoice
logger = logging.getLogger(__name__)
class WebServer:
    def __init__(
        self,
        controller: ATCController,
        flight_plan: FlightPlan,
        audio_in: AudioCapture,
        stt: ATCVoiceEngine,
        voice_out: ATCVoice,
    ):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.static_dir = os.path.join(current_dir, 'static')
        self.app = Quart(__name__, static_url_path='', static_folder=self.static_dir)
        self.controller = controller
        self.flight_plan = flight_plan
        self.audio_in = audio_in
        self.stt = stt
        self.voice_out = voice_out
        self.clients = set()
        self.broadcast_queue = queue.Queue()
        self._setup_routes()
        self._setup_hooks()
    def _setup_routes(self):
        @self.app.route('/')
        async def index():
            return await send_from_directory(self.static_dir, 'index.html')
        @self.app.websocket('/ws')
        async def ws():
            import asyncio
            await websocket.send_json({
                "type": "state_update",
                "phase": self.controller.current_phase.name,
                "squawk": self.controller.assigned_squawk,
                "altitude": self.controller.assigned_altitude,
                "heading": self.controller.assigned_heading,
                "runway": self.controller.active_runway,
            })
            self.clients.add(websocket._get_current_object())
            try:
                while True:
                    data = await websocket.receive_json()
                    action = data.get("action")
                    if action == "start_ptt":
                        self.audio_in.start_recording()
                    elif action == "stop_ptt":
                        self.audio_in.stop_recording()
            except asyncio.CancelledError:
                pass
            finally:
                self.clients.remove(websocket._get_current_object())
        @self.app.before_serving
        async def startup():
            self.app.add_background_task(self._broadcast_loop)
            self.app.add_background_task(self._state_monitor_loop)
    def _setup_hooks(self):
        original_stt_callback = self.stt.callback
        def wrapped_stt_callback(text: str):
            self.broadcast_queue.put({"type": "transcript", "speaker": "Pilot", "text": text})
            original_stt_callback(text)
        self.stt.callback = wrapped_stt_callback
        def stt_status_cb(status: str):
            self.broadcast_queue.put({"type": "stt_status", "status": status})
        self.stt.status_callback = stt_status_cb
    async def _broadcast_loop(self):
        import asyncio
        while True:
            try:
                msg = self.broadcast_queue.get_nowait()
                for client in set(self.clients):
                    try:
                        await client.send_json(msg)
                    except Exception:
                        self.clients.discard(client)
            except queue.Empty:
                await asyncio.sleep(0.1)
    async def _state_monitor_loop(self):
        import asyncio
        last_instr_count = 0
        while True:
            current_count = len(self.controller.instructions)
            if current_count > last_instr_count:
                for i in range(last_instr_count, current_count):
                    instr = self.controller.instructions[i]
                    self.broadcast_queue.put({
                        "type": "transcript", 
                        "speaker": "ATC", 
                        "text": instr.text,
                        "time": instr.time_str
                    })
                last_instr_count = current_count
            self.broadcast_queue.put({
                "type": "state_update",
                "phase": self.controller.current_phase.name,
                "squawk": self.controller.assigned_squawk,
                "altitude": self.controller.assigned_altitude,
                "heading": self.controller.assigned_heading,
                "runway": self.controller.active_runway,
            })
            await asyncio.sleep(1.0)
    def run(self, host="127.0.0.1", port=5000):
        logger.info(f"Starting beyondATC UI on http://{host}:{port}")
        self.app.run(host=host, port=port, use_reloader=False)