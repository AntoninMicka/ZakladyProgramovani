"""Průvodce ověřením páček/tlačítek. Čte tentýž abstraktní stav jako zařízení."""

import json
import tkinter as tk
from pathlib import Path
from time import monotonic
from tkinter import filedialog, messagebox, ttk

from gamepad_check import LABELS, GamepadCheck


class GamepadCheckDialog:
    def __init__(self, parent, joypad, on_close):
        self.on_close = on_close
        self.session = None
        self.latest = joypad.semantic_state()
        self.device, self.name = joypad.device, joypad.name
        self.connected = joypad.fd is not None
        self.window = tk.Toplevel(parent)
        self.window.title("Ověření páček a tlačítek · " + joypad.name)
        self.window.geometry("850x750")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.grab_set()
        self.prompt = tk.StringVar(
            value="Uvolni obě páčky, kříž, jednosměrné páky a tlačítka. Pak zahaj ověřování."
        )
        self.progress = tk.StringVar(value="20 kroků · po každém je nutný návrat do klidu")
        self.detail = tk.StringVar(value="Ověřují se pojmenované prvky; jízdní mapování se nemění.")
        ttk.Label(self.window, textvariable=self.progress).pack(anchor="w", padx=14, pady=(12, 4))
        ttk.Label(
            self.window, textvariable=self.prompt, font=("Sans", 15, "bold"), wraplength=800
        ).pack(anchor="w", padx=14, pady=8)
        ttk.Label(self.window, textvariable=self.detail, wraplength=800).pack(
            anchor="w", padx=14, pady=4
        )
        toolbar = ttk.Frame(self.window, padding=10)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Zahájit / začít znovu", command=self.start).pack(side="left")
        ttk.Button(toolbar, text="Nefunguje", command=lambda: self.mark("failed")).pack(
            side="left", padx=6
        )
        ttk.Button(toolbar, text="Přeskočit", command=lambda: self.mark("skipped")).pack(
            side="left"
        )
        ttk.Button(toolbar, text="Uložit protokol…", command=self.save).pack(side="right")
        ttk.Label(self.window, text="Živé pojmenované vstupy").pack(anchor="w", padx=14)
        self.live = ttk.Treeview(
            self.window, columns=("value", "binding"), show="tree headings", height=14
        )
        self.live.heading("#0", text="Prvek ovladače")
        self.live.heading("value", text="Hodnota")
        self.live.heading("binding", text="Fyzická vazba (diagnostika)")
        self.live.column("#0", width=300)
        self.live.column("value", width=80)
        self.live.pack(fill="both", expand=True, padx=14, pady=6)
        for key, label in LABELS.items():
            self.live.insert("", "end", iid=key, text=label)
        self.log = tk.Text(self.window, height=7, state="disabled", wrap="word")
        self.log.pack(fill="x", padx=14, pady=6)
        ttk.Button(self.window, text="Zavřít", command=self.close).pack(
            anchor="e", padx=14, pady=(0, 12)
        )
        self.render()

    def start(self):
        if not self.connected:
            messagebox.showerror(
                "Ovladač odpojen", "Nejprve připoj ovladač v hlavním okně.", parent=self.window
            )
            return
        try:
            self.session = GamepadCheck(self.latest, self.device, self.name)
        except ValueError as exc:
            messagebox.showerror("Vstupy nejsou v klidu", str(exc), parent=self.window)
            return
        self.render()

    def mark(self, status):
        if self.session:
            self.session.mark(status)
        self.render()

    def update(self, joypad, connected):
        self.connected = connected and joypad.device == self.device
        self.latest = joypad.semantic_state()
        if self.session:
            if not self.connected:
                self.session.disconnected()
            else:
                self.session.observe(self.latest, monotonic())
        self.render()

    def render(self):
        for key in LABELS:
            value = self.latest.values[key]
            self.live.item(
                key,
                values=(
                    "—" if value is None else f"{value:+.3f}",
                    str(self.latest.bindings.get(key, "nedostupné")),
                ),
            )
        if not self.session:
            return
        session = self.session
        self.prompt.set(session.prompt)
        self.detail.set(session.message)
        report = session.report()
        self.progress.set(
            f"Krok {min(session.index + 1, len(session.steps))}/{len(session.steps)} · "
            f"OK {report['passed']} · nefunguje {report['failed']} · přeskočeno {report['skipped']}"
        )
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        for result in report["results"]:
            status = {
                "passed": "OK + návrat do klidu",
                "failed": "NEFUNGUJE",
                "skipped": "NEOVĚŘENO",
            }[result["status"]]
            self.log.insert("end", f"{status}: {result['prompt']}\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def save(self):
        if self.session is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".json",
            initialfile="overeni-gamepadu.json",
            filetypes=[("JSON", "*.json")],
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(self.session.report(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                messagebox.showerror("Nelze uložit", str(exc), parent=self.window)

    def close(self):
        self.window.grab_release()
        self.window.destroy()
        self.on_close()
