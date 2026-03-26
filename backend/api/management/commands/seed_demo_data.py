from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import CorrectiveAction, Defect, DefectHistory, FiveWhyAnalysis, WorkflowStatus


@dataclass(frozen=True)
class _SeedDefect:
    defect_key: str
    title: str
    description: str
    severity: str
    priority: str
    status_code: str

    # Additional logging fields
    part_number: str
    defect_type: str
    quantity_affected: int | None
    production_line: str
    shift: str

    # People/metadata
    reported_by: str
    assigned_to: str
    area: str
    source: str

    # Relative dates (in days from "now")
    occurred_days_ago: int
    created_days_ago: int
    due_in_days: int | None  # negative => overdue; None => no due date

    # Optional closure (in days ago)
    closed_days_ago: int | None

    # Optional 5-Why/root cause (if provided, we create a FiveWhyAnalysis)
    five_why: dict | None

    # Optional corrective actions list
    actions: list[dict]


def _get_or_seed_statuses() -> dict[str, WorkflowStatus]:
    """
    Ensure the workflow statuses required by the demo exist.

    The project currently has a workflow seeding command, but it seeds a slightly
    different status set. The app code/gating references IN_ANALYSIS and
    ACTIONS_IN_PROGRESS, so we ensure those exist here.
    """
    defaults = [
        ("NEW", "Open", "Reported; awaiting triage", 10, False),
        ("IN_ANALYSIS", "In Analysis", "Root cause investigation in progress", 20, False),
        ("ACTIONS_IN_PROGRESS", "Actions In Progress", "Corrective actions being executed", 30, False),
        ("PENDING_VERIFICATION", "Pending Verification", "Fix/actions completed; awaiting verification", 40, False),
        ("VERIFIED", "Verified", "Verified effective; ready to close", 50, False),
        ("CLOSED", "Closed", "Closed/completed", 60, True),
    ]

    status_by_code: dict[str, WorkflowStatus] = {}
    now = timezone.now()

    for code, name, description, sort_order, is_terminal in defaults:
        obj, _created = WorkflowStatus.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "is_terminal": is_terminal,
                "is_active": True,
                "created_at": now,
            },
        )
        # If pre-existing, we keep user data but ensure it's active so demos work.
        if not obj.is_active:
            obj.is_active = True
            obj.updated_at = now
            obj.save(update_fields=["is_active", "updated_at"])

        status_by_code[code] = obj

    return status_by_code


def _days_ago(n: int) -> timezone.datetime:
    return timezone.now() - timedelta(days=int(n))


def _days_from_now(n: int) -> timezone.datetime:
    return timezone.now() + timedelta(days=int(n))


def _make_history(defect: Defect, *, event_type: str, message: str, actor: str = "system") -> None:
    DefectHistory.objects.create(
        defect=defect,
        event_type=event_type,
        message=message,
        actor=actor,
        from_status=None,
        to_status=defect.status,
    )


