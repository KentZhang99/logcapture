from __future__ import annotations

import json
import os
import queue
import platform
import site
import sys
import threading
import time
from datetime import datetime

try:
	import grp
	import pwd
except ImportError:
	grp = None
	pwd = None

TK_AVAILABLE = True
try:
	import tkinter as tk
	from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, W, Y, filedialog, messagebox
	from tkinter import colorchooser, ttk
except ImportError:
	TK_AVAILABLE = False

SERIAL_AVAILABLE = True


def _add_sudo_user_site_packages() -> None:
	# Running GUI with sudo may lose access to user-installed packages.
	sudo_user = os.environ.get("SUDO_USER")
	if not sudo_user:
		return
	py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
	candidates = [
		f"/home/{sudo_user}/.local/lib/python{py_ver}/site-packages",
		f"/Users/{sudo_user}/Library/Python/{py_ver}/lib/python/site-packages",
	]
	for user_site in candidates:
		if os.path.isdir(user_site):
			site.addsitedir(user_site)


_add_sudo_user_site_packages()

try:
	import serial
	from serial.tools import list_ports
except ImportError:
	SERIAL_AVAILABLE = False
	serial = None
	list_ports = None

SSH_LIB_AVAILABLE = True
try:
	import paramiko
except ImportError:
	SSH_LIB_AVAILABLE = False
	paramiko = None

BAUD_RATES = [
	"1200",
	"2400",
	"4800",
	"9600",
	"19200",
	"38400",
	"57600",
	"115200",
	"230400",
	"460800",
	"921600",
]

if SERIAL_AVAILABLE:
	DATA_BITS_MAP = {
		"5": serial.FIVEBITS,
		"6": serial.SIXBITS,
		"7": serial.SEVENBITS,
		"8": serial.EIGHTBITS,
	}

	STOP_BITS_MAP = {
		"1": serial.STOPBITS_ONE,
		"1.5": serial.STOPBITS_ONE_POINT_FIVE,
		"2": serial.STOPBITS_TWO,
	}

	PARITY_MAP = {
		"None": serial.PARITY_NONE,
		"Even": serial.PARITY_EVEN,
		"Odd": serial.PARITY_ODD,
		"Mark": serial.PARITY_MARK,
		"Space": serial.PARITY_SPACE,
	}
else:
	DATA_BITS_MAP = {}
	STOP_BITS_MAP = {}
	PARITY_MAP = {}


