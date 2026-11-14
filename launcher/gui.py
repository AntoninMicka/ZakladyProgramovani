"""Tk rozcestník: výběr projektu, čitelný popis, zadání a živý konzolový výstup."""

from pathlib import Path
import re
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from launcher.catalog import ROOT, PROJECTS, make_plan
from launcher.process import Runner


class Document(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.text = tk.Text(
            self,
            wrap="word",
            height=8,
            state="disabled",
            padx=22,
            pady=18,
            font=("Sans", 11),
            bg="#ffffff",
            fg="#182234",
            relief="flat",
        )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        for level, size in ((1, 21), (2, 15), (3, 12)):
            self.text.tag_configure(
                f"h{level}", font=("Sans", size, "bold"), spacing1=15, spacing3=8
            )
        self.text.tag_configure(
            "code", font=("Monospace", 10), background="#edf2f8", spacing1=3
        )
        self.text.tag_configure("link", foreground="#145ac7", underline=True)

    def load(self, path):
        path = Path(path)
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            content = "# Dokument nelze načíst\n\n" + str(exc)
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        # Značky odkazů mají vlastní vazby; při změně dokumentu se uklidí.
        for tag in self.text.tag_names():
            if tag.startswith("url_"):
                self.text.tag_delete(tag)
        if path.suffix.lower() not in (".md", ".txt"):
            self.text.insert("end", str(path.relative_to(ROOT)) + "\n\n", "h3")
            self.text.insert("end", content, "code")
            self.text.configure(state="disabled")
            self.text.yview_moveto(0)
            return
        code, number = False, 0
        for line in content.splitlines():
            if line.startswith("```"):
                code = not code
                continue
            match = re.match(r"^(#{1,3}) (.*)", line)
            if code:
                self.text.insert("end", line + "\n", "code")
            elif match:
                self.text.insert("end", match[2] + "\n", f"h{len(match[1])}")
            else:
                cursor = 0
                for link in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", line):
                    self.text.insert(
                        "end",
                        line[cursor : link.start()].replace("**", "").replace("`", ""),
                    )
                    tag = f"url_{number}"
                    number += 1
                    destination = link[2]
                    self.text.insert("end", link[1], ("link", tag))
                    self.text.tag_bind(
                        tag,
                        "<Button-1>",
                        lambda event, url=destination: self.open_link(path, url),
                    )
                    cursor = link.end()
                self.text.insert(
                    "end", line[cursor:].replace("**", "").replace("`", "") + "\n"
                )
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)

    def open_link(self, source, destination):
        if destination.startswith(("https://", "http://")):
            webbrowser.open(destination)
            return
        if destination.startswith("#"):
            return
        path = (source.parent / destination.split("#")[0]).resolve()
        if not path.is_relative_to(ROOT):
            return
        if path.suffix.lower() in (
            ".md",
            ".txt",
            ".py",
            ".c",
            ".cpp",
            ".h",
            ".sh",
            ".ps1",
        ):
            self.load(path)
        else:
            open_local(path)


