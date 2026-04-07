from __future__ import annotations
import time
from typing import TYPE_CHECKING
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
if TYPE_CHECKING:
    from ai_atc.atc.controller import ATCController
    from ai_atc.flightplan.flight_plan import FlightPlan
    from ai_atc.weather.metar import MetarData
    from ai_atc.xplane.aircraft import AircraftState
class TerminalUI:
    def __init__(self) -> None:
        self.console = Console()
        self._live: Live | None = None
    def start(self) -> Live:
        self._live = Live(
            self._build_placeholder(),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        )
        self._live.start()
        return self._live
    def stop(self) -> None:
        if self._live:
            self._live.stop()
    def update(
        self,
        aircraft: AircraftState,
        controller: ATCController,
        flight_plan: FlightPlan,
        metar: MetarData | None = None,
        connected: bool = False,
    ) -> None:
        if self._live:
            layout = self._build_layout(
                aircraft, controller, flight_plan, metar, connected
            )
            self._live.update(layout)
    def _build_placeholder(self) -> Panel:
        return Panel(
            "[bold yellow]Connecting to X-Plane...[/]",
            title="[bold cyan]AI ATC[/]",
        )
    def _build_layout(
        self,
        aircraft: AircraftState,
        controller: ATCController,
        flight_plan: FlightPlan,
        metar: MetarData | None,
        connected: bool,
    ) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        status = "[bold green]● CONNECTED[/]" if connected else "[bold red]● DISCONNECTED[/]"
        phase = controller.current_phase.display
        header_text = Text.from_markup(
            f" AI ATC  {status}  │  Phase: [bold cyan]{phase}[/]  │  "
            f"Callsign: [bold white]{flight_plan.airline_callsign}[/]  │  "
            f"Runway: [bold yellow]{controller.active_runway or 'N/A'}[/]"
        )
        layout["header"].update(Panel(header_text, style="bold"))
        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )
        left_panels = []
        left_panels.append(self._build_aircraft_panel(aircraft))
        if metar:
            left_panels.append(self._build_metar_panel(metar, controller))
        left_panels.append(self._build_flightplan_panel(flight_plan))
        layout["left"].split_column(
            *[Layout(name=f"l{i}", ratio=1) for i in range(len(left_panels))]
        )
        for i, panel in enumerate(left_panels):
            layout[f"l{i}"].update(panel)
        layout["right"].update(self._build_instructions_panel(controller))
        footer = Text.from_markup(
            " [dim]Commands:[/] [bold]C[/]=Clearance  [bold]P[/]=Pushback  "
            "[bold]T[/]=Taxi  [bold]K[/]=Takeoff  [bold]V[/]=Toggle Voice  "
            "[bold]Q[/]=Quit"
        )
        layout["footer"].update(Panel(footer, style="dim"))
        return layout
    def _build_aircraft_panel(self, ac: AircraftState) -> Panel:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Label", style="dim")
        table.add_column("Value", style="bold white")
        table.add_column("Label2", style="dim")
        table.add_column("Value2", style="bold white")
        table.add_row(
            "LAT", f"{ac.latitude:.5f}",
            "LON", f"{ac.longitude:.5f}",
        )
        table.add_row(
            "ALT", f"{ac.altitude_ft:.0f} ft",
            "GS", f"{ac.groundspeed_kts:.0f} kts",
        )
        table.add_row(
            "HDG", f"{ac.heading_mag:.0f}°",
            "VS", f"{ac.vertical_speed_fpm:+.0f} fpm",
        )
        table.add_row(
            "IAS", f"{ac.airspeed_kts:.0f} kts",
            "GND", "YES" if ac.on_ground else "NO",
        )
        table.add_row(
            "GEAR", "DOWN" if ac.gear_is_down else "UP",
            "BRK", "SET" if ac.parking_brake_set else "OFF",
        )
        return Panel(table, title="[bold cyan]Aircraft State[/]")
    def _build_metar_panel(
        self, metar: MetarData, controller: ATCController
    ) -> Panel:
        lines = []
        lines.append(f"[dim]Station:[/] {metar.station}")
        if metar.wind:
            lines.append(f"[dim]Wind:[/] {metar.wind}")
        lines.append(f"[dim]Visibility:[/] {metar.visibility_sm} SM")
        if metar.ceiling_ft:
            lines.append(f"[dim]Ceiling:[/] {metar.ceiling_ft} ft")
        lines.append(f"[dim]Altimeter:[/] {metar.altimeter_inhg:.2f}")
        lines.append(f"[dim]Flight Rules:[/] {metar.flight_rules}")
        return Panel(
            "\n".join(lines),
            title=f"[bold cyan]METAR / ATIS {controller._active_runway}[/]",
        )
    def _build_flightplan_panel(self, fp: FlightPlan) -> Panel:
        lines = []
        lines.append(
            f"[dim]Route:[/] {fp.origin_icao} → {fp.destination_icao}"
        )
        lines.append(
            f"[dim]Cruise:[/] FL{fp.cruise_altitude_ft // 100}"
        )
        if fp.sid_name:
            lines.append(f"[dim]SID:[/] {fp.sid_name}")
        if fp.star_name:
            lines.append(f"[dim]STAR:[/] {fp.star_name}")
        lines.append(
            f"[dim]Progress:[/] {fp.progress_percent:.0f}% "
            f"({fp.current_waypoint_index}/{len(fp.waypoints)} wpts)"
        )
        if fp.squawk:
            lines.append(f"[dim]Squawk:[/] {fp.squawk:04d}")
        return Panel(
            "\n".join(lines),
            title="[bold cyan]Flight Plan[/]",
        )
    def _build_instructions_panel(self, controller: ATCController) -> Panel:
        lines = []
        instructions = controller.instructions[-20:]
        for instr in instructions:
            phase_color = "green" if instr.phase.is_ground else "cyan"
            lines.append(
                f"[dim]{instr.time_str}[/] "
                f"[{phase_color}]{instr.phase.display}[/]"
            )
            lines.append(f"  [bold white]{instr.text}[/]")
            lines.append("")
        if not lines:
            lines.append("[dim]No instructions yet. Press C for clearance.[/]")
        return Panel(
            "\n".join(lines),
            title="[bold cyan]ATC Instructions[/]",
        )