class SerialToolApp:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("Serial Tool")
		self.root.geometry("1200x760")

		self.config_path = os.path.join(os.path.dirname(__file__), "serial_tool_config.json")

		self.ser = None
		self.ssh_client = None
		self.ssh_shell = None
		self.ssh_read_thread = None
		self.read_thread = None
		self.stop_event = threading.Event()
		self.ssh_stop_event = threading.Event()
		self.rx_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

		self.log_buffer = []
		self.log_base_path = ""
		self.log_file_path = tk.StringVar(value="")
		self.auto_save_var = tk.BooleanVar(value=False)
		self.hex_send_var = tk.BooleanVar(value=False)
		self.terminal_font_size_var = tk.IntVar(value=10)

		self.connection_mode_var = tk.StringVar(value="serial")

		self.port_var = tk.StringVar()
		self.baud_var = tk.StringVar(value="115200")
		self.databits_var = tk.StringVar(value="8")
		self.stopbits_var = tk.StringVar(value="1")
		self.parity_var = tk.StringVar(value="None")
		self.rtscts_var = tk.BooleanVar(value=False)
		self.xonxoff_var = tk.BooleanVar(value=False)
		self.dsrdtr_var = tk.BooleanVar(value=False)

		self.ssh_host_var = tk.StringVar(value="")
		self.ssh_port_var = tk.StringVar(value="22")
		self.ssh_user_var = tk.StringVar(value="")
		self.ssh_password_var = tk.StringVar(value="")
		self.ssh_key_path_var = tk.StringVar(value="")
		self.ssh_use_key_var = tk.BooleanVar(value=False)

		self.keyword_entries = []  # list of (word, color, stop_log)
		self.logging_active = True

		self._build_ui()
		self.refresh_ports()
		self.load_config()
		self.on_connection_mode_changed()
		self.root.after(50, self.process_queue)

	def _build_ui(self) -> None:
		container = ttk.Frame(self.root, padding=8)
		container.pack(fill=BOTH, expand=True)

		top = ttk.LabelFrame(container, text="Configuration", padding=8)
		top.pack(fill="x")

		mode_row = ttk.Frame(top)
		mode_row.pack(fill="x", pady=(0, 6))
		ttk.Label(mode_row, text="Mode").pack(side=LEFT)
		self.serial_mode_radio = ttk.Radiobutton(
			mode_row,
			text="Serial",
			value="serial",
			variable=self.connection_mode_var,
			command=self.on_connection_mode_changed,
		)
		self.serial_mode_radio.pack(side=LEFT, padx=(8, 4))
		self.ssh_mode_radio = ttk.Radiobutton(
			mode_row,
			text="SSH",
			value="ssh",
			variable=self.connection_mode_var,
			command=self.on_connection_mode_changed,
		)
		self.ssh_mode_radio.pack(side=LEFT)

		self.save_config_btn = ttk.Button(mode_row, text="Save Config", command=self.save_config)
		self.save_config_btn.pack(side=RIGHT)
		self.connect_btn = ttk.Button(mode_row, text="Connect", command=self.toggle_connection)
		self.connect_btn.pack(side=RIGHT, padx=(0, 6))

		if not SERIAL_AVAILABLE:
			self.serial_mode_radio.configure(state="disabled")
			self.connection_mode_var.set("ssh")

		self.config_stack = ttk.Frame(top)
		self.config_stack.pack(fill="x")

		self.serial_config_frame = ttk.Frame(self.config_stack)
		self._build_serial_config(self.serial_config_frame)

		self.ssh_config_frame = ttk.Frame(self.config_stack)
		self._build_ssh_config(self.ssh_config_frame)

		body = ttk.Panedwindow(container, orient="horizontal")
		body.pack(fill=BOTH, expand=True, pady=(8, 0))

		log_frame = ttk.LabelFrame(body, text="Terminal", padding=6)
		body.add(log_frame, weight=3)

		text_frame = ttk.Frame(log_frame)
		text_frame.pack(fill=BOTH, expand=True)
		self.log_text = tk.Text(
			text_frame,
			wrap="word",
			height=30,
			bg="#1e1e1e",
			fg="#f0f0f0",
			insertbackground="#f0f0f0",
			selectbackground="#444",
			font=("Courier", 10),
		)
		log_scroll = ttk.Scrollbar(text_frame, orient=VERTICAL, command=self.log_text.yview)
		self.log_text.configure(yscrollcommand=log_scroll.set)
		self.log_text.tag_configure("tag_system", foreground="#ffff66")
		self.log_text.tag_configure("tag_rx",     foreground="#7ecfff")
		self.log_text.tag_configure("tag_tx",     foreground="#aaffaa")
		self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
		log_scroll.pack(side=RIGHT, fill=Y)

		action_row = ttk.Frame(log_frame)
		action_row.pack(fill="x", pady=(6, 0))

		ttk.Checkbutton(action_row, text="Auto save", variable=self.auto_save_var).pack(side=LEFT)
		ttk.Button(action_row, text="Choose log file", command=self.choose_log_file).pack(side=LEFT, padx=6)
		ttk.Button(action_row, text="Save log now", command=self.save_log_now).pack(side=LEFT)
		ttk.Label(action_row, text="Font").pack(side=LEFT, padx=(12, 4))
		self.font_size_spin = tk.Spinbox(
			action_row,
			from_=8,
			to=28,
			width=4,
			textvariable=self.terminal_font_size_var,
			command=self.update_terminal_font,
		)
		self.font_size_spin.pack(side=LEFT)
		self.font_size_spin.bind("<Return>", lambda _event: self.update_terminal_font())
		self.font_size_spin.bind("<FocusOut>", lambda _event: self.update_terminal_font())
		ttk.Button(action_row, text="Clear", command=self.clear_log).pack(side=RIGHT)

		log_path_row = ttk.Frame(log_frame)
		log_path_row.pack(fill="x", pady=(4, 0))
		ttk.Label(log_path_row, text="Log file:").pack(side=LEFT)
		ttk.Entry(log_path_row, textvariable=self.log_file_path).pack(side=LEFT, fill="x", expand=True, padx=6)

		prompt_row = ttk.Frame(log_frame)
		prompt_row.pack(fill="x", pady=(4, 0))
		self.prompt_label = tk.Label(
			prompt_row, text=">",
			bg="#2d2d2d", fg="#00cc66",
			font=("Courier", 10, "bold"),
			padx=4,
		)
		self.prompt_label.pack(side=LEFT)
		self.send_entry = tk.Entry(
			prompt_row,
			bg="#2d2d2d",
			fg="#f0f0f0",
			insertbackground="#f0f0f0",
			font=("Courier", 10),
			relief="flat",
		)
		self.send_entry.pack(side=LEFT, fill="x", expand=True)
		self.send_entry.bind("<Return>", lambda _event: self.send_data())
		ttk.Checkbutton(prompt_row, text="HEX", variable=self.hex_send_var).pack(side=LEFT, padx=8)
		ttk.Button(prompt_row, text="Send", command=self.send_data).pack(side=LEFT)
		self.update_terminal_font()

		kw_frame = ttk.LabelFrame(body, text="Keyword Highlight", padding=6)
		body.add(kw_frame, weight=2)

		self.keyword_word_var = tk.StringVar()
		self.keyword_color_var = tk.StringVar(value="#ff4444")
		self.keyword_stop_log_var = tk.BooleanVar(value=False)

		kw_input_row = ttk.Frame(kw_frame)
		kw_input_row.pack(fill="x", pady=(0, 4))
		ttk.Label(kw_input_row, text="Keyword").pack(side=LEFT)
		ttk.Entry(kw_input_row, textvariable=self.keyword_word_var, width=16).pack(side=LEFT, padx=4)

		ttk.Label(kw_input_row, text="Color").pack(side=LEFT, padx=(8, 0))
		self.color_preview = tk.Label(kw_input_row, width=3, bg=self.keyword_color_var.get())
		self.color_preview.pack(side=LEFT, padx=4)
		ttk.Button(kw_input_row, text="Pick", command=self.pick_color).pack(side=LEFT)

		kw_opt_row = ttk.Frame(kw_frame)
		kw_opt_row.pack(fill="x", pady=(0, 6))
		ttk.Checkbutton(
			kw_opt_row,
			text="Stop log on match",
			variable=self.keyword_stop_log_var,
		).pack(side=LEFT)
		ttk.Button(kw_opt_row, text="Add", command=self.add_keyword).pack(side=LEFT, padx=8)

		self.keyword_list = tk.Listbox(kw_frame, height=12)
		self.keyword_list.pack(fill=BOTH, expand=True)

		kw_action_row = ttk.Frame(kw_frame)
		kw_action_row.pack(fill="x", pady=(6, 0))
		ttk.Button(kw_action_row, text="Remove selected", command=self.remove_selected_keyword).pack(side=LEFT)
		ttk.Button(kw_action_row, text="Clear keywords", command=self.clear_keywords).pack(side=LEFT, padx=6)

		kw_log_row = ttk.Frame(kw_frame)
		kw_log_row.pack(fill="x", pady=(6, 0))
		self.log_status_label = ttk.Label(kw_log_row, text="Log: active", foreground="#22aa44")
		self.log_status_label.pack(side=LEFT)
		ttk.Button(
			kw_log_row,
			text="Resume log",
			command=self.resume_logging,
		).pack(side=LEFT, padx=8)

	def _build_serial_config(self, parent: ttk.Frame) -> None:
		row1 = ttk.Frame(parent)
		row1.pack(fill="x", pady=2)
		ttk.Label(row1, text="Port").pack(side=LEFT)
		self.port_combo = ttk.Combobox(row1, width=16, textvariable=self.port_var, state="readonly")
		self.port_combo.pack(side=LEFT, padx=4)
		self.refresh_btn = ttk.Button(row1, text="Refresh", command=self.refresh_ports)
		self.refresh_btn.pack(side=LEFT, padx=(0, 16))

		ttk.Label(row1, text="Baud").pack(side=LEFT)
		self.baud_combo = ttk.Combobox(
			row1,
			width=10,
			textvariable=self.baud_var,
			values=BAUD_RATES,
		)
		self.baud_combo.pack(side=LEFT, padx=4)

		ttk.Label(row1, text="Data bits").pack(side=LEFT, padx=(16, 0))
		self.databits_combo = ttk.Combobox(
			row1,
			width=6,
			textvariable=self.databits_var,
			values=list(DATA_BITS_MAP.keys()),
			state="readonly",
		)
		self.databits_combo.pack(side=LEFT, padx=4)

		ttk.Label(row1, text="Stop bits").pack(side=LEFT, padx=(16, 0))
		self.stopbits_combo = ttk.Combobox(
			row1,
			width=6,
			textvariable=self.stopbits_var,
			values=list(STOP_BITS_MAP.keys()),
			state="readonly",
		)
		self.stopbits_combo.pack(side=LEFT, padx=4)

		ttk.Label(row1, text="Parity").pack(side=LEFT, padx=(16, 0))
		self.parity_combo = ttk.Combobox(
			row1,
			width=8,
			textvariable=self.parity_var,
			values=list(PARITY_MAP.keys()),
			state="readonly",
		)
		self.parity_combo.pack(side=LEFT, padx=4)

		row2 = ttk.Frame(parent)
		row2.pack(fill="x", pady=2)
		self.rtscts_check = ttk.Checkbutton(row2, text="RTS/CTS", variable=self.rtscts_var)
		self.rtscts_check.pack(side=LEFT)
		self.xonxoff_check = ttk.Checkbutton(row2, text="XON/XOFF", variable=self.xonxoff_var)
		self.xonxoff_check.pack(side=LEFT, padx=10)
		self.dsrdtr_check = ttk.Checkbutton(row2, text="DSR/DTR", variable=self.dsrdtr_var)
		self.dsrdtr_check.pack(side=LEFT)

		perm_row = ttk.Frame(parent)
		perm_row.pack(fill="x", pady=(6, 2))
		ttk.Label(perm_row, text="Serial access:").pack(side=LEFT)
		self.perm_status_label = ttk.Label(perm_row, text="", foreground="#888")
		self.perm_status_label.pack(side=LEFT, padx=6)
		self._update_permission_status()

	def _build_ssh_config(self, parent: ttk.Frame) -> None:
		row1 = ttk.Frame(parent)
		row1.pack(fill="x", pady=2)
		ttk.Label(row1, text="Host").pack(side=LEFT)
		ttk.Entry(row1, textvariable=self.ssh_host_var, width=20).pack(side=LEFT, padx=4)
		ttk.Label(row1, text="Port").pack(side=LEFT, padx=(12, 0))
		ttk.Entry(row1, textvariable=self.ssh_port_var, width=8).pack(side=LEFT, padx=4)
		ttk.Label(row1, text="Username").pack(side=LEFT, padx=(12, 0))
		ttk.Entry(row1, textvariable=self.ssh_user_var, width=16).pack(side=LEFT, padx=4)

		row2 = ttk.Frame(parent)
		row2.pack(fill="x", pady=2)
		ttk.Label(row2, text="Password").pack(side=LEFT)
		ttk.Entry(row2, textvariable=self.ssh_password_var, show="*", width=24).pack(side=LEFT, padx=4)
		ttk.Checkbutton(row2, text="Use private key", variable=self.ssh_use_key_var).pack(side=LEFT, padx=(12, 0))

		row3 = ttk.Frame(parent)
		row3.pack(fill="x", pady=2)
		ttk.Label(row3, text="Key file").pack(side=LEFT)
		ttk.Entry(row3, textvariable=self.ssh_key_path_var).pack(side=LEFT, fill="x", expand=True, padx=4)
		ttk.Button(row3, text="Browse", command=self.choose_ssh_key_file).pack(side=LEFT)

	def _check_dialout_permission(self) -> bool:
		sys_name = platform.system()
		if sys_name != "Linux":
			return True

		if hasattr(os, "geteuid") and os.geteuid() == 0:
			return True

		if grp is None or pwd is None:
			return True

		try:
			username = os.environ.get("SUDO_USER") or os.environ.get("USER") or os.environ.get("LOGNAME") or ""
			if not username:
				return False

			for group_name in ("dialout", "uucp"):
				try:
					target_group = grp.getgrnam(group_name)
				except KeyError:
					continue
				if username in target_group.gr_mem:
					return True
				user_info = pwd.getpwnam(username)
				if user_info.pw_gid == target_group.gr_gid:
					return True
			return False
		except Exception:
			return True

	def _update_permission_status(self) -> None:
		if not hasattr(self, "perm_status_label"):
			return

		sys_name = platform.system()
		if sys_name == "Windows":
			self.perm_status_label.configure(
				text="OK (Windows usually requires no extra group)", foreground="#22aa44"
			)
			return
		if sys_name == "Darwin":
			self.perm_status_label.configure(
				text="macOS: ensure /dev/cu.* is accessible", foreground="#888"
			)
			return

		if self._check_dialout_permission():
			self.perm_status_label.configure(
				text="OK (in dialout/uucp group)", foreground="#22aa44"
			)
		else:
			self.perm_status_label.configure(
				text="No access — not in dialout/uucp group", foreground="#cc3333"
			)

	def refresh_ports(self) -> None:
		if not SERIAL_AVAILABLE:
			return
		ports = [p.device for p in list_ports.comports()]
		self.port_combo["values"] = ports
		if ports and not self.port_var.get():
			self.port_var.set(ports[0])

	def on_connection_mode_changed(self) -> None:
		is_serial = self.connection_mode_var.get() == "serial"
		if is_serial and self.ssh_client is not None:
			self.disconnect_ssh()
		if (not is_serial) and self.ser and self.ser.is_open:
			self.disconnect_serial()

		self.serial_config_frame.pack_forget()
		self.ssh_config_frame.pack_forget()
		if is_serial:
			self.serial_config_frame.pack(fill="x")
		else:
			self.ssh_config_frame.pack(fill="x")

		self._update_connect_button_text()

	def _update_connect_button_text(self) -> None:
		if self.connection_mode_var.get() == "serial":
			text = "Disconnect Serial" if (self.ser and self.ser.is_open) else "Connect Serial"
		else:
			text = "Disconnect SSH" if self.ssh_client is not None else "Connect SSH"
		self.connect_btn.configure(text=text)

	def choose_ssh_key_file(self) -> None:
		path = filedialog.askopenfilename(
			title="Select private key file",
			filetypes=[("All files", "*.*")],
		)
		if path:
			self.ssh_key_path_var.set(path)

	def toggle_connection(self) -> None:
		mode = self.connection_mode_var.get()
		if mode == "serial":
			if self.ser and self.ser.is_open:
				self.disconnect_serial()
			else:
				self.connect_serial()
		else:
			if self.ssh_client is not None:
				self.disconnect_ssh()
			else:
				self.connect_ssh()

	def connect_ssh(self) -> None:
		if self.ser and self.ser.is_open:
			messagebox.showwarning("Warning", "Serial is connected. Disconnect it first.")
			return

		if not SSH_LIB_AVAILABLE:
			messagebox.showerror(
				"SSH unavailable",
				"Missing dependency: paramiko\nInstall with: pip3 install paramiko",
			)
			return

		host = self.ssh_host_var.get().strip()
		user = self.ssh_user_var.get().strip()
		port_text = self.ssh_port_var.get().strip() or "22"
		if not host or not user:
			messagebox.showwarning("Warning", "Please configure SSH host and username first.")
			return

		try:
			port = int(port_text)
		except Exception:
			messagebox.showwarning("Warning", "SSH port is invalid.")
			return

		connect_args = {
			"hostname": host,
			"port": port,
			"username": user,
			"timeout": 8,
		}
		if self.ssh_use_key_var.get():
			key_path = self.ssh_key_path_var.get().strip()
			if not key_path or not os.path.exists(key_path):
				messagebox.showwarning("Warning", "Private key path is invalid.")
				return
			connect_args["key_filename"] = key_path
		else:
			connect_args["password"] = self.ssh_password_var.get()

		try:
			client = paramiko.SSHClient()
			client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
			client.connect(**connect_args)
			self.ssh_client = client
			self.ssh_shell = client.invoke_shell()
			self.ssh_shell.settimeout(0.0)
		except Exception as exc:
			messagebox.showerror("SSH connect error", str(exc))
			self.ssh_client = None
			self.ssh_shell = None
			return

		self.ssh_stop_event.clear()
		self.ssh_read_thread = threading.Thread(target=self.ssh_read_loop, daemon=True)
		self.ssh_read_thread.start()

		self._update_connect_button_text()
		self.append_log("SYSTEM", f"SSH connected: {user}@{host}:{port}")

	def disconnect_ssh(self) -> None:
		self.ssh_stop_event.set()
		if self.ssh_read_thread and self.ssh_read_thread.is_alive():
			self.ssh_read_thread.join(timeout=1.0)
		self.ssh_read_thread = None

		if self.ssh_shell is not None:
			try:
				self.ssh_shell.close()
			except Exception:
				pass
			self.ssh_shell = None

		if self.ssh_client is not None:
			try:
				self.ssh_client.close()
			except Exception:
				pass
			self.ssh_client = None
			self.append_log("SYSTEM", "SSH disconnected")
		self._update_connect_button_text()

	def connect_serial(self) -> None:
		if self.ssh_client is not None:
			messagebox.showwarning("Warning", "SSH is connected. Disconnect it first.")
			return

		if not SERIAL_AVAILABLE:
			messagebox.showerror("Serial unavailable", "Missing dependency: pyserial")
			return

		if not self._check_dialout_permission():
			self.append_log(
				"SYSTEM",
				"Warning: not in dialout/uucp group — serial port access may be denied on Linux.",
			)

		port = self.port_var.get().strip()
		if not port:
			messagebox.showwarning("Warning", "Please select a serial port.")
			return

		try:
			self.ser = serial.Serial(
				port=port,
				baudrate=int(self.baud_var.get()),
				bytesize=DATA_BITS_MAP[self.databits_var.get()],
				stopbits=STOP_BITS_MAP[self.stopbits_var.get()],
				parity=PARITY_MAP[self.parity_var.get()],
				rtscts=self.rtscts_var.get(),
				xonxoff=self.xonxoff_var.get(),
				dsrdtr=self.dsrdtr_var.get(),
				timeout=0.2,
			)
		except Exception as exc:
			messagebox.showerror("Connect error", str(exc))
			return

		self.stop_event.clear()
		self.read_thread = threading.Thread(target=self.read_loop, daemon=True)
		self.read_thread.start()
		self._update_connect_button_text()
		self.append_log("SYSTEM", f"Connected: {port}")

	def disconnect_serial(self) -> None:
		was_connected = bool(self.ser and self.ser.is_open)
		self.stop_event.set()
		if self.read_thread and self.read_thread.is_alive():
			self.read_thread.join(timeout=1.0)

		if self.ser:
			try:
				self.ser.close()
			except Exception:
				pass
		self.ser = None

		if was_connected:
			self.append_log("SYSTEM", "Disconnected")
		self._update_connect_button_text()

	def read_loop(self) -> None:
		while not self.stop_event.is_set():
			if not self.ser or not self.ser.is_open:
				break
			try:
				data = self.ser.read(self.ser.in_waiting or 1)
				if data:
					text = data.decode(errors="replace")
					self.rx_queue.put(("RX", text))
			except Exception as exc:
				self.rx_queue.put(("SYSTEM", f"Read error: {exc}"))
				break
			time.sleep(0.01)

	def ssh_read_loop(self) -> None:
		while not self.ssh_stop_event.is_set():
			if self.ssh_shell is None:
				break
			try:
				if self.ssh_shell.recv_ready():
					data = self.ssh_shell.recv(4096)
					if data:
						text = data.decode(errors="replace")
						self.rx_queue.put(("RX", text))
			except Exception as exc:
				self.rx_queue.put(("SYSTEM", f"SSH read error: {exc}"))
				break
			time.sleep(0.02)

	def process_queue(self) -> None:
		while True:
			try:
				direction, text = self.rx_queue.get_nowait()
			except queue.Empty:
				break
			self.append_log(direction, text)
		self.root.after(50, self.process_queue)

	def append_log(self, direction: str, payload: str) -> None:
		timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
		line = f"[{timestamp}] [{direction}] {payload}"

		if not line.endswith("\n"):
			line += "\n"

		start_index = self.log_text.index(END)
		self.log_text.insert(END, line)
		line_end = self.log_text.index(END)
		direction_tag = {"SYSTEM": "tag_system", "RX": "tag_rx", "TX": "tag_tx"}.get(direction)
		if direction_tag:
			self.log_text.tag_add(direction_tag, start_index, line_end)

		# Always buffer/save the current line first, then check stop-log keywords
		if self.logging_active:
			self.log_buffer.append(line)
			if self.auto_save_var.get() and self.log_file_path.get().strip():
				self.append_log_to_file(line)

		self._check_stop_log_keywords(payload)

		self.highlight_keywords(start_index)
		self.log_text.see(END)

	def _check_stop_log_keywords(self, text: str) -> None:
		if not self.logging_active:
			return
		for word, _color, stop_log in self.keyword_entries:
			if stop_log and word and word in text:
				self.logging_active = False
				if hasattr(self, "log_status_label"):
					self.log_status_label.configure(
						text=f"Log: STOPPED (keyword: {word!r})",
						foreground="#cc3333",
					)
				# insert a notice into terminal (not into log_buffer)
				notice = f"--- Log recording stopped: keyword {word!r} matched ---\n"
				self.log_text.insert(END, notice)
				self.log_text.tag_add("tag_system", f"end - {len(notice)+1}c", END)
				self.log_text.see(END)
				break

	def highlight_keywords(self, start_index: str) -> None:
		end_index = self.log_text.index(END)
		for idx, (keyword, color, _stop) in enumerate(self.keyword_entries):
			if not keyword:
				continue
			tag = f"kw_{idx}"
			self.log_text.tag_configure(tag, foreground=color)
			search_start = start_index
			while True:
				pos = self.log_text.search(keyword, search_start, stopindex=end_index, nocase=False)
				if not pos:
					break
				finish = f"{pos}+{len(keyword)}c"
				self.log_text.tag_add(tag, pos, finish)
				search_start = finish

	def send_data(self) -> None:
		raw = self.send_entry.get()
		if not raw:
			return

		try:
			if self.connection_mode_var.get() == "serial":
				if not self.ser or not self.ser.is_open:
					messagebox.showwarning("Warning", "Serial is not connected.")
					return
				if self.hex_send_var.get():
					data = bytes.fromhex(raw.strip())
				else:
					data = raw.encode()
				self.ser.write(data)
				shown = raw if not self.hex_send_var.get() else data.hex(" ")
				self.append_log("TX", shown)
			else:
				if self.ssh_shell is None:
					messagebox.showwarning("Warning", "SSH is not connected.")
					return
				self.ssh_shell.send(raw + "\n")
				self.append_log("TX", raw)

			self.send_entry.delete(0, END)
		except Exception as exc:
			messagebox.showerror("Send error", str(exc))

	def pick_color(self) -> None:
		color = colorchooser.askcolor(color=self.keyword_color_var.get())[1]
		if color:
			self.keyword_color_var.set(color)
			self.color_preview.configure(bg=color)

	def add_keyword(self) -> None:
		word = self.keyword_word_var.get().strip()
		color = self.keyword_color_var.get().strip() or "#ff4444"
		stop_log = self.keyword_stop_log_var.get()
		if not word:
			messagebox.showwarning("Warning", "Keyword cannot be empty.")
			return

		self.keyword_entries.append((word, color, stop_log))
		label = f"[STOP] {word}  ({color})" if stop_log else f"{word}  ({color})"
		self.keyword_list.insert(END, label)
		self.keyword_word_var.set("")
		self.keyword_stop_log_var.set(False)

	def resume_logging(self) -> None:
		self.logging_active = True
		if self.log_base_path:
			self.log_file_path.set(self._make_timestamped_path(self.log_base_path))
		if hasattr(self, "log_status_label"):
			self.log_status_label.configure(text="Log: active", foreground="#22aa44")
		self.append_log("SYSTEM", "Log recording resumed.")

	def remove_selected_keyword(self) -> None:
		selected = self.keyword_list.curselection()
		if not selected:
			return
		idx = selected[0]
		del self.keyword_entries[idx]
		self.keyword_list.delete(idx)
		self.rebuild_highlight_tags()

	def clear_keywords(self) -> None:
		self.keyword_entries.clear()
		self.keyword_list.delete(0, END)
		self.rebuild_highlight_tags()

	def rebuild_highlight_tags(self) -> None:
		for tag in self.log_text.tag_names():
			if tag.startswith("kw_"):
				self.log_text.tag_delete(tag)
		self.highlight_keywords("1.0")

	def choose_log_file(self) -> None:
		path = filedialog.asksaveasfilename(
			title="Select log file",
			defaultextension=".log",
			filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
		)
		if path:
			self.log_base_path = path
			self.log_file_path.set(self._make_timestamped_path(path))

	@staticmethod
	def _make_timestamped_path(base: str) -> str:
		ts = datetime.now().strftime("%Y%m%d_%H%M%S")
		root_part, ext = os.path.splitext(base)
		return f"{root_part}_{ts}{ext}"

	def append_log_to_file(self, line: str) -> None:
		path = self.log_file_path.get().strip()
		if not path:
			return
		try:
			with open(path, "a", encoding="utf-8") as f:
				f.write(line)
		except Exception as exc:
			messagebox.showerror("Save error", str(exc))
			self.auto_save_var.set(False)

	def save_log_now(self) -> None:
		path = self.log_file_path.get().strip()
		if not path:
			self.choose_log_file()
			path = self.log_file_path.get().strip()
			if not path:
				return

		try:
			with open(path, "w", encoding="utf-8") as f:
				f.writelines(self.log_buffer)
			messagebox.showinfo("Saved", f"Log saved to:\n{path}")
		except Exception as exc:
			messagebox.showerror("Save error", str(exc))

	def clear_log(self) -> None:
		self.log_text.delete("1.0", END)
		self.log_buffer.clear()

	def update_terminal_font(self) -> None:
		try:
			size = int(self.terminal_font_size_var.get())
		except Exception:
			size = 10
		if size < 8:
			size = 8
		if size > 28:
			size = 28
		self.terminal_font_size_var.set(size)

		if hasattr(self, "log_text"):
			self.log_text.configure(font=("Courier", size))
		if hasattr(self, "send_entry"):
			self.send_entry.configure(font=("Courier", size))
		if hasattr(self, "prompt_label"):
			self.prompt_label.configure(font=("Courier", size, "bold"))

	def get_config_data(self) -> dict:
		return {
			"connection_mode": self.connection_mode_var.get(),
			"serial": {
				"port": self.port_var.get(),
				"baud": self.baud_var.get(),
				"data_bits": self.databits_var.get(),
				"stop_bits": self.stopbits_var.get(),
				"parity": self.parity_var.get(),
				"rtscts": self.rtscts_var.get(),
				"xonxoff": self.xonxoff_var.get(),
				"dsrdtr": self.dsrdtr_var.get(),
				"hex_send": self.hex_send_var.get(),
			},
			"ssh": {
				"host": self.ssh_host_var.get(),
				"port": self.ssh_port_var.get(),
				"user": self.ssh_user_var.get(),
				"password": self.ssh_password_var.get(),
				"use_key": self.ssh_use_key_var.get(),
				"key_path": self.ssh_key_path_var.get(),
			},
			"log": {
				"auto_save": self.auto_save_var.get(),
				"log_file": self.log_base_path,
				"terminal_font_size": self.terminal_font_size_var.get(),
			},
			"keywords": [
				{"word": word, "color": color, "stop_log": stop_log}
				for word, color, stop_log in self.keyword_entries
			],
		}

	def apply_config_data(self, config: dict) -> None:
		serial_cfg = config.get("serial", {})
		ssh_cfg = config.get("ssh", {})
		log_cfg = config.get("log", {})

		mode = config.get("connection_mode", "serial")
		if mode not in ("serial", "ssh"):
			mode = "serial"
		if mode == "serial" and not SERIAL_AVAILABLE:
			mode = "ssh"
		self.connection_mode_var.set(mode)

		self.port_var.set(serial_cfg.get("port", self.port_var.get()))
		self.baud_var.set(str(serial_cfg.get("baud", self.baud_var.get())))
		self.databits_var.set(str(serial_cfg.get("data_bits", self.databits_var.get())))
		self.stopbits_var.set(str(serial_cfg.get("stop_bits", self.stopbits_var.get())))
		self.parity_var.set(str(serial_cfg.get("parity", self.parity_var.get())))
		self.rtscts_var.set(bool(serial_cfg.get("rtscts", self.rtscts_var.get())))
		self.xonxoff_var.set(bool(serial_cfg.get("xonxoff", self.xonxoff_var.get())))
		self.dsrdtr_var.set(bool(serial_cfg.get("dsrdtr", self.dsrdtr_var.get())))
		self.hex_send_var.set(bool(serial_cfg.get("hex_send", self.hex_send_var.get())))

		self.ssh_host_var.set(str(ssh_cfg.get("host", self.ssh_host_var.get())))
		self.ssh_port_var.set(str(ssh_cfg.get("port", self.ssh_port_var.get())))
		self.ssh_user_var.set(str(ssh_cfg.get("user", self.ssh_user_var.get())))
		self.ssh_password_var.set(str(ssh_cfg.get("password", self.ssh_password_var.get())))
		self.ssh_use_key_var.set(bool(ssh_cfg.get("use_key", self.ssh_use_key_var.get())))
		self.ssh_key_path_var.set(str(ssh_cfg.get("key_path", self.ssh_key_path_var.get())))

		self.auto_save_var.set(bool(log_cfg.get("auto_save", self.auto_save_var.get())))
		base = str(log_cfg.get("log_file", self.log_base_path)).strip()
		if base:
			self.log_base_path = base
			self.log_file_path.set(self._make_timestamped_path(base))
		self.terminal_font_size_var.set(int(log_cfg.get("terminal_font_size", self.terminal_font_size_var.get())))
		self.update_terminal_font()

		self.keyword_entries.clear()
		self.keyword_list.delete(0, END)
		for item in config.get("keywords", []):
			word = str(item.get("word", "")).strip()
			color = str(item.get("color", "#ff4444")).strip() or "#ff4444"
			stop_log = bool(item.get("stop_log", False))
			if word:
				self.keyword_entries.append((word, color, stop_log))
				label = f"[STOP] {word}  ({color})" if stop_log else f"{word}  ({color})"
				self.keyword_list.insert(END, label)
		self.rebuild_highlight_tags()

	def load_config(self) -> None:
		if not os.path.exists(self.config_path):
			return
		try:
			with open(self.config_path, "r", encoding="utf-8") as f:
				config = json.load(f)
		except Exception as exc:
			self.append_log("SYSTEM", f"Load config failed: {exc}")
			return
		if isinstance(config, dict):
			self.apply_config_data(config)

	def save_config(self) -> None:
		config = self.get_config_data()
		try:
			with open(self.config_path, "w", encoding="utf-8") as f:
				json.dump(config, f, ensure_ascii=True, indent=2)
		except Exception as exc:
			messagebox.showerror("Save config error", str(exc))
			return
		self.append_log("SYSTEM", f"Configuration saved: {self.config_path}")

	def on_close(self) -> None:
		self.save_config()
		self.disconnect_serial()
		if self.ssh_client is not None:
			self.disconnect_ssh()
		self.root.destroy()


def main() -> None:
	missing = []
	if not TK_AVAILABLE:
		missing.append("tkinter")
	if missing:
		sys_name = platform.system()
		if sys_name == "Linux":
			tk_tip = "  sudo apt update && sudo apt install -y python3-tk"
		elif sys_name == "Darwin":
			tk_tip = "  brew install python-tk@3.12  # or install Python.org build with tkinter"
		else:
			tk_tip = "  Reinstall Python from python.org and enable tcl/tk (tkinter)"

		tips = [
			f"Missing dependencies: {', '.join(missing)}",
			"Install tkinter:",
			tk_tip,
			"Optional dependencies:",
			"  pip3 install pyserial   # for Serial mode",
			"  pip3 install paramiko   # for SSH mode",
			"Then run: python3 Console.py",
		]
		raise SystemExit("\n".join(tips))

	root = tk.Tk()
	app = SerialToolApp(root)
	root.protocol("WM_DELETE_WINDOW", app.on_close)
	root.mainloop()


if __name__ == "__main__":
	main()