def open_local(path):
    opener = shutil.which("xdg-open")
    if not opener:
        raise ValueError("Chybí xdg-open pro otevření souboru nebo složky.")
    subprocess.Popen(
        [opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


class Launcher:
    def __init__(self, root, runner=None):
        self.root = root
        self.runner = runner or Runner()
        self.closing = False
        self.closed = False
        self.timer = None
        root.title("Základy programování · projekty a studentské úkoly")
        root.geometry("1240x880")
        root.minsize(960, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", padding=(12, 7))
        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)
        heading = ttk.Frame(outer)
        heading.pack(fill="x", pady=(0, 14))
        ttk.Label(heading, text="DÍLNA PROGRAMOVÁNÍ", font=("Sans", 21, "bold")).pack(
            side="left"
        )
        ttk.Label(
            heading,
            text="Vyber projekt · přečti zadání · vyzkoušej kód",
            foreground="#57677e",
        ).pack(side="right")
        split = ttk.Panedwindow(outer, orient="horizontal")
        split.pack(fill="both", expand=True)
        sidebar = ttk.Frame(split, padding=(0, 0, 14, 0))
        content = ttk.Frame(split)
        split.add(sidebar, weight=0)
        split.add(content, weight=1)
        ttk.Label(sidebar, text="PODPROJEKTY", font=("Sans", 10, "bold")).pack(
            anchor="w"
        )
        self.search = tk.StringVar()
        entry = ttk.Entry(sidebar, textvariable=self.search, width=30)
        entry.pack(fill="x", pady=8)
        self.search.trace_add("write", lambda *args: self.filter_projects())
        self.projects = tk.Listbox(
            sidebar,
            exportselection=False,
            width=31,
            height=10,
            font=("Sans", 11),
            activestyle="none",
            relief="flat",
            selectbackground="#d9e8ff",
            selectforeground="#12375c",
        )
        self.projects.pack(fill="both", expand=True)
        self.projects.bind("<<ListboxSelect>>", self.selected)
        ttk.Label(
            sidebar,
            text="Jedna spuštěná akce najednou.\nPopisy a úkoly lze číst i za běhu.",
            foreground="#57677e",
        ).pack(anchor="w", pady=12)
        self.title = tk.StringVar()
        self.subtitle = tk.StringVar()
        ttk.Label(content, textvariable=self.title, font=("Sans", 20, "bold")).pack(
            anchor="w"
        )
        ttk.Label(content, textvariable=self.subtitle, wraplength=810).pack(
            anchor="w", pady=(5, 12)
        )
        toolbar = ttk.Frame(content)
        toolbar.pack(fill="x")
        self.action = tk.StringVar()
        self.actions = ttk.Combobox(toolbar, textvariable=self.action, state="readonly")
        self.actions.pack(side="left", fill="x", expand=True)
        self.actions.bind("<<ComboboxSelected>>", lambda event: self.update_note())
        self.start_button = ttk.Button(toolbar, text="Spustit akci", command=self.start)
        self.start_button.pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(
            toolbar, text="Zastavit", command=self.runner.stop
        )
        self.stop_button.pack(side="left", padx=(8, 0))
        self.note = tk.StringVar()
        ttk.Label(
            content, textvariable=self.note, foreground="#526176", wraplength=850
        ).pack(anchor="w", pady=(6, 8))
        shortcuts = ttk.Frame(content)
        shortcuts.pack(fill="x", pady=(0, 10))
        ttk.Button(
            shortcuts,
            text="Otevřít složku",
            command=lambda: self.open_path(ROOT / self.project.directory),
        ).pack(side="left")
        ttk.Button(
            shortcuts, text="Zobrazit zdrojový kód", command=self.show_source
        ).pack(side="left", padx=8)
        self.path = tk.StringVar()
        ttk.Label(content, textvariable=self.path, foreground="#68748a").pack(
            anchor="w", pady=(0, 8)
        )
        self.notebook = ttk.Notebook(content)
        self.notebook.pack(fill="both", expand=True)
        self.overview = Document(self.notebook)
        self.tasks = Document(self.notebook)
        self.documentation = Document(self.notebook)
        self.notebook.add(self.overview, text="Podrobný popis")
        self.notebook.add(self.tasks, text="Úkoly pro studenta")
        self.notebook.add(self.documentation, text="README / zdroj")
        output_page = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(output_page, text="Výstup programu")
        self.output = tk.Text(
            output_page,
            height=8,
            bg="#142033",
            fg="#e5eefb",
            insertbackground="white",
            font=("Monospace", 10),
            wrap="word",
            state="disabled",
        )
        scroll = ttk.Scrollbar(output_page, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.output.pack(fill="both", expand=True)
        inputs = ttk.Frame(content)
        inputs.pack(fill="x", pady=(10, 4))
        ttk.Label(inputs, text="Vstup do běžícího programu:").pack(side="left")
        self.input = ttk.Entry(inputs)
        self.input.pack(side="left", fill="x", expand=True, padx=8)
        self.input.bind("<Return>", self.send)
        self.send_button = ttk.Button(inputs, text="Odeslat ↵", command=self.send)
        self.send_button.pack(side="left")
        ttk.Button(
            inputs, text="Konec vstupu (EOF)", command=self.runner.end_input
        ).pack(side="left", padx=5)
        self.status = tk.StringVar(value="Připraveno")
        ttk.Label(outer, textvariable=self.status, foreground="#37547a").pack(
            anchor="w", pady=(12, 0)
        )
        self.visible = []
        self.project = None
        self.filter_projects()
        self.select_project("ecu")
        self.poll()

    def filter_projects(self):
        query = self.search.get().casefold()
        old = self.project.id if self.project else None
        self.visible = [
            p for p in PROJECTS if query in (p.title + " " + p.subtitle).casefold()
        ]
        self.projects.delete(0, "end")
        for project in self.visible:
            self.projects.insert("end", project.title)
        if self.visible:
            self.select_project(
                old if any(p.id == old for p in self.visible) else self.visible[0].id
            )

    def select_project(self, identifier):
        for i, project in enumerate(self.visible):
            if project.id == identifier:
                self.projects.selection_clear(0, "end")
                self.projects.selection_set(i)
                self.projects.see(i)
                self.show_project(project)
                return

    def selected(self, event=None):
        selection = self.projects.curselection()
        if selection:
            self.show_project(self.visible[selection[0]])

    def show_project(self, project):
        self.project = project
        self.title.set(project.title)
        self.subtitle.set(project.subtitle)
        self.path.set("Složka: " + project.directory)
        self.actions.configure(values=[a.title for a in project.actions])
        self.actions.current(0)
        self.update_note()
        self.overview.load(ROOT / project.overview)
        self.tasks.load(ROOT / project.tasks)
        self.documentation.load(ROOT / project.readme)

    def selected_action(self):
        index = self.actions.current()
        return self.project.actions[max(index, 0)]

    def update_note(self):
        self.note.set(
            self.selected_action().note or "Výpis se zobrazí v záložce Výstup programu."
        )

    def start(self):
        try:
            plan = make_plan(self.project, self.selected_action())
            self.runner.start(plan)
            self.output.configure(state="normal")
            self.output.delete("1.0", "end")
            self.output.insert(
                "end",
                "Projekt: " + plan.title + "\nPracovní složka: " + str(plan.cwd) + "\n",
            )
            self.output.configure(state="disabled")
            self.notebook.select(3)
        except (OSError, ValueError) as exc:
            self.status.set(str(exc))
            messagebox.showerror("Akci nelze spustit", str(exc), parent=self.root)

    def show_source(self):
        self.documentation.load(ROOT / self.project.source)
        self.notebook.select(2)

    def open_path(self, path):
        try:
            open_local(path)
        except (OSError, ValueError) as exc:
            self.status.set(str(exc))

    def send(self, event=None):
        try:
            self.runner.send(self.input.get())
            self.input.delete(0, "end")
        except ValueError as exc:
            self.status.set(str(exc))
        return "break"

    def poll(self):
        if self.closed:
            return
        chunk = self.runner.drain()
        if chunk:
            self.output.configure(state="normal")
            self.output.insert("end", chunk)
            if int(self.output.index("end-1c").split(".")[0]) > 2000:
                self.output.delete("1.0", "end-2000l")
            if len(self.output.get("1.0", "end-1c")) > 200000:
                self.output.delete("1.0", "end-200000c")
            self.output.see("end")
            self.output.configure(state="disabled")
        self.start_button.configure(
            state="disabled" if self.runner.busy or self.closing else "normal"
        )
        self.stop_button.configure(
            state="normal" if self.runner.busy and not self.closing else "disabled"
        )
        self.send_button.configure(
            state="normal" if self.runner.busy and not self.closing else "disabled"
        )
        self.status.set(
            self.runner.status
            + (
                f" · vynechané bloky výstupu: {self.runner.dropped}"
                if self.runner.dropped
                else ""
            )
        )
        if self.closing and not self.runner.busy:
            self.closed = True
            self.root.destroy()
            return
        self.timer = self.root.after(60, self.poll)

    def close(self):
        if self.closed:
            return
        self.closing = True
        self.runner.stop()
        if not self.runner.busy:
            self.closed = True
            if self.timer:
                self.root.after_cancel(self.timer)
            self.root.destroy()


def run_gui():
    root = tk.Tk()
    Launcher(root)
    root.mainloop()
