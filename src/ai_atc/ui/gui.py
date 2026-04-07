from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
import time
import queue
import threading
import logging
from ai_atc.config import config

logger = logging.getLogger(__name__)

PALETTE = {
    "bg": "#0B0E14",
    "surface": "#111520",
    "surface_dim": "#0D1117",
    "border": "#1E2433",
    "border_dim": "#161B22",
    "accent": "#3B82F6",
    "accent_dim": "#1D3461",
    "green": "#22C55E",
    "green_dim": "#14532D",
    "red": "#EF4444",
    "red_dim": "#7F1D1D",
    "amber": "#F59E0B",
    "amber_dim": "#78350F",
    "purple": "#A855F7",
    "purple_dim": "#3B0764",
    "muted": "#4B5563",
    "label": "#6B7280",
    "text": "#E2E8F0",
    "text_dim": "#94A3B8",
}

FONT_MONO = "JetBrains Mono"
FONT_UI = "Inter"


class SettingsPanel(ctk.CTkFrame):
    """Hidden by default, handles configuration of X-Plane and SimBrief."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=PALETTE["surface"], corner_radius=12, border_width=1, border_color=PALETTE["border"], **kwargs)

        header = ctk.CTkLabel(
            self,
            text="SYSTEM SETTINGS",
            font=ctk.CTkFont(family=FONT_UI, size=12, weight="bold"),
            text_color=PALETTE["accent"],
        )
        header.pack(pady=(16, 12))

        # X-Plane Path
        ctk.CTkLabel(self, text="X-PLANE LOCATION", font=ctk.CTkFont(family=FONT_MONO, size=9), text_color=PALETTE["label"]).pack(anchor="w", padx=20)
        path_frame = ctk.CTkFrame(self, fg_color="transparent")
        path_frame.pack(fill="x", padx=20, pady=(4, 12))
        
        self.path_entry = ctk.CTkEntry(path_frame, height=32, fg_color=PALETTE["bg"], border_color=PALETTE["border"], text_color=PALETTE["text"], font=ctk.CTkFont(family=FONT_MONO, size=10))
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.path_entry.insert(0, config.get("xplane_path", ""))
        
        self.browse_btn = ctk.CTkButton(path_frame, text="BROWSE", width=80, height=32, fg_color=PALETTE["accent_dim"], hover_color=PALETTE["accent"], font=ctk.CTkFont(family=FONT_UI, size=10, weight="bold"), command=self._on_browse)
        self.browse_btn.pack(side="right")

        # SimBrief / Callsign
        ctk.CTkLabel(self, text="SIMBRIEF USERNAME", font=ctk.CTkFont(family=FONT_MONO, size=9), text_color=PALETTE["label"]).pack(anchor="w", padx=20)
        self.simbrief_entry = ctk.CTkEntry(self, height=32, fg_color=PALETTE["bg"], border_color=PALETTE["border"], text_color=PALETTE["text"], font=ctk.CTkFont(family=FONT_MONO, size=11))
        self.simbrief_entry.pack(fill="x", padx=20, pady=(4, 12))
        self.simbrief_entry.insert(0, config.get("simbrief_username", ""))

        ctk.CTkLabel(self, text="DEFAULT CALLSIGN", font=ctk.CTkFont(family=FONT_MONO, size=9), text_color=PALETTE["label"]).pack(anchor="w", padx=20)
        self.callsign_entry = ctk.CTkEntry(self, height=32, fg_color=PALETTE["bg"], border_color=PALETTE["border"], text_color=PALETTE["text"], font=ctk.CTkFont(family=FONT_MONO, size=11))
        self.callsign_entry.pack(fill="x", padx=20, pady=(4, 12))
        self.callsign_entry.insert(0, config.get("callsign", "N12345"))

        # Save Button
        self.save_btn = ctk.CTkButton(self, text="SAVE & RESTART REQUIRED", height=40, fg_color=PALETTE["green_dim"], hover_color=PALETTE["green"], font=ctk.CTkFont(family=FONT_UI, size=12, weight="bold"), command=self._on_save, text_color=PALETTE["text"])
        self.save_btn.pack(fill="x", padx=20, pady=(8, 20))

    def _on_browse(self):
        folder = filedialog.askdirectory(title="Select X-Plane 11 or 12 Folder")
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _on_save(self):
        config.set("xplane_path", self.path_entry.get().strip())
        config.set("simbrief_username", self.simbrief_entry.get().strip())
        config.set("callsign", self.callsign_entry.get().strip())
        self.master._show_settings(False)


class FlightDataPanel(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=PALETTE["surface"], corner_radius=12, border_width=1, border_color=PALETTE["border"], **kwargs)

        header = ctk.CTkLabel(self, text="FLIGHT DATA", font=ctk.CTkFont(family=FONT_UI, size=10, weight="bold"), text_color=PALETTE["label"])
        header.pack(anchor="w", padx=12, pady=(8, 4))
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.phase_val = self._make_row(container, "PHASE", "PARKED", PALETTE["purple"])
        self.runway_val = self._make_row(container, "RUNWAY", "---", PALETTE["text_dim"])
        self.squawk_val = self._make_row(container, "SQUAWK", "----", PALETTE["green"])
        self.alt_val = self._make_row(container, "ALTITUDE", "0 / ---", PALETTE["text"])
        self.hdg_val = self._make_row(container, "HEADING", "000 / ---", PALETTE["text"])
        self.spd_val = self._make_row(container, "SPEED", "0 / ---", PALETTE["text"])

    def _make_row(self, parent, label, value, color) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        lbl = ctk.CTkLabel(row, text=label, font=ctk.CTkFont(family=FONT_MONO, size=9), text_color=PALETTE["label"], width=70, anchor="w")
        lbl.pack(side="left")
        val = ctk.CTkLabel(row, text=value, font=ctk.CTkFont(family=FONT_MONO, size=12, weight="bold"), text_color=color, anchor="e", justify="right")
        val.pack(side="right")
        return val


class RadioPanel(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=PALETTE["surface"], corner_radius=12, border_width=1, border_color=PALETTE["border"], **kwargs)
        header = ctk.CTkLabel(self, text="COMMS & NAV", font=ctk.CTkFont(family=FONT_UI, size=10, weight="bold"), text_color=PALETTE["label"])
        header.pack(anchor="w", padx=12, pady=(8, 4))
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        active_frame = ctk.CTkFrame(self.container, fg_color=PALETTE["surface_dim"], corner_radius=8)
        active_frame.pack(fill="x", pady=(0, 8))
        self.status_val = ctk.CTkLabel(active_frame, text="On frequency", font=ctk.CTkFont(family=FONT_MONO, size=9, weight="bold"), text_color=PALETTE["green"])
        self.status_val.pack(anchor="w", padx=8, pady=(4, 0))
        self.cur_fac_val = self._make_row(active_frame, "ACTIVE", "---", PALETTE["text"])
        self.next_fac_val = self._make_row(active_frame, "NEXT", "---", PALETTE["text_dim"])
        ctk.CTkFrame(self.container, height=1, fg_color=PALETTE["border"]).pack(fill="x", pady=(4, 8))
        self._rows: dict[str, ctk.CTkLabel] = {}
        self.cur_fac_name = ""

    def _make_row(self, parent, label, value, color) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(family=FONT_MONO, size=9), text_color=PALETTE["label"], width=50, anchor="w").pack(side="left")
        val = ctk.CTkLabel(row, text=value, font=ctk.CTkFont(family=FONT_MONO, size=11, weight="bold"), text_color=color, anchor="e", justify="right")
        val.pack(side="right")
        return val

    def update_panel(self, cur_fac, cur_freq, next_fac, next_freq, pending, frequencies: dict[str, int]) -> None:
        c_freq = f"{cur_freq:.3f}" if cur_freq else "---"
        n_freq = f"{next_freq:.3f}" if next_freq else "---"
        self.cur_fac_val.configure(text=f"{cur_fac} ({c_freq})")
        self.next_fac_val.configure(text=f"{next_fac} ({n_freq})")
        if pending and cur_freq:
            self.status_val.configure(text=f"TUNE {cur_freq:.3f}", text_color=PALETTE["amber"])
        else:
            self.status_val.configure(text="On frequency", text_color=PALETTE["green"])
        LABELS = {"ATIS": "ATIS", "DELIVERY": "DELIVERY", "GROUND": "GROUND", "TOWER": "TOWER", "DEPARTURE": "DEPARTURE", "APPROACH": "APPROACH", "CENTER": "CENTER"}
        for facility, hz in frequencies.items():
            label = LABELS.get(facility, facility)
            mhz = hz / 100.0
            freq_str = f"{mhz:.3f}"
            if facility not in self._rows:
                row = ctk.CTkFrame(self.container, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=label, font=ctk.CTkFont(family=FONT_MONO, size=9), text_color=PALETTE["label"], width=70, anchor="w").pack(side="left")
                val_lbl = ctk.CTkLabel(row, text=freq_str, font=ctk.CTkFont(family=FONT_MONO, size=11, weight="bold"), text_color=PALETTE["accent"], anchor="e", justify="right")
                val_lbl.pack(side="right")
                self._rows[facility] = val_lbl
            else:
                self._rows[facility].configure(text=freq_str)
                color = PALETTE["green"] if facility == self.cur_fac_name else PALETTE["accent"]
                self._rows[facility].configure(text_color=color)


class StatusBar(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=PALETTE["surface"], corner_radius=8, height=36, **kwargs)
        self._indicators: dict[str, ctk.CTkLabel] = {}
        items = [("MIC", "mic"), ("STT", "brain"), ("TALK", "mouth")]
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.pack(side="left", padx=16, pady=6)
        for label, key in items:
            ind = ctk.CTkFrame(left, fg_color="transparent")
            ind.pack(side="left", padx=8)
            dot = ctk.CTkLabel(ind, text="", width=8, height=8, fg_color=PALETTE["muted"], corner_radius=4)
            dot.pack(side="left", padx=(0, 4))
            name = ctk.CTkLabel(ind, text=label, font=ctk.CTkFont(family=FONT_MONO, size=9, weight="bold"), text_color=PALETTE["muted"])
            name.pack(side="left")
            self._indicators[key] = (dot, name)
        self._meter = ctk.CTkFrame(self, fg_color=PALETTE["surface_dim"], corner_radius=2, height=4, width=80)
        self._meter.pack(side="right", padx=16, pady=10)
        self._bar = ctk.CTkFrame(self._meter, fg_color=PALETTE["accent"], corner_radius=2, width=0, height=4)
        self._bar.place(x=0, y=0)
        ctk.CTkLabel(self, text="AUDIO", font=ctk.CTkFont(family=FONT_MONO, size=8, weight="bold"), text_color=PALETTE["muted"]).pack(side="right")

    def set_status(self, component: str, status: str) -> None:
        mapping = {
            "mic": {"recording": PALETTE["red"], "idle": PALETTE["muted"]},
            "brain": {"thinking": PALETTE["accent"], "idle": PALETTE["muted"], "error": PALETTE["red"]},
            "mouth": {"talking": PALETTE["green"], "idle": PALETTE["muted"]},
        }
        pair = self._indicators.get(component)
        if pair:
            colors = mapping.get(component, {}).get(status, PALETTE["muted"])
            pair[0].configure(fg_color=colors)
            pair[1].configure(text_color=colors)

    def set_volume(self, level: float) -> None:
        w = int(max(0, min(1, level * 10.0)) * 80)
        self._bar.configure(width=w)


class CommLog(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(header_row, text="COMM LOG", font=ctk.CTkFont(family=FONT_UI, size=10, weight="bold"), text_color=PALETTE["label"]).pack(side="left")
        self._text = ctk.CTkTextbox(self, font=ctk.CTkFont(family=FONT_MONO, size=13), fg_color=PALETTE["surface"], text_color=PALETTE["text"], corner_radius=8, border_width=1, border_color=PALETTE["border"], wrap="word")
        self._text.pack(fill="both", expand=True)
        self._text.configure(state="disabled")

    def append(self, speaker: str, text: str, facility: str = "") -> None:
        self._text.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._text.insert("end", f"[{ts}]  ", "ts")
        if speaker == "ATC":
            fac = f"[{facility}]  " if facility else ""
            self._text.insert("end", fac, "facility")
            self._text.insert("end", "ATC  ", "atc_label")
            self._text.insert("end", f"{text}\n\n", "atc_text")
        else:
            self._text.insert("end", "PILOT  ", "pilot_label")
            self._text.insert("end", f"{text}\n\n", "pilot_text")
        self._text.tag_config("ts", foreground=PALETTE["muted"])
        self._text.tag_config("facility", foreground=PALETTE["amber"])
        self._text.tag_config("atc_label", foreground=PALETTE["accent"])
        self._text.tag_config("pilot_label", foreground=PALETTE["green"])
        self._text.configure(state="disabled")
        self._text.see("end")


class ATCApp(ctk.CTk):
    def __init__(self, controller, audio_in, stt_engine):
        super().__init__()
        self.controller = controller
        self.audio_in = audio_in
        self.stt_engine = stt_engine
        self._ptt_active = False
        self._last_instr_count = 0
        self._latest_state = None

        ctk.set_appearance_mode("dark")
        self.title("AI ATC")
        self.geometry("1024x640")
        self.configure(fg_color=PALETTE["bg"])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_sidebar()
        self._build_topbar()
        self._build_main()
        self._build_bottom()

        self.settings_panel = SettingsPanel(self)
        
        self.bind("<KeyPress-space>", self._handle_space_press)
        self.bind("<KeyRelease-space>", self._handle_space_release)
        self.after(200, self._update_loop)

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=280, fg_color=PALETTE["bg"])
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=12, pady=12)
        self.sidebar.grid_propagate(False)

        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", pady=(8, 16))
        ctk.CTkLabel(logo_frame, text="AI ATC", font=ctk.CTkFont(family=FONT_UI, size=24, weight="bold"), text_color=PALETTE["text"]).pack(side="left")
        self.flight_info_lbl = ctk.CTkLabel(logo_frame, text="  READY", font=ctk.CTkFont(family=FONT_MONO, size=11, weight="bold"), text_color=PALETTE["accent"])
        self.flight_info_lbl.pack(side="left", pady=(6, 0))

        self.flight_panel = FlightDataPanel(self.sidebar)
        self.flight_panel.pack(fill="x", pady=(0, 12))
        self.radio_panel = RadioPanel(self.sidebar)
        self.radio_panel.pack(fill="x")

        self.cfg_btn = ctk.CTkButton(self.sidebar, text="SYSTEM SETTINGS", fg_color=PALETTE["surface"], hover_color=PALETTE["border"], text_color=PALETTE["label"], font=ctk.CTkFont(family=FONT_UI, size=10, weight="bold"), command=lambda: self._show_settings(True))
        self.cfg_btn.pack(side="bottom", fill="x", pady=4)

    def _build_topbar(self):
        self.topbar = ctk.CTkFrame(self, height=48, fg_color=PALETTE["bg"])
        self.topbar.grid(row=0, column=1, sticky="ew", pady=(12, 0), padx=(0, 16))
        self.status_bar = StatusBar(self.topbar)
        self.status_bar.pack(side="left")
        self._connection_dot = ctk.CTkLabel(self.topbar, text="  X-PLANE DISCONNECTED", font=ctk.CTkFont(family=FONT_MONO, size=10, weight="bold"), text_color=PALETTE["muted"])
        self._connection_dot.pack(side="right")

    def _build_main(self):
        self.comm_log = CommLog(self)
        self.comm_log.grid(row=1, column=1, sticky="nsew", padx=(0, 16), pady=(8, 0))

    def _build_bottom(self):
        bottom = ctk.CTkFrame(self, corner_radius=8, fg_color=PALETTE["surface"], border_width=1, border_color=PALETTE["border"])
        bottom.grid(row=2, column=1, sticky="ew", padx=(0, 16), pady=12)
        bottom.grid_columnconfigure(1, weight=1)
        self.ptt_btn = ctk.CTkButton(bottom, text="PUSH TO TALK", height=36, width=140, fg_color=PALETTE["accent_dim"], hover_color=PALETTE["accent"], command=self._on_ptt_start)
        self.ptt_btn.grid(row=0, column=0, padx=12, pady=12)
        self.ptt_btn.bind("<ButtonPress-1>", lambda e: self._on_ptt_start())
        self.ptt_btn.bind("<ButtonRelease-1>", lambda e: self._on_ptt_stop())
        self.cmd_entry = ctk.CTkEntry(bottom, placeholder_text="Type a direct command...", height=36, fg_color=PALETTE["bg"], border_color=PALETTE["border"])
        self.cmd_entry.grid(row=0, column=1, padx=(0, 16), pady=12, sticky="ew")
        self.cmd_entry.bind("<Return>", lambda e: self._on_cmd_submit())
        self.hearing_label = ctk.CTkLabel(bottom, text="", font=ctk.CTkFont(family=FONT_UI, size=11, slant="italic"), text_color=PALETTE["amber"])
        self.hearing_label.grid(row=0, column=2, padx=(0, 16))

    def _show_settings(self, show: bool):
        if show:
            self.settings_panel.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.4, relheight=0.6)
        else:
            self.settings_panel.place_forget()

    def _update_loop(self):
        c = self.controller
        fp = c.flight_plan
        self.flight_info_lbl.configure(text=f"  |  {fp.callsign}  |  {fp.origin_icao} → {fp.destination_icao}")
        self.flight_panel.phase_val.configure(text=c.current_phase.name.replace("_", " "))
        self.flight_panel.runway_val.configure(text=c.active_runway or "---")
        self.flight_panel.squawk_val.configure(text=f"{c.assigned_squawk:04d}" if c.assigned_squawk else "----")
        
        assign_alt = f"{c.assigned_altitude} FT" if c.assigned_altitude else "---"
        assign_hdg = f"{c.assigned_heading:03.0f}°" if c.assigned_heading else "---"
        assign_spd = f"{c.assigned_speed} KT" if c.assigned_speed else "---"
        
        if self._latest_state:
            s = self._latest_state
            self.flight_panel.alt_val.configure(text=f"{s.altitude_ft:.0f} / {assign_alt}")
            self.flight_panel.hdg_val.configure(text=f"{s.heading_mag:03.0f}° / {assign_hdg}")
            self.flight_panel.spd_val.configure(text=f"{s.groundspeed_kts:.0f} / {assign_spd}")

        self.radio_panel.cur_fac_name = c.target_facility
        self.radio_panel.update_panel(c.target_facility_name, c.target_frequency/100.0 if c.target_frequency else 0, c.next_facility_name, c.next_frequency/100.0 if c.next_frequency else 0, c.handoff_pending, c.get_all_frequencies())
        
        instrs = c.instructions
        if len(instrs) > self._last_instr_count:
            for i in range(self._last_instr_count, len(instrs)):
                self.comm_log.append("ATC", instrs[i].text, instrs[i].facility)
            self._last_instr_count = len(instrs)
        self.after(200, self._update_loop)

    def _on_ptt_start(self):
        if not self._ptt_active:
            self._ptt_active = True
            self.audio_in.start_recording()
            self.ptt_btn.configure(fg_color=PALETTE["red_dim"], text="RECORDING...")

    def _on_ptt_stop(self):
        if self._ptt_active:
            self._ptt_active = False
            self.audio_in.stop_recording()
            self.ptt_btn.configure(fg_color=PALETTE["accent_dim"], text="PUSH TO TALK")

    def _handle_space_press(self, e):
        if self.focus_get() != self.cmd_entry: self._on_ptt_start()

    def _handle_space_release(self, e):
        if self.focus_get() != self.cmd_entry: self._on_ptt_stop()

    def _on_cmd_submit(self):
        txt = self.cmd_entry.get().strip()
        if txt:
            self.cmd_entry.delete(0, "end")
            self.comm_log.append("PILOT", txt)
            self.stt_engine.callback(txt)

    def update_aircraft_state(self, state): self._latest_state = state
    def update_xplane_connection(self, conn):
        self._connection_dot.configure(text="  X-PLANE CONNECTED" if conn else "  X-PLANE DISCONNECTED", text_color=PALETTE["green"] if conn else PALETTE["muted"])
    def set_led_status(self, comp, stat): self.status_bar.set_status(comp, stat)
    def set_hearing(self, txt):
        self.hearing_label.configure(text=f"Hearing: \"{txt}\"...")
        self.after(5000, lambda: self.hearing_label.configure(text=""))
    def update_vu(self, level): self.status_bar.set_volume(level)
    def mainloop(self): super().mainloop()