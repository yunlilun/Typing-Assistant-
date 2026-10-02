# -*- coding: utf-8 -*-

# ============================================================
# 金山打字通 自动打字助手 (TypeEasy Auto Typer)
# 原创：LUN雲鲤
# 本作品完全开源
# 警告：禁止用于任何商业用途
# GITHUB：https://github.com/yunlilun
# ============================================================

import os
import re
import sys
import time
import ctypes
import threading
import queue
import argparse
from ctypes import wintypes
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# 项目信息
PROJECT_INFO = {
    'author':    'LUN雲鲤',
    'license':   '本作品完全开源',
    'warning':   '禁止用于任何商业用途',
    'github':    'https://github.com/yunlilun',
    'title':     '金山打字通 自动打字助手',
    'version':   'v1.0',
}

# 推荐配置（可被 GUI 修改，点「恢复推荐配置」可重置）
RECOMMENDED_CONFIG = {
    'course_dir':  r"F:\app\Typeeasy\12.3\course",
    'speed':       8.0,
    'delay':       2.5,
    'punct_mode':  'unicode_slow',
    'punct_wait':  0.20,
    'auto_focus':  True,
    'strip_num':   False,
}


# Windows SendInput / IME 检测
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
try:
    imm32 = ctypes.windll.imm32
except OSError:
    imm32 = None

INPUT_KEYBOARD    = 1
KEYEVENTF_KEYUP   = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_SHIFT          = 0x10
VK_RETURN         = 0x0D

IME_CMODE_NATIVE = 0x0001


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype  = wintypes.UINT


def _send(inp):
    n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if n != 1:
        raise OSError(f"SendInput 失败 GetLastError={kernel32.GetLastError()}")
    return n


def _key(vk=0, scan=0, flags=0):
    i = INPUT()
    i.type = INPUT_KEYBOARD
    i.u.ki.wVk = vk
    i.u.ki.wScan = scan
    i.u.ki.dwFlags = flags
    i.u.ki.time = 0
    i.u.ki.dwExtraInfo = None
    return i


# 输入法状态检测
def get_keyboard_layout_langid(hwnd):
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    hkl = user32.GetKeyboardLayout(tid)
    return hkl & 0xFFFF


def get_ime_conversion_mode(hwnd):
    if imm32 is None:
        return None
    himc = imm32.ImmGetContext(hwnd)
    if not himc:
        return None
    conv = wintypes.DWORD()
    sent = wintypes.DWORD()
    ok = imm32.ImmGetConversionStatus(himc, ctypes.byref(conv),
                                      ctypes.byref(sent))
    imm32.ImmReleaseContext(hwnd, himc)
    if not ok:
        return None
    return conv.value


def describe_ime_state(hwnd):
    if not hwnd:
        return 'unknown', "未找到窗口"
    langid = get_keyboard_layout_langid(hwnd)
    lang_map = {
        0x0409: 'English (US)', 0x0804: '简体中文', 0x0404: '繁體中文',
        0x0C04: '繁體中文(香港)', 0x1004: '简体中文(新加坡)',
        0x0407: 'Deutsch', 0x0411: '日本語', 0x0412: '한국어',
    }
    lang_name = lang_map.get(langid, f'0x{langid:04X}')
    if langid == 0x0409:
        return 'en', f"英文（{lang_name}）"
    mode = get_ime_conversion_mode(hwnd)
    if mode is None:
        return 'unknown', f"{lang_name}（无法读取IME模式）"
    if mode & IME_CMODE_NATIVE:
        return 'cn', f"中文输入（{lang_name}）"
    return 'en', f"英文状态（{lang_name}）"


# 字符发送
VK_MAP = {
    'a':0x41,'b':0x42,'c':0x43,'d':0x44,'e':0x45,'f':0x46,'g':0x47,
    'h':0x48,'i':0x49,'j':0x4A,'k':0x4B,'l':0x4C,'m':0x4D,'n':0x4E,
    'o':0x4F,'p':0x50,'q':0x51,'r':0x52,'s':0x53,'t':0x54,'u':0x55,
    'v':0x56,'w':0x57,'x':0x58,'y':0x59,'z':0x5A,
    '0':0x30,'1':0x31,'2':0x32,'3':0x33,'4':0x34,'5':0x35,'6':0x36,
    '7':0x37,'8':0x38,'9':0x39,
    ' ':0x20,'\n':VK_RETURN,'\t':0x09,
    '.':0xBE, ',':0xBC, ';':0xBA, '/':0xBF, '\\':0xDC,
    '[':0xDB, ']':0xDD, "'":0xDE, '`':0xC0, '-':0xBD, '=':0xBB,
}
SHIFT_MAP = {
    '!':'1','@':'2','#':'3','$':'4','%':'5','^':'6','&':'7','*':'8',
    '(':'9',')':'0','_':'-','+':'=','{':'[','}':']','|':'\\',
    ':':';','"':"'",'<':',','>':'.','?':'/','~':'`',
}