def _seed_defects() -> list[_SeedDefect]:
    """
    Demo dataset (20 defects) to create a visually rich dashboard:
    - 5+ closed
    - 5+ open/in analysis
    - 3-5 overdue (non-terminal with past due dates)
    - 5-Why analysis for 5-8 defects
    - Corrective actions for ~8-10 defects (mix done/open/blocked)
    """
    return [
        _SeedDefect(
            defect_key="DEF-1001",
            title="Screen flicker under low brightness after 10 minutes",
            description=(
                "Customer reports intermittent screen flicker when brightness < 20% and device warms up. "
                "Reproducible on Batch 24-03 units. Impacts usability and may indicate unstable display power rail."
            ),
            severity=Defect.Severity.HIGH,
            priority=Defect.Priority.HIGH,
            status_code="IN_ANALYSIS",
            part_number="LCD-5.8-REV-C",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=14,
            production_line="Production Line 1",
            shift="Night",
            reported_by="QA Team",
            assigned_to="Engineering - Display",
            area="Testing",
            source="End-of-line test",
            occurred_days_ago=18,
            created_days_ago=17,
            due_in_days=-5,  # overdue
            closed_days_ago=None,
            five_why={
                "problem_statement": "Display flicker observed at low brightness after thermal soak.",
                "why1": "Why did the screen flicker? → Display backlight PWM signal became unstable.",
                "why2": "Why was PWM unstable? → Driver IC supply voltage dipped intermittently under load.",
                "why3": "Why did supply dip? → DC/DC converter compensation network out of tolerance.",
                "why4": "Why out of tolerance? → Incorrect resistor value used during feeder changeover.",
                "why5": "Why was incorrect value not detected? → Incoming inspection did not verify reel change against BOM.",
                "root_cause": "Incorrect compensation resistor installed due to feeder changeover without BOM verification.",
                "created_by": "Engineering - Display",
            },
            actions=[
                {
                    "title": "Quarantine suspect resistor reels and verify values",
                    "description": "Stop using affected reels; verify compensation resistor value against BOM and labeling.",
                    "owner": "Production",
                    "due_in_days": -2,
                    "status": CorrectiveAction.Status.DONE,
                    "completed_days_ago": 1,
                    "effectiveness_check": "No flicker observed in 20-unit re-test after resistor correction.",
                },
                {
                    "title": "Update incoming inspection checklist for feeder/BOM verification",
                    "description": "Add mandatory check for reel changeover and photo record for critical passives.",
                    "owner": "Quality",
                    "due_in_days": 10,
                    "status": CorrectiveAction.Status.IN_PROGRESS,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                },
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1002",
            title="Speaker crackling at 70% volume on left channel",
            description=(
                "Crackling noise occurs at higher volumes on left speaker only. "
                "Affected units fail audio sweep at 1–2 kHz. Potential solder void or membrane defect."
            ),
            severity=Defect.Severity.MEDIUM,
            priority=Defect.Priority.MEDIUM,
            status_code="ACTIONS_IN_PROGRESS",
            part_number="SPK-1W-REV-A",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=9,
            production_line="Production Line 2",
            shift="Day",
            reported_by="Quality",
            assigned_to="Engineering - Audio",
            area="Assembly",
            source="In-process audit",
            occurred_days_ago=11,
            created_days_ago=10,
            due_in_days=4,
            closed_days_ago=None,
            five_why={
                "problem_statement": "Left speaker crackling at high volume during audio sweep.",
                "why1": "Why crackling? → Intermittent open/short at speaker terminals when vibrating.",
                "why2": "Why intermittent connection? → Cold solder joint on speaker flex connector pin.",
                "why3": "Why cold joint? → Reflow profile below spec during peak temp window.",
                "why4": "Why profile drifted? → Oven zone 4 heater degraded, lowering peak temperature.",
                "why5": "Why not detected? → Preventive maintenance interval exceeded during staffing shortage.",
                "root_cause": "Reflow oven heater degradation caused insufficient peak temperature, leading to cold solder joints.",
                "created_by": "Engineering - Audio",
            },
            actions=[
                {
                    "title": "Replace zone 4 heater element and re-qualify reflow profile",
                    "description": "Maintenance to replace heater; run profile validation with thermocouples.",
                    "owner": "Production",
                    "due_in_days": 1,
                    "status": CorrectiveAction.Status.IN_PROGRESS,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                },
                {
                    "title": "Rework affected WIP units with speaker flex reflow touch-up",
                    "description": "Perform touch-up reflow and audio sweep retest on flagged serials.",
                    "owner": "QA Team",
                    "due_in_days": 3,
                    "status": CorrectiveAction.Status.OPEN,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                },
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1003",
            title="Charging port loose; intermittent connection during cable movement",
            description=(
                "USB-C port shows excessive play. Cable disconnects with minimal movement. "
                "Risk: returns and field failures. Suspected insufficient solder fillet or fixture misalignment."
            ),
            severity=Defect.Severity.CRITICAL,
            priority=Defect.Priority.URGENT,
            status_code="IN_ANALYSIS",
            part_number="USB-C-REV-D",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=6,
            production_line="Production Line 1",
            shift="Swing",
            reported_by="QA Team",
            assigned_to="Engineering - HW",
            area="Assembly",
            source="Customer return",
            occurred_days_ago=33,
            created_days_ago=30,
            due_in_days=-12,  # overdue
            closed_days_ago=None,
            five_why={
                "problem_statement": "USB-C connector loosens and disconnects under minor movement.",
                "why1": "Why disconnect? → Connector shifts and breaks contact.",
                "why2": "Why shifting? → Anchor solder joints have insufficient wetting/fillet.",
                "why3": "Why insufficient wetting? → Flux deposition inconsistent on anchor pads.",
                "why4": "Why inconsistent flux? → Flux nozzle partially clogged; spray pattern uneven.",
                "why5": "Why clog not caught? → Nozzle inspection step removed from weekly checklist.",
                "root_cause": "Flux nozzle clogging led to poor solder wetting on USB-C anchor pads.",
                "created_by": "Engineering - HW",
            },
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1004",
            title="Dead pixels cluster in upper-right quadrant",
            description=(
                "2–5 dead pixels observed on incoming display panels from Supplier X. "
                "Failing visual inspection threshold for premium SKUs."
            ),
            severity=Defect.Severity.HIGH,
            priority=Defect.Priority.MEDIUM,
            status_code="NEW",
            part_number="LCD-5.8-REV-C",
            defect_type=Defect.DefectType.COSMETIC,
            quantity_affected=22,
            production_line="Production Line 2",
            shift="Day",
            reported_by="Quality",
            assigned_to="Supplier Quality",
            area="Quality Check",
            source="Incoming inspection",
            occurred_days_ago=4,
            created_days_ago=4,
            due_in_days=8,
            closed_days_ago=None,
            five_why=None,
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1005",
            title="Cosmetic scratch on bezel after packaging",
            description=(
                "Light scratch observed on anodized bezel. Appears after packaging step; "
                "pattern indicates contact with tray edge. Increases rework time."
            ),
            severity=Defect.Severity.LOW,
            priority=Defect.Priority.LOW,
            status_code="ACTIONS_IN_PROGRESS",
            part_number="BEZ-AL-REV-B",
            defect_type=Defect.DefectType.COSMETIC,
            quantity_affected=38,
            production_line="Production Line 1",
            shift="Day",
            reported_by="QA Team",
            assigned_to="Packaging",
            area="Packaging",
            source="End-of-line test",
            occurred_days_ago=9,
            created_days_ago=9,
            due_in_days=2,
            closed_days_ago=None,
            five_why=None,
            actions=[
                {
                    "title": "Add protective film to bezel contact points in tray",
                    "description": "Apply film or felt strip where bezel contacts tray edge during insertion.",
                    "owner": "Production",
                    "due_in_days": 2,
                    "status": CorrectiveAction.Status.IN_PROGRESS,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                }
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1006",
            title="Overheating during fast-charge (device > 48°C)",
            description=(
                "Thermal test shows device exceeds 48°C at back cover after 25 minutes of 30W fast-charge. "
                "Potential safety concern; needs immediate investigation of thermal pad placement and firmware limits."
            ),
            severity=Defect.Severity.CRITICAL,
            priority=Defect.Priority.URGENT,
            status_code="ACTIONS_IN_PROGRESS",
            part_number="BAT-4200MAH-REV-E",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=5,
            production_line="Production Line 2",
            shift="Night",
            reported_by="Quality",
            assigned_to="Engineering - Power",
            area="Testing",
            source="Reliability test",
            occurred_days_ago=21,
            created_days_ago=20,
            due_in_days=-1,  # overdue
            closed_days_ago=None,
            five_why={
                "problem_statement": "Device exceeds thermal limit during 30W fast-charge reliability test.",
                "why1": "Why overheating? → Heat not dissipating from charge IC and battery area.",
                "why2": "Why poor dissipation? → Thermal pad missing between IC and shield can.",
                "why3": "Why pad missing? → Operator skipped pad placement due to unclear work instruction photo.",
                "why4": "Why unclear instruction? → Photo in WI shows old revision with different shield geometry.",
                "why5": "Why revision not updated? → ECO approval didn't include WI update step.",
                "root_cause": "Work instruction not updated after ECO, leading to missing thermal pad placement.",
                "created_by": "Engineering - Power",
            },
            actions=[
                {
                    "title": "Update work instruction (WI) with correct thermal pad placement photo",
                    "description": "Revise WI and retrain operators for shield assembly step.",
                    "owner": "Engineering",
                    "due_in_days": 5,
                    "status": CorrectiveAction.Status.OPEN,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                },
                {
                    "title": "Screen WIP units for missing thermal pad; rework as needed",
                    "description": "Audit 100% of WIP for pad presence; add pad and re-test thermal.",
                    "owner": "QA Team",
                    "due_in_days": 0,
                    "status": CorrectiveAction.Status.IN_PROGRESS,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                },
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1007",
            title="Battery pack loose rattle heard during shake test",
            description=(
                "Audible rattle from battery region. Foam spacer appears compressed; adhesive not holding. "
                "May lead to connector stress in shipping."
            ),
            severity=Defect.Severity.MEDIUM,
            priority=Defect.Priority.MEDIUM,
            status_code="IN_ANALYSIS",
            part_number="FOAM-SPACER-REV-A",
            defect_type=Defect.DefectType.PACKAGING,
            quantity_affected=12,
            production_line="Production Line 1",
            shift="Night",
            reported_by="QA Team",
            assigned_to="Engineering - ME",
            area="Assembly",
            source="Shake test",
            occurred_days_ago=15,
            created_days_ago=14,
            due_in_days=6,
            closed_days_ago=None,
            five_why={
                "problem_statement": "Battery pack movement causes audible rattle during shake test.",
                "why1": "Why rattle? → Battery pack can move within cavity.",
                "why2": "Why can it move? → Foam spacer is compressed and does not provide preload.",
                "why3": "Why is spacer compressed? → Spacer thickness out of tolerance on recent lot.",
                "why4": "Why out of tolerance? → Supplier changed material density without notification.",
                "why5": "Why not detected? → Incoming inspection lacks compression set / thickness sampling for this spacer.",
                "root_cause": "Foam spacer supplier changed material/density leading to reduced preload; inspection plan missed it.",
                "created_by": "Engineering - ME",
            },
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1008",
            title="Camera images blurred (autofocus hunts in low light)",
            description=(
                "Camera module shows focus hunting in low-light conditions. Blurry images across 30% of test shots. "
                "Suspected firmware tuning or lens contamination."
            ),
            severity=Defect.Severity.HIGH,
            priority=Defect.Priority.HIGH,
            status_code="ACTIONS_IN_PROGRESS",
            part_number="CAM-12MP-REV-F",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=7,
            production_line="Production Line 2",
            shift="Swing",
            reported_by="QA Team",
            assigned_to="Engineering - Camera",
            area="Testing",
            source="End-of-line test",
            occurred_days_ago=27,
            created_days_ago=26,
            due_in_days=3,
            closed_days_ago=None,
            five_why={
                "problem_statement": "Autofocus instability in low light causing blurred images.",
                "why1": "Why blur? → Focus settles late or oscillates.",
                "why2": "Why oscillates? → AF algorithm gain too high for low signal-to-noise scenes.",
                "why3": "Why gain too high? → Default tuning profile used for bright scenes only.",
                "why4": "Why wrong profile deployed? → Low-light tuning ticket not merged before release branch cut.",
                "why5": "Why not merged? → Branch cut checklist did not require AF tuning sign-off.",
                "root_cause": "Release checklist gap allowed camera low-light AF tuning to be omitted from release branch.",
                "created_by": "Engineering - Camera",
            },
            actions=[
                {
                    "title": "Patch firmware with low-light AF tuning parameters",
                    "description": "Adjust AF gain and damping; validate against low-light test suite.",
                    "owner": "Engineering",
                    "due_in_days": 2,
                    "status": CorrectiveAction.Status.IN_PROGRESS,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                }
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1009",
            title="Label misprint: serial number barcode truncated",
            description=(
                "Barcode truncation on shipping label results in scan failures at outbound dock. "
                "Likely printer calibration or template margin issue."
            ),
            severity=Defect.Severity.LOW,
            priority=Defect.Priority.MEDIUM,
            status_code="CLOSED",
            part_number="LBL-SHIP-REV-K",
            defect_type=Defect.DefectType.LABELING,
            quantity_affected=55,
            production_line="Production Line 1",
            shift="Day",
            reported_by="Packaging",
            assigned_to="Quality",
            area="Packaging",
            source="Outbound scan",
            occurred_days_ago=40,
            created_days_ago=39,
            due_in_days=5,
            closed_days_ago=20,
            five_why=None,
            actions=[
                {
                    "title": "Recalibrate label printer and lock template margins",
                    "description": "Run calibration and update template with safe margins; restrict edits.",
                    "owner": "Production",
                    "due_in_days": -25,
                    "status": CorrectiveAction.Status.DONE,
                    "completed_days_ago": 22,
                    "effectiveness_check": "Outbound scan success rate returned to 99.8% over 3 days.",
                }
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1010",
            title="Packaging seal weak; box opens during drop test",
            description=(
                "Carton seal tape adhesion inconsistent; several boxes opened during 1m drop test. "
                "Could lead to cosmetic damage in transit."
            ),
            severity=Defect.Severity.MEDIUM,
            priority=Defect.Priority.MEDIUM,
            status_code="IN_ANALYSIS",
            part_number="TAPE-ADH-REV-C",
            defect_type=Defect.DefectType.PACKAGING,
            quantity_affected=16,
            production_line="Production Line 2",
            shift="Night",
            reported_by="QA Team",
            assigned_to="Packaging",
            area="Packaging",
            source="Reliability test",
            occurred_days_ago=13,
            created_days_ago=12,
            due_in_days=7,
            closed_days_ago=None,
            five_why={
                "problem_statement": "Carton seal fails drop test; tape adhesion inconsistent.",
                "why1": "Why does the box open? → Tape does not maintain adhesion under impact.",
                "why2": "Why low adhesion? → Tape applied to dusty/low-energy carton surface.",
                "why3": "Why is surface dusty? → Cartons stored near cutting operation; particulate settles.",
                "why4": "Why stored there? → Space constraint moved carton staging next to cutting line.",
                "why5": "Why not prevented? → Packaging area layout change wasn’t assessed for contamination risk.",
                "root_cause": "Carton staging moved near cutting line causing dust contamination; tape applied to dirty surface reduces adhesion.",
                "created_by": "Packaging",
            },
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1011",
            title="Random reboot when NFC enabled",
            description=(
                "Unit reboots randomly during NFC payment simulation. Logs suggest watchdog reset. "
                "High customer impact if shipped."
            ),
            severity=Defect.Severity.CRITICAL,
            priority=Defect.Priority.URGENT,
            status_code="ACTIONS_IN_PROGRESS",
            part_number="NFC-MOD-REV-B",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=3,
            production_line="Production Line 1",
            shift="Swing",
            reported_by="Engineering",
            assigned_to="Engineering - Firmware",
            area="Testing",
            source="Validation lab",
            occurred_days_ago=16,
            created_days_ago=15,
            due_in_days=1,
            closed_days_ago=None,
            five_why={
                "problem_statement": "Watchdog resets during NFC transaction simulation.",
                "why1": "Why reset? → Main thread blocked causing watchdog timeout.",
                "why2": "Why blocked? → NFC interrupt handler triggers synchronous flash write.",
                "why3": "Why flash write in handler? → Metrics logger called from ISR path.",
                "why4": "Why called from ISR? → Refactor changed call site without real-time review.",
                "why5": "Why review missed? → No ISR safety checklist in code review template.",
                "root_cause": "Synchronous flash write executed in NFC interrupt context causing watchdog timeouts.",
                "created_by": "Engineering - Firmware",
            },
            actions=[
                {
                    "title": "Move NFC metrics logging to deferred worker queue",
                    "description": "Replace synchronous flash writes with buffered queue flush in background task.",
                    "owner": "Engineering",
                    "due_in_days": 3,
                    "status": CorrectiveAction.Status.IN_PROGRESS,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                },
                {
                    "title": "Add ISR-safety checklist to PR template",
                    "description": "Update code review template and require sign-off for ISR changes.",
                    "owner": "Quality",
                    "due_in_days": 14,
                    "status": CorrectiveAction.Status.OPEN,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                },
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1012",
            title="Bluetooth pairing fails with certain headsets (timeout)",
            description=(
                "Pairing times out with Headset Model QZ-200 after PIN exchange. "
                "Repro rate ~60%. Likely interoperability issue."
            ),
            severity=Defect.Severity.MEDIUM,
            priority=Defect.Priority.MEDIUM,
            status_code="NEW",
            part_number="BT-MOD-REV-H",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=None,
            production_line="Production Line 2",
            shift="Day",
            reported_by="QA Team",
            assigned_to="Engineering - Wireless",
            area="Testing",
            source="Compatibility test",
            occurred_days_ago=3,
            created_days_ago=2,
            due_in_days=14,
            closed_days_ago=None,
            five_why=None,
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1013",
            title="Touchscreen unresponsive on first boot until reboot",
            description=(
                "On first boot after firmware flash, touchscreen does not register input. "
                "A reboot resolves. Suspected driver init race condition."
            ),
            severity=Defect.Severity.HIGH,
            priority=Defect.Priority.HIGH,
            status_code="IN_ANALYSIS",
            part_number="TOUCH-CTRL-REV-D",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=8,
            production_line="Production Line 1",
            shift="Night",
            reported_by="QA Team",
            assigned_to="Engineering - Firmware",
            area="Testing",
            source="End-of-line test",
            occurred_days_ago=19,
            created_days_ago=19,
            due_in_days=5,
            closed_days_ago=None,
            five_why=None,
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1014",
            title="Wi-Fi throughput drops after 30 minutes (thermal throttling suspected)",
            description=(
                "Sustained Wi-Fi transfer test drops from 180 Mbps to 40 Mbps after ~30 minutes. "
                "Potential thermal throttling or antenna detuning under heat."
            ),
            severity=Defect.Severity.HIGH,
            priority=Defect.Priority.MEDIUM,
            status_code="ACTIONS_IN_PROGRESS",
            part_number="WIFI-MOD-REV-G",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=4,
            production_line="Production Line 2",
            shift="Night",
            reported_by="Engineering",
            assigned_to="Engineering - Wireless",
            area="Testing",
            source="Reliability test",
            occurred_days_ago=24,
            created_days_ago=23,
            due_in_days=9,
            closed_days_ago=None,
            five_why=None,
            actions=[
                {
                    "title": "Add thermal pad between Wi-Fi module and chassis",
                    "description": "Prototype pad placement; rerun sustained throughput tests.",
                    "owner": "Engineering",
                    "due_in_days": 6,
                    "status": CorrectiveAction.Status.OPEN,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                }
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1015",
            title="Gasket misalignment causing IP rating failure",
            description=(
                "Water ingress test fails on 2/10 units. Teardown shows gasket shifted near top speaker cutout. "
                "Assembly fixture may not constrain gasket during closure."
            ),
            severity=Defect.Severity.CRITICAL,
            priority=Defect.Priority.URGENT,
            status_code="CLOSED",
            part_number="GSKT-IP-REV-A",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=2,
            production_line="Production Line 1",
            shift="Day",
            reported_by="Quality",
            assigned_to="Engineering - ME",
            area="Assembly",
            source="Ingress test",
            occurred_days_ago=55,
            created_days_ago=54,
            due_in_days=-30,
            closed_days_ago=28,
            five_why={
                "problem_statement": "IP test failure due to gasket misalignment near speaker cutout.",
                "why1": "Why did water ingress? → Seal gap at top cutout.",
                "why2": "Why gap? → Gasket shifted during cover installation.",
                "why3": "Why shifted? → Fixture did not clamp gasket at speaker cutout region.",
                "why4": "Why no clamp? → Fixture revision never updated after speaker geometry change.",
                "why5": "Why update missed? → ECO process didn't include fixture update verification.",
                "root_cause": "Assembly fixture not updated after geometry change, allowing gasket shift during closure.",
                "created_by": "Engineering - ME",
            },
            actions=[
                {
                    "title": "Revise closure fixture to clamp gasket at speaker cutout",
                    "description": "Update fixture and validate IP test on 20 units.",
                    "owner": "Engineering",
                    "due_in_days": -35,
                    "status": CorrectiveAction.Status.DONE,
                    "completed_days_ago": 30,
                    "effectiveness_check": "20/20 units passed IP test after fixture update.",
                }
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1016",
            title="Lens dust contamination visible in camera module",
            description=(
                "Black specks visible in captured images; teardown shows particulate inside lens assembly. "
                "Potential cleanroom breach or handling issue."
            ),
            severity=Defect.Severity.HIGH,
            priority=Defect.Priority.HIGH,
            status_code="IN_ANALYSIS",
            part_number="CAM-12MP-REV-F",
            defect_type=Defect.DefectType.COSMETIC,
            quantity_affected=11,
            production_line="Production Line 2",
            shift="Day",
            reported_by="QA Team",
            assigned_to="Quality",
            area="Quality Check",
            source="Visual inspection",
            occurred_days_ago=14,
            created_days_ago=14,
            due_in_days=2,
            closed_days_ago=None,
            five_why=None,
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1017",
            title="Protective film bubbles under screen (cosmetic)",
            description=(
                "Air bubbles trapped under protective film after lamination. "
                "Customer-visible defect; increases scrap/rework."
            ),
            severity=Defect.Severity.LOW,
            priority=Defect.Priority.MEDIUM,
            status_code="ACTIONS_IN_PROGRESS",
            part_number="FILM-PROT-REV-D",
            defect_type=Defect.DefectType.COSMETIC,
            quantity_affected=27,
            production_line="Production Line 1",
            shift="Swing",
            reported_by="QA Team",
            assigned_to="Production",
            area="Assembly",
            source="End-of-line test",
            occurred_days_ago=8,
            created_days_ago=8,
            due_in_days=6,
            closed_days_ago=None,
            five_why=None,
            actions=[
                {
                    "title": "Adjust lamination roller pressure and speed",
                    "description": "Tune roller settings; validate with 50-piece trial run.",
                    "owner": "Production",
                    "due_in_days": 4,
                    "status": CorrectiveAction.Status.IN_PROGRESS,
                    "completed_days_ago": None,
                    "effectiveness_check": "",
                }
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1018",
            title="Incorrect torque on back cover screws (strip risk)",
            description=(
                "Torque audit shows 6 screws above spec by 20%. Risk of stripping threads and reduced serviceability. "
                "Possible driver calibration issue."
            ),
            severity=Defect.Severity.MEDIUM,
            priority=Defect.Priority.MEDIUM,
            status_code="CLOSED",
            part_number="SCR-M2X4-REV-A",
            defect_type=Defect.DefectType.DIMENSIONAL,
            quantity_affected=19,
            production_line="Production Line 2",
            shift="Night",
            reported_by="Quality",
            assigned_to="Production",
            area="Assembly",
            source="Torque audit",
            occurred_days_ago=48,
            created_days_ago=47,
            due_in_days=-20,
            closed_days_ago=15,
            five_why=None,
            actions=[
                {
                    "title": "Calibrate torque drivers and implement daily verification log",
                    "description": "Calibrate all drivers; add daily check with reference tool and sign-off.",
                    "owner": "Production",
                    "due_in_days": -18,
                    "status": CorrectiveAction.Status.DONE,
                    "completed_days_ago": 16,
                    "effectiveness_check": "Audit of 30 units shows torque within spec.",
                }
            ],
        ),
        _SeedDefect(
            defect_key="DEF-1019",
            title="Paint discoloration on side rail after curing",
            description=(
                "Yellowish tint observed after curing process on side rail. "
                "Noticed on dark blue colorway only. Suspected oven temperature overshoot."
            ),
            severity=Defect.Severity.LOW,
            priority=Defect.Priority.LOW,
            status_code="NEW",
            part_number="RAIL-PAINT-REV-C",
            defect_type=Defect.DefectType.COSMETIC,
            quantity_affected=31,
            production_line="Production Line 1",
            shift="Day",
            reported_by="Quality",
            assigned_to="Production",
            area="Quality Check",
            source="Visual inspection",
            occurred_days_ago=2,
            created_days_ago=2,
            due_in_days=12,
            closed_days_ago=None,
            five_why=None,
            actions=[],
        ),
        _SeedDefect(
            defect_key="DEF-1020",
            title="Microphone low sensitivity (voice calls muffled)",
            description=(
                "Call quality test indicates microphone sensitivity ~6 dB below spec. "
                "May be caused by acoustic mesh obstruction or incorrect gasket."
            ),
            severity=Defect.Severity.HIGH,
            priority=Defect.Priority.MEDIUM,
            status_code="CLOSED",
            part_number="MIC-MEMS-REV-D",
            defect_type=Defect.DefectType.FUNCTIONAL,
            quantity_affected=10,
            production_line="Production Line 2",
            shift="Swing",
            reported_by="QA Team",
            assigned_to="Engineering - Audio",
            area="Testing",
            source="End-of-line test",
            occurred_days_ago=62,
            created_days_ago=61,
            due_in_days=-45,
            closed_days_ago=10,
            five_why={
                "problem_statement": "Microphone sensitivity below spec causing muffled calls.",
                "why1": "Why low sensitivity? → Acoustic port partially blocked.",
                "why2": "Why blocked? → Mesh adhesive overflow into port.",
                "why3": "Why overflow? → Dispenser volume set too high after maintenance.",
                "why4": "Why setting not restored? → No golden settings record for dispenser.",
                "why5": "Why no record? → Process documentation incomplete for adhesive dispenser maintenance.",
                "root_cause": "Adhesive dispenser volume mis-set after maintenance, causing mesh adhesive overflow and blockage.",
                "created_by": "Engineering - Audio",
            },
            actions=[
                {
                    "title": "Restore adhesive dispenser settings and create golden settings record",
                    "description": "Validate dispense volume and document baseline parameters post-maintenance.",
                    "owner": "Engineering",
                    "due_in_days": -30,
                    "status": CorrectiveAction.Status.DONE,
                    "completed_days_ago": 12,
                    "effectiveness_check": "Sensitivity within spec on 25-unit sample after settings restoration.",
                }
            ],
        ),
    ]


class Command(BaseCommand):
    help = "Seed 20+ realistic demo defects (with 5-Why and corrective actions) for hackathon/demo dashboards."

    # PUBLIC_INTERFACE
    def add_arguments(self, parser):
        """Add CLI args for the demo seed command."""
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo defects (DEF-1001..DEF-1999) before seeding.",
        )

    # PUBLIC_INTERFACE
    def handle(self, *args, **options):
        """
        Seed demo data into the database.

        Creates:
        - Workflow statuses (if missing)
        - 20 defects with varied severities/priorities/statuses/areas/dates including overdue
        - 5-Why analyses for a subset
        - Corrective actions for a subset (mix of done/open/in_progress/blocked)
        """
        with transaction.atomic():
            statuses = _get_or_seed_statuses()

            if options.get("reset"):
                # Only remove our demo range, to avoid deleting user-entered data.
                demo_defects = Defect.objects.filter(defect_key__startswith="DEF-1")
                # Narrow to our explicit keys (1001-1020), but allow future extension.
                demo_defects = demo_defects.filter(defect_key__in=[d.defect_key for d in _seed_defects()])
                count = demo_defects.count()
                demo_defects.delete()
                self.stdout.write(self.style.WARNING(f"Deleted {count} existing demo defects."))

            seeds = _seed_defects()

            created = 0
            skipped = 0

            for sd in seeds:
                if Defect.objects.filter(defect_key=sd.defect_key).exists():
                    skipped += 1
                    continue

                status_obj = statuses.get(sd.status_code)
                if not status_obj:
                    # Should not happen because we seed required statuses above
                    raise RuntimeError(f"Missing workflow status for code: {sd.status_code}")

                occurred_at = _days_ago(sd.occurred_days_ago)
                created_at = _days_ago(sd.created_days_ago)
                due_date = _days_from_now(sd.due_in_days) if sd.due_in_days is not None else None

                defect = Defect.objects.create(
                    defect_key=sd.defect_key,
                    title=sd.title,
                    description=sd.description,
                    severity=sd.severity,
                    priority=sd.priority,
                    status=status_obj,
                    part_number=sd.part_number,
                    defect_type=sd.defect_type,
                    quantity_affected=sd.quantity_affected,
                    production_line=sd.production_line,
                    shift=sd.shift,
                    reported_by=sd.reported_by,
                    assigned_to=sd.assigned_to,
                    area=sd.area,
                    source=sd.source,
                    occurred_at=occurred_at,
                    due_date=due_date,
                    closed_at=_days_ago(sd.closed_days_ago) if sd.closed_days_ago is not None else None,
                    created_at=created_at,
                    updated_at=created_at,
                )

                # Create initial history entry
                _make_history(defect, event_type=DefectHistory.EventType.SYSTEM, message="Demo defect seeded")

                # 5-Why analysis (optional)
                if sd.five_why:
                    FiveWhyAnalysis.objects.create(
                        defect=defect,
                        problem_statement=sd.five_why.get("problem_statement", ""),
                        why1=sd.five_why.get("why1", ""),
                        why2=sd.five_why.get("why2", ""),
                        why3=sd.five_why.get("why3", ""),
                        why4=sd.five_why.get("why4", ""),
                        why5=sd.five_why.get("why5", ""),
                        root_cause=sd.five_why.get("root_cause", ""),
                        created_by=sd.five_why.get("created_by", ""),
                        created_at=created_at,
                        updated_at=created_at,
                    )
                    DefectHistory.objects.create(
                        defect=defect,
                        event_type=DefectHistory.EventType.ANALYSIS_UPDATE,
                        message="5-Why analysis seeded",
                        actor=sd.five_why.get("created_by", "") or "system",
                        created_at=created_at,
                    )

                # Corrective actions (optional)
                for act in sd.actions or []:
                    act_due = _days_from_now(int(act["due_in_days"])) if act.get("due_in_days") is not None else None
                    completed_at = (
                        _days_ago(int(act["completed_days_ago"]))
                        if act.get("completed_days_ago") is not None
                        else None
                    )
                    action_obj = CorrectiveAction.objects.create(
                        defect=defect,
                        title=act["title"],
                        description=act.get("description", ""),
                        owner=act.get("owner", ""),
                        due_date=act_due,
                        status=act.get("status", CorrectiveAction.Status.OPEN),
                        completed_at=completed_at,
                        effectiveness_check=act.get("effectiveness_check", ""),
                        created_at=created_at,
                        updated_at=created_at,
                    )
                    DefectHistory.objects.create(
                        defect=defect,
                        event_type=DefectHistory.EventType.ACTION_UPDATE,
                        message=f"Corrective action seeded: {action_obj.title}",
                        actor=act.get("owner", "") or "system",
                        created_at=created_at,
                    )

                created += 1

            # A quick summary that helps the demo operator.
            total_defects = Defect.objects.count()
            open_defects = Defect.objects.exclude(status__is_terminal=True).count()
            closed_defects = Defect.objects.filter(status__is_terminal=True).count()
            overdue_defects = (
                Defect.objects.filter(due_date__isnull=False, due_date__lt=timezone.now())
                .exclude(status__is_terminal=True)
                .count()
            )

            self.stdout.write(self.style.SUCCESS(f"Demo seeding complete. Created={created}, skipped={skipped}."))
            self.stdout.write(
                self.style.SUCCESS(
                    f"DB totals: defects={total_defects}, open={open_defects}, closed={closed_defects}, overdue={overdue_defects}."
                )
            )
            self.stdout.write(
                "Run: python manage.py seed_demo_data\n"
                "Optional reset: python manage.py seed_demo_data --reset"
            )
