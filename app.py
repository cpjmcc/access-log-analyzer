#!/usr/bin/env python3
"""
app.py — Access Log Analyzer GUI
A macOS desktop application for analyzing Jira and Confluence DC access logs
to predict rate limiting issues when migrating to Atlassian Cloud.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import tempfile
import io
from PIL import Image, ImageTk
from pdf2image import convert_from_path

from analyzer.parser import parse_log_file
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_button(parent, text, command, primary=True, small=False):
    bg     = BLUE if primary else CARD_BG
    fg     = "white" if primary else TEXT_DARK
    border = BLUE if primary else BORDER
    font_size = 9 if small else 10
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, relief="flat", cursor="hand2",
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
        self.geometry("900x820")
        self.minsize(800, 700)
        self.configure(bg=BG)
        self.resizable(True, True)

        # State
        self.log_rows: list[LogFileRow] = []
        self.product_rows: list[ProductRow] = []
        self.pdf_output_path = tk.StringVar(value="No output path selected")
        self.user_count_var = tk.StringVar(value="")
        self.excluded_ips_var = tk.StringVar(value="")
        self._pdf_images = []  # Keep references to avoid GC

        self._build_ui()
        self._add_log_row("Jira Log File")
        self._add_product_row()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BLUE)
        header.pack(fill="x")
        tk.Label(
            header, text="Access Log Analyzer",
            font=("Helvetica", 16, "bold"), bg=BLUE, fg="white",
            pady=14, padx=20
        ).pack(side="left")
        tk.Label(
            header, text="Jira & Confluence DC → Cloud Migration",
            font=("Helvetica", 10), bg=BLUE, fg=BLUE_LIGHT,
            pady=14, padx=0
        ).pack(side="left")

        # ── Scrollable main content ────────────────────────────────────────────
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=16)

        # ── Log Files Card ─────────────────────────────────────────────────────
        self._log_card = self._make_card(main, "📁  Log Files")
        self._log_card.pack(fill="x", pady=(0, 12))

        self._log_rows_frame = tk.Frame(self._log_card, bg=CARD_BG)
        self._log_rows_frame.pack(fill="x", padx=16, pady=(0, 8))

        add_log_btn = make_button(self._log_card, "+ Add Log File", self._add_log_row, primary=False, small=True)
        add_log_btn.pack(anchor="w", padx=16, pady=(0, 12))

        # ── Product Configuration Card ─────────────────────────────────────────
        self._prod_card = self._make_card(main, "⚙️  Product Configuration")
        self._prod_card.pack(fill="x", pady=(0, 12))

        self._product_rows_frame = tk.Frame(self._prod_card, bg=CARD_BG)
        self._product_rows_frame.pack(fill="x", padx=16, pady=(0, 8))

        add_prod_btn = make_button(self._prod_card, "+ Add Product", self._add_product_row, primary=False, small=True)
        add_prod_btn.pack(anchor="w", padx=16, pady=(0, 4))

        # User count
        user_frame = tk.Frame(self._prod_card, bg=CARD_BG)
        user_frame.pack(fill="x", padx=16, pady=(4, 12))
        make_label(user_frame, "User Count:", color=TEXT_MID, size=9).pack(side="left", padx=(0, 8))
        vcmd = (self.register(self._validate_int), "%P")
        self._user_entry = tk.Entry(
            user_frame, textvariable=self.user_count_var,
            validate="key", validatecommand=vcmd,
            font=("Helvetica", 9), relief="flat", width=12,
            bg=BG, fg=TEXT_DARK,
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=BLUE,
        )
        self._user_entry.pack(side="left")
        make_label(user_frame, "  (optional — enables Tier 2 per-tenant quota)", color=TEXT_LIGHT, size=8).pack(side="left")

        # ── PDF Output Card ────────────────────────────────────────────────────
        pdf_card = self._make_card(main, "📄  PDF Output")
        pdf_card.pack(fill="x", pady=(0, 12))

        pdf_row = tk.Frame(pdf_card, bg=CARD_BG)
        pdf_row.pack(fill="x", padx=16, pady=(0, 12))

        browse_btn = make_button(pdf_row, "📂  Choose PDF Output Path", self._browse_output, primary=False, small=True)
        browse_btn.pack(side="left", padx=(0, 8))

        out_entry = make_path_entry(pdf_row, self.pdf_output_path)
        out_entry.pack(side="left", fill="x", expand=True)

        # ── Run Button ─────────────────────────────────────────────────────────
        run_frame = tk.Frame(self, bg=BG)
        run_frame.pack(pady=(0, 12))

        self._run_btn = make_button(run_frame, "▶   RUN ANALYSIS", self._run, primary=True)
        self._run_btn.configure(font=("Helvetica", 12, "bold"), padx=32, pady=10)
        self._run_btn.pack()

        self._status_label = make_label(run_frame, "", color=TEXT_MID, size=9)
        self._status_label.pack(pady=(6, 0))

        # ── PDF Preview Card ───────────────────────────────────────────────────
        preview_card = self._make_card(self, "🔍  Report Preview")
        preview_card.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        preview_inner = tk.Frame(preview_card, bg=CARD_BG)
        preview_inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Scrollable canvas
        self._canvas = tk.Canvas(preview_inner, bg="#E0E0E0", highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(preview_inner, orient="vertical", command=self._canvas.yview)
        scrollbar_x = ttk.Scrollbar(preview_inner, orient="horizontal", command=self._canvas.xview)

        self._canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        self._canvas.pack(side="left", fill="both", expand=True)

        # Mouse wheel scrolling
        self._canvas.bind("<MouseWheel>", lambda e: self._canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._canvas.bind("<Button-4>", lambda e: self._canvas.yview_scroll(-1, "units"))
        self._canvas.bind("<Button-5>", lambda e: self._canvas.yview_scroll(1, "units"))

        # Placeholder text
        self._placeholder = tk.Label(
            self._canvas, text="Run an analysis to see the PDF report here",
            font=("Helvetica", 12), bg="#E0E0E0", fg=TEXT_LIGHT
        )
        self._canvas.create_window(450, 100, window=self._placeholder)

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
        row.pack(fill="x", pady=4)
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
        row.pack(fill="x", pady=4)
        self.product_rows.append(row)

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

    # ── Run Analysis ──────────────────────────────────────────────────────────

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

        # Get product configs
        prod_configs = [row.get_values() for row in self.product_rows]

        # Disable run button and show status
        self._run_btn.configure(state="disabled", text="⏳  Running...")
        self._status_label.configure(text="Analyzing logs...", fg=TEXT_MID)
        self.update()

        # Run in background thread
        thread = threading.Thread(
            target=self._run_analysis,
            args=(log_paths, prod_configs, user_count, pdf_path, excluded_ips),
            daemon=True
        )
        thread.start()

    def _run_analysis(self, log_paths, prod_configs, user_count, pdf_path, excluded_ips=None):
        try:
            all_calls = []

            for log_path in log_paths:
                # Determine product from filename or use first product config
                product = "jira"
                for config in prod_configs:
                    if config["product"] in log_path.lower():
                        product = config["product"]
                        break
                else:
                    product = prod_configs[0]["product"] if prod_configs else "jira"

                calls = parse_log_file(log_path, product, excluded_ips=excluded_ips)
                calls = enrich_calls(calls)
                all_calls.extend(calls)

            if not all_calls:
                self.after(0, lambda: self._on_error("No external API calls found in the selected log files.\n\nCheck that you selected the correct log file and product type."))
                return

            # Use first product config for plan
            plan = prod_configs[0]["edition"] if prod_configs else "standard"

            # Generate PDF
            generate_pdf(all_calls, prod_configs[0]["product"], plan, pdf_path, user_count, excluded_ips=excluded_ips or [])

            # Update UI on main thread
            self.after(0, lambda: self._on_success(pdf_path, len(all_calls)))

        except Exception as e:
            self.after(0, lambda: self._on_error(str(e)))

    def _on_success(self, pdf_path: str, call_count: int):
        self._run_btn.configure(state="normal", text="▶   RUN ANALYSIS")
        self._status_label.configure(
            text=f"✅  Analysis complete — {call_count:,} API calls analyzed. PDF saved to: {pdf_path}",
            fg=GREEN
        )
        self._render_pdf(pdf_path)

    def _on_error(self, message: str):
        self._run_btn.configure(state="normal", text="▶   RUN ANALYSIS")
        self._status_label.configure(text=f"❌  Error: {message}", fg=RED)
        messagebox.showerror("Analysis Error", message)

    # ── PDF Preview ───────────────────────────────────────────────────────────

    def _render_pdf(self, pdf_path: str):
        """Render all pages of the PDF into the canvas."""
        try:
            self._placeholder.place_forget()
            self._canvas.delete("all")
            self._pdf_images.clear()

            canvas_width = self._canvas.winfo_width() or 860

            # Convert PDF pages to images using pdf2image + poppler
            pages = convert_from_path(pdf_path, dpi=150, poppler_path='/opt/homebrew/bin')
            y_offset = 10

            for img in pages:
                # Scale to fit canvas width
                scale = (canvas_width - 20) / img.width
                new_w = int(img.width * scale)
                new_h = int(img.height * scale)
                img = img.resize((new_w, new_h), Image.LANCZOS)

                img_tk = ImageTk.PhotoImage(img)
                self._pdf_images.append(img_tk)

                # Page shadow
                self._canvas.create_rectangle(
                    14, y_offset + 4, 14 + new_w, y_offset + 4 + new_h,
                    fill="#BBBBBB", outline=""
                )
                # Page image
                self._canvas.create_image(12, y_offset, anchor="nw", image=img_tk)

                y_offset += new_h + 16

            self._canvas.configure(scrollregion=(0, 0, canvas_width, y_offset))

        except Exception as e:
            self._status_label.configure(text=f"⚠️  PDF preview error: {e}", fg=YELLOW)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = AccessLogAnalyzerApp()
    app.mainloop()