CN_PUNCT_SET = set('，。；：！？“”‘’《》【】（）—…、·')

CN_PUNCT_VK = {
    '，': (0xBC, False), '。': (0xBE, False), '；': (0xBA, False),
    '：': (0xBA, True),  '！': (0x31, True),  '？': (0xBF, True),
    '“': (0xDE, True),  '”': (0xDE, True),
    '‘': (0xDE, False), '’': (0xDE, False),
    '（': (0x39, True),  '）': (0x30, True),
    '《': (0xBC, True),  '》': (0xBE, True),
    '、': (0xDC, False), '—': (0xBD, True),  '…': (0xBE, True),
    '·': (0xC0, False),
}

CN_PUNCT_MODE = RECOMMENDED_CONFIG['punct_mode']
CN_PUNCT_WAIT = RECOMMENDED_CONFIG['punct_wait']

_stop_flag  = threading.Event()
_pause_flag = threading.Event()


def send_vk(vk, shift=False):
    if shift:
        _send(_key(vk=VK_SHIFT)); time.sleep(0.006)
    _send(_key(vk=vk));           time.sleep(0.010)
    _send(_key(vk=vk, flags=KEYEVENTF_KEYUP)); time.sleep(0.006)
    if shift:
        _send(_key(vk=VK_SHIFT, flags=KEYEVENTF_KEYUP)); time.sleep(0.006)


