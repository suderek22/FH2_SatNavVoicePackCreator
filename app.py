"""SatNav Voice pack creator - GUI."""
import ctypes
import os
import queue
import threading
import time
import traceback
import tkinter as tk
import winsound
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import engine as E

BG = '#eef0f3'
PANEL = '#ffffff'
TEXT = '#111827'
MUTED = '#6b7280'
LINE = '#e5e7eb'
ACCENT = '#2563eb'
GOOD = '#15803d'
WARN = '#b45309'
BAD = '#b91c1c'
CAT_COLORS = {'imperial': '#2563eb', 'metric': '#dc2626', 'various': '#eab308', 'other': '#9ca3af'}
CAT_NAMES = {'imperial': 'IMPERIAL', 'metric': 'METRIC', 'various': 'VARIOUS', 'other': 'OTHER'}
FONT = ('Segoe UI', 10)
FONT_BOLD = ('Segoe UI', 10, 'bold')
FONT_SMALL = ('Segoe UI', 9)


def play_file(path):
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


def stop_sound():
    winsound.PlaySound(None, winsound.SND_PURGE)


def center(win, parent):
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    win.geometry('+%d+%d' % (max(x, 0), max(y, 0)))


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind('<Enter>', self.show)
        widget.bind('<Leave>', self.hide)

    def show(self, _event=None):
        if self.tip:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip.wm_geometry('+%d+%d' % (x, y))
        tk.Label(self.tip, text=self.text, bg='#111827', fg='white', font=FONT_SMALL, padx=8,
                 pady=5, justify='left', wraplength=320).pack()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Modal(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.parent = parent
        self.title(title)
        self.configure(bg=BG)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.bind('<Escape>', lambda _e: self.cancel())
        self.body = ttk.Frame(self, padding=18)
        self.body.pack(fill='both', expand=True)

    def buttons(self, ok_text='OK', cancel_text='Cancel'):
        bar = ttk.Frame(self.body)
        bar.grid(row=99, column=0, columnspan=3, sticky='e', pady=(16, 0))
        ttk.Button(bar, text=cancel_text, command=self.cancel).pack(side='right')
        ok = ttk.Button(bar, text=ok_text, style='Accent.TButton', command=self.ok)
        ok.pack(side='right', padx=(0, 8))
        self.bind('<Return>', lambda _e: self.ok())

    def ok(self):
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()

    def show(self):
        center(self, self.parent)
        self.grab_set()
        self.focus_set()
        self.wait_window(self)
        return self.result


def guess_dirs():
    here = E.app_dir()
    for base in [here] + list(here.parents)[:4]:
        game = base / E.GAME_FOLDER_NAME
        if game.is_dir():
            mods = base / 'fh2-mods'
            return str(game), str(mods) if mods.is_dir() else ''
    return '', ''


class SettingsDialog(Modal):
    def __init__(self, parent, game, mods, required):
        super().__init__(parent, 'Game folders')
        if not game and not mods:
            game, mods = guess_dirs()
        self.game, self.mods = tk.StringVar(value=game), tk.StringVar(value=mods)
        b = self.body
        ttk.Label(b, text='Where is Forza Horizon 2?', font=('Segoe UI', 12, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(b, foreground=MUTED, wraplength=520, text=(
            'The tool reads the stock SatNav banks from the game folder and installs finished packs '
            'into the fh2-mods folder.')).grid(row=1, column=0, columnspan=3, sticky='w', pady=(2, 12))
        ttk.Label(b, text='Game folder (%s)' % E.GAME_FOLDER_NAME).grid(row=2, column=0, columnspan=3,
                                                                       sticky='w')
        ttk.Entry(b, textvariable=self.game, width=62).grid(row=3, column=0, columnspan=2, sticky='we')
        ttk.Button(b, text='Browse...', command=self.pick_game).grid(row=3, column=2, padx=(6, 0))
        self.game_err = ttk.Label(b, foreground=BAD)
        self.game_err.grid(row=4, column=0, columnspan=3, sticky='w')
        ttk.Label(b, text='fh2-mods folder').grid(row=5, column=0, columnspan=3, sticky='w', pady=(10, 0))
        ttk.Entry(b, textvariable=self.mods, width=62).grid(row=6, column=0, columnspan=2, sticky='we')
        ttk.Button(b, text='Browse...', command=self.pick_mods).grid(row=6, column=2, padx=(6, 0))
        self.mods_err = ttk.Label(b, foreground=BAD)
        self.mods_err.grid(row=7, column=0, columnspan=3, sticky='w')
        self.buttons('OK', 'Quit' if required else 'Cancel')

    def pick_game(self):
        p = filedialog.askdirectory(parent=self, title='Select the %s folder' % E.GAME_FOLDER_NAME)
        if p:
            self.game.set(os.path.normpath(p))
            sibling = Path(p).parent / 'fh2-mods'
            if not self.mods.get() and sibling.is_dir():
                self.mods.set(os.path.normpath(str(sibling)))

    def pick_mods(self):
        p = filedialog.askdirectory(parent=self, title='Select the fh2-mods folder')
        if p:
            self.mods.set(os.path.normpath(p))

    def ok(self):
        ge = E.validate_game_dir(self.game.get().strip())
        me = E.validate_mods_dir(self.mods.get().strip())
        self.game_err.configure(text=ge or '')
        self.mods_err.configure(text=me or '')
        if not ge and not me:
            self.result = (self.game.get().strip(), self.mods.get().strip())
            self.destroy()


class NewPackDialog(Modal):
    def __init__(self, parent, langs, loaded):
        super().__init__(parent, 'New voice pack')
        self.loaded = loaded
        self.map = {E.lang_label(l): l for l in langs}
        self.name = tk.StringVar(value='My voice pack')
        b = self.body
        ttk.Label(b, text='Create a voice pack', font=('Segoe UI', 12, 'bold')).grid(
            row=0, column=0, sticky='w')
        ttk.Label(b, text='Name').grid(row=1, column=0, sticky='w', pady=(12, 0))
        entry = ttk.Entry(b, textvariable=self.name, width=40)
        entry.grid(row=2, column=0, sticky='we')
        ttk.Label(b, text='Language').grid(row=3, column=0, sticky='w', pady=(10, 0))
        self.lang = ttk.Combobox(b, values=list(self.map), state='readonly', width=37)
        preferred = [k for k, v in self.map.items() if v == 'EN'] or list(self.map)
        self.lang.set(preferred[0])
        self.lang.grid(row=4, column=0, sticky='we')
        self.lang.bind('<<ComboboxSelected>>', lambda _e: self.note())
        self.note_label = ttk.Label(b, foreground=MUTED, wraplength=320)
        self.note_label.grid(row=5, column=0, sticky='w', pady=(6, 0))
        self.err = ttk.Label(b, foreground=BAD)
        self.err.grid(row=6, column=0, sticky='w')
        self.note()
        self.buttons('Create')
        entry.focus_set()
        entry.select_range(0, 'end')

    def note(self):
        lang = self.map[self.lang.get()]
        self.note_label.configure(text='' if lang in self.loaded else
                                  'The stock %s sounds will be exported first (takes a few seconds).' % lang)

    def ok(self):
        name = self.name.get().strip()
        if not name:
            self.err.configure(text='Enter a name.')
            return
        self.result = (name, self.map[self.lang.get()])
        self.destroy()


class LoadStockDialog(Modal):
    def __init__(self, parent, langs, loaded):
        super().__init__(parent, 'Load stock bank')
        self.loaded = loaded
        self.map = {E.lang_label(l): l for l in langs}
        b = self.body
        ttk.Label(b, text='Load a stock SatNav bank', font=('Segoe UI', 12, 'bold')).grid(
            row=0, column=0, sticky='w')
        ttk.Label(b, foreground=MUTED, wraplength=340, text=(
            'Exports every sound of the game bank to WAV files (with a CSV list) in the tool folder.'
        )).grid(row=1, column=0, sticky='w', pady=(2, 10))
        ttk.Label(b, text='Language').grid(row=2, column=0, sticky='w')
        self.lang = ttk.Combobox(b, values=list(self.map), state='readonly', width=37)
        self.lang.set(list(self.map)[0] if self.map else '')
        self.lang.grid(row=3, column=0, sticky='we')
        self.lang.bind('<<ComboboxSelected>>', lambda _e: self.note())
        self.note_label = ttk.Label(b, foreground=MUTED)
        self.note_label.grid(row=4, column=0, sticky='w', pady=(6, 0))
        self.note()
        self.buttons('Load')

    def note(self):
        lang = self.map.get(self.lang.get())
        self.note_label.configure(text='Already loaded - it will be exported again.'
                                  if lang in self.loaded else '')

    def ok(self):
        if self.lang.get():
            self.result = self.map[self.lang.get()]
        self.destroy()


class ProgressDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.transient(parent)
        self.resizable(False, False)
        self.protocol('WM_DELETE_WINDOW', lambda: None)
        body = ttk.Frame(self, padding=18)
        body.pack()
        ttk.Label(body, text=title, font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        self.text = tk.StringVar(value='Starting...')
        ttk.Label(body, textvariable=self.text, width=70).pack(anchor='w', pady=(8, 6))
        self.bar = ttk.Progressbar(body, length=460, maximum=100)
        self.bar.pack()
        self.q = queue.Queue()
        center(self, parent)
        self.grab_set()

    def report(self, fraction, text):
        self.q.put((fraction, text))

    def finish(self):
        self.q.put(None)

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    self.grab_release()
                    self.destroy()
                    return
                self.bar['value'] = item[0] * 100
                self.text.set(item[1][:90])
        except queue.Empty:
            pass
        self.after(40, self.poll)


class RowWidgets:
    pass


class App:
    def __init__(self, root):
        self.root = root
        self.engine = E.Engine()
        self.engine.load_packs()
        self.current = None
        self.lines = []
        self.rows = {}
        self.name_guard = False
        self.log_q = queue.Queue()
        root.title('%s %s' % (E.APP_NAME, E.APP_VERSION))
        root.geometry('1320x800')
        root.minsize(1100, 640)
        root.configure(bg=BG)
        icon = E.resource_dir() / 'app.ico'
        if icon.exists():
            try:
                root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.setup_style()
        self.build_ui()
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.report_callback_exception = self.on_exception
        root.bind_all('<MouseWheel>', self.on_wheel)
        root.bind_all('<Control-s>', lambda _e: self.on_save())
        self.refresh_tree()
        root.after(150, self.startup)

    # ------------------------------------------------------------ style / layout
    def setup_style(self):
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('.', background=BG, foreground=TEXT, font=FONT)
        s.configure('TFrame', background=BG)
        s.configure('TLabel', background=BG, foreground=TEXT)
        s.configure('TButton', padding=(12, 6), background='#e5e7eb', borderwidth=0, focusthickness=0)
        s.map('TButton', background=[('active', '#d1d5db'), ('disabled', '#f3f4f6')],
              foreground=[('disabled', '#9ca3af')])
        s.configure('Accent.TButton', background=ACCENT, foreground='white')
        s.map('Accent.TButton', background=[('active', '#1d4ed8'), ('disabled', '#93c5fd')],
              foreground=[('disabled', 'white')])
        s.configure('Danger.TButton', background='#fee2e2', foreground=BAD)
        s.map('Danger.TButton', background=[('active', '#fecaca'), ('disabled', '#f3f4f6')],
              foreground=[('disabled', '#9ca3af')])
        s.configure('Small.TButton', padding=(8, 3), font=FONT_SMALL)
        s.configure('Big.TButton', padding=(26, 14), font=('Segoe UI', 13, 'bold'))
        s.configure('Treeview', rowheight=34, background=PANEL, fieldbackground=PANEL,
                    borderwidth=0, font=FONT)
        s.map('Treeview', background=[('selected', '#dbeafe')], foreground=[('selected', TEXT)])
        s.configure('Treeview.Heading', font=FONT_BOLD, background='#e5e7eb', padding=6)
        s.configure('TNotebook', background=BG, borderwidth=0)
        s.configure('TNotebook.Tab', padding=(18, 8), font=FONT_BOLD, background='#dfe2e7')
        s.map('TNotebook.Tab', background=[('selected', PANEL)], padding=[('selected', (18, 8))],
              expand=[('selected', (0, 0, 0, 0))])

    def build_ui(self):
        top = tk.Frame(self.root, bg='#111827')
        top.pack(fill='x')
        tk.Label(top, text=E.APP_NAME, bg='#111827', fg='white',
                 font=('Segoe UI', 12, 'bold')).pack(side='left', padx=14, pady=10)
        for text, cmd in (('Import pack (.zip)', self.on_import), ('Load stock .bank', self.on_load_stock),
                          ('Game folders', self.on_settings), ('Stop sound', stop_sound)):
            ttk.Button(top, text=text, command=cmd, style='Small.TButton').pack(side='left', padx=(0, 6),
                                                                              pady=8)
        tk.Label(top, text='v' + E.APP_VERSION, bg='#111827', fg='#9ca3af', font=FONT_SMALL).pack(
            side='right', padx=14)
        ttk.Button(top, text='README', command=self.open_readme, style='Small.TButton').pack(
            side='right', pady=8)

        self.status = tk.StringVar(value='')
        tk.Label(self.root, textvariable=self.status, bg=BG, fg=MUTED, anchor='w', font=FONT_SMALL).pack(
            side='bottom', fill='x', padx=12, pady=3)

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill='both', expand=True, padx=10, pady=(8, 0))
        self.packs_tab = ttk.Frame(self.tabs)
        self.stock_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.packs_tab, text='Voice packs')
        self.tabs.add(self.stock_tab, text='Stock sounds')
        self.console_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.console_tab, text='Console')
        self.guide_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.guide_tab, text='How to')
        self.build_packs_tab()
        self.build_stock_tab()
        self.build_console_tab()
        self.build_guide_tab()
        self.tabs.bind('<<NotebookTabChanged>>', lambda _e: self.refresh_stock_tab())

    def build_packs_tab(self):
        tab = self.packs_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        left = tk.Frame(tab, bg=PANEL, width=250)
        left.grid(row=0, column=0, sticky='ns', padx=(0, 8), pady=8)
        left.grid_propagate(False)
        left.pack_propagate(False)
        head = tk.Frame(left, bg=PANEL)
        head.pack(fill='x', padx=10, pady=10)
        tk.Label(head, text='VOICE PACKS', bg=PANEL, fg=MUTED, font=FONT_BOLD).pack(anchor='w')
        ttk.Button(head, text='+  New voice pack', style='Accent.TButton',
                   command=self.on_new).pack(fill='x', pady=(8, 0))
        self.tree = ttk.Treeview(left, columns=('lang',), show='tree', selectmode='browse')
        self.tree.column('#0', width=170)
        self.tree.column('lang', width=50, anchor='center')
        self.tree.pack(fill='both', expand=True, padx=4, pady=(0, 6))
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)

        self.center = tk.Frame(tab, bg=PANEL)
        self.center.grid(row=0, column=1, sticky='nsew', pady=8)
        self.center.rowconfigure(0, weight=1)
        self.center.columnconfigure(0, weight=1)

        self.empty = tk.Frame(self.center, bg=PANEL)
        self.empty.grid(row=0, column=0, sticky='nsew')
        mid = tk.Frame(self.empty, bg=PANEL)
        mid.place(relx=0.5, rely=0.5, anchor='center')
        tk.Label(mid, text='No voice pack yet', bg=PANEL, fg=TEXT, font=('Segoe UI', 16, 'bold')).pack()
        tk.Label(mid, text='Create one to start replacing the SatNav voice lines.', bg=PANEL, fg=MUTED,
                 font=FONT).pack(pady=(4, 18))
        ttk.Button(mid, text='Create voice pack', style='Big.TButton', command=self.on_new).pack()

        self.listf = tk.Frame(self.center, bg=PANEL)
        self.listf.grid(row=0, column=0, sticky='nsew')
        self.listf.rowconfigure(1, weight=1)
        self.listf.columnconfigure(0, weight=1)
        lh = tk.Frame(self.listf, bg=PANEL)
        lh.grid(row=0, column=0, columnspan=2, sticky='we', padx=12, pady=(10, 6))
        self.list_title = tk.Label(lh, text='', bg=PANEL, fg=TEXT, font=('Segoe UI', 13, 'bold'))
        self.list_title.pack(side='left')
        self.list_count = tk.Label(lh, text='', bg=PANEL, fg=MUTED, font=FONT)
        self.list_count.pack(side='left', padx=12)
        for cat in ('various', 'metric', 'imperial'):
            tk.Label(lh, text=CAT_NAMES[cat].title(), bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(
                side='right', padx=(4, 10))
            tk.Frame(lh, bg=CAT_COLORS[cat], width=12, height=12).pack(side='right')
        self.canvas = tk.Canvas(self.listf, bg=PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(self.listf, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.grid(row=1, column=0, sticky='nsew', padx=(12, 0), pady=(0, 8))
        sb.grid(row=1, column=1, sticky='ns', pady=(0, 8))
        self.inner = tk.Frame(self.canvas, bg=PANEL)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))

        right = tk.Frame(tab, bg=PANEL, width=290)
        right.grid(row=0, column=2, sticky='ns', padx=(8, 0), pady=8)
        right.grid_propagate(False)
        right.pack_propagate(False)
        self.build_right(right)

    def build_right(self, right):
        pad = {'padx': 16}
        tk.Label(right, text='PACK', bg=PANEL, fg=MUTED, font=FONT_BOLD).pack(anchor='w', pady=(12, 4), **pad)
        tk.Label(right, text='Name', bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(anchor='w', **pad)
        self.name_var = tk.StringVar()
        self.name_var.trace_add('write', self.on_name_edit)
        self.name_entry = ttk.Entry(right, textvariable=self.name_var)
        self.name_entry.pack(fill='x', pady=(0, 8), **pad)
        tk.Label(right, text='Language', bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(anchor='w', **pad)
        self.lang_label = tk.Label(right, text='-', bg=PANEL, fg=TEXT, font=FONT_BOLD)
        self.lang_label.pack(anchor='w', pady=(0, 8), **pad)
        tk.Label(right, text='Loader (included)', bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(anchor='w', **pad)
        name, version = E.loader_info()
        tk.Label(right, text='%s  v%s' % (name, version), bg=PANEL, fg=TEXT, font=FONT_BOLD).pack(
            anchor='w', pady=(0, 8), **pad)
        tk.Label(right, text='Replaced lines', bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(anchor='w', **pad)
        self.replaced_label = tk.Label(right, text='-', bg=PANEL, fg=TEXT, font=FONT_BOLD)
        self.replaced_label.pack(anchor='w', pady=(0, 8), **pad)
        tk.Label(right, text='Status', bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(anchor='w', **pad)
        self.build_label = tk.Label(right, text='', bg=PANEL, font=FONT, anchor='w', justify='left',
                                    wraplength=250)
        self.build_label.pack(anchor='w', **pad)
        self.install_label = tk.Label(right, text='', bg=PANEL, font=FONT, anchor='w', justify='left',
                                      wraplength=250)
        self.install_label.pack(anchor='w', pady=(0, 14), **pad)

        self.btn_build = ttk.Button(right, text='BUILD', style='Accent.TButton', command=self.on_build)
        self.btn_build.pack(fill='x', pady=3, **pad)
        self.btn_install = ttk.Button(right, text='INSTALL', style='Accent.TButton', command=self.on_install)
        self.btn_install.pack(fill='x', pady=3, **pad)
        self.btn_export = ttk.Button(right, text='Export pack (.zip)', command=self.on_export)
        self.btn_export.pack(fill='x', pady=3, **pad)
        self.btn_save = ttk.Button(right, text='Save  (Ctrl+S)', command=self.on_save)
        self.btn_save.pack(fill='x', pady=3, **pad)
        self.btn_remove = ttk.Button(right, text='REMOVE', style='Danger.TButton', command=self.on_remove)
        self.btn_remove.pack(fill='x', pady=(14, 3), **pad)
        self.right_buttons = (self.btn_build, self.btn_install, self.btn_export, self.btn_save,
                              self.btn_remove, self.name_entry)

    def build_stock_tab(self):
        tab = self.stock_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        bar = tk.Frame(tab, bg=PANEL)
        bar.grid(row=0, column=0, sticky='we', pady=(8, 8))
        tk.Label(bar, text='Stock bank', bg=PANEL, fg=MUTED, font=FONT_BOLD).pack(side='left', padx=12, pady=10)
        self.stock_combo = ttk.Combobox(bar, state='readonly', width=26)
        self.stock_combo.pack(side='left')
        self.stock_combo.bind('<<ComboboxSelected>>', lambda _e: self.fill_stock_list())
        ttk.Button(bar, text='Load stock .bank', command=self.on_load_stock).pack(side='left', padx=(12, 6))
        ttk.Button(bar, text='Open folder', command=self.on_open_stock).pack(side='left', padx=6)
        ttk.Button(bar, text='Delete', style='Danger.TButton', command=self.on_delete_stock).pack(side='left', padx=6)
        self.stock_info = tk.Label(bar, text='', bg=PANEL, fg=MUTED, font=FONT)
        self.stock_info.pack(side='left', padx=12)

        body = tk.Frame(tab, bg=PANEL)
        body.grid(row=1, column=0, sticky='nsew', pady=(0, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.stock_tree = ttk.Treeview(body, columns=('idx', 'name', 'group', 'sec'), show='headings',
                                       selectmode='browse')
        for col, text, width, anchor in (('idx', '#', 60, 'center'), ('name', 'Bank name', 620, 'w'),
                                         ('group', 'Group', 110, 'center'), ('sec', 'Seconds', 90, 'e')):
            self.stock_tree.heading(col, text=text)
            self.stock_tree.column(col, width=width, anchor=anchor, stretch=(col == 'name'))
        for cat, color in CAT_COLORS.items():
            self.stock_tree.tag_configure(cat, foreground=color if cat != 'various' else '#a16207')
        sb = ttk.Scrollbar(body, orient='vertical', command=self.stock_tree.yview)
        self.stock_tree.configure(yscrollcommand=sb.set)
        self.stock_tree.grid(row=0, column=0, sticky='nsew')
        sb.grid(row=0, column=1, sticky='ns')
        self.stock_tree.bind('<Double-1>', lambda _e: self.play_stock_selected())
        self.stock_tree.bind('<Return>', lambda _e: self.play_stock_selected())
        foot = tk.Frame(body, bg=PANEL)
        foot.grid(row=1, column=0, columnspan=2, sticky='we', padx=8, pady=8)
        ttk.Button(foot, text='Play selected', style='Accent.TButton',
                   command=self.play_stock_selected).pack(side='left')
        ttk.Button(foot, text='Stop', command=stop_sound).pack(side='left', padx=8)
        tk.Label(foot, text='Double-click a line to play it.', bg=PANEL, fg=MUTED, font=FONT_SMALL).pack(
            side='left', padx=8)

    def build_console_tab(self):
        tab = self.console_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        bar = tk.Frame(tab, bg=PANEL)
        bar.grid(row=0, column=0, sticky='we', pady=(8, 8))
        tk.Label(bar, text='Console (read only)', bg=PANEL, fg=MUTED, font=FONT_BOLD).pack(
            side='left', padx=12, pady=10)
        ttk.Button(bar, text='Copy all', command=self.copy_console).pack(side='right', padx=(6, 12))
        ttk.Button(bar, text='Clear', command=self.clear_console).pack(side='right')
        body = tk.Frame(tab, bg='#0b1020')
        body.grid(row=1, column=0, sticky='nsew', pady=(0, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.console = tk.Text(body, bg='#0b1020', fg='#d1d5db', insertbackground='#d1d5db',
                               font=('Consolas', 10), wrap='none', borderwidth=0, padx=10, pady=8,
                               state='disabled')
        sb = ttk.Scrollbar(body, orient='vertical', command=self.console.yview)
        self.console.configure(yscrollcommand=sb.set)
        self.console.grid(row=0, column=0, sticky='nsew')
        sb.grid(row=0, column=1, sticky='ns')
        self.console.tag_configure('time', foreground='#6b7280')
        self.console.tag_configure('error', foreground='#f87171')
        self.console.tag_configure('ok', foreground='#4ade80')
        self.console.tag_configure('step', foreground='#93c5fd')
        self.log('%s %s started' % (E.APP_NAME, E.APP_VERSION), 'ok')
        self.root.after(100, self.drain_log)

    def log(self, text, tag=None):
        # thread-safe: may be called from worker threads
        self.log_q.put((time.strftime('%H:%M:%S'), text, tag))

    def drain_log(self):
        items = []
        try:
            while True:
                items.append(self.log_q.get_nowait())
        except queue.Empty:
            pass
        if items:
            at_end = self.console.yview()[1] >= 0.999
            self.console.configure(state='normal')
            for stamp, text, tag in items:
                self.console.insert('end', stamp + '  ', 'time')
                self.console.insert('end', text + '\n', tag or ())
            self.console.configure(state='disabled')
            if at_end:
                self.console.see('end')
        self.root.after(100, self.drain_log)

    def clear_console(self):
        self.console.configure(state='normal')
        self.console.delete('1.0', 'end')
        self.console.configure(state='disabled')

    def copy_console(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.console.get('1.0', 'end'))

    def open_readme(self):
        for p in (E.app_dir() / 'README.md', E.resource_dir() / 'README.md'):
            if p.exists():
                os.startfile(str(p))
                return
        self.error('README.md was not found next to the program.')

    GUIDE = [
        ('h1', 'How to make your own SatNav voice pack'),
        ('p', 'Follow these steps in order. It takes a few minutes plus the time to prepare your sounds.'),
        ('h2', 'Before you start'),
        ('li', 'Close Forza Horizon 2 while you build and install.'),
        ('li', 'Prepare your voice clips as .mp3, .wav or .ogg files. One short clip per line, for example "Turn left".'),
        ('h2', 'Step 1 - Create the pack'),
        ('li', 'Click "New voice pack" (top left) or the big "Create voice pack" button.'),
        ('li', 'Type a name and pick the language of the game SatNav you want to replace.'),
        ('li', 'Press Create. The first time, the tool reads the game sounds for that language (a few seconds).'),
        ('h2', 'Step 2 - Add your sounds'),
        ('li', 'In the middle list every line the SatNav can say is shown. Press the "Stock" play button to hear the original.'),
        ('li', 'Press "Attach file..." under a line and choose your own sound. Press the small play button to listen.'),
        ('li', 'Colour stripe: blue = Imperial (miles), red = Metric (km), yellow = Various (both).'),
        ('li', 'The line with the (i) mark is used for both Imperial and Metric - one sound covers both.'),
        ('li', 'Lines you leave empty keep the original game voice. You do not have to fill everything.'),
        ('li', 'Wrong file? Press "Change..." to swap it or the X button to remove it.'),
        ('h2', 'Step 3 - Build'),
        ('li', 'Press BUILD. The tool trims silence, matches the volume and converts everything to the game format.'),
        ('li', 'If it warns that some lines are longer than the original, they may be cut off in the game - test them.'),
        ('li', 'Open the Console tab any time to see exactly what the tool is doing.'),
        ('h2', 'Step 4 - Install and play'),
        ('li', 'Press INSTALL. The tool copies the mod files into your fh2-mods folder.'),
        ('li', 'Start the game and set the speech language to the same language as your pack.'),
        ('li', 'In the mod menu, make sure "SatNavVoice" is switched on.'),
        ('h2', 'Other things you can do'),
        ('li', 'Save (Ctrl+S) keeps your work so you can continue later. The tool asks when you close it.'),
        ('li', 'Export pack (.zip) makes a file you can share. Import pack (.zip) in the top bar opens one.'),
        ('li', 'REMOVE deletes the pack from this tool only. It asks first and does not touch the game.'),
        ('li', 'Stock sounds tab lets you listen to all original game sounds and open their folder.'),
        ('note', 'Tip: if you edit a pack after building, press BUILD again - the status on the right shows when it is out of date.'),
    ]

    def build_guide_tab(self):
        tab = self.guide_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        body = tk.Frame(tab, bg=PANEL)
        body.grid(row=0, column=0, sticky='nsew', pady=8)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        t = tk.Text(body, bg=PANEL, fg=TEXT, font=('Segoe UI', 11), wrap='word', borderwidth=0,
                    padx=40, pady=24, spacing1=2, spacing3=4, cursor='arrow')
        sb = ttk.Scrollbar(body, orient='vertical', command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.grid(row=0, column=0, sticky='nsew')
        sb.grid(row=0, column=1, sticky='ns')
        t.tag_configure('h1', font=('Segoe UI', 18, 'bold'), spacing3=8)
        t.tag_configure('h2', font=('Segoe UI', 13, 'bold'), foreground=ACCENT, spacing1=16, spacing3=6)
        t.tag_configure('p', foreground=MUTED, spacing3=6)
        t.tag_configure('li', lmargin1=24, lmargin2=44)
        t.tag_configure('note', background='#eff6ff', foreground='#1e3a8a', lmargin1=12, lmargin2=12,
                        spacing1=14, spacing3=10)
        for kind, text in self.GUIDE:
            if kind == 'li':
                t.insert('end', '\u2022  ' + text + '\n', 'li')
            else:
                t.insert('end', text + '\n', kind)
        t.configure(state='disabled')

    # ------------------------------------------------------------ helpers    def set_status(self, text):
        self.status.set(text)
        self.log(text)

    def log_error(self, text):
        try:
            with open(self.engine.paths.data / 'error.log', 'a', encoding='utf-8') as f:
                f.write('[%s]\n%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), text))
        except OSError:
            pass

    def on_exception(self, exc, val, tb):
        trace = ''.join(traceback.format_exception(exc, val, tb))
        self.log_error(trace)
        self.log('UNEXPECTED ERROR:\n' + trace, 'error')
        messagebox.showerror(E.APP_NAME, 'Unexpected error:\n\n%s' % val, parent=self.root)

    def error(self, message):
        self.log('ERROR: ' + message, 'error')
        messagebox.showerror(E.APP_NAME, message, parent=self.root)

    def run_task(self, title, fn):
        dlg = ProgressDialog(self.root, title)
        box = {}
        self.log('--- %s ---' % title, 'step')
        started = time.time()

        def report(fraction, text):
            self.log('[%3d%%] %s' % (round(fraction * 100), text))
            dlg.report(fraction, text)

        def work():
            try:
                box['v'] = fn(report)
            except BaseException as ex:  # reported on the UI thread
                box['e'] = ex
                box['tb'] = traceback.format_exc()
            finally:
                dlg.finish()

        threading.Thread(target=work, daemon=True).start()
        dlg.poll()
        self.root.wait_window(dlg)
        if 'e' in box:
            self.log('FAILED: %s' % box['e'], 'error')
            self.log(box['tb'], 'error')
            if not isinstance(box['e'], (E.NeedStock, ValueError)):
                self.log_error(box['tb'])
            raise box['e']
        self.log('--- done in %.1f s ---' % (time.time() - started), 'ok')
        return box.get('v')

    def settings_ok(self):
        if self.engine.settings_valid():
            return True
        return self.on_settings()

    def on_wheel(self, event):
        w = self.root.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w is self.canvas:
                self.canvas.yview_scroll(int(-event.delta / 120) * 3, 'units')
                return
            w = w.master

    # ------------------------------------------------------------ startup / settings
    def startup(self):
        if not self.engine.settings_valid():
            dlg = SettingsDialog(self.root, self.engine.game_dir, self.engine.mods_dir, required=True)
            result = dlg.show()
            if not result:
                self.root.destroy()
                return
            self.engine.set_dirs(*result)
        self.refresh_stock_tab()

    def on_settings(self):
        dlg = SettingsDialog(self.root, self.engine.game_dir, self.engine.mods_dir, required=False)
        result = dlg.show()
        if result:
            self.engine.set_dirs(*result)
            self.refresh_right()
            return True
        return self.engine.settings_valid()

    # ------------------------------------------------------------ pack list
    def refresh_tree(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for p in self.engine.packs:
            self.tree.insert('', 'end', iid=p.id, text=self.tree_text(p), values=(p.language,))
        target = select or (self.current.id if self.current else None)
        if target is None and self.engine.packs:
            target = self.engine.packs[0].id
        if target and self.tree.exists(target):
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.select_pack(self.pack_by_id(target))
        else:
            self.select_pack(None)

    def tree_text(self, pack):
        return pack.name + ('  *' if pack.dirty else '')

    def pack_by_id(self, pack_id):
        return next((p for p in self.engine.packs if p.id == pack_id), None)

    def on_tree_select(self, _event=None):
        sel = self.tree.selection()
        pack = self.pack_by_id(sel[0]) if sel else None
        if pack is not self.current:
            self.select_pack(pack)

    def select_pack(self, pack):
        self.current = pack
        stop_sound()
        if pack is None:
            self.empty.tkraise()
            for w in self.right_buttons:
                w.state(['disabled'])
            self.name_guard = True
            self.name_var.set('')
            self.name_guard = False
            self.lang_label.configure(text='-')
            self.replaced_label.configure(text='-')
            self.build_label.configure(text='')
            self.install_label.configure(text='')
            return
        self.listf.tkraise()
        self.populate(pack)
        self.refresh_right()

    def update_tree_item(self):
        if self.current and self.tree.exists(self.current.id):
            self.tree.item(self.current.id, text=self.tree_text(self.current))

    # ------------------------------------------------------------ sound rows
    def populate(self, pack):
        for child in self.inner.winfo_children():
            child.destroy()
        self.rows = {}
        if not self.engine.stock_loaded(pack.language):
            self.lines = []
            self.error('The stock %s bank is not loaded. Use "Load stock .bank".' % pack.language)
            return
        self.lines = self.engine.stock_lines(pack.language)
        self.list_title.configure(text=pack.name)
        for line in self.lines:
            self.make_row(pack, line)
        self.canvas.yview_moveto(0)
        self.refresh_list_header()

    def make_row(self, pack, line):
        name = line['name']
        cat = E.line_category(name)
        total = len(self.lines)
        r = RowWidgets()
        row = tk.Frame(self.inner, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        row.pack(fill='x', pady=2, padx=(0, 6))
        row.columnconfigure(2, weight=1)
        tk.Frame(row, bg=CAT_COLORS[cat], width=8).grid(row=0, column=0, rowspan=2, sticky='ns')
        tk.Label(row, text='%d / %d' % (line['index'], total), bg=PANEL, fg=MUTED, font=FONT_SMALL,
                 width=8).grid(row=0, column=1, padx=(8, 0), pady=(6, 0), sticky='w')
        title = tk.Frame(row, bg=PANEL)
        title.grid(row=0, column=2, sticky='we', pady=(6, 0))
        tk.Label(title, text=name, bg=PANEL, fg=TEXT, font=('Segoe UI', 9, 'bold')).pack(side='left')
        if name == E.SHARED_LINE:
            info = tk.Label(title, text=' \u24d8', bg=PANEL, fg=ACCENT, font=('Segoe UI', 12, 'bold'),
                            cursor='question_arrow')
            info.pack(side='left')
            Tooltip(info, 'This line is used for both Imperial and Metric units.')
        tag_color = CAT_COLORS[cat] if cat != 'various' else '#a16207'
        tk.Label(row, text='%s  \u2022  %.1f s' % (CAT_NAMES[cat], line['seconds']), bg=PANEL, fg=tag_color,
                 font=FONT_SMALL, width=15, anchor='e').grid(row=0, column=3, padx=8, pady=(6, 0))
        stock_btn = ttk.Button(row, text='\u25b6  Stock', style='Small.TButton',
                               command=lambda l=line: self.play_stock(pack.language, l))
        stock_btn.grid(row=0, column=4, padx=(0, 10), pady=(6, 0), sticky='e')

        r.file = tk.Label(row, text='', bg=PANEL, font=FONT, anchor='w')
        r.file.grid(row=1, column=2, sticky='we', pady=(0, 6))
        r.dur = tk.Label(row, text='', bg=PANEL, font=FONT_SMALL, width=15, anchor='e')
        r.dur.grid(row=1, column=3, padx=8, pady=(0, 6))
        ctl = tk.Frame(row, bg=PANEL)
        ctl.grid(row=1, column=4, padx=(0, 10), pady=(0, 6), sticky='e')
        r.attach = ttk.Button(ctl, text='Attach file...', style='Small.TButton',
                              command=lambda n=name: self.attach_row(n))
        r.attach.pack(side='left')
        r.play = ttk.Button(ctl, text='\u25b6', style='Small.TButton', width=3,
                            command=lambda n=name: self.play_user(n))
        r.play.pack(side='left', padx=(4, 0))
        r.clear = ttk.Button(ctl, text='\u2715', style='Small.TButton', width=3,
                             command=lambda n=name: self.clear_row(n))
        r.clear.pack(side='left', padx=(4, 0))
        r.stock_seconds = line['seconds']
        self.rows[name] = r
        self.refresh_row(pack, name)

    def refresh_row(self, pack, name):
        r = self.rows[name]
        entry = pack.lines.get(name)
        if entry:
            r.file.configure(text=entry['orig'], fg=TEXT, font=FONT)
            longer = entry.get('dur', 0) > r.stock_seconds + 0.05
            r.dur.configure(text='%.1f s%s' % (entry.get('dur', 0), ' (longer)' if longer else ''),
                            fg=WARN if longer else MUTED)
            r.attach.configure(text='Change...')
            r.play.state(['!disabled'])
            r.clear.state(['!disabled'])
        else:
            r.file.configure(text='Original game sound will be used', fg=MUTED,
                             font=('Segoe UI', 10, 'italic'))
            r.dur.configure(text='')
            r.attach.configure(text='Attach file...')
            r.play.state(['disabled'])
            r.clear.state(['disabled'])

    def refresh_list_header(self):
        if self.current:
            self.list_count.configure(text='%d of %d lines replaced' % (len(self.current.lines),
                                                                       len(self.lines)))

    def play_stock(self, lang, line):
        try:
            play_file(self.engine.stock_wav(lang, line))
        except RuntimeError as ex:
            self.error(str(ex))

    def play_user(self, name):
        entry = self.current.lines.get(name)
        if not entry:
            return
        try:
            play_file(self.engine.preview_wav(entry))
        except Exception as ex:
            self.error('Could not play the file: %s' % ex)

    def attach_row(self, name):
        pack = self.current
        last = self.engine.settings.get('last_audio_dir', '')
        path = filedialog.askopenfilename(
            parent=self.root, title='Choose a sound for ' + name, initialdir=last or None,
            filetypes=[('Audio files (.mp3 .wav .ogg)', '*.mp3 *.wav *.ogg')])
        if not path:
            return
        if Path(path).suffix.lower() not in E.ALLOWED_EXT:
            self.error('Only .mp3, .wav and .ogg files are accepted.')
            return
        try:
            self.engine.attach(pack, name, path)
        except (ValueError, RuntimeError) as ex:
            self.error(str(ex))
            return
        self.log('Attached %s -> %s' % (Path(path).name, name))
        self.engine.settings['last_audio_dir'] = str(Path(path).parent)
        E.save_settings(self.engine.paths, self.engine.settings)
        self.after_edit(pack, name)

    def clear_row(self, name):
        self.log('Cleared custom sound for %s' % name)
        self.engine.detach(self.current, name)
        self.after_edit(self.current, name)

    def after_edit(self, pack, name):
        self.refresh_row(pack, name)
        self.refresh_list_header()
        self.update_tree_item()
        self.refresh_right()

    # ------------------------------------------------------------ right panel
    def on_name_edit(self, *_args):
        if self.name_guard or not self.current:
            return
        text = self.name_var.get()
        if text != self.current.name:
            self.current.name = text
            self.current.dirty = True
            self.update_tree_item()
            self.list_title.configure(text=text)

    def refresh_right(self):
        pack = self.current
        if not pack:
            return
        for w in self.right_buttons:
            w.state(['!disabled'])
        self.name_guard = True
        self.name_var.set(pack.name)
        self.name_guard = False
        self.lang_label.configure(text=E.lang_label(pack.language))
        self.replaced_label.configure(text='%d / %d' % (len(pack.lines), len(self.lines)))
        state = self.engine.build_state(pack)
        text, color = {'none': ('Not built', MUTED),
                       'outdated': ('Built - outdated (changed since the build)', WARN),
                       'current': ('Built - up to date', GOOD)}[state]
        self.build_label.configure(text=text, fg=color)
        if self.engine.settings_valid():
            inst = self.engine.install_state(pack)
            text, color = {'none': ('Not installed', MUTED),
                           'different': ('A different %s bank is installed' % pack.language, WARN),
                           'installed': ('Installed - up to date', GOOD)}[inst]
        else:
            text, color = 'fh2-mods folder not set', MUTED
        self.install_label.configure(text=text, fg=color)

    # ------------------------------------------------------------ actions
    def ensure_stock(self, lang):
        if self.engine.stock_loaded(lang):
            return True
        if not self.settings_ok():
            return False
        try:
            self.run_task('Loading the stock %s bank' % lang, lambda cb: self.engine.export_stock(lang, cb))
        except Exception as ex:
            self.error('Could not load the stock bank: %s' % ex)
            return False
        return True

    def on_new(self):
        if not self.settings_ok():
            return
        langs = sorted(set(E.game_languages(self.engine.game_dir)) | set(self.engine.loaded_languages()))
        if not langs:
            self.error('No SatNav banks were found in the game folder.')
            return
        result = NewPackDialog(self.root, langs, self.engine.loaded_languages()).show()
        if not result:
            return
        name, lang = result
        if not self.ensure_stock(lang):
            return
        pack = self.engine.new_pack(name, lang)
        self.refresh_tree(select=pack.id)
        self.tabs.select(self.packs_tab)
        self.set_status('Created "%s".' % name)

    def build_current(self):
        pack = self.current
        try:
            res = self.run_task('Building "%s"' % pack.name, lambda cb: self.engine.build_pack(pack, cb))
        except Exception as ex:
            self.error('Build failed: %s' % ex)
            return None
        self.refresh_right()
        return res

    def on_build(self):
        res = self.build_current()
        if not res:
            return
        msg = 'Built %d of %d lines.' % (res['replaced'], res['total'])
        if res['longer']:
            msg += ('\n\n%d replaced lines are longer than the stock ones (marked in the list). '
                    'Test them in the game.' % len(res['longer']))
        messagebox.showinfo(E.APP_NAME, msg, parent=self.root)
        self.set_status('Built "%s".' % self.current.name)

    def on_install(self):
        pack = self.current
        if not self.settings_ok():
            return
        if E.game_running():
            self.error('The game is running. Close Forza Horizon 2 before installing.')
            return
        if self.engine.build_state(pack) != 'current':
            if not messagebox.askyesno(E.APP_NAME, 'The pack has to be built first. Build it now?',
                                       parent=self.root):
                return
            if not self.build_current():
                return
        if self.engine.install_state(pack) == 'different':
            if not messagebox.askyesno(
                    E.APP_NAME, 'A SatNav %s bank is already installed in fh2-mods (from another pack '
                                'or an older build). Replace it?' % pack.language, parent=self.root):
                return
        try:
            self.engine.install_pack(pack)
        except Exception as ex:
            self.error(str(ex))
            return
        self.refresh_right()
        messagebox.showinfo(E.APP_NAME, 'Installed in fh2-mods.\n\nSet the game speech language to %s '
                            'and restart the game.' % E.LANG_NAMES.get(pack.language, pack.language),
                            parent=self.root)
        self.set_status('Installed "%s".' % pack.name)

    def on_export(self):
        pack = self.current
        if self.engine.build_state(pack) != 'current':
            if not messagebox.askyesno(E.APP_NAME, 'The pack has to be built first. Build it now?',
                                       parent=self.root):
                return
            if not self.build_current():
                return
        safe = ''.join(c if c.isalnum() or c in ' -_' else '_' for c in pack.name).strip() or 'pack'
        path = filedialog.asksaveasfilename(
            parent=self.root, title='Export pack', defaultextension='.zip',
            initialfile='%s_%s.zip' % (safe, pack.language), filetypes=[('Zip archive', '*.zip')])
        if not path:
            return
        try:
            self.engine.export_pack(pack, path)
        except Exception as ex:
            self.error('Export failed: %s' % ex)
            return
        self.set_status('Exported to %s' % path)

    def on_save(self):
        pack = self.current
        if not pack:
            return
        try:
            self.engine.save_pack(pack)
        except Exception as ex:
            self.error('Save failed: %s' % ex)
            return
        self.update_tree_item()
        self.set_status('Saved "%s".' % pack.name)

    def on_remove(self):
        pack = self.current
        if not messagebox.askyesno(
                E.APP_NAME,
                'Remove the voice pack "%s"?\n\nThis deletes the pack and its sound files from the tool. '
                'Files already installed in fh2-mods are not touched.' % pack.name,
                icon='warning', default='no', parent=self.root):
            return
        self.engine.delete_pack(pack)
        self.current = None
        self.refresh_tree()
        self.set_status('Removed "%s".' % pack.name)

    def on_import(self):
        path = filedialog.askopenfilename(parent=self.root, title='Import a voice pack',
                                          filetypes=[('Zip archive', '*.zip')])
        if not path:
            return
        pack = None
        for _ in range(2):
            try:
                pack = self.run_task('Importing', lambda cb: self.engine.import_zip(path, cb))
                break
            except E.NeedStock as need:
                if not messagebox.askyesno(
                        E.APP_NAME, 'This pack is for the %s bank, whose stock sounds are not loaded '
                                    'yet. Load them now?' % need.args[0], parent=self.root):
                    return
                if not self.ensure_stock(need.args[0]):
                    return
            except Exception as ex:
                self.error('Import failed: %s' % ex)
                return
        if pack:
            self.refresh_tree(select=pack.id)
            self.tabs.select(self.packs_tab)
            self.set_status('Imported "%s".' % pack.name)

    # ------------------------------------------------------------ stock tab
    def on_load_stock(self):
        if not self.settings_ok():
            return
        langs = E.game_languages(self.engine.game_dir)
        if not langs:
            self.error('No SatNav banks were found in the game folder.')
            return
        lang = LoadStockDialog(self.root, langs, self.engine.loaded_languages()).show()
        if not lang:
            return
        try:
            n = self.run_task('Loading the stock %s bank' % lang, lambda cb: self.engine.export_stock(lang, cb))
        except Exception as ex:
            self.error('Could not load the stock bank: %s' % ex)
            return
        self.tabs.select(self.stock_tab)
        self.refresh_stock_tab(select=lang)
        self.set_status('Stock %s bank loaded (%s sounds).' % (lang, n))

    def current_stock_lang(self):
        label = self.stock_combo.get()
        for lang in self.engine.loaded_languages():
            if E.lang_label(lang) == label:
                return lang
        return None

    def refresh_stock_tab(self, select=None):
        langs = self.engine.loaded_languages()
        self.stock_combo['values'] = [E.lang_label(l) for l in langs]
        keep = select or self.current_stock_lang()
        if keep not in langs:
            keep = langs[0] if langs else None
        self.stock_combo.set(E.lang_label(keep) if keep else '')
        self.fill_stock_list()

    def fill_stock_list(self):
        self.stock_tree.delete(*self.stock_tree.get_children())
        lang = self.current_stock_lang()
        if not lang:
            self.stock_info.configure(text='No stock bank loaded yet. Use "Load stock .bank".')
            return
        lines = self.engine.stock_lines(lang)
        for l in lines:
            cat = E.line_category(l['name'])
            self.stock_tree.insert('', 'end', iid=str(l['index']), tags=(cat,),
                                   values=(l['index'], l['name'], CAT_NAMES[cat].title(),
                                           '%.2f' % l['seconds']))
        self.stock_info.configure(text='%d sounds - %s' % (len(lines), self.engine.stock_dir(lang)))

    def play_stock_selected(self):
        lang = self.current_stock_lang()
        sel = self.stock_tree.selection()
        if not lang or not sel:
            return
        line = next(l for l in self.engine.stock_lines(lang) if str(l['index']) == sel[0])
        self.play_stock(lang, line)

    def on_open_stock(self):
        lang = self.current_stock_lang()
        os.startfile(self.engine.stock_dir(lang) if lang else self.engine.paths.stock)

    def on_delete_stock(self):
        lang = self.current_stock_lang()
        if not lang:
            return
        users = [p.name for p in self.engine.packs if p.language == lang]
        if users:
            self.error('The stock %s sounds are used by: %s.\nRemove those packs first.'
                       % (lang, ', '.join(users)))
            return
        if messagebox.askyesno(E.APP_NAME, 'Delete the exported stock %s sounds from the tool folder? '
                               'You can load them again later.' % lang, default='no', parent=self.root):
            self.engine.delete_stock(lang)
            self.refresh_stock_tab()

    # ------------------------------------------------------------ closing
    def on_close(self):
        stop_sound()
        dirty = [p for p in self.engine.packs if p.dirty]
        if dirty:
            answer = messagebox.askyesnocancel(
                E.APP_NAME, 'Save changes to %d voice pack(s) before closing?' % len(dirty),
                parent=self.root)
            if answer is None:
                return
            if answer:
                for p in dirty:
                    self.engine.save_pack(p)
        self.root.destroy()


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SatNavVoice.PackCreator')
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
