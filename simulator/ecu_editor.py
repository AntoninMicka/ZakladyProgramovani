"""Samostatná záložka C/C++ editoru s explicitním buildem a aplikací firmware."""

from pathlib import Path
import re
from time import monotonic
import tkinter as tk
from tkinter import ttk, messagebox
from ecu_source import SourceDocument, source_files, source_revision


class EcuEditor:
    def __init__(self, page, panel, show_log):
        self.page, self.panel = page, panel
        self.document = None
        self.project = None
        self.paths = {}
        self.highlight_timer = None
        self.closed = False
        self.next_poll = 0
        self.filename = tk.StringVar()
        self.status = tk.StringVar(value="Načítám zdroj ECU…")
        self.revisions = tk.StringVar()
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        self.selector = ttk.Combobox(toolbar, textvariable=self.filename, state="readonly")
        self.selector.pack(side="left", fill="x", expand=True)
        self.selector.bind("<<ComboboxSelected>>", lambda event: self.load_selected())
        ttk.Button(toolbar, text="Načíst", command=self.reload).pack(side="left", padx=5)
        self.save_button = ttk.Button(toolbar, text="Uložit", command=self.save)
        self.save_button.pack(side="left")
        self.build_button = ttk.Button(toolbar, text="Sestavit", command=self.build)
        self.build_button.pack(side="left", padx=5)
        self.apply_button = ttk.Button(
            toolbar, text="Použít v simulaci", command=lambda: self.build(True)
        )
        self.apply_button.pack(side="left")
        ttk.Button(toolbar, text="Výpis Wokwi", command=show_log).pack(side="left", padx=5)
        ttk.Label(
            page,
            text="Úpravy lze psát za běhu. Použít = uložit, sestavit a po úspěchu obnovit aktivní Mock nebo Wokwi od času nula.",
            wraplength=1080,
        ).pack(anchor="w")
        ttk.Label(
            page,
            text="Mock používá řídicí logiku ecu_controller.h. main.cpp obsluhuje piny a časovače desky ve Wokwi.",
            wraplength=1080,
        ).pack(anchor="w")
        ttk.Label(page, textvariable=self.status, wraplength=1080).pack(anchor="w", pady=5)
        ttk.Label(page, textvariable=self.revisions, wraplength=1080).pack(anchor="w", pady=(0, 6))
        body = ttk.Frame(page)
        body.pack(fill="both", expand=True)
        self.lines = tk.Text(
            body,
            width=5,
            bg="#1e293b",
            fg="#94a3b8",
            state="disabled",
            font=("Monospace", 11),
            takefocus=False,
        )
        self.code = tk.Text(
            body,
            undo=True,
            wrap="none",
            font=("Monospace", 11),
            bg="#0b1220",
            fg="#e2e8f0",
            insertbackground="white",
            tabs=("4c",),
        )
        vertical = ttk.Scrollbar(body, orient="vertical", command=self.scroll)
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=self.code.xview)
        self.code.configure(
            yscrollcommand=lambda a, b: (
                vertical.set(a, b),
                self.lines.yview_moveto(a),
            ),
            xscrollcommand=horizontal.set,
        )
        self.lines.grid(row=0, column=0, sticky="ns")
        self.code.grid(row=0, column=1, sticky="nsew")
        vertical.grid(row=0, column=2, sticky="ns")
        horizontal.grid(row=1, column=1, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        self.code.tag_configure("keyword", foreground="#c4b5fd")
        self.code.tag_configure("comment", foreground="#86efac")
        self.code.tag_configure("string", foreground="#fcd34d")
        self.code.bind("<<Modified>>", self.changed)
        self.code.bind("<Control-s>", self.save_shortcut)
        self.code.bind("<Tab>", self.insert_tab)
        ttk.Label(page, text="Výsledek sestavení / poslední řádky překladače").pack(
            anchor="w", pady=(8, 3)
        )
        self.build_log = tk.Text(
            page,
            height=6,
            bg="#1e293b",
            fg="#e2e8f0",
            font=("Monospace", 10),
            state="disabled",
        )
        self.build_log.pack(fill="x")
        self.sync_project()

    @property
    def dirty(self):
        return self.document is not None and self.code.get("1.0", "end-1c") != self.document.text

    def save_shortcut(self, event=None):
        self.save()
        return "break"

    def scroll(self, *args):
        self.code.yview(*args)
        self.lines.yview(*args)

    def insert_tab(self, event):
        self.code.insert("insert", "    ")
        return "break"

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Neuložený kód ECU",
            "Uložit změny před zavřením nebo načtením jiného souboru?",
            parent=self.page.winfo_toplevel(),
        )
        if answer is None:
            return False
        return self.save() if answer else True

    def sync_project(self):
        project = Path(self.panel.project.get()).expanduser().resolve()
        if project == self.project:
            return
        if self.dirty:
            self.status.set("Projekt Wokwi se změnil. Uložte rozepsaný soubor a použijte Načíst.")
            return
        self.document = None
        self.project = project
        self.paths = {str(path.relative_to(project)): path for path in source_files(project)}
        self.selector.configure(values=list(self.paths))
        self.filename.set(next(iter(self.paths), ""))
        self.load_selected(confirm=False)

    def load_selected(self, confirm=True):
        if confirm and not self.confirm_discard():
            if self.document:
                self.filename.set(str(self.document.path.relative_to(self.project)))
            return
        path = self.paths.get(self.filename.get())
        if path is None:
            self.document = None
            self.code.configure(state="normal")
            self.code.delete("1.0", "end")
            self.code.configure(state="disabled")
            self.status.set("Projekt nemá editovatelné firmware/src nebo src soubory.")
            return
        try:
            self.document = SourceDocument(path)
            self.code.configure(state="normal")
            self.code.delete("1.0", "end")
            self.code.insert("1.0", self.document.text)
            self.code.edit_reset()
            self.code.edit_modified(False)
            self.status.set("Načteno: " + str(path))
            self.highlight()
        except (OSError, ValueError) as exc:
            if self.document:
                self.filename.set(str(self.document.path.relative_to(self.project)))
            self.status.set(str(exc))

    def reload(self):
        if not self.confirm_discard():
            return
        project = Path(self.panel.project.get()).expanduser().resolve()
        if project != self.project:
            self.document = None
            self.project = None
            self.sync_project()
        else:
            self.load_selected(confirm=False)

    def save(self):
        if self.document is None:
            return False
        if (
            self.panel.mock_busy
            or self.panel.builder.busy
            or self.panel.build_context is not None
            or self.panel.pending_apply is not None
        ):
            self.status.set(
                "Během sestavení lze psát, ale uložit další revizi až po dokončení buildu."
            )
            return False
        try:
            self.document.save(self.code.get("1.0", "end-1c"))
            self.status.set("Uloženo. Běžící firmware se zatím nezměnil.")
            return True
        except (OSError, ValueError) as exc:
            self.status.set(str(exc))
            return False

    def build(self, apply=False):
        if self.project != Path(self.panel.project.get()).expanduser().resolve():
            self.status.set("Nejdříve načtěte soubor z aktuálního projektu.")
            return
        if self.save():
            if self.panel.app.mode == "mock":
                self.panel.build_mock(apply_after=apply)
            else:
                self.panel.build(apply_after=apply)

    def changed(self, event=None):
        if not self.code.edit_modified():
            return
        self.code.edit_modified(False)
        if self.highlight_timer:
            self.code.after_cancel(self.highlight_timer)
        self.highlight_timer = self.code.after(150, self.highlight)

    def highlight(self):
        self.highlight_timer = None
        if self.closed:
            return
        text = self.code.get("1.0", "end-1c")
        self.lines.configure(state="normal")
        self.lines.delete("1.0", "end")
        self.lines.insert("1.0", "\n".join(str(i) for i in range(1, text.count("\n") + 2)))
        self.lines.configure(state="disabled")
        for name in ("keyword", "comment", "string"):
            self.code.tag_remove(name, "1.0", "end")
        patterns = {
            "keyword": r"\b(?:void|static|const|if|else|for|while|return|struct|bool|double|unsigned|int|float|true|false|uint32_t|uint64_t|include|define)\b",
            "string": r'"(?:\\.|[^"\\])*"',
            "comment": r"//[^\n]*|/\*[\s\S]*?\*/",
        }
        for name, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                self.code.tag_add(name, f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def poll(self):
        if monotonic() < self.next_poll:
            return
        self.next_poll = monotonic() + 0.25
        self.sync_project()
        busy = (
            self.panel.mock_busy
            or self.panel.builder.busy
            or self.panel.build_context is not None
            or self.panel.pending_apply is not None
        )
        for button in (self.save_button, self.build_button, self.apply_button):
            button.configure(state="disabled" if busy else "normal")
        saved = source_revision(self.project)[:10] if self.project and self.document else "—"
        built = (
            (
                self.panel.mock_built_revision
                if self.panel.app.mode == "mock"
                else self.panel.built_revision
            )
            or "—"
        )[:10]
        if self.panel.app.mode == "mock":
            running = self.panel.app.bridge.controller.revision[:10]
            backend = "Mock ECU"
        else:
            running = (self.panel.running_revision or "neověřeno")[:10]
            backend = "Wokwi / předaná revize"
        self.revisions.set(
            f"Soubor: {'NEULOŽENÉ ZMĚNY' if self.dirty else 'uložen'} · disk {saved} · sestaveno {built} · {backend} {running}"
        )
        self.build_log.configure(state="normal")
        self.build_log.delete("1.0", "end")
        self.build_log.insert(
            "1.0", self.panel.build_status + "\n" + "\n".join(self.panel.build_lines)
        )
        self.build_log.configure(state="disabled")
        self.build_log.see("end")

    def close(self):
        self.closed = True
        if self.highlight_timer:
            try:
                self.code.after_cancel(self.highlight_timer)
            except tk.TclError:
                pass