def send_unicode(ch):
    code = ord(ch)
    _send(_key(scan=code, flags=KEYEVENTF_UNICODE))
    time.sleep(0.010)
    _send(_key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    time.sleep(0.010)


def type_char(ch):
    if ch in CN_PUNCT_SET:
        if CN_PUNCT_MODE == 'vk' and ch in CN_PUNCT_VK:
            vk, sh = CN_PUNCT_VK[ch]
            send_vk(vk, shift=sh)
        else:
            send_unicode(ch)
            time.sleep(CN_PUNCT_WAIT)
        return
    if ch in VK_MAP:
        send_vk(VK_MAP[ch])
    elif ch in SHIFT_MAP:
        base = SHIFT_MAP[ch]
        if base in VK_MAP:
            send_vk(VK_MAP[base], shift=True)
        else:
            send_unicode(ch)
    elif 'A' <= ch <= 'Z':
        send_vk(VK_MAP[ch.lower()], shift=True)
    else:
        send_unicode(ch)


# 课程解析
def list_courses(course_dir):
    result = []
    if not os.path.isdir(course_dir):
        return result
    skip = {'exam', 'jump', 'bk', '备份'}
    for root, dirs, files in os.walk(course_dir):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        for f in sorted(files):
            if not f.lower().endswith('.xml'):
                continue
            if f.lower().startswith('mission'):
                continue
            full = os.path.join(root, f)
            result.append(os.path.relpath(full, course_dir).replace('\\', '/'))
    return result


def parse_course_xml(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    lines = []
    for m in re.finditer(r'<item\b[^>]*?\bcomparision="([^"]*)"',
                         content, re.IGNORECASE):
        t = m.group(1).strip()
        if t:
            lines.append(t)
    if lines:
        return lines
    for m in re.finditer(r'<item\b[^>]*?\bdisplay="([^"]+)"',
                         content, re.IGNORECASE):
        t = m.group(1).strip()
        if t:
            lines.append(t)
    if lines:
        return lines
    try:
        root = ET.fromstring(content)
        for item in root.iter('item'):
            t = (item.get('comparision') or item.get('display')
                 or item.get('display1') or item.text or '').strip()
            if t:
                lines.append(t)
    except ET.ParseError:
        pass
    return lines


def find_course_file(course_dir, name):
    if not name:
        return None
    if os.path.isfile(name):
        return name
    for suffix in ('', '.xml'):
        p = os.path.join(course_dir, name + suffix)
        if os.path.isfile(p):
            return p
    key = name.replace('\\', '/').lower()
    for root, dirs, files in os.walk(course_dir):
        for f in files:
            if not f.lower().endswith('.xml'):
                continue
            rel = os.path.relpath(os.path.join(root, f),
                                  course_dir).replace('\\', '/')
            if key in rel.lower():
                return os.path.join(root, f)
    return None


# 关于窗口
class AboutWindow:

    def __init__(self, parent):
        self.parent = parent
        self.win = tk.Toplevel(parent)
        self.win.title("关于 TypeEasy Helper")
        self.win.geometry("500x380")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()

        self.win.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - 500) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - 380) // 2
        self.win.geometry(f"+{max(px, 0)}+{max(py, 0)}")

        self._build()

    def _build(self):
        pad = tk.Frame(self.win, bg='#fafafa')
        pad.pack(fill='both', expand=True, padx=28, pady=24)

        tk.Label(pad, text="TypeEasy Helper",
                 font=('Microsoft YaHei', 16, 'bold'),
                 fg='#2a2a55', bg='#fafafa')\
            .pack(anchor='w')
        tk.Label(pad, text=f"{PROJECT_INFO['title']}  {PROJECT_INFO['version']}",
                 font=('Microsoft YaHei', 9),
                 fg='#888', bg='#fafafa')\
            .pack(anchor='w', pady=(2, 18))

        self._line(pad, "原创", PROJECT_INFO['author'],
                   color='#2a2a55', bold=True)
        self._line(pad, "协议", PROJECT_INFO['license'],
                   color='#1a6a3a')
        self._line(pad, "警告", PROJECT_INFO['warning'],
                   color='#b03030', bold=True)

        tk.Label(pad, text="GitHub",
                 font=('Microsoft YaHei', 9),
                 fg='#888', bg='#fafafa')\
            .pack(anchor='w', pady=(16, 0))

        link = tk.Label(pad, text=PROJECT_INFO['github'],
                        font=('Consolas', 10, 'underline'),
                        fg='#3a3aee', bg='#fafafa', cursor='hand2')
        link.pack(anchor='w', pady=(2, 0))
        link.bind('<Button-1>', lambda e: self._open_github())

        btn_row = tk.Frame(pad, bg='#fafafa')
        btn_row.pack(anchor='w', pady=(14, 0))
        ttk.Button(btn_row, text="复制链接",
                   command=self._copy_github).pack(side='left')
        ttk.Button(btn_row, text="打开链接",
                   command=self._open_github).pack(side='left', padx=6)

        foot = tk.Frame(self.win, bg='#eaeaef')
        foot.pack(fill='x', side='bottom')
        ttk.Button(foot, text="关闭", command=self.win.destroy)\
            .pack(side='right', padx=12, pady=10)

    def _line(self, parent, label, value, color='#333', bold=False):
        row = tk.Frame(parent, bg='#fafafa')
        row.pack(fill='x', pady=5)
        tk.Label(row, text=label,
                 font=('Microsoft YaHei', 10),
                 fg='#888', bg='#fafafa', width=5, anchor='w')\
            .pack(side='left')
        tk.Label(row, text=value,
                 font=('Microsoft YaHei', 11, 'bold' if bold else 'normal'),
                 fg=color, bg='#fafafa', anchor='w')\
            .pack(side='left')

    def _copy_github(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(PROJECT_INFO['github'])
        messagebox.showinfo("已复制",
                            f"GitHub 链接已复制到剪贴板:\n\n"
                            f"{PROJECT_INFO['github']}",
                            parent=self.win)

    def _open_github(self):
        import webbrowser
        try:
            webbrowser.open(PROJECT_INFO['github'])
        except Exception as e:
            messagebox.showerror("打开失败",
                                 f"无法打开浏览器: {e}",
                                 parent=self.win)


# GUI
class TypeEasyApp:

    def __init__(self, root):
        self.root = root
        self.root.title("金山打字通 自动打字助手")
        self.root.geometry("1020x840")
        self.root.minsize(880, 720)

        self._load_config(RECOMMENDED_CONFIG)

        self.text_content = ""
        self.worker = None
        self.log_queue = queue.Queue()
        self.typing_hwnd = None

        self._build_ui()
        self._refresh_course_list()
        self._poll_log()
        self._poll_ime_state()

    def _load_config(self, cfg):
        self.course_dir    = tk.StringVar(value=cfg['course_dir'])
        self.speed_var     = tk.DoubleVar(value=cfg['speed'])
        self.delay_var     = tk.DoubleVar(value=cfg['delay'])
        self.punct_mode    = tk.StringVar(value=cfg['punct_mode'])
        self.punct_wait    = tk.DoubleVar(value=cfg['punct_wait'])
        self.focus_var     = tk.BooleanVar(value=cfg['auto_focus'])
        self.strip_num_var = tk.BooleanVar(value=cfg['strip_num'])
        self.current_course = tk.StringVar(value="")

    def _restore_defaults(self):
        cfg = RECOMMENDED_CONFIG
        self.course_dir.set(cfg['course_dir'])
        self.speed_var.set(cfg['speed'])
        self.delay_var.set(cfg['delay'])
        self.punct_mode.set(cfg['punct_mode'])
        self.punct_wait.set(cfg['punct_wait'])
        self.focus_var.set(cfg['auto_focus'])
        self.strip_num_var.set(cfg['strip_num'])
        self._refresh_course_list()
        self.log_msg("已恢复推荐配置:", 'ok')
        self.log_msg(f"  速度={cfg['speed']}  延迟={cfg['delay']}s  "
                     f"标点模式={cfg['punct_mode']}  "
                     f"标点等待={cfg['punct_wait']}s", 'info')
        self.log_msg(f"  自动聚焦={cfg['auto_focus']}  "
                     f"去首序号={cfg['strip_num']}", 'info')

    def _current_config(self):
        return {
            'course_dir':  self.course_dir.get(),
            'speed':       float(self.speed_var.get()),
            'delay':       float(self.delay_var.get()),
            'punct_mode':  self.punct_mode.get(),
            'punct_wait':  float(self.punct_wait.get()),
            'auto_focus':  bool(self.focus_var.get()),
            'strip_num':   bool(self.strip_num_var.get()),
        }

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill='x')
        ttk.Label(top, text="课程目录:").grid(row=0, column=0, sticky='w')
        ttk.Entry(top, textvariable=self.course_dir, width=60)\
            .grid(row=0, column=1, sticky='we', padx=4)
        ttk.Button(top, text="刷新", command=self._refresh_course_list)\
            .grid(row=0, column=2, padx=2)
        top.columnconfigure(1, weight=1)

        mid = ttk.PanedWindow(self.root, orient='horizontal')
        mid.pack(fill='both', expand=True, padx=8, pady=4)

        left = ttk.Frame(mid)
        mid.add(left, weight=1)
        ttk.Label(left, text="课程列表（双击加载）").pack(anchor='w')
        self.course_tree = ttk.Treeview(left, show='tree')
        self.course_tree.pack(fill='both', expand=True, side='left')
        sb = ttk.Scrollbar(left, orient='vertical',
                           command=self.course_tree.yview)
        sb.pack(side='right', fill='y')
        self.course_tree.configure(yscrollcommand=sb.set)
        self.course_tree.bind('<Double-1>', self._on_course_double_click)

        right = ttk.Frame(mid)
        mid.add(right, weight=2)
        ttk.Label(right, text="文本预览").pack(anchor='w')
        self.preview = scrolledtext.ScrolledText(right, wrap='word',
                                                 height=16,
                                                 font=('Consolas', 10))
        self.preview.pack(fill='both', expand=True)

        param = ttk.LabelFrame(self.root,
                               text="参数（推荐配置，可手动修改）",
                               padding=8)
        param.pack(fill='x', padx=8, pady=4)

        ttk.Label(param, text="速度(字符/秒):").grid(row=0, column=0, sticky='w')
        ttk.Spinbox(param, from_=1, to=200, increment=1,
                    textvariable=self.speed_var, width=8)\
            .grid(row=0, column=1, sticky='w', padx=4)

        ttk.Label(param, text="起始延迟(秒):").grid(
            row=0, column=2, sticky='w', padx=(16, 0))
        ttk.Spinbox(param, from_=0, to=60, increment=0.5,
                    textvariable=self.delay_var, width=8)\
            .grid(row=0, column=3, sticky='w', padx=4)

        ttk.Checkbutton(param, text="去掉行首序号",
                        variable=self.strip_num_var)\
            .grid(row=0, column=4, sticky='w', padx=16)

        ttk.Checkbutton(param, text="自动聚焦打字通",
                        variable=self.focus_var)\
            .grid(row=0, column=5, sticky='w', padx=16)

        ttk.Label(param, text="中文标点模式:").grid(
            row=1, column=0, sticky='w', pady=(8, 0))
        ttk.Combobox(param, textvariable=self.punct_mode,
                     values=['unicode_slow', 'vk'], width=16,
                     state='readonly')\
            .grid(row=1, column=1, sticky='w', padx=4, pady=(8, 0))

        ttk.Label(param, text="标点等待(秒):").grid(
            row=1, column=2, sticky='w', pady=(8, 0))
        ttk.Spinbox(param, from_=0.0, to=1.0, increment=0.05,
                    textvariable=self.punct_wait, width=8)\
            .grid(row=1, column=3, sticky='w', padx=4, pady=(8, 0))

        ttk.Label(param,
                  text="(unicode_slow 更稳；vk 更快，靠 IME 转全角)",
                  foreground='#888')\
            .grid(row=1, column=4, columnspan=2, sticky='w',
                  padx=16, pady=(8, 0))

        ttk.Button(param, text="恢复推荐配置",
                   command=self._restore_defaults)\
            .grid(row=1, column=6, sticky='e', padx=8, pady=(8, 0))
        param.columnconfigure(6, weight=1)

        ime_frame = ttk.LabelFrame(self.root,
                                   text="打字通输入法状态（关键！）",
                                   padding=6)
        ime_frame.pack(fill='x', padx=8, pady=4)
        self.lbl_ime = tk.Label(ime_frame, text="● 未知",
                                font=('Microsoft YaHei', 11, 'bold'),
                                fg='#888', bg='#f0f0f0', padx=12, pady=4)
        self.lbl_ime.pack(side='left')
        self.lbl_ime_hint = ttk.Label(
            ime_frame,
            text="英文状态才能零干扰；按一下 Shift 切换",
            foreground='#888')
        self.lbl_ime_hint.pack(side='left', padx=12)
        ttk.Button(ime_frame, text="检测输入法",
                   command=self._check_ime).pack(side='right')
        ttk.Button(ime_frame, text="定位打字通",
                   command=self._locate_typing_window).pack(side='right',
                                                           padx=4)

        btns = ttk.Frame(self.root, padding=(8, 0))
        btns.pack(fill='x')
        self.btn_start = ttk.Button(btns, text="开始输入",
                                    command=self._on_start)
        self.btn_start.pack(side='left', padx=2)
        self.btn_pause = ttk.Button(btns, text="暂停",
                                    command=self._on_pause, state='disabled')
        self.btn_pause.pack(side='left', padx=2)
        self.btn_stop = ttk.Button(btns, text="停止",
                                   command=self._on_stop, state='disabled')
        self.btn_stop.pack(side='left', padx=2)

        ttk.Button(btns, text="关于",
                   command=self._show_about).pack(side='right', padx=2)
        ttk.Button(btns, text="清空日志",
                   command=self._clear_log).pack(side='right', padx=2)
        ttk.Button(btns, text="复制课程名",
                   command=self._copy_course_name).pack(side='right', padx=2)

        prog = ttk.Frame(self.root, padding=(8, 4))
        prog.pack(fill='x')
        self.progress = ttk.Progressbar(prog, mode='determinate',
                                        maximum=100)
        self.progress.pack(fill='x', side='left', expand=True)
        self.lbl_prog = ttk.Label(prog, text="0 / 0", width=14)
        self.lbl_prog.pack(side='left', padx=8)

        logf = ttk.LabelFrame(self.root, text="日志", padding=4)
        logf.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.log = scrolledtext.ScrolledText(logf, wrap='word', height=10,
                                             font=('Consolas', 9),
                                             state='disabled')
        self.log.pack(fill='both', expand=True)
        self.log.tag_config('info', foreground='#a0a0d0')
        self.log.tag_config('ok',   foreground='#3a9a5a')
        self.log.tag_config('warn', foreground='#b58a20')
        self.log.tag_config('err',  foreground='#b03030')
        self.log.tag_config('char', foreground='#4a6aa0')
        self.log.tag_config('hint', foreground='#8a6aaa')

    def _show_about(self):
        AboutWindow(self.root)
        self.log_msg("打开「关于」窗口", 'info')

    def _refresh_course_list(self):
        self.course_tree.delete(*self.course_tree.get_children())
        cdir = self.course_dir.get()
        courses = list_courses(cdir)
        self.log_msg(f"共发现 {len(courses)} 个课程文件", 'info')

        groups = {}
        for c in courses:
            parts = c.split('/')
            g = '/'.join(parts[:-1]) or '.'
            groups.setdefault(g, []).append(c)

        nodes = {'.': ''}
        for g in sorted(groups):
            parent = ''
            parts = g.split('/')
            path = ''
            for p in parts:
                path = path + '/' + p if path else p
                if path not in nodes:
                    nodes[path] = self.course_tree.insert(
                        parent, 'end', text=p, open=False, values=(path,))
                parent = nodes[path]
            for c in sorted(groups[g]):
                self.course_tree.insert(nodes[g], 'end',
                                        text=os.path.basename(c),
                                        values=(c,))

    def _on_course_double_click(self, event):
        item = self.course_tree.focus()
        vals = self.course_tree.item(item, 'values')
        if not vals:
            return
        rel = vals[0]
        cdir = self.course_dir.get()
        path = os.path.join(cdir, rel)
        if not os.path.isfile(path):
            path = find_course_file(cdir, rel)
        if not path or not os.path.isfile(path):
            self.log_msg(f"找不到文件: {rel}", 'err')
            return
        lines = parse_course_xml(path)
        if not lines:
            self.log_msg(f"{rel} 未解析出文本", 'warn')
            return
        if self.strip_num_var.get():
            lines = [re.sub(r'^\s*\d+\s*[：:]\s*', '', x) for x in lines]
        self.text_content = '\n'.join(lines)
        self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', self.text_content)
        self.current_course.set(rel)
        self.root.title(f"金山打字通 自动打字助手 — 当前: {rel}")
        self.log_msg(f"已加载 {rel}，{len(lines)} 条，"
                     f"{len(self.text_content)} 字符", 'ok')
        self.log_msg(f"请确认打字通「课程选择」也为: {rel}", 'hint')

    def _copy_course_name(self):
        name = self.current_course.get()
        if not name:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(name)
        self.log_msg(f"已复制: {name}", 'ok')

    def _on_start(self):
        global CN_PUNCT_MODE, CN_PUNCT_WAIT
        if not self.text_content:
            messagebox.showwarning("提示", "请先双击加载一个课程")
            return
        if self.worker and self.worker.is_alive():
            self.log_msg("已在运行中", 'warn')
            return

        _stop_flag.clear()
        _pause_flag.clear()

        try:
            cfg = self._current_config()
        except Exception as e:
            messagebox.showerror("参数错误", f"读取配置失败: {e}")
            return

        if cfg['speed'] <= 0:
            cfg['speed'] = 8.0
        if cfg['delay'] < 0:
            cfg['delay'] = 0.0

        CN_PUNCT_MODE = cfg['punct_mode']
        CN_PUNCT_WAIT = cfg['punct_wait']

        self._check_ime(quiet=True)

        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        self.btn_pause.config(state='normal', text="暂停")

        self.worker = threading.Thread(
            target=self._typing_worker,
            args=(self.text_content, cfg['speed'], cfg['delay'],
                  cfg['auto_focus']),
            daemon=True)
        self.worker.start()

    def _on_pause(self):
        if _pause_flag.is_set():
            _pause_flag.clear()
            self.btn_pause.config(text="暂停")
            self.log_msg("继续", 'info')
        else:
            _pause_flag.set()
            self.btn_pause.config(text="继续")
            self.log_msg("暂停", 'warn')

    def _on_stop(self):
        _stop_flag.set()
        _pause_flag.clear()
        self.log_msg("发送停止信号…", 'warn')

    def _locate_typing_window(self):
        hwnd = self._find_typing_window()
        if hwnd:
            self.typing_hwnd = hwnd
            state, desc = describe_ime_state(hwnd)
            self.log_msg(f"已定位打字通窗口 0x{hwnd:08X}，输入法: {desc}",
                         'ok' if state == 'en' else 'warn')
            self._update_ime_label(state, desc)
            return True
        self.log_msg("未找到打字通窗口", 'err')
        return False

    def _check_ime(self, quiet=False):
        hwnd = self.typing_hwnd
        if not hwnd or not user32.IsWindow(hwnd):
            hwnd = self._find_typing_window()
            self.typing_hwnd = hwnd
        if not hwnd:
            self._update_ime_label('unknown', "未找到打字通窗口")
            if not quiet:
                self.log_msg("未找到打字通窗口，请先打开打字通", 'warn')
            return 'unknown'
        state, desc = describe_ime_state(hwnd)
        self._update_ime_label(state, desc)
        if quiet:
            return state
        if state == 'en':
            self.log_msg(f"输入法状态: {desc} — 可以开跑", 'ok')
        elif state == 'cn':
            self.log_msg(f"输入法状态: {desc}", 'err')
            self.log_msg("  请在打字通里按一下 Shift 切到英文", 'warn')
        else:
            self.log_msg(f"输入法状态: {desc}", 'warn')
        return state

    def _update_ime_label(self, state, desc):
        def _do():
            if state == 'en':
                self.lbl_ime.config(text=f"● {desc}", fg='#1a8a3a',
                                    bg='#e6f5ea')
                self.lbl_ime_hint.config(
                    text="已就绪，Unicode 字符不会被输入法干扰",
                    foreground='#1a8a3a')
            elif state == 'cn':
                self.lbl_ime.config(text=f"● {desc}", fg='#b03030',
                                    bg='#fbe6e6')
                self.lbl_ime_hint.config(
                    text="请在打字通里按一下 Shift 切到英文！",
                    foreground='#b03030')
            else:
                self.lbl_ime.config(text=f"● {desc}", fg='#888',
                                    bg='#f0f0f0')
                self.lbl_ime_hint.config(
                    text="点击「定位打字通」开始检测",
                    foreground='#888')
        self.root.after(0, _do)

    def _poll_ime_state(self):
        try:
            if self.typing_hwnd and user32.IsWindow(self.typing_hwnd):
                state, desc = describe_ime_state(self.typing_hwnd)
                self._update_ime_label(state, desc)
            else:
                hwnd = self._find_typing_window()
                if hwnd:
                    self.typing_hwnd = hwnd
                    state, desc = describe_ime_state(hwnd)
                    self._update_ime_label(state, desc)
        except Exception:
            pass
        self.root.after(1500, self._poll_ime_state)

    def _typing_worker(self, text, speed, delay, auto_focus):
        text = ''.join(c for c in text
                       if c == '\n' or c == '\t' or c.isprintable())
        if not text.strip():
            self.log_msg("文本为空", 'err')
            self._finish_ui()
            return

        total = len(text)
        self.log_msg(f"待打 {total} 字符，速度 {speed} cps，"
                     f"标点模式 {CN_PUNCT_MODE}，等待 {CN_PUNCT_WAIT}s，"
                     f"{delay}s 后开始", 'info')

        try:
            _send(_key(scan=0, flags=KEYEVENTF_UNICODE))
            _send(_key(scan=0, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        except OSError as e:
            self.log_msg(f"SendInput 自检失败: {e}", 'err')
            self.log_msg("若 GetLastError=5，请用管理员身份运行本脚本",
                         'warn')
            self._finish_ui()
            return

        if auto_focus:
            ok = self._focus_typing_window()
            self.log_msg("已聚焦打字通" if ok
                         else "未找到打字通窗口，请手动点输入框",
                         'ok' if ok else 'warn')

        hwnd = self.typing_hwnd or self._find_typing_window()
        if hwnd:
            state, desc = describe_ime_state(hwnd)
            if state == 'cn':
                self.log_msg(f"警告: 打字通当前输入法为「{desc}」",
                             'err')
                self.log_msg("  Unicode 标点会被输入法二次处理，"
                             "正确率会掉！建议先按 Shift 切英文",
                             'err')
            elif state == 'en':
                self.log_msg(f"打字通输入法: {desc}", 'ok')

        end_cd = time.time() + delay
        while time.time() < end_cd:
            if _stop_flag.is_set():
                self._finish_ui()
                return
            self.log_msg(f"倒计时 {end_cd - time.time():.1f}s", 'info',
                         replace_last=True)
            time.sleep(0.1)
        self.log_msg("GO!", 'ok')

        interval = 1.0 / speed
        start = time.time()
        done = 0

        try:
            for i, ch in enumerate(text):
                if _stop_flag.is_set():
                    self.log_msg(f"已停止，{done}/{total}", 'warn')
                    break
                while _pause_flag.is_set():
                    if _stop_flag.is_set():
                        break
                    time.sleep(0.05)
                if _stop_flag.is_set():
                    self.log_msg(f"已停止，{done}/{total}", 'warn')
                    break

                try:
                    type_char(ch)
                except OSError as e:
                    self.log_msg(f"第 {i} 字发送失败: {e}", 'err')
                    break

                done += 1
                self._set_progress(done * 100.0 / total, done, total)

                if done % 20 == 0 or done == total:
                    el = time.time() - start
                    cps = done / el if el > 0 else 0
                    tail = text[max(0, i - 8):i + 1].replace('\n', '↵')
                    self.log_msg(f"[{done}/{total}] ...{tail} "
                                 f"({cps:.1f} cps)", 'char')

                if interval > 0.0005:
                    target = start + (i + 1) * interval
                    dt = target - time.time()
                    if dt > 0:
                        time.sleep(dt)
        except Exception as e:
            self.log_msg(f"运行时异常: {e}", 'err')
        finally:
            el = time.time() - start
            self.log_msg(
                f"完成 {done}/{total}，用时 {el:.1f}s"
                + (f"，均速 {done/el:.1f} cps" if el > 0 else ""),
                'ok')
            self._finish_ui()

    def _finish_ui(self):
        def _do():
            self.btn_start.config(state='normal')
            self.btn_stop.config(state='disabled')
            self.btn_pause.config(state='disabled', text="暂停")
        self.root.after(0, _do)

    def _set_progress(self, pct, done, total):
        def _do():
            self.progress['value'] = pct
            self.lbl_prog.config(text=f"{done} / {total}")
        self.root.after(0, _do)

    def _find_typing_window(self):
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        IsWindowVisible = user32.IsWindowVisible
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowTextW = user32.GetWindowTextW
        keywords = ('打字通', 'TypeEasy', 'typeeasy')
        found = []

        def cb(hwnd, lp):
            if not IsWindowVisible(hwnd):
                return True
            l = GetWindowTextLengthW(hwnd)
            if l == 0:
                return True
            buf = ctypes.create_unicode_buffer(l + 1)
            GetWindowTextW(hwnd, buf, l + 1)
            t = buf.value
            if any(k in t for k in keywords):
                found.append(hwnd)
                return False
            return True

        EnumWindows(EnumWindowsProc(cb), 0)
        return found[0] if found else None

    def _focus_typing_window(self):
        hwnd = self._find_typing_window()
        if not hwnd:
            return False
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        self.typing_hwnd = hwnd
        time.sleep(0.4)
        return True

    def log_msg(self, msg, level='info', replace_last=False):
        self.log_queue.put((msg, level, replace_last))

    def _poll_log(self):
        try:
            while True:
                msg, level, replace_last = self.log_queue.get_nowait()
                self.log.config(state='normal')
                if replace_last:
                    self.log.delete('end-2l', 'end-1l')
                    self.log.insert('end', msg + '\n', level)
                else:
                    t = time.strftime('[%H:%M:%S] ')
                    self.log.insert('end', t + msg + '\n', level)
                self.log.see('end')
                self.log.config(state='disabled')
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log)

    def _clear_log(self):
        self.log.config(state='normal')
        self.log.delete('1.0', 'end')
        self.log.config(state='disabled')


def main():
    ap = argparse.ArgumentParser(description='金山打字通自动打字助手')
    ap.add_argument('--dir', default=None,
                    help='course 目录（默认使用推荐配置里的路径）')
    args, _ = ap.parse_known_args()

    root = tk.Tk()
    app = TypeEasyApp(root)

    if args.dir:
        app.course_dir.set(args.dir)
        app._refresh_course_list()

    def welcome():
        time.sleep(0.3)
        cfg = RECOMMENDED_CONFIG
        app.log_msg(f"金山打字通自动打字助手  {PROJECT_INFO['version']}",
                    'ok')
        app.log_msg(f"原创: {PROJECT_INFO['author']}  |  "
                    f"{PROJECT_INFO['license']}", 'hint')
        app.log_msg("使用步骤:", 'hint')
        app.log_msg("  1. 打字通打开课程，点一下它的输入框", 'hint')
        app.log_msg("  2. 按 Shift 切到英文（用「定位打字通」确认）",
                    'hint')
        app.log_msg("  3. 本工具双击加载同一课程", 'hint')
        app.log_msg("  4. 点「开始输入」，倒计时结束切回打字通", 'hint')
        app.log_msg(f"当前使用推荐配置：速度={cfg['speed']}  "
                    f"延迟={cfg['delay']}s  "
                    f"标点模式={cfg['punct_mode']}  "
                    f"标点等待={cfg['punct_wait']}s", 'info')
        app.log_msg("参数可随时修改，点「恢复推荐配置」可一键还原",
                    'hint')

    threading.Thread(target=welcome, daemon=True).start()
    root.mainloop()


if __name__ == '__main__':
    main()