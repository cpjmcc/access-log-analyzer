#!/usr/bin/env python3
"""
app.py — Access Log Analyzer GUI
A macOS desktop application for analyzing Jira and Confluence DC access logs
to predict rate limiting issues when migrating to Atlassian Cloud.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import os
import queue
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from typing import cast

from analyzer.parser import parse_log_file, iter_parsed_calls
from analyzer.calculator import enrich_calls, calculate_quota
from analyzer.reporter import generate_report
from analyzer.pdf_exporter import generate_pdf

# ── Colours ───────────────────────────────────────────────────────────────────
BG          = "#F4F5F7"
CARD_BG     = "#FFFFFF"
BLUE        = "#0052CC"
BLUE_HOVER  = "#0065FF"
BLUE_LIGHT  = "#DEEBFF"
TEXT_DARK   = "#172B4D"
TEXT_MID    = "#42526E"
TEXT_LIGHT  = "#6B778C"
BORDER      = "#DFE1E6"
RED         = "#DE350B"
GREEN       = "#00875A"
YELLOW      = "#FF991F"

PRODUCTS    = ["Jira", "Confluence"]
EDITIONS    = ["Standard", "Premium", "Enterprise"]
EDITION_MAP = {"standard": "Standard", "premium": "Premium", "enterprise": "Enterprise"}
LOGGER = logging.getLogger("access_log_analyzer.gui")


# ── Helpers ───────────────────────────────────────────────────────────────────

# ── Custom Flat Button Class ──────────────────────────────────────────────
class FlatButton(tk.Frame):
    """
    A macOS-friendly flat button widget based on tk.Frame + tk.Label.
    Honors bg/fg colors cross-platform, supports configure(state=...),
    cget for state, command invocation, and Enter/Leave hover effects.
    """
    def __init__(self, parent, text="", command=None, bg=BLUE, fg="white",
                 font=("Helvetica", 10, "normal"), padx=16, pady=8,
                 cursor="hand2", **kwargs):
        super().__init__(parent, bg=kwargs.get("bg", parent.cget("bg")), 
                         highlightthickness=0, **{k: v for k, v in kwargs.items() 
                                                   if k not in ["bg"]})
        self._text = text
        self._command = command
        self._state = "normal"
        self._bg_normal = bg
        self._fg_normal = fg
        self._bg_hover = None
        self._fg_hover = None
        self._bg_disabled = BG
        self._fg_disabled = "#A5ADBA"
        self._font = font
        self._cursor = cursor
        self._original_cursor = cursor
        
        self.label = tk.Label(
            self, text=text, bg=bg, fg=fg, font=font,
            padx=padx, pady=pady, cursor=cursor, highlightthickness=0
        )
        self.label.pack(fill="both", expand=True)
        
        self.label.bind("<Button-1>", self._on_click)
        self.label.bind("<Enter>", self._on_enter)
        self.label.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
    
    def configure(self, **kwargs):
        """Configure button properties, including state and colors."""
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            self._update_appearance()
        if "bg" in kwargs:
            self._bg_normal = kwargs.pop("bg")
        if "fg" in kwargs:
            self._fg_normal = kwargs.pop("fg")
        if "activebackground" in kwargs:
            self._bg_hover = kwargs.pop("activebackground")
        if "activeforeground" in kwargs:
            self._fg_hover = kwargs.pop("activeforeground")
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            self.label.configure(text=self._text)
        if "cursor" in kwargs:
            self._cursor = kwargs.pop("cursor")
            self._original_cursor = self._cursor
        if "disabledforeground" in kwargs:
            self._fg_disabled = kwargs.pop("disabledforeground")
        if kwargs:
            super().configure(**kwargs)
        self._update_appearance()
    
    def cget(self, key):
        """Get button property."""
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        return super().cget(key)
    
    def _update_appearance(self):
        """Update label appearance based on current state."""
        if self._state == "normal":
            super().configure(bg=self._bg_normal)
            self.label.configure(
                bg=self._bg_normal, fg=self._fg_normal,
                cursor=self._original_cursor
            )
        elif self._state == "disabled":
            super().configure(bg=self._bg_disabled)
            self.label.configure(
                bg=self._bg_disabled, fg=self._fg_disabled,
                cursor=""
            )
    
    def _on_click(self, event):
        """Handle button click."""
        if self._state == "normal" and self._command:
            self._command()
    
    def _on_enter(self, event):
        """Handle mouse enter (hover)."""
        if self._state == "normal":
            if self._bg_hover:
                self.label.configure(bg=self._bg_hover)
            if self._fg_hover:
                self.label.configure(fg=self._fg_hover)
    
    def _on_leave(self, event):
        """Handle mouse leave (unhover)."""
        if self._state == "normal":
            self.label.configure(bg=self._bg_normal, fg=self._fg_normal)


def make_button(parent, text, command, primary=True, small=False):
    bg     = BLUE if primary else CARD_BG
    fg     = "white" if primary else TEXT_DARK
    border = BLUE if primary else BORDER
    font_size = 9 if small else 10
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, relief="flat", cursor="hand2",
        default="active" if primary else "normal",
        takefocus=False,
        font=("Helvetica", font_size, "bold" if primary else "normal"),
        padx=10 if small else 16, pady=4 if small else 8,
        highlightthickness=1, highlightbackground=border,
        activebackground=BLUE_HOVER if primary else BLUE_LIGHT,
        activeforeground="white" if primary else BLUE,
    )
    return btn


def make_label(parent, text, bold=False, color=TEXT_DARK, size=10):
    return tk.Label(
        parent, text=text,
        font=("Helvetica", size, "bold" if bold else "normal"),
        bg=parent["bg"] if hasattr(parent, "__getitem__") else BG,
        fg=color
    )


def make_path_entry(parent, textvariable):
    entry = tk.Entry(
        parent, textvariable=textvariable,
        font=("Helvetica", 9), relief="flat",
        bg=CARD_BG, fg=TEXT_MID,
        highlightthickness=1, highlightbackground=BORDER,
        highlightcolor=BLUE, readonlybackground=CARD_BG,
        state="readonly"
    )
    return entry


# ── Log File Row ──────────────────────────────────────────────────────────────

class LogFileRow(tk.Frame):
    """A single log file picker row (browse button + path display)."""

    def __init__(self, parent, label="Log File", **kwargs):
        super().__init__(parent, bg=CARD_BG, **kwargs)
        self.path_var = tk.StringVar(value="No file selected")

        btn = make_button(self, f"📂  {label}", self._browse, primary=False, small=True)
        btn.pack(side="left", padx=(0, 8))

        entry = make_path_entry(self, self.path_var)
        entry.pack(side="left", fill="x", expand=True)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select access log file",
            filetypes=[("All files", "*.*"), ("Log files", "*.log *.txt")]
        )
        if path:
            self.path_var.set(path)

    def get_path(self):
        p = self.path_var.get()
        return p if p != "No file selected" else ""


# ── Product Config Row ────────────────────────────────────────────────────────

class ProductRow(tk.Frame):
    """A single product + edition selector row."""

    def __init__(self, parent, on_remove=None, **kwargs):
        super().__init__(parent, bg=CARD_BG, **kwargs)
        self.on_remove = on_remove

        # Product dropdown
        make_label(self, "Product:", color=TEXT_MID, size=9).pack(side="left", padx=(0, 4))
        self.product_var = tk.StringVar(value="Jira")
        product_dd = ttk.Combobox(
            self, textvariable=self.product_var,
            values=PRODUCTS, state="readonly", width=12,
            font=("Helvetica", 9)
        )
        product_dd.pack(side="left", padx=(0, 16))

        # Edition dropdown
        make_label(self, "Edition:", color=TEXT_MID, size=9).pack(side="left", padx=(0, 4))
        self.edition_var = tk.StringVar(value="Standard")
        edition_dd = ttk.Combobox(
            self, textvariable=self.edition_var,
            values=EDITIONS, state="readonly", width=12,
            font=("Helvetica", 9)
        )
        edition_dd.pack(side="left", padx=(0, 16))

        # Remove button (only shown when there are multiple rows)
        if on_remove:
            remove_btn = tk.Button(
                self, text="✕", command=on_remove,
                bg=CARD_BG, fg=RED, relief="flat", cursor="hand2",
                font=("Helvetica", 10), padx=4, pady=2,
                activebackground=BG, activeforeground=RED,
            )
            remove_btn.pack(side="left")

    def get_values(self):
        return {
            "product": self.product_var.get().lower(),
            "edition": self.edition_var.get().lower(),
        }


# ── Main App ──────────────────────────────────────────────────────────────────

class AccessLogAnalyzerApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Access Log Analyzer")
        self.geometry("700x550")
        self.minsize(700, 550)
        self.configure(bg=BG)
        self.resizable(True, True)

        # State
        self.log_rows: list[LogFileRow] = []
        self.product_rows: list[ProductRow] = []
        self.pdf_output_path = tk.StringVar(value="No output path selected")
        self.user_count_var = tk.StringVar(value="")
        self.excluded_ips_var = tk.StringVar(value="")
        self.exclude_system_var = tk.BooleanVar(value=True)  # Exclude system calls by default
        self._latest_pdf_path: str | None = None
        self._analysis_events: queue.Queue[
            tuple[str, int, str | tuple[str, int]]
        ] = queue.Queue()
        self._analysis_run_id = 0
        self._cancel_event: threading.Event | None = None  # Cooperative cancellation signal

        self._build_ui()
        self._add_log_row("Log File")
        self._add_product_row()
        self.after(100, self._poll_analysis_events)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BLUE)
        header.pack(fill="x")
        tk.Label(
            header, text="Access Log Analyzer",
            font=("Helvetica", 16, "bold"), bg=BLUE, fg="white",
            pady=8, padx=20
        ).pack(side="left")
        tk.Label(
            header, text="Jira & Confluence DC → Cloud Migration",
            font=("Helvetica", 10), bg=BLUE, fg=BLUE_LIGHT,
            pady=8, padx=0
        ).pack(side="left")

        # ── Scrollable config area ─────────────────────────────────────────────
        config_outer = tk.Frame(self, bg=BG)
        config_outer.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))

        config_canvas = tk.Canvas(config_outer, bg=BG, highlightthickness=0)
        config_scrollbar = ttk.Scrollbar(config_outer, orient="vertical", command=config_canvas.yview)
        config_canvas.configure(yscrollcommand=config_scrollbar.set)

        config_scrollbar.pack(side="right", fill="y")
        config_canvas.pack(side="left", fill="both", expand=True)

        main = tk.Frame(config_canvas, bg=BG)
        main_window = config_canvas.create_window((0, 0), window=main, anchor="nw")

        def _on_config_resize(event):
            config_canvas.itemconfig(main_window, width=event.width)
        config_canvas.bind("<Configure>", _on_config_resize)

        def _on_main_configure(event):
            # Keep the scroll region current while the canvas fills all available space.
            config_canvas.configure(scrollregion=config_canvas.bbox("all"))
        main.bind("<Configure>", _on_main_configure)

        # Mouse wheel scrolling on config area
        config_canvas.bind("<MouseWheel>", lambda e: config_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        config_canvas.bind("<Button-4>", lambda e: config_canvas.yview_scroll(-1, "units"))
        config_canvas.bind("<Button-5>", lambda e: config_canvas.yview_scroll(1, "units"))

        # ── Unified Analysis Setup Form ────────────────────────────────────────
        setup_card = self._make_card(main, "⚙️  Analysis Setup")
        setup_card.pack(fill="x", pady=(0, 8), padx=0)

        # Source input: single row on top
        source_header = tk.Frame(setup_card, bg=CARD_BG)
        source_header.pack(fill="x", padx=10, pady=(10, 4))
        make_label(source_header, "Source input", bold=True, color=TEXT_DARK, size=9).pack(side="left")
        self._log_rows_frame = tk.Frame(setup_card, bg=CARD_BG)
        self._log_rows_frame.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Separator(setup_card, orient="horizontal").pack(fill="x", padx=10, pady=5)

        # Existing options directly below
        options_frame = tk.Frame(setup_card, bg=CARD_BG)
        options_frame.pack(fill="x", padx=10, pady=5)
        
        # Product configuration
        product_header = tk.Frame(options_frame, bg=CARD_BG)
        product_header.pack(fill="x", pady=(0, 6))
        make_label(product_header, "Product and plan", bold=True, color=TEXT_DARK, size=9).pack(side="left")
        make_button(
            product_header, "+ Add Product", self._add_product_row, primary=False, small=True,
        ).pack(side="right")
        self._product_rows_frame = tk.Frame(options_frame, bg=CARD_BG)
        self._product_rows_frame.pack(fill="x", pady=(0, 10))

        # Analysis options
        analysis_opts = tk.Frame(options_frame, bg=CARD_BG)
        analysis_opts.pack(fill="x", pady=5)
        make_label(analysis_opts, "User count:", color=TEXT_MID, size=9).pack(side="left", padx=(0, 6))
        vcmd = (self.register(self._validate_int), "%P")
        self._user_entry = tk.Entry(
            analysis_opts, textvariable=self.user_count_var,
            validate="key", validatecommand=vcmd,
            font=("Helvetica", 9), relief="flat", width=10,
            bg=BG, fg=TEXT_DARK,
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=BLUE,
        )
        self._user_entry.pack(side="left", padx=(0, 12))
        self._system_toggle = tk.Checkbutton(
            analysis_opts,
            text="Exclude unauthenticated / system API calls",
            variable=self.exclude_system_var,
            command=self._on_toggle_system_calls,
            bg=CARD_BG, fg=TEXT_DARK,
            activebackground=CARD_BG, activeforeground=TEXT_DARK,
            selectcolor=BLUE_LIGHT,
            font=("Helvetica", 9),
            cursor="hand2",
        )
        self._system_toggle.pack(side="left")

        ttk.Separator(setup_card, orient="horizontal").pack(fill="x", padx=10, pady=5)

        # PDF output
        pdf_row = tk.Frame(setup_card, bg=CARD_BG)
        pdf_row.pack(fill="x", padx=10, pady=5)
        make_label(pdf_row, "PDF output:", bold=True, color=TEXT_DARK, size=9).pack(side="left", padx=(0, 8))
        browse_btn = make_button(
            pdf_row, "Choose Path", self._browse_output, primary=False, small=True,
        )
        browse_btn.pack(side="left", padx=(0, 8))
        out_entry = make_path_entry(pdf_row, self.pdf_output_path)
        out_entry.pack(side="left", fill="x", expand=True)

        # ── Actions, progress, and completed report (sequential below settings) ─
        actions_frame = tk.Frame(main, bg=BG)
        actions_frame.pack(fill="x", pady=(5, 5))
        self._run_btn = FlatButton(
            actions_frame, text="▶   RUN ANALYSIS", command=self._run,
            bg=BLUE, fg="white",
            font=("Helvetica", 11, "bold"), padx=18, pady=8,
            cursor="hand2"
        )
        self._run_btn.configure(
            activebackground="#0747A6", activeforeground="white",
        )
        self._run_btn.pack(side="left", padx=6)
        self._cancel_btn = FlatButton(
            actions_frame, text="✕  CANCEL", command=self._cancel_analysis,
            bg=BG, fg="#A5ADBA",
            font=("Helvetica", 11, "normal"), padx=18, pady=8,
            cursor=""
        )
        self._cancel_btn.configure(
            state="disabled",
            activebackground="#FF991F", activeforeground=TEXT_DARK,
            disabledforeground="#A5ADBA",
        )
        self._cancel_btn.pack(side="left", padx=6)

        progress_frame = tk.Frame(main, bg=BG)
        progress_frame.pack(fill="x", pady=(5, 10))
        self._progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
        self._progress_bar.pack(fill="x", expand=True)
        self._status_label = make_label(progress_frame, "", color=TEXT_MID, size=9)
        self._status_label.pack(pady=(4, 0), anchor="w")

        self._report_card = tk.Frame(main, bg=BG)
        self._report_card.pack(fill="x", pady=(5, 10))
        report_inner = tk.Frame(self._report_card, bg=BG)
        report_inner.pack(fill="x")
        self._open_pdf_btn = make_button(report_inner, "↗  Open Completed Report", self._open_completed_pdf, primary=False, small=True)
        self._open_pdf_btn.configure(state="disabled")
        self._open_pdf_btn.pack(anchor="w")
        self._report_card.pack_forget()

    def _make_card(self, parent, title: str) -> tk.Frame:
        """Create a white card with a section title."""
        card = tk.Frame(parent, bg=CARD_BG, highlightthickness=1, highlightbackground=BORDER)
        tk.Label(
            card, text=title,
            font=("Helvetica", 11, "bold"), bg=CARD_BG, fg=TEXT_DARK,
            pady=10, padx=16, anchor="w"
        ).pack(fill="x")
        ttk.Separator(card, orient="horizontal").pack(fill="x")
        return card

    # ── Dynamic Row Management ────────────────────────────────────────────────

    def _add_log_row(self, label="Log File"):
        row = LogFileRow(self._log_rows_frame, label=label)
        row.pack(fill="x", padx=10, pady=5)
        self.log_rows.append(row)

    def _add_product_row(self):
        def remove():
            if len(self.product_rows) > 1:
                row.pack_forget()
                row.destroy()
                self.product_rows.remove(row)

        row = ProductRow(
            self._product_rows_frame,
            on_remove=remove if len(self.product_rows) >= 1 else None
        )
        row.pack(fill="x", padx=10, pady=5)
        self.product_rows.append(row)

    # ── Toggle Handler ────────────────────────────────────────────────────────

    def _on_toggle_system_calls(self):
        """Re-run analysis automatically when the system calls toggle changes, if a PDF exists."""
        pdf_path = self.pdf_output_path.get()
        if pdf_path and pdf_path != "No output path selected" and os.path.exists(pdf_path):
            self._run()

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_int(self, value):
        return value == "" or value.isdigit()

    def _validate_ips(self, value):
        """Allow digits, dots, commas and spaces only (for IP entry)."""
        return all(c in "0123456789., " for c in value)

    # ── File Browsing ─────────────────────────────────────────────────────────

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save PDF Report As",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")]
        )
        if path:
            self.pdf_output_path.set(path)

    # ── Run Analysis ──────────────────────────────────────────────────────

    def _run(self):
        # Validate log files
        log_paths = [row.get_path() for row in self.log_rows if row.get_path()]
        if not log_paths:
            messagebox.showerror("Missing Input", "Please select at least one log file.")
            return

        # Validate PDF output
        pdf_path = self.pdf_output_path.get()
        if pdf_path == "No output path selected":
            # Auto-generate a temp path
            pdf_path = os.path.join(tempfile.gettempdir(), "access-log-report.pdf")
            self.pdf_output_path.set(pdf_path)

        # Get user count
        user_count = int(self.user_count_var.get()) if self.user_count_var.get() else 0

        # Get excluded IPs
        excluded_ips = [ip.strip() for ip in self.excluded_ips_var.get().split(",") if ip.strip()]
        if len(excluded_ips) > 10:
            messagebox.showwarning("Too Many IPs", "Maximum 10 IPs allowed. Only the first 10 will be used.")
            excluded_ips = excluded_ips[:10]

        prod_configs = [row.get_values() for row in self.product_rows]
        exclude_system = self.exclude_system_var.get()

        # The worker communicates only through a thread-safe queue. Tkinter calls
        # must stay on the main thread or the status can remain stale indefinitely.
        self._analysis_run_id += 1
        run_id = self._analysis_run_id
        self._analysis_events = queue.Queue()
        event_queue = self._analysis_events
        self._latest_pdf_path = None
        self._cancel_event = threading.Event()  # Create cancellation event
        self._open_pdf_btn.configure(state="disabled")
        self._open_pdf_btn.pack_forget()
        self._report_card.pack_forget()

        self._run_btn.configure(state="disabled", text="⏳  Running...", bg=BG, fg="#A5ADBA")
        self._cancel_btn.configure(state="normal", bg="#FFAB00", fg=TEXT_DARK, cursor="hand2")
        self._progress_bar.start()
        self._status_label.configure(
            text=f"Preparing to analyze {len(log_paths)} selected log file(s)...", fg=TEXT_MID
        )
        self.update_idletasks()
        LOGGER.info(
            "Run %d started: files=%d, output=%s, excluded_ips=%d, exclude_system=%s",
            run_id, len(log_paths), pdf_path, len(excluded_ips), exclude_system,
        )

        thread = threading.Thread(
            target=self._run_analysis,
            args=(
                log_paths, prod_configs, user_count, pdf_path, excluded_ips,
                exclude_system, run_id, event_queue,
            ),
            daemon=True,
            name=f"analysis-run-{run_id}",
        )
        thread.start()

    def _cancel_analysis(self):
        """Signal the analysis thread to cancel gracefully."""
        if self._cancel_event:
            LOGGER.info("Cancel requested by user")
            self._cancel_event.set()
            self._cancel_btn.configure(state="disabled", bg=BG, fg="#A5ADBA")
            self._status_label.configure(text="Cancelling analysis...", fg=YELLOW)

    def _run_analysis(
        self, log_paths, prod_configs, user_count, pdf_path, excluded_ips,
        exclude_system, run_id, event_queue,
    ):
        """Parse logs and build the report without touching Tkinter widgets."""
        def emit(event_type, payload):
            if event_type == "status":
                LOGGER.info("Run %d: %s", run_id, payload)
            elif event_type == "error":
                LOGGER.error("Run %d failed: %s", run_id, payload)
            event_queue.put((event_type, run_id, payload))

        try:
            # Determine if we should use streaming mode for large logs
            total_size = sum(os.path.getsize(p) for p in log_paths if os.path.isfile(p))
            use_streaming = total_size >= 1 * 1024 * 1024 * 1024  # >= 1 GiB
            
            if use_streaming:
                emit("status", f"Log size {total_size / (1024**3):.1f} GiB detected - using streaming mode...")
                self._run_analysis_streaming(
                    log_paths, prod_configs, user_count, pdf_path, excluded_ips,
                    exclude_system, run_id, event_queue, emit
                )
            else:
                self._run_analysis_list_mode(
                    log_paths, prod_configs, user_count, pdf_path, excluded_ips,
                    exclude_system, run_id, event_queue, emit
                )
        except Exception as exc:
            LOGGER.exception("Run %d terminated with an error", run_id)
            emit("error", f"{type(exc).__name__}: {exc}")

    def _run_analysis_list_mode(
        self, log_paths, prod_configs, user_count, pdf_path, excluded_ips,
        exclude_system, run_id, event_queue, emit,
    ):
        """Parse logs into a list (existing behavior for small files)."""
        all_calls = []
        total_logs = len(log_paths)

        for index, log_path in enumerate(log_paths, start=1):
            # Check for cancellation per log file
            if self._cancel_event and self._cancel_event.is_set():
                LOGGER.info("Run %d cancelled by user during list-mode parsing", run_id)
                emit("cancelled", "Analysis cancelled by user")
                return

            product = "jira"
            for config in prod_configs:
                if config["product"] in log_path.lower():
                    product = config["product"]
                    break
            else:
                product = prod_configs[0]["product"] if prod_configs else "jira"

            log_name = os.path.basename(log_path)
            emit("status", f"Parsing log {index}/{total_logs}: {log_name}...")

            def report_progress(lines_scanned, api_calls):
                # Check for cancellation during parsing
                if self._cancel_event and self._cancel_event.is_set():
                    return
                emit(
                    "status",
                    f"Parsing log {index}/{total_logs}: {log_name} - "
                    f"{lines_scanned:,} lines scanned, {api_calls:,} API calls found.",
                )

            calls = parse_log_file(
                log_path,
                product,
                excluded_ips=excluded_ips,
                progress_callback=report_progress,
            )
            calls = enrich_calls(calls)
            all_calls.extend(calls)
            emit(
                "status",
                f"Parsed log {index}/{total_logs}: {len(calls):,} external API calls "
                f"({len(all_calls):,} total).",
            )

        if not all_calls:
            emit(
                "error",
                "No external API calls were found in the selected log files.\n\n"
                "Check the log format, product selection, and exclusion settings.",
            )
            return

        plan = prod_configs[0]["edition"] if prod_configs else "standard"
        report_product = prod_configs[0]["product"] if prod_configs else "jira"
        emit("status", f"Generating final PDF from {len(all_calls):,} parsed API calls...")
        self._generate_pdf_atomically(
            all_calls, report_product, plan, pdf_path, user_count,
            excluded_ips or [], exclude_system,
        )
        LOGGER.info(
            "Run %d complete: all selected logs parsed; api_calls=%d, pdf=%s",
            run_id, len(all_calls), pdf_path,
        )
        emit("success", (pdf_path, len(all_calls)))

    def _run_analysis_streaming(
        self, log_paths, prod_configs, user_count, pdf_path, excluded_ips,
        exclude_system, run_id, event_queue, emit,
    ):
        """Parse logs using StreamingAggregator for memory-efficient processing."""
        from analyzer.streaming import StreamingAggregator
        from analyzer.parser import iter_parsed_calls
        from analyzer.calculator import enrich_calls
        from analyzer.pdf_exporter import generate_streaming_pdf
        
        # Create temp SQLite database next to the target PDF
        output_dir = os.path.dirname(os.path.abspath(pdf_path))
        db_path = os.path.join(output_dir, f".streaming-{run_id}.db")
        
        try:
            with StreamingAggregator(db_path=db_path, excluded_ips=excluded_ips) as aggregator:
                run_started_at = time.monotonic()
                total_logs = len(log_paths)
                total_calls = 0
                
                for index, log_path in enumerate(log_paths, start=1):
                    # Check for cancellation per log file
                    if self._cancel_event and self._cancel_event.is_set():
                        LOGGER.info("Run %d cancelled by user during streaming mode", run_id)
                        emit("cancelled", "Analysis cancelled by user")
                        return

                    product = "jira"
                    for config in prod_configs:
                        if config["product"] in log_path.lower():
                            product = config["product"]
                            break
                    else:
                        product = prod_configs[0]["product"] if prod_configs else "jira"
                    
                    log_name = os.path.basename(log_path)
                    emit("status", f"Streaming log {index}/{total_logs}: {log_name}...")
                    
                    lines_scanned = 0
                    
                    total_bytes = os.path.getsize(log_path)

                    def report_progress(total_lines, yielded_calls, bytes_scanned):
                        nonlocal lines_scanned
                        # Check for cancellation during progress reporting
                        if self._cancel_event and self._cancel_event.is_set():
                            return
                        lines_scanned = total_lines
                        elapsed_seconds = max(time.monotonic() - run_started_at, 0.001)
                        bytes_per_second = bytes_scanned / elapsed_seconds
                        remaining_seconds = max(total_bytes - bytes_scanned, 0) / max(bytes_per_second, 1)
                        database_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
                        database_mib = database_bytes / (1024 * 1024)
                        elapsed_text = time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds))
                        eta_text = time.strftime("%H:%M:%S", time.gmtime(remaining_seconds))
                        emit(
                            "status",
                            f"Streaming {index}/{total_logs}: {total_lines:,} lines, "
                            f"{total_calls + yielded_calls:,} API calls, {bytes_per_second / (1024 * 1024):,.1f} MiB/s, "
                            f"{elapsed_text} elapsed, ~{eta_text} remaining, SQLite {database_mib:,.1f} MiB.",
                        )
                    
                    # Stream parse calls without loading into a list
                    ingested_this_log = 0
                    for call in iter_parsed_calls(
                        log_path,
                        product,
                        excluded_ips=excluded_ips,
                        progress_callback=report_progress,
                    ):
                        # Check for cancellation per record
                        if self._cancel_event and self._cancel_event.is_set():
                            LOGGER.info("Run %d cancelled by user during record ingestion", run_id)
                            emit("cancelled", "Analysis cancelled by user")
                            return

                        # Enrich and ingest into aggregator
                        call = enrich_calls([call])[0]
                        aggregator.ingest(call)
                        ingested_this_log += 1
                    
                    total_calls += ingested_this_log
                    emit(
                        "status",
                        f"Streamed log {index}/{total_logs}: {ingested_this_log:,} API calls "
                        f"({total_calls:,} total aggregated).",
                    )
                
                if total_calls == 0:
                    emit(
                        "error",
                        "No external API calls were found in the selected log files.\n\n"
                        "Check the log format, product selection, and exclusion settings.",
                    )
                    return
                
                plan = prod_configs[0]["edition"] if prod_configs else "standard"
                report_product = prod_configs[0]["product"] if prod_configs else "jira"
                
                emit("status", f"Generating PDF from {total_calls:,} aggregated API calls (streaming mode)...")
                self._generate_streaming_pdf_atomically(
                    aggregator, report_product, plan, pdf_path, user_count,
                    excluded_ips or [], exclude_system,
                )
                
                LOGGER.info(
                    "Run %d complete: all selected logs streamed; api_calls=%d, pdf=%s",
                    run_id, total_calls, pdf_path,
                )
                emit("success", (pdf_path, total_calls))
        finally:
            # Clean up temp database on success
            if os.path.exists(db_path):
                try:
                    os.unlink(db_path)
                except Exception as e:
                    LOGGER.warning("Failed to clean up temp database %s: %s", db_path, e)

    @staticmethod
    def _generate_pdf_atomically(
        calls, product, plan, pdf_path, user_count, excluded_ips, exclude_system,
    ):
        """Replace the destination only after a complete PDF was generated."""
        output_dir = os.path.dirname(os.path.abspath(pdf_path))
        fd, temporary_pdf_path = tempfile.mkstemp(
            prefix=".access-log-analyzer-", suffix=".pdf", dir=output_dir,
        )
        os.close(fd)
        LOGGER.info("Building PDF in temporary file: %s", temporary_pdf_path)
        try:
            generate_pdf(
                calls, product, plan, temporary_pdf_path, user_count,
                excluded_ips=excluded_ips, exclude_system=exclude_system,
            )
            os.replace(temporary_pdf_path, pdf_path)
            LOGGER.info("Complete PDF atomically saved to: %s", pdf_path)
        except Exception:
            if os.path.exists(temporary_pdf_path):
                os.unlink(temporary_pdf_path)
            raise

    @staticmethod
    def _generate_streaming_pdf_atomically(
        aggregator, product, plan, pdf_path, user_count, excluded_ips, exclude_system,
    ):
        """Generate streaming PDF and atomically replace the destination."""
        from analyzer.pdf_exporter import generate_streaming_pdf
        
        output_dir = os.path.dirname(os.path.abspath(pdf_path))
        fd, temporary_pdf_path = tempfile.mkstemp(
            prefix=".access-log-analyzer-", suffix=".pdf", dir=output_dir,
        )
        os.close(fd)
        LOGGER.info("Building streaming PDF in temporary file: %s", temporary_pdf_path)
        try:
            generate_streaming_pdf(
                aggregator, product, plan, temporary_pdf_path, user_count,
                excluded_ips=excluded_ips, exclude_system=exclude_system,
            )
            os.replace(temporary_pdf_path, pdf_path)
            LOGGER.info("Complete streaming PDF atomically saved to: %s", pdf_path)
        except Exception:
            if os.path.exists(temporary_pdf_path):
                os.unlink(temporary_pdf_path)
            raise

    def _poll_analysis_events(self):
        """Apply worker events safely from the Tkinter main thread."""
        try:
            while True:
                event_type, run_id, payload = self._analysis_events.get_nowait()
                if run_id != self._analysis_run_id:
                    continue
                if event_type == "status":
                    self._status_label.configure(text=cast(str, payload), fg=TEXT_MID)
                elif event_type == "success":
                    pdf_path, call_count = cast(tuple[str, int], payload)
                    self._on_success(pdf_path, call_count)
                elif event_type == "cancelled":
                    self._on_cancelled()
                elif event_type == "error":
                    self._on_error(cast(str, payload))
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_analysis_events)

    def _on_success(self, pdf_path: str, call_count: int):
        self._progress_bar.stop()
        self._run_btn.configure(state="normal", text="▶   RUN ANALYSIS", bg=BLUE, fg="white", cursor="hand2")
        self._cancel_btn.configure(state="disabled", bg=BG, fg="#A5ADBA")
        self._status_label.configure(
            text=(
                f"✅  Analysis complete — all selected logs were parsed; "
                f"{call_count:,} API calls analyzed. PDF saved to: {pdf_path}"
            ),
            fg=GREEN,
        )
        self._latest_pdf_path = pdf_path
        self._report_card.pack(fill="x", pady=(5, 10))
        self._open_pdf_btn.configure(state="normal")
        self._open_pdf_btn.pack(anchor="w")

    def _on_cancelled(self):
        """Handle cancelled analysis - clean up PDF and reset UI."""
        self._progress_bar.stop()
        self._run_btn.configure(state="normal", text="▶   RUN ANALYSIS", bg=BLUE, fg="white", cursor="hand2")
        self._cancel_btn.configure(state="disabled", bg=BG, fg="#A5ADBA")
        self._status_label.configure(text="⏸  Analysis cancelled by user", fg=YELLOW)
        
        # Clean up the PDF file if it exists
        pdf_path = self.pdf_output_path.get()
        if pdf_path and pdf_path != "No output path selected" and os.path.exists(pdf_path):
            try:
                os.unlink(pdf_path)
                LOGGER.info("Cleaned up PDF after cancellation: %s", pdf_path)
            except Exception as e:
                LOGGER.warning("Failed to clean up PDF after cancellation: %s", e)
        
        # Hide the Open PDF button
        self._latest_pdf_path = None
        self._open_pdf_btn.configure(state="disabled")
        self._open_pdf_btn.pack_forget()
        self._report_card.pack_forget()

    def _on_error(self, message: str):
        self._progress_bar.stop()
        self._run_btn.configure(state="normal", text="▶   RUN ANALYSIS", bg=BLUE, fg="white", cursor="hand2")
        self._cancel_btn.configure(state="disabled", bg=BG, fg="#A5ADBA")
        self._status_label.configure(text=f"❌  Error: {message}", fg=RED)
        messagebox.showerror("Analysis Error", message)

    def _open_completed_pdf(self):
        """Open the fully generated report without rendering it in Tkinter."""
        if not self._latest_pdf_path:
            return
        pdf_path = Path(self._latest_pdf_path)
        if not pdf_path.is_file():
            messagebox.showerror("Report Not Found", f"The completed PDF no longer exists:\n{pdf_path}")
            return
        LOGGER.info("Opening completed PDF in the system viewer: %s", pdf_path)
        webbrowser.open(pdf_path.resolve().as_uri())


# ── Entry Point ───────────────────────────────────────────────────────────────

def configure_terminal_logging():
    """Configure concise, timestamped diagnostics for GUI runs."""
    level_name = os.environ.get("ACCESS_LOG_ANALYZER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    configure_terminal_logging()
    LOGGER.info("Starting Access Log Analyzer GUI")
    app = AccessLogAnalyzerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